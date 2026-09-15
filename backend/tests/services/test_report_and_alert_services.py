"""Service-level tests for the report rule and the scheduled evaluation.

The HTTP suites prove what a caller receives. What this file adds is the two claims the job rests
on and that no response body can show.

**There is one definition of "low".** `low_stock_for_tenant` is what the evaluator calls and
`low_stock_products` is what the report screen calls; a test asserts they return the same rows for
the same business. Two implementations would eventually disagree, and the alert and the screen
would then tell a business two different things about the same shelf.

**A run reports a failure instead of raising one.** A job that dies on the third tenant leaves the
rest unevaluated and nobody knows which ones, so the evaluator records the business and the reason
and carries on. The test breaks one business's evaluation deliberately and asserts the run
completes, the failure is reported, and the other businesses are still evaluated.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.core.database import Base, Database
from ahia.core.permissions.permissions_registry import permission_codes_for_role
from ahia.core.ports.storage_port import StorageUploadRequest, StoredObject, compute_sha256
from ahia.core.security import TokenService
from ahia.core.tenant_context import build_tenant_context
from ahia.crud import (
    inventory_crud,
    product_crud,
    tenant_crud,
    tenant_membership_crud,
    user_crud,
)
from ahia.models.entities.inventory_model import InventoryModel
from ahia.models.entities.product_model import ProductModel
from ahia.models.entities.tenant_membership_model import TenantMembershipModel
from ahia.models.entities.tenant_model import TenantModel
from ahia.models.entities.user_model import UserModel
from ahia.services.audit_event_service import AuditEventService
from ahia.services.low_stock_alert_service import LowStockAlertEvaluator
from ahia.services.notification_service import NotificationService
from ahia.services.report_service import ReportService
from ahia.services.share_link_service import ShareLinkService

DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test"
)
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def build_settings(**overrides: Any) -> Settings:
    baseline: dict[str, Any] = {
        "_env_file": None,
        "app_env": AppEnvironment.TEST,
        "database_url": os.environ.get("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL),
        "jwt_secret": "test-signing-secret-value-0000000001",
        "refresh_token_pepper": "test-refresh-pepper-value-00000000011",
        "storage_provider": StorageProviderName.R2,
        "r2_endpoint": "https://account.r2.cloudflarestorage.com",
        "r2_access_key_id": "r2-access-key",
        "r2_secret_access_key": "r2-secret-key",
        "r2_bucket": "ahia-test",
    }
    baseline.update(overrides)
    return Settings(**baseline)


class NullStorage:
    """A store that keeps nothing: these tests never look at an export's bytes."""

    provider_name = "null"

    async def upload(self, request: StorageUploadRequest) -> StoredObject:
        return StoredObject(
            provider=self.provider_name,
            key=request.key,
            mime_type=request.mime_type,
            size_bytes=len(request.content),
            checksum_sha256=compute_sha256(request.content),
        )

    async def delete(self, *, key: str, tenant_id: str) -> None:
        return None

    async def exists(self, *, key: str, tenant_id: str) -> bool:
        return False

    async def build_delivery_url(
        self, *, key: str, presentation_width: int | None = None, is_public: bool = False
    ) -> str:
        return f"https://cdn.example.test/{key}"

    async def close(self) -> None:
        return None


@pytest.fixture
async def database() -> AsyncIterator[Database]:
    instance = Database(build_settings())
    async with instance.engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(sync_connection, checkfirst=True)
        )
        await connection.execute(
            text(
                "TRUNCATE TABLE notifications, report_exports, share_links, audit_events, "
                "inventory_movements, inventory, products, tenant_memberships, tenants, "
                "users CASCADE"
            )
        )
    try:
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def report_service(database: Database) -> ReportService:
    token_service = TokenService(
        secret="test-signing-secret-value-0000000001",
        algorithm="HS256",
        issuer="ahia-test",
        audience="ahia-test",
        access_token_ttl_minutes=15,
        refresh_token_pepper="test-refresh-pepper-value-00000000011",
        public_token_bytes=24,
    )
    audit = AuditEventService(unit_of_work_factory=database.unit_of_work_factory())
    return ReportService(
        unit_of_work_factory=database.unit_of_work_factory(),
        storage=NullStorage(),  # type: ignore[arg-type]
        share_link_service=ShareLinkService(
            unit_of_work_factory=database.unit_of_work_factory(),
            token_service=token_service,
            audit_event_service=audit,
        ),
        audit_event_service=audit,
    )


@pytest.fixture
def notification_service(database: Database) -> NotificationService:
    return NotificationService(unit_of_work_factory=database.unit_of_work_factory())


async def insert_tenant(database: Database, *, name: str = "Obi Electronics") -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await tenant_crud.create(
            unit_of_work.session_handle,
            TenantModel.create(
                tenant_id=identifier, name=name, slug=f"shop-{identifier.hex[:8]}", now=NOW
            ),
        )
        await unit_of_work.commit()
    return identifier


async def insert_user(database: Database) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        await user_crud.create(
            unit_of_work.session_handle,
            UserModel.create(
                user_id=identifier,
                first_name="Emeka",
                email=f"emeka.{identifier.hex[:8]}@example.com",
                now=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


async def add_member(database: Database, *, tenant_id: UUID, user_id: UUID, role_name: str) -> None:
    membership = TenantMembershipModel.activate_immediately(
        membership_id=uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role_name=role_name,
        now=NOW,
    )
    async with database.transaction_scope() as unit_of_work:
        await tenant_membership_crud.create(unit_of_work.session_handle, membership)
        await unit_of_work.commit()


async def seed_product(
    database: Database,
    *,
    tenant_id: UUID,
    name: str,
    quantity: Decimal,
    threshold: Decimal,
) -> UUID:
    identifier = uuid4()
    async with database.transaction_scope() as unit_of_work:
        session = unit_of_work.session_handle
        await product_crud.create(
            session,
            ProductModel.create(
                product_id=identifier,
                tenant_id=tenant_id,
                name=name,
                selling_price=Decimal("45000.00"),
                low_stock_threshold=threshold,
                now=NOW,
            ),
        )
        await inventory_crud.lock_for_product(
            session,
            inventory_id=uuid4(),
            tenant_id=tenant_id,
            product_id=identifier,
            now=NOW,
        )
        # The movement path is what a real stock level goes through; for a seeded fixture the
        # projection is set directly through the entity's own transition.
        stored_level = await inventory_crud.get_for_product(
            session, tenant_id=tenant_id, product_id=identifier
        )
        assert stored_level is not None
        await inventory_crud.save(
            session,
            InventoryModel(
                id=stored_level.id,
                tenant_id=tenant_id,
                product_id=identifier,
                quantity_on_hand=quantity,
                created_at=stored_level.created_at,
                updated_at=NOW,
            ),
        )
        await unit_of_work.commit()
    return identifier


def context_for(tenant_id: UUID, role_name: str) -> Any:
    return build_tenant_context(
        user_id=uuid4(),
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role(role_name),
        role_name=role_name,
    )


# ---------------------------------------------------------------------------
# One definition of "low"
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_the_job_and_the_screen_agree_on_what_is_low(
    database: Database, report_service: ReportService
) -> None:
    """Two answers to one question is how an alert and a screen come to disagree."""
    tenant_id = await insert_tenant(database)
    await seed_product(
        database,
        tenant_id=tenant_id,
        name="Beans",
        quantity=Decimal("2.000"),
        threshold=Decimal("10.000"),
    )
    await seed_product(
        database,
        tenant_id=tenant_id,
        name="Rice",
        quantity=Decimal("50.000"),
        threshold=Decimal("10.000"),
    )

    from_screen = await report_service.low_stock_products(context_for(tenant_id, "OWNER"))
    from_job = await report_service.low_stock_for_tenant(tenant_id=tenant_id)

    assert [entry.product_id for entry in from_screen] == [entry.product_id for entry in from_job]
    assert [entry.product_name for entry in from_job] == ["Beans"]


# ---------------------------------------------------------------------------
# A run that survives one business
# ---------------------------------------------------------------------------


class ExplodingReportService:
    """A report service whose low-stock call fails, for one tenant only."""

    def __init__(self, *, failing_tenant: UUID) -> None:
        self._failing_tenant = failing_tenant

    async def low_stock_for_tenant(self, *, tenant_id: UUID, limit: int = 200) -> list[Any]:
        if tenant_id == self._failing_tenant:
            raise RuntimeError("the database dropped this query")
        return []


@pytest.mark.integration
async def test_a_failing_business_is_reported_and_the_run_continues(
    database: Database, notification_service: NotificationService
) -> None:
    broken = await insert_tenant(database, name="Broken Shop")
    healthy = await insert_tenant(database, name="Healthy Shop")
    evaluator = LowStockAlertEvaluator(
        unit_of_work_factory=database.unit_of_work_factory(),
        report_service=ExplodingReportService(failing_tenant=broken),  # type: ignore[arg-type]
        notification_service=notification_service,
    )

    report = await evaluator.evaluate_all(today=date(2026, 9, 15))

    assert [tenant_id for tenant_id, _reason in report.failures] == [broken]
    assert report.failures[0][1] == "RuntimeError"
    assert {tenant.tenant_id for tenant in report.tenants} == {healthy}, (
        "the business that failed is recorded, and the others are still evaluated"
    )


@pytest.mark.integration
async def test_a_business_with_nobody_to_tell_raises_nothing(
    database: Database, report_service: ReportService, notification_service: NotificationService
) -> None:
    tenant_id = await insert_tenant(database)
    await seed_product(
        database,
        tenant_id=tenant_id,
        name="Beans",
        quantity=Decimal("1.000"),
        threshold=Decimal("10.000"),
    )
    evaluator = LowStockAlertEvaluator(
        unit_of_work_factory=database.unit_of_work_factory(),
        report_service=report_service,
        notification_service=notification_service,
    )

    evaluation = await evaluator.evaluate_tenant(tenant_id=tenant_id, today=date(2026, 9, 15))

    assert evaluation.low_stock_products == 1
    assert evaluation.recipients == 0
    assert evaluation.notifications_raised == 0


@pytest.mark.integration
async def test_the_alert_names_the_product_and_the_day_it_is_about(
    database: Database, report_service: ReportService, notification_service: NotificationService
) -> None:
    """The dedupe key is what makes a second run in one day a no-op, so it is asserted directly."""
    tenant_id = await insert_tenant(database)
    owner_id = await insert_user(database)
    await add_member(database, tenant_id=tenant_id, user_id=owner_id, role_name="OWNER")
    product_id = await seed_product(
        database,
        tenant_id=tenant_id,
        name="Beans",
        quantity=Decimal("0.000"),
        threshold=Decimal("5.000"),
    )
    evaluator = LowStockAlertEvaluator(
        unit_of_work_factory=database.unit_of_work_factory(),
        report_service=report_service,
        notification_service=notification_service,
    )

    await evaluator.evaluate_tenant(tenant_id=tenant_id, today=date(2026, 9, 15))
    inbox = await notification_service.list_notifications(_context_for_user(tenant_id, owner_id))

    assert len(inbox) == 1
    notification = inbox[0]
    assert notification.notification_type.value == "STOCK_OUT", (
        "nothing on the shelf is a different alert from nearly nothing"
    )
    assert notification.entity_id == product_id
    assert notification.dedupe_key == f"low_stock:{product_id}:2026-09-15"


def _context_for_user(tenant_id: UUID, user_id: UUID) -> Any:
    return build_tenant_context(
        user_id=user_id,
        tenant_id=tenant_id,
        membership_id=uuid4(),
        permission_codes=permission_codes_for_role("OWNER"),
        role_name="OWNER",
    )
