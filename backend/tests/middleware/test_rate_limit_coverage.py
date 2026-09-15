"""The rate-limit review, written as a test so it cannot fall behind the routes.

A review kept in a document is a review that is true on the day it was written. This walks every
route the application registers and asserts the two invariants that matter, so adding an endpoint
that escapes a limit is a red build rather than a surprise in production.

**Every write consumes the write budget, or a tighter one.** A mutating route that landed in the
global bucket would be limited at six hundred requests a minute, which is not a limit for an
endpoint that writes rows.

**Every class the milestone names has routes.** Authentication, message sending, writes and the
public shop: if one of them has no routes the classification is untested, and a classification that
is never exercised is one that can break silently.

**The public shop keeps its own budget.** It is the one surface an anonymous caller reaches, and
sharing the global budget would let one scraper spend a business's allowance on the endpoint that
needs it least.
"""

from __future__ import annotations

from typing import Final

import pytest
from fastapi.routing import APIRoute

from ahia.core.config import AppEnvironment, Settings, StorageProviderName
from ahia.main import create_application
from ahia.middleware.rate_limit_middleware import (
    RateLimitBucket,
    RateLimitMiddleware,
    build_default_limiter,
)

_WRITE_METHODS: Final[frozenset[str]] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def build_settings() -> Settings:
    return Settings(
        _env_file=None,
        app_env=AppEnvironment.TEST,
        database_url="postgresql+asyncpg://ksschkw:ahia_local_dev_only@127.0.0.1:5432/ahia_test",
        jwt_secret="test-signing-secret-value-0000000001",
        refresh_token_pepper="test-refresh-pepper-value-00000000011",
        storage_provider=StorageProviderName.R2,
        r2_endpoint="https://account.r2.cloudflarestorage.com",
        r2_access_key_id="r2-access-key",
        r2_secret_access_key="r2-secret-key",
        r2_bucket="ahia-test",
    )


def registered_routes() -> list[tuple[str, str]]:
    """Return (method, path) for every route the application serves.

    The walk descends into included routers: FastAPI keeps them as nested objects rather than
    flattening them into one list, and a walker that only looked at the top level would find no
    routes at all - which is how the first version of this test passed while asserting nothing.
    """
    application = create_application(build_settings())
    routes: list[tuple[str, str]] = []

    def walk(candidates: list[object]) -> None:
        for candidate in candidates:
            # An included router keeps its own routes under `original_router` rather than being
            # flattened into the application's list, so the walk follows that as well.
            original = getattr(candidate, "original_router", None)
            if original is not None:
                walk(list(getattr(original, "routes", [])))
                continue
            nested = getattr(candidate, "routes", None)
            if nested is not None:
                walk(list(nested))
                continue
            if not isinstance(candidate, APIRoute):
                continue
            for method in sorted(candidate.methods):
                if method in {"HEAD", "OPTIONS"}:
                    continue
                routes.append((method, candidate.path))

    walk(list(application.routes))
    return routes


@pytest.mark.unit
def test_no_write_route_escapes_the_write_budget() -> None:
    """A mutating route in the global bucket is limited at six hundred a minute: not a limit."""
    offenders = [
        f"{method} {path}"
        for method, path in registered_routes()
        if method in _WRITE_METHODS
        and RateLimitMiddleware._bucket_for(path=path, method=method) is RateLimitBucket.GLOBAL
    ]

    assert not offenders, (
        "these routes write and are only limited by the global budget:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.unit
def test_every_class_the_review_names_has_routes() -> None:
    """A classification that is never exercised is a classification that can break silently."""
    buckets = {
        RateLimitMiddleware._bucket_for(path=path, method=method)
        for method, path in registered_routes()
    }

    for bucket in (
        RateLimitBucket.AUTHENTICATION,
        RateLimitBucket.MESSAGE_SENDING,
        RateLimitBucket.WRITE,
        RateLimitBucket.PUBLIC_READ,
    ):
        assert bucket in buckets, f"no route is classified as {bucket.value}"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/api/v1/auth/login", RateLimitBucket.AUTHENTICATION),
        ("POST", "/api/v1/auth/register", RateLimitBucket.AUTHENTICATION),
        ("POST", "/api/v1/auth/password-reset", RateLimitBucket.MESSAGE_SENDING),
        # An invitation is a message to somebody who is not using the product yet.
        ("POST", "/api/v1/tenants/{tenant_id}/invitations", RateLimitBucket.MESSAGE_SENDING),
        ("POST", "/api/v1/tenants/{tenant_id}/sales", RateLimitBucket.WRITE),
        ("GET", "/shop/{tenant_slug}", RateLimitBucket.PUBLIC_READ),
        ("GET", "/share/{token}", RateLimitBucket.PUBLIC_READ),
        ("GET", "/share/report/{token}", RateLimitBucket.PUBLIC_READ),
        # The metrics endpoint is infrastructure, and it answers only to a configured scraping
        # token - so it consumes the global budget rather than the public one, which is for
        # strangers.
        ("GET", "/metrics", RateLimitBucket.GLOBAL),
        (
            "GET",
            "/api/v1/tenants/{tenant_id}/reports/daily-sales",
            RateLimitBucket.GLOBAL,
        ),
    ],
)
def test_the_class_of_a_representative_route(
    method: str, path: str, expected: RateLimitBucket
) -> None:
    """The classes are asserted one path at a time, so a change to the fragments is visible."""
    assert RateLimitMiddleware._bucket_for(path=path, method=method) is expected


@pytest.mark.unit
def test_the_public_shop_is_not_in_the_global_bucket() -> None:
    """One scraper must not be able to spend a business's allowance on the cheapest endpoint."""
    assert (
        RateLimitMiddleware._bucket_for(path="/shop/obi-electronics", method="GET")
        is RateLimitBucket.PUBLIC_READ
    )


@pytest.mark.unit
def test_every_bucket_has_a_configured_limit() -> None:
    """A bucket with no rule is a bucket that raises the first time a request reaches it."""
    limiter = build_default_limiter(
        authentication_per_minute=10,
        password_reset_per_hour=5,
        write_per_minute=120,
        global_per_minute=600,
        public_read_per_minute=120,
    )

    for bucket in RateLimitBucket:
        assert limiter.check("probe", bucket).allowed is True
