"""The product entity: what a business sells, at what price, and whether it is visible.

This is the entity money touches, so it carries the strictest rules in the codebase.

Money is a Decimal with at most two places, and a float is refused outright
    `0.1 + 0.2 != 0.3` in binary floating point, and a shop that loses a kobo per sale
    is a shop whose books do not balance. A price arriving as a float is therefore an
    invariant violation rather than a value to be rounded: rounding silently would
    mean the price the person typed and the price that was stored are different, and
    nothing would say so. Prices are stored as NUMERIC in the database for the same
    reason, and the schema layer refuses a float before it reaches here.

The slug is derived from the name and does not follow a rename
    A product page is a link a customer already holds, exactly like a business page,
    so the slug is a stable handle. A rename changes what people read.

Publication is a state with rules, not a flag
    A product that is not active cannot be published, and deactivating a published
    product unpublishes it in the same transition. Without that, the storefront would
    keep serving something the business has stopped selling, and the first person to
    notice would be a customer.

The public token is issued once and never rotated by a publish
    Publishing an already-published product is idempotent, so a link that has been
    shared on WhatsApp keeps working. Rotation, if it is ever needed, is a separate
    deliberate operation rather than a side effect of pressing "publish" twice.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Final
from uuid import UUID

from ahia.core.errors import EntityInvariantError
from ahia.core.slug import normalize_slug, require_slug_shape

MAXIMUM_NAME_LENGTH: Final[int] = 200
MAXIMUM_SLUG_LENGTH: Final[int] = 63
MAXIMUM_DESCRIPTION_LENGTH: Final[int] = 5_000
MAXIMUM_IDENTIFIER_LENGTH: Final[int] = 64

#: How many decimal places each kind of number may carry. A price with three places is
#: a value the column cannot hold, and rounding it would change what somebody typed.
MONEY_PLACES: Final[Decimal] = Decimal("0.01")
QUANTITY_PLACES: Final[Decimal] = Decimal("0.001")

#: The largest price this product accepts. NUMERIC(18,2) can hold more, but a product
#: priced above a trillion units is a typo rather than a price, and catching it here
#: means the mistake is a validation error instead of a number nobody notices.
MAXIMUM_PRICE: Final[Decimal] = Decimal("999999999999.99")

#: The largest stock threshold, in the same unit as a quantity.
MAXIMUM_QUANTITY: Final[Decimal] = Decimal("999999999999.999")

ZERO_PRICE: Final[Decimal] = Decimal("0.00")
ZERO_QUANTITY: Final[Decimal] = Decimal("0.000")


@dataclass(frozen=True, slots=True)
class ProductModel:
    """One thing a business sells."""

    id: UUID
    tenant_id: UUID
    name: str
    slug: str
    selling_price: Decimal
    created_at: datetime
    updated_at: datetime
    category_id: UUID | None = None
    description: str | None = None
    sku: str | None = None
    barcode: str | None = None
    cost_price: Decimal | None = None
    low_stock_threshold: Decimal = ZERO_QUANTITY
    is_active: bool = True
    is_published: bool = False
    public_token: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, field_name="created_at", product_id=self.id)
        _require_aware(self.updated_at, field_name="updated_at", product_id=self.id)
        if self.updated_at < self.created_at:
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail="updated_at is earlier than created_at",
            )

        if not self.name.strip():
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail="name is empty after trimming",
            )
        if len(self.name) > MAXIMUM_NAME_LENGTH:
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail=f"name exceeds {MAXIMUM_NAME_LENGTH} characters",
            )

        try:
            require_slug_shape(self.slug, maximum_length=MAXIMUM_SLUG_LENGTH)
        except ValueError as invalid_slug:
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail=f"invalid slug: {invalid_slug}",
            ) from invalid_slug

        self._check_money()
        self._check_identifiers()
        self._check_publication()

    # ------------------------------------------------------------------
    # Field rules
    # ------------------------------------------------------------------

    def _check_money(self) -> None:
        _require_money(
            self.selling_price,
            field_name="selling_price",
            product_id=self.id,
            minimum=ZERO_PRICE,
            maximum=MAXIMUM_PRICE,
        )
        if self.cost_price is not None:
            _require_money(
                self.cost_price,
                field_name="cost_price",
                product_id=self.id,
                minimum=ZERO_PRICE,
                maximum=MAXIMUM_PRICE,
            )
        # Selling below cost is a clearance decision, not a defect, so it is allowed
        # and nothing here warns about it. Only the numbers' shape is enforced.

        _require_quantity(
            self.low_stock_threshold,
            field_name="low_stock_threshold",
            product_id=self.id,
            maximum=MAXIMUM_QUANTITY,
        )

    def _check_identifiers(self) -> None:
        """Check the two strings a business uses to recognise its own stock.

        Both are normalised by the factory and checked again here, because a
        dataclass can also be built field by field - by the persistence mapper, for
        instance - and a rule that only the factory enforces is not a rule.
        """
        for field_name, value, maximum in (
            ("sku", self.sku, MAXIMUM_IDENTIFIER_LENGTH),
            ("barcode", self.barcode, MAXIMUM_IDENTIFIER_LENGTH),
        ):
            if value is None:
                continue
            if not value.strip():
                raise EntityInvariantError(
                    operation="build_product",
                    entity="product",
                    identifier=str(self.id),
                    detail=f"{field_name} is empty after trimming; use None instead",
                )
            if len(value) > maximum:
                raise EntityInvariantError(
                    operation="build_product",
                    entity="product",
                    identifier=str(self.id),
                    detail=f"{field_name} exceeds {maximum} characters",
                )
            if " " in value:
                raise EntityInvariantError(
                    operation="build_product",
                    entity="product",
                    identifier=str(self.id),
                    detail=f"{field_name} contains a space",
                )
        if self.sku is not None and self.sku != self.sku.upper():
            # Compared case-insensitively by the uniqueness index only if the value is
            # stored in one case, so SKUs are stored uppercase and a duplicate is
            # caught by the database rather than by a person noticing.
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail="sku must be uppercase",
            )

        if self.description is not None and len(self.description) > MAXIMUM_DESCRIPTION_LENGTH:
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail=f"description exceeds {MAXIMUM_DESCRIPTION_LENGTH} characters",
            )

    def _check_publication(self) -> None:
        if self.is_published and not self.is_active:
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail="a product that is not active cannot be published",
            )
        if self.is_published and not self.public_token:
            # A published product without a token would have no public address, so the
            # state and the value that makes it reachable travel together.
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail="a published product must carry a public token",
            )
        if self.public_token is not None and not self.public_token.strip():
            raise EntityInvariantError(
                operation="build_product",
                entity="product",
                identifier=str(self.id),
                detail="public_token is empty; use None instead",
            )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        product_id: UUID,
        tenant_id: UUID,
        name: str,
        selling_price: Decimal,
        now: datetime,
        category_id: UUID | None = None,
        description: str | None = None,
        sku: str | None = None,
        barcode: str | None = None,
        cost_price: Decimal | None = None,
        low_stock_threshold: Decimal = ZERO_QUANTITY,
    ) -> ProductModel:
        """Create a product, deriving its slug and normalising its identifiers.

        A new product is active and unpublished: it exists in the catalogue and is not
        visible to customers, so a business can prepare it before anyone sees it.
        """
        trimmed_name = name.strip()
        return cls(
            id=product_id,
            tenant_id=tenant_id,
            name=trimmed_name,
            slug=normalize_slug(trimmed_name),
            selling_price=selling_price,
            category_id=category_id,
            description=_clean_optional_text(description),
            sku=_clean_sku(sku),
            barcode=_clean_barcode(barcode),
            cost_price=cost_price,
            low_stock_threshold=low_stock_threshold,
            is_active=True,
            is_published=False,
            public_token=None,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Derived state
    # ------------------------------------------------------------------

    @property
    def sells_at_a_loss(self) -> bool:
        """Return True when the cost is known and above the selling price."""
        return self.cost_price is not None and self.cost_price > self.selling_price

    def is_visible_to_customers(self) -> bool:
        """Return True only when the product is both active and published."""
        return self.is_active and self.is_published

    def describe_for_audit(self) -> dict[str, str]:
        """Return the identifiers an audit record needs.

        Prices are absent: an audit line about a product identifies it, and a price is
        business information that belongs in the product's own history rather than in
        every log line that mentions it.
        """
        return {
            "product_id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "product_slug": self.slug,
            "is_active": "true" if self.is_active else "false",
            "is_published": "true" if self.is_published else "false",
        }

    # ------------------------------------------------------------------
    # Transitions: identity
    # ------------------------------------------------------------------

    def renamed(self, *, name: str, at: datetime) -> ProductModel:
        """Return the product with a new display name. The slug is untouched."""
        return replace(self, name=name.strip(), updated_at=at)

    def described(self, *, description: str | None, at: datetime) -> ProductModel:
        """Return the product with its description set, or cleared."""
        return replace(self, description=_clean_optional_text(description), updated_at=at)

    def categorised(self, *, category_id: UUID | None, at: datetime) -> ProductModel:
        """Return the product assigned to a category, or none.

        Uncategorised is a legitimate state, which is why the category column is
        nullable and this transition accepts None.
        """
        return replace(self, category_id=category_id, updated_at=at)

    def identified(
        self,
        *,
        sku: str | None,
        barcode: str | None,
        at: datetime,
    ) -> ProductModel:
        """Return the product with both stock identifiers set.

        Both are applied because both are clearable: a caller that wants to change one
        and keep the other passes the current value for the other, which makes the
        intent visible at the call site instead of hidden in a sentinel.
        """
        return replace(
            self,
            sku=_clean_sku(sku),
            barcode=_clean_barcode(barcode),
            updated_at=at,
        )

    # ------------------------------------------------------------------
    # Transitions: price and stock
    # ------------------------------------------------------------------

    def repriced(
        self,
        *,
        selling_price: Decimal,
        cost_price: Decimal | None,
        at: datetime,
    ) -> ProductModel:
        """Return the product with new prices.

        Cost is set together with the selling price for the same reason the two stock
        identifiers are set together: clearing the cost is an editing operation, and a
        sentinel would make "leave it" and "clear it" the same request.
        """
        return replace(
            self,
            selling_price=selling_price,
            cost_price=cost_price,
            updated_at=at,
        )

    def rethresholded(self, *, low_stock_threshold: Decimal, at: datetime) -> ProductModel:
        """Return the product with a new low-stock threshold."""
        return replace(self, low_stock_threshold=low_stock_threshold, updated_at=at)

    # ------------------------------------------------------------------
    # Transitions: lifecycle
    # ------------------------------------------------------------------

    def publish(self, *, public_token: str, at: datetime) -> ProductModel:
        """Return the product published at its public address.

        Idempotent, and stable across a withdrawal: a product that has been published
        before keeps the token it already had. A caller publishing a withdrawn product
        therefore does not have to know whether it had an address - passing a fresh
        token cannot silently break a link that is already printed on a QR code.

        A product that is not active cannot be published: the storefront would serve
        something the business stopped selling.
        """
        if not self.is_active:
            raise EntityInvariantError(
                operation="publish_product",
                entity="product",
                identifier=str(self.id),
                detail="a product that is not active cannot be published",
            )
        if self.is_published:
            return self
        return replace(
            self,
            is_published=True,
            public_token=self.public_token or public_token,
            updated_at=at,
        )

    def unpublish(self, *, at: datetime) -> ProductModel:
        """Return the product withdrawn from the storefront.

        The public token is kept: unpublishing is a decision to stop showing something,
        and a link that is re-published later should resolve to the same product rather
        than to a new one with the same name.
        """
        if not self.is_published:
            return self
        return replace(self, is_published=False, updated_at=at)

    def deactivate(self, *, at: datetime) -> ProductModel:
        """Return the product withdrawn from sale, and unpublished with it.

        The two states move together: a product that is no longer sold must not remain
        on the storefront, and leaving that to a second call would make forgetting it a
        silent mistake.
        """
        if not self.is_active:
            return self
        return replace(self, is_active=False, is_published=False, updated_at=at)

    def activate(self, *, at: datetime) -> ProductModel:
        """Return the product returned to the catalogue. It stays unpublished."""
        return replace(self, is_active=True, updated_at=at)


# ---------------------------------------------------------------------------
# Field helpers
# ---------------------------------------------------------------------------


def coerce_money(value: object, *, field_name: str) -> Decimal:
    """Return the Decimal a price or cost represents, or raise ValueError.

    This is the boundary's parser and the domain's rule in one function, so the edge
    and the entity cannot disagree about what a price is - the same reason the tenant
    slice shares `validate_slug` between its schema and its entity.

    A JSON body carries money as a number or as a string, and both are accepted:

    * a string is the safest form, and the one this API publishes, because no client
      ever has to pass a value through a binary float to send it
    * a number is accepted because most clients send one, and it is converted through
      its own decimal text rather than through its binary value

    Raises ValueError rather than a domain error so the schema layer can turn it into a
    422 for a client while the entity layer turns it into an invariant violation.
    """
    parsed = _parse_decimal_like(value, field_name=field_name)
    _check_money_rules(
        parsed,
        field_name=field_name,
        minimum=ZERO_PRICE,
        maximum=MAXIMUM_PRICE,
    )
    return parsed


def coerce_quantity(value: object, *, field_name: str) -> Decimal:
    """Return the Decimal a quantity represents, or raise ValueError.

    Quantities carry three decimal places rather than two, because stock is counted in
    kilos and litres as well as in units.
    """
    parsed = _parse_decimal_like(value, field_name=field_name)
    _check_quantity_rules(parsed, field_name=field_name, maximum=MAXIMUM_QUANTITY)
    return parsed


def _parse_decimal_like(value: object, *, field_name: str) -> Decimal:
    """Turn a wire value into a Decimal without ever going through a binary float."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field_name} must be a number")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        # A float that reached this point came from JSON, so its shortest decimal text
        # is what the client sent. `Decimal(float)` would instead expose the binary
        # approximation, which is the value nobody typed.
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} is empty")
        try:
            return Decimal(text)
        except InvalidOperation as invalid:
            raise ValueError(f"{field_name} is not a number") from invalid
    raise ValueError(f"{field_name} must be a number, not {type(value).__name__}")


def _check_money_rules(
    value: Decimal,
    *,
    field_name: str,
    minimum: Decimal,
    maximum: Decimal,
) -> None:
    """Raise ValueError unless the Decimal is a price this column can hold."""
    if not value.is_finite():
        raise ValueError(f"{field_name} is not a finite number")
    try:
        quantised = value.quantize(MONEY_PLACES)
    except InvalidOperation as unrepresentable:
        raise ValueError(
            f"{field_name} cannot be represented with two decimal places"
        ) from unrepresentable
    if quantised != value:
        raise ValueError(f"{field_name} has more than two decimal places")
    if value < minimum:
        raise ValueError(f"{field_name} is below {minimum}")
    if value > maximum:
        raise ValueError(f"{field_name} exceeds {maximum}")


def _check_quantity_rules(value: Decimal, *, field_name: str, maximum: Decimal) -> None:
    """Raise ValueError unless the Decimal is a quantity this column can hold."""
    if not value.is_finite():
        raise ValueError(f"{field_name} is not a finite number")
    if value.quantize(QUANTITY_PLACES) != value:
        raise ValueError(f"{field_name} has more than three decimal places")
    if value < ZERO_QUANTITY:
        raise ValueError(f"{field_name} is negative")
    if value > maximum:
        raise ValueError(f"{field_name} exceeds {maximum}")


def _require_money(
    value: object,
    *,
    field_name: str,
    product_id: UUID,
    minimum: Decimal,
    maximum: Decimal,
) -> None:
    """Raise unless the field already holds a Decimal price this column can hold.

    The parameter is typed as `object` on purpose. The annotation on the field says
    `Decimal`, and that is the contract; this function is where the contract is
    enforced, and Python does not enforce annotations at run time. Typing it as
    `Decimal` here would tell the checker the float case cannot happen, which is the
    case the check exists for.

    A float is refused rather than converted. The wire parser converts, because JSON
    has no decimal type; an entity holding a float means something upstream skipped
    that boundary, and rounding it here would hide the bug where it can be caught.
    """
    if isinstance(value, float):
        raise EntityInvariantError(
            operation="build_product",
            entity="product",
            identifier=str(product_id),
            detail=(
                f"{field_name} is a float; money must be a Decimal, "
                "because binary floating point cannot represent it exactly"
            ),
        )
    if not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_product",
            entity="product",
            identifier=str(product_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    try:
        _check_money_rules(value, field_name=field_name, minimum=minimum, maximum=maximum)
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="build_product",
            entity="product",
            identifier=str(product_id),
            detail=str(invalid),
        ) from invalid


def _require_quantity(
    value: object,
    *,
    field_name: str,
    product_id: UUID,
    maximum: Decimal,
) -> None:
    """Raise unless the field already holds a Decimal quantity.

    Typed as `object` for the same reason as `_require_money`: this is the check that
    makes the field's annotation true, so it must assume nothing.
    """
    if isinstance(value, float):
        raise EntityInvariantError(
            operation="build_product",
            entity="product",
            identifier=str(product_id),
            detail=(
                f"{field_name} is a float; quantities must be a Decimal, "
                "because a quantity that cannot be represented exactly is a stock "
                "count that does not reconcile"
            ),
        )
    if not isinstance(value, Decimal):
        raise EntityInvariantError(
            operation="build_product",
            entity="product",
            identifier=str(product_id),
            detail=f"{field_name} must be a Decimal, not {type(value).__name__}",
        )
    try:
        _check_quantity_rules(value, field_name=field_name, maximum=maximum)
    except ValueError as invalid:
        raise EntityInvariantError(
            operation="build_product",
            entity="product",
            identifier=str(product_id),
            detail=str(invalid),
        ) from invalid


def _clean_optional_text(value: str | None) -> str | None:
    """Trim, and treat a value that is only whitespace as absent."""
    if value is None:
        return None
    return value.strip() or None


def _clean_sku(value: str | None) -> str | None:
    """Return the stored form of a stock keeping unit.

    Uppercase and without surrounding whitespace, so a business that types `abc-1` one
    day and `ABC-1` the next has one product rather than two that look different in a
    report.
    """
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned or None


def _clean_barcode(value: str | None) -> str | None:
    """Return the stored form of a barcode.

    Case is preserved, because a barcode is a code somebody else assigned. Internal
    whitespace is removed rather than rejected here, so a scanned code that arrived
    with a stray space still matches the one that was typed.
    """
    if value is None:
        return None
    cleaned = "".join(value.split())
    return cleaned or None


def _require_aware(moment: datetime, *, field_name: str, product_id: UUID) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise EntityInvariantError(
            operation="build_product",
            entity="product",
            identifier=str(product_id),
            detail=f"{field_name} is a naive datetime; timestamps must carry a timezone",
        )
