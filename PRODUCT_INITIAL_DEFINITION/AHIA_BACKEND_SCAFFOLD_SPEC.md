# AHỊA --- Backend Scaffold Specification

**Document status:** Architecture baseline\
**Product:** AHỊA --- Multitenant Business Operating System for Informal
Commerce\
**Backend:** Python + FastAPI\
**Database:** PostgreSQL\
**ORM:** SQLAlchemy\
**Migrations:** Alembic\
**Runtime:** ASGI / Uvicorn\
**Architecture:** Strict five-layer vertical slices with cross-cutting
core

------------------------------------------------------------------------

# 1. Purpose

This document defines exactly how the AHỊA backend should be scaffolded
and how future entities and use cases should be added.

It incorporates the project's existing `project-init` engineering
preset:

-   strict five-layer architecture
-   one file per entity per layer
-   inward-only dependencies
-   thin transport
-   business logic in services
-   persistence isolated in CRUD/repository files
-   deny-by-default authorization
-   structured internal errors
-   opaque external errors
-   correlation IDs
-   resilience at outbound boundaries
-   environment-driven feature flags
-   architecture enforcement
-   secret scanning
-   dependency vulnerability scanning
-   codebase hygiene rules

The preset is treated as the engineering guardrail.

AHỊA's domain requirements are then mapped onto that guardrail.

------------------------------------------------------------------------

# 2. Important Architecture Reconciliation

The preset defines:

``` text
Entities
    ↓
Schemas
    ↓
CRUD
    ↓
Services
    ↓
Routers
```

with dependencies pointing inward.

It also requires entities to be framework-independent.

AHỊA will therefore use a **pure domain entity + persistence mapping**
approach rather than making SQLAlchemy ORM classes the domain source of
truth.

This matters because directly making:

``` python
class UserModel(Base):
```

the domain entity would make the entity depend on SQLAlchemy, violating
the preset.

The implementation should instead distinguish:

``` text
models/entities/
    Pure domain objects

crud/
    SQLAlchemy persistence mappings and database operations
```

The CRUD layer owns the database representation and maps it to/from
domain entities.

This preserves both:

``` text
strict architecture
+
real PostgreSQL/SQLAlchemy persistence
```

without weakening either.

------------------------------------------------------------------------

# 3. Dependency Direction

The allowed dependency direction is:

``` text
Transport
    ↓
Services
    ↓
CRUD
    ↓
Entities
```

Schemas are transport contracts and may reference domain types where
useful.

Cross-cutting core modules may be imported by any layer, but the core
must not import application layers.

Conceptually:

``` text
                         core/
                          ↑
                          │
routers → services → crud → entities
   │          │        │
 schemas     schemas   │
                       │
                  database driver
```

Forbidden:

``` text
entity → schema
entity → SQLAlchemy
entity → FastAPI
crud → service
service → router
service → SQLAlchemy session
router → CRUD
```

The service layer should not know how PostgreSQL works.

------------------------------------------------------------------------

# 4. Canonical AHỊA Backend Layout

``` text
backend/
├── src/
│   └── ahia/
│       ├── __init__.py
│       ├── main.py
│       │
│       ├── models/
│       │   ├── __init__.py
│       │   └── entities/
│       │       ├── __init__.py
│       │       ├── user_model.py
│       │       ├── tenant_model.py
│       │       ├── tenant_membership_model.py
│       │       ├── role_model.py
│       │       ├── permission_model.py
│       │       ├── role_permission_model.py
│       │       └── device_model.py
│       │
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── user_schema.py
│       │   ├── tenant_schema.py
│       │   ├── tenant_membership_schema.py
│       │   ├── role_schema.py
│       │   ├── permission_schema.py
│       │   └── device_schema.py
│       │
│       ├── crud/
│       │   ├── __init__.py
│       │   ├── user_crud.py
│       │   ├── tenant_crud.py
│       │   ├── tenant_membership_crud.py
│       │   ├── role_crud.py
│       │   ├── permission_crud.py
│       │   ├── role_permission_crud.py
│       │   └── device_crud.py
│       │
│       ├── services/
│       │   ├── __init__.py
│       │   ├── user_service.py
│       │   ├── tenant_service.py
│       │   ├── tenant_membership_service.py
│       │   ├── role_service.py
│       │   ├── permission_service.py
│       │   └── device_service.py
│       │
│       ├── routers/
│       │   ├── __init__.py
│       │   ├── user_router.py
│       │   ├── tenant_router.py
│       │   ├── tenant_membership_router.py
│       │   ├── role_router.py
│       │   ├── permission_router.py
│       │   └── device_router.py
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   ├── database.py
│       │   ├── errors.py
│       │   ├── logging.py
│       │   ├── resilience.py
│       │   ├── security.py
│       │   ├── container.py
│       │   ├── tenant_context.py
│       │   └── feature_flags.py
│       │
│       ├── middleware/
│       │   ├── __init__.py
│       │   ├── correlation_middleware.py
│       │   ├── security_headers_middleware.py
│       │   ├── rate_limit_middleware.py
│       │   └── error_handler_middleware.py
│       │
│       └── integrations/
│           ├── __init__.py
│           ├── storage/
│           │   ├── __init__.py
│           │   └── r2_client.py
│           └── whatsapp/
│               ├── __init__.py
│               └── click_to_chat.py
│
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── tests/
│   ├── entities/
│   ├── schemas/
│   ├── crud/
│   ├── services/
│   ├── routers/
│   ├── security/
│   ├── tenancy/
│   ├── sync/
│   └── architecture/
│
├── pyproject.toml
├── alembic.ini
├── Dockerfile
├── .dockerignore
├── .gitignore
├── .env.example
├── import-linter.ini
├── .pre-commit-config.yaml
└── README.md
```

The source root is `src/` so the installed package is tested rather than
accidentally importing files from the working directory.

------------------------------------------------------------------------

# 5. One File Per Entity Per Layer

The preset's rule remains strict.

For an entity:

``` text
User
```

the normal vertical slice is:

``` text
models/entities/user_model.py
schemas/user_schema.py
crud/user_crud.py
services/user_service.py
routers/user_router.py
```

For:

``` text
Product
```

it becomes:

``` text
models/entities/product_model.py
schemas/product_schema.py
crud/product_crud.py
services/product_service.py
routers/product_router.py
```

Do not create:

``` text
product_helpers.py
product_utils.py
product_common.py
product_logic.py
```

just because the feature grows.

If logic belongs to a use case spanning multiple entities, create a
service named after that use case.

------------------------------------------------------------------------

# 6. Entity Layer

Entities are the domain source of truth.

They contain:

-   domain fields
-   domain enums
-   value objects
-   domain invariants

They do NOT import:

``` text
FastAPI
Pydantic
SQLAlchemy
Alembic
HTTP clients
PostgreSQL drivers
```

Example conceptual entity:

``` python
@dataclass(frozen=True)
class UserModel:
    id: UUID
    email: str | None
    phone: str | None
    first_name: str
    last_name: str | None
    is_active: bool
```

The exact implementation can use Python dataclasses or another
standard-library-only domain representation.

------------------------------------------------------------------------

# 7. Schema Layer

Pydantic is used at the transport boundary.

Schemas validate:

``` text
HTTP input
query parameters
path parameters
request bodies
response serialization
```

Examples:

``` text
UserCreateSchema
UserUpdateSchema
UserResponseSchema
```

The schema layer must not contain business decisions such as:

``` text
"only owners may..."
"stock cannot..."
"this sale requires..."
```

Those belong to services.

------------------------------------------------------------------------

# 8. CRUD Layer

CRUD is the persistence boundary.

Each CRUD file owns one entity's persistence.

For example:

``` text
user_crud.py
```

may contain:

``` text
get_by_id
get_by_email
create
update
delete
```

It must not coordinate:

``` text
User + Tenant + Membership
```

in one repository.

Cross-entity workflows belong in a service.

## SQLAlchemy placement

SQLAlchemy-specific persistence mapping is allowed here.

The CRUD layer may contain:

``` python
class UserRecord(Base):
    ...
```

if the project uses SQLAlchemy ORM.

The important rule is that `UserRecord` is a persistence representation,
not the domain `UserModel`.

Mapping:

``` text
UserModel
    ↕
UserRecord
```

happens inside the CRUD/persistence boundary.

------------------------------------------------------------------------

# 9. Repository Transaction Strategy

The service owns the transaction boundary.

The service must not import the SQLAlchemy driver or manipulate
SQLAlchemy sessions directly.

Therefore transaction control should be exposed through an injected
persistence abstraction.

Conceptually:

``` text
Service
    ↓
UnitOfWork / transaction port
    ↓
CRUD implementations
    ↓
SQLAlchemy
```

The exact implementation must preserve the preset's rule that services
do not import a database driver.

For single-entity operations, a repository call may be sufficient.

For cross-entity operations such as completing a sale, the composition
root provides a transaction/unit-of-work abstraction to the service.

------------------------------------------------------------------------

# 10. Service Layer

Services contain all business behavior.

Examples:

``` text
register_user
create_tenant
invite_member
assign_role
create_product
receive_stock
complete_sale
cancel_sale
record_expense
publish_storefront
push_sync_operations
pull_sync_changes
```

A service may coordinate multiple CRUD components.

Example:

``` text
complete_sale
    ↓
validate membership
    ↓
authorize sales.create
    ↓
load products
    ↓
validate inventory
    ↓
create sale
    ↓
create sale items
    ↓
create payment
    ↓
create inventory movements
    ↓
update inventory projection
    ↓
write ledger
    ↓
write audit
```

The service remains independent of the transport protocol.

It must be callable by:

``` text
HTTP
scheduled job
CLI
future worker
tests
```

without duplicating business rules.

------------------------------------------------------------------------

# 11. Use-Case Naming

The preset's use-case naming rule is especially important for AHỊA.

Prefer:

``` text
complete_sale
receive_stock
cancel_sale
invite_tenant_member
publish_storefront
synchronize_operations
```

over vague methods such as:

``` text
process
handle
do_operation
manage
update_data
```

A cross-entity service should be named after the business operation.

For example:

``` text
sales_service.py
```

may contain `complete_sale` because sales are the natural domain home.

But if a workflow is fundamentally:

``` text
receive purchase order into inventory
```

then a dedicated use-case service can coordinate procurement and
inventory rather than forcing all logic into `inventory_service.py`.

------------------------------------------------------------------------

# 12. Router Layer

Routers are HTTP adapters.

A normal endpoint should be conceptually:

``` python
@router.post(...)
async def create_product(
    request: ProductCreateSchema,
    service: ProductService = Depends(...),
):
    return await service.create_product(request)
```

No:

``` text
database query
inventory calculation
permission decision
tenant lookup
business validation
external HTTP request
```

inside the route.

Error conversion is centralized in middleware.

------------------------------------------------------------------------

# 13. Composition Root

`core/container.py` is the composition root.

It is responsible for wiring:

``` text
database
repositories
services
external integrations
resilience policies
configuration
```

Dependencies should be constructed there or through explicit dependency
providers.

Avoid:

``` python
service = ProductService()
```

inside random modules.

Avoid module-level mutable singletons such as:

``` python
client = SomeHttpClient()
session = Session(...)
```

unless the lifecycle is explicitly managed by the application
composition root.

------------------------------------------------------------------------

# 14. Application Startup

`main.py` should remain small.

Conceptually:

``` text
create application
    ↓
load configuration
    ↓
create managed resources
    ↓
register middleware
    ↓
register routers
    ↓
configure exception handlers
    ↓
startup
```

Lifespan-managed resources include:

``` text
database engine/pool
external clients
resilience primitives
```

Shutdown must close resources cleanly.

------------------------------------------------------------------------

# 15. Configuration

Use typed settings.

Recommended environment variables:

``` text
APP_ENV
APP_NAME
APP_VERSION
LOG_LEVEL

DATABASE_URL

JWT_ISSUER
JWT_AUDIENCE
JWT_SECRET

CORS_ALLOWED_ORIGINS

R2_ENDPOINT
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_BUCKET

FEATURE_STOREFRONT_PUBLIC_PUBLISHING
FEATURE_OFFLINE_SYNC
FEATURE_R2_STORAGE
FEATURE_AI_INSIGHTS
```

Only `core/config.py` reads environment variables.

Other modules receive configuration through dependency injection.

------------------------------------------------------------------------

# 16. Feature Flags

Follow the preset exactly.

New/unstable features default to off.

Example:

``` text
FEATURE_OFFLINE_SYNC=false
FEATURE_AI_INSIGHTS=false
```

Security controls are never feature flagged.

Never create:

``` text
FEATURE_AUTH_ENABLED
FEATURE_AUTHORIZATION_ENABLED
FEATURE_RATE_LIMITING_ENABLED
```

Security is always on.

Each feature flag must have:

``` text
name
type
default
description
date added
removal condition
```

Flags are logged once at startup.

------------------------------------------------------------------------

# 17. TenantContext

Tenant context is a cross-cutting authorization object.

Conceptually:

``` text
TenantContext
├── user_id
├── tenant_id
├── membership_id
├── role_id
├── permissions
└── device_id
```

It is resolved from authenticated identity plus the requested tenant.

The tenant ID from a URL is only a selection hint.

It is NOT proof of access.

Flow:

``` text
JWT
 ↓
user identity
 ↓
requested tenant
 ↓
membership lookup
 ↓
membership active?
 ↓
permissions resolved
 ↓
TenantContext
```

------------------------------------------------------------------------

# 18. Authorization

Authorization is deny-by-default.

The service must explicitly require the permission for the use case.

Conceptually:

``` text
require_permission(
    tenant_context,
    "sales.create"
)
```

If the permission is absent:

``` text
deny
```

not:

``` text
allow unless explicitly blocked
```

Every authorization decision should generate structured audit/security
logging.

------------------------------------------------------------------------

# 19. Permission Registry

The permission registry should be centralized.

Initial permissions:

``` text
products.read
products.create
products.update
products.delete

inventory.read
inventory.stock_in
inventory.adjust
inventory.scan

sales.read
sales.create
sales.cancel

customers.read
customers.create
customers.update

expenses.read
expenses.create

reports.read

staff.read
staff.invite
staff.update
staff.remove

storefront.read
storefront.manage
```

Additional permissions should be added by domain module rather than
scattered across services.

------------------------------------------------------------------------

# 20. Authentication

Recommended initial mechanism:

``` text
JWT access token
+
secure refresh/session mechanism
```

Password hashing:

``` text
Argon2id
```

Do not implement cryptography manually.

Authentication errors should externally appear as:

``` text
invalid credentials
```

without revealing whether an account exists.

------------------------------------------------------------------------

# 21. Error Architecture

All application errors descend from one base error hierarchy.

Internal errors contain:

``` text
operation
entity
identifier
layer
correlation_id
cause chain
```

External errors contain:

``` text
error_code
safe message
correlation_id
```

Never expose:

``` text
stack trace
SQL
database schema
filesystem path
internal hostname
dependency exception
```

Example external response:

``` json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Invalid credentials.",
    "correlation_id": "..."
  }
}
```

------------------------------------------------------------------------

# 22. Correlation IDs

Use one request correlation ID.

Recommended header:

``` text
X-Correlation-ID
```

If supplied:

``` text
validate and use it according to the application's allowed format
```

If absent:

``` text
generate one
```

The ID must be available to:

``` text
middleware
router
service
CRUD
external integration
logger
error response
```

Never expose sensitive request context through the correlation ID
itself.

------------------------------------------------------------------------

# 23. Structured Logging

Logs should be structured.

Every important log event should include:

``` text
timestamp
level
correlation_id
operation
layer
tenant_id where safe
actor_id where safe
entity_id where safe
event
```

Never log:

``` text
password
password hash
JWT
refresh token
API key
private key
full request body containing secrets
unnecessary PII
```

Redaction belongs in the logging infrastructure.

------------------------------------------------------------------------

# 24. Middleware

Required middleware:

``` text
correlation_middleware.py
security_headers_middleware.py
rate_limit_middleware.py
error_handler_middleware.py
```

## Correlation

Creates/propagates correlation ID.

## Security headers

At minimum:

``` text
Strict-Transport-Security
Content-Security-Policy
X-Content-Type-Options
X-Frame-Options
Referrer-Policy
```

## Rate limiting

Must protect:

``` text
authentication
password reset
expensive endpoints
message-sending endpoints
```

Do not make rate limiting a security bypass.

## Error handling

All typed application errors are mapped centrally to HTTP responses.

------------------------------------------------------------------------

# 25. Database Setup

Use:

``` text
SQLAlchemy 2.x
async PostgreSQL driver
Alembic
```

The database connection lifecycle belongs in:

``` text
core/database.py
```

The composition root manages the engine lifecycle.

The rest of the application receives database capabilities through
injected abstractions.

------------------------------------------------------------------------

# 26. PostgreSQL

PostgreSQL is the authoritative transactional store.

Recommended baseline:

``` text
UUID identifiers
NUMERIC monetary values
TIMESTAMP WITH TIME ZONE
JSONB only where schema flexibility is justified
foreign keys
unique constraints
check constraints
indexes
transactions
```

Do not use:

``` text
floating-point money
JSON blobs for the entire business model
implicit tenant ownership
```

------------------------------------------------------------------------

# 27. Alembic

Alembic owns schema evolution.

Rules:

``` text
one migration for one coherent schema change
migrations committed to version control
never manually edit production schema
never delete old migrations merely to clean history
```

Initial migration order should follow domain dependencies:

``` text
users
tenants
permissions
roles
role_permissions
tenant_memberships
devices
categories
products
product_images
storefronts
inventory
inventory_movements
customers
sales
sale_items
payments
expenses
ledger_entries
sync_operations
sync_cursors
audit_events
```

The exact migration grouping can be adjusted during implementation.

------------------------------------------------------------------------

# 28. Multi-Tenant Database Enforcement

Repositories must always operate within tenant context.

Bad:

``` python
get_product(product_id)
```

for tenant-owned data if it can return another tenant's row.

Prefer:

``` python
get_product(
    tenant_id,
    product_id,
)
```

The service obtains `tenant_id` from trusted `TenantContext`.

It does not trust a body field to define ownership.

------------------------------------------------------------------------

# 29. Cross-Tenant Foreign Keys

Where appropriate, enforce tenant consistency at the database level.

Example:

``` text
products
    (id, tenant_id)

sale_items
    (product_id, tenant_id)
```

with a composite foreign key:

``` text
(product_id, tenant_id)
    →
products(id, tenant_id)
```

This prevents a record belonging to Tenant A from referencing a product
belonging to Tenant B.

Use this selectively where it meaningfully strengthens an invariant
without making the schema unnecessarily complex.

------------------------------------------------------------------------

# 30. RLS Strategy

PostgreSQL Row-Level Security is a defense-in-depth layer.

Do not treat it as a replacement for application authorization.

Target model:

``` text
JWT/authentication
+
TenantContext
+
service authorization
+
tenant-scoped CRUD
+
RLS where appropriate
```

RLS implementation should be added only after the connection/session
architecture can reliably establish the current tenant.

------------------------------------------------------------------------

# 31. External Integrations

External providers are isolated from domain services through
ports/adapters.

Initial integrations:

``` text
R2
WhatsApp click-to-chat
```

Future:

``` text
Paystack
Flutterwave
email
SMS
AI/LLM providers
maps
```

Core operations should remain functional if optional providers fail.

------------------------------------------------------------------------

# 32. Resilience

Apply resilience only at outbound failure boundaries.

Every outbound HTTP/API dependency gets:

``` text
timeout
circuit breaker
bulkhead/concurrency limit
bounded retry where safe
explicit fallback
observability
```

Never put circuit breakers around:

``` text
service → CRUD
CRUD → entity
service → service
```

Those are in-process calls, not external failure domains.

------------------------------------------------------------------------

# 33. R2 Integration

`integrations/storage/r2_client.py` owns R2-specific behavior.

It must not leak R2-specific implementation into:

``` text
ProductService
StorefrontService
```

Services should depend on an injected storage capability.

R2 operations require:

``` text
explicit timeout
retry only for safe/idempotent operations
circuit breaker
```

------------------------------------------------------------------------

# 34. WhatsApp Integration

Initial AHỊA WhatsApp integration is click-to-chat.

The adapter constructs:

``` text
wa.me
```

links with approved prefilled messages.

It does not require a full WhatsApp Business API.

The service should produce the intent/message data.

The integration layer produces the provider-specific link.

------------------------------------------------------------------------

# 35. AI Integration

AI is not part of the critical operational path.

Therefore:

``` text
sale
inventory
customer creation
product creation
staff access
```

must work without AI.

AI features such as:

``` text
demand forecasting
business questions
anomaly detection
recommendations
```

are optional dependencies.

When unavailable:

``` text
typed degraded result
```

not:

``` text
None
silent failure
fake result
```

------------------------------------------------------------------------

# 36. Initial Vertical Slice

The project-init preset says that initialization should contain one
complete demonstrative entity.

For AHỊA, use:

``` text
User
```

as the initial vertical slice.

Create:

``` text
models/entities/user_model.py
schemas/user_schema.py
crud/user_crud.py
services/user_service.py
routers/user_router.py
```

plus the required core/middleware/enforcement infrastructure.

The slice must be runnable.

No TODO stubs.

------------------------------------------------------------------------

# 37. User Slice Contract

The first demonstrative slice should support a minimal real operation:

``` text
GET /users/me
```

It should demonstrate:

``` text
authentication
TenantContext where relevant
service call
repository boundary
entity mapping
schema response
correlation ID
typed error handling
```

Do not build all AHỊA business functionality into the first slice.

The goal is to prove the architecture before multiplying it across
entities.

------------------------------------------------------------------------

# 38. Foundation Vertical Slices

After the demonstrative User slice passes:

``` text
Tenant
TenantMembership
Role
Permission
Device
```

should be implemented as real slices.

Then:

``` text
Category
Product
ProductImage
Storefront
```

Then inventory and sales.

This preserves the architecture while still moving toward the actual
product.

------------------------------------------------------------------------

# 39. Transactional Use Cases

Some AHỊA operations intentionally cross entity boundaries.

They must NOT be forced into one repository.

Examples:

## Complete sale

``` text
SalesService
 ├── SaleCrud
 ├── SaleItemCrud
 ├── PaymentCrud
 ├── InventoryCrud
 ├── InventoryMovementCrud
 ├── LedgerEntryCrud
 └── AuditEventCrud
```

## Receive stock

``` text
InventoryService
 ├── InventoryCrud
 ├── InventoryMovementCrud
 └── AuditEventCrud
```

## Cancel sale

``` text
SalesService
 ├── SaleCrud
 ├── InventoryMovementCrud
 ├── InventoryCrud
 ├── LedgerEntryCrud
 └── AuditEventCrud
```

The service owns the use-case orchestration.

------------------------------------------------------------------------

# 40. Offline Sync Boundary

Sync is a cross-cutting business capability.

Initial files:

``` text
schemas/sync_operation_schema.py
models/entities/sync_operation_model.py
crud/sync_operation_crud.py
services/sync_service.py
routers/sync_router.py
```

Additional change-feed persistence can be introduced as its own entity
when implemented.

The sync service handles:

``` text
operation authentication
tenant resolution
permission validation
idempotency
operation ordering
transaction execution
conflict classification
change-feed generation
```

------------------------------------------------------------------------

# 41. Idempotency

Every client-originated mutating operation receives:

``` text
operation_id UUID
```

The server must enforce uniqueness.

Example:

``` text
POST sale operation_id=ABC
    → creates sale

POST same sale operation_id=ABC
    → returns original result
```

Never blindly create another sale.

------------------------------------------------------------------------

# 42. Inventory Sync

Inventory must be synchronized through movements.

Do not synchronize:

``` text
quantity_on_hand = 7
```

as an isolated command.

Synchronize:

``` text
SALE -2
STOCK_RECEIVED +10
DAMAGE -1
```

The server calculates the resulting projection.

This is what allows offline workers to operate without destructive
latest-write-wins behavior.

------------------------------------------------------------------------

# 43. Testing Architecture

Tests mirror the source layers:

``` text
tests/
├── entities/
├── schemas/
├── crud/
├── services/
├── routers/
├── security/
├── tenancy/
├── sync/
└── architecture/
```

## Entity tests

Test:

``` text
domain invariants
value objects
enum behavior
```

## Schema tests

Test:

``` text
wire validation
serialization
invalid inputs
```

## CRUD tests

Mock or use an isolated database.

Test:

``` text
persistence behavior
tenant filters
mapping
```

## Service tests

Mock CRUD beneath the service.

Test:

``` text
business rules
authorization
transaction behavior
cross-entity coordination
```

## Router tests

Mock the service.

Test only:

``` text
request parsing
response shape
dependency wiring
HTTP behavior
```

------------------------------------------------------------------------

# 44. Security Tests

Mandatory tests include:

``` text
cross-tenant read denied
cross-tenant update denied
cross-tenant delete denied
permission denied
revoked device denied
inactive membership denied
invalid token denied
malformed token denied
duplicate operation rejected/deduplicated
```

Also test that external errors do not expose:

``` text
SQL
stack traces
filesystem paths
framework names
database details
```

------------------------------------------------------------------------

# 45. Architecture Enforcement

Use `import-linter`.

The architecture check must fail if:

``` text
entities import schemas
entities import CRUD
entities import services
entities import frameworks

CRUD imports services

services import routers

routers import CRUD
```

The exact contract configuration should be committed as:

``` text
import-linter.ini
```

and run locally and in CI.

------------------------------------------------------------------------

# 46. Secret Scanning

Use:

``` text
gitleaks
```

or an equivalent secret scanner.

Scan:

``` text
source
tests
configuration
git history where configured
```

Never commit:

``` text
DATABASE_URL with credentials
JWT secrets
R2 secrets
API keys
provider tokens
```

`.env.example` contains placeholders only.

------------------------------------------------------------------------

# 47. Dependency Security

Dependencies should be pinned through the chosen package/lock mechanism.

The project should run a vulnerability scan in CI.

Critical findings should fail the build.

Do not add a package merely because it is convenient.

Every dependency should have a reason.

------------------------------------------------------------------------

# 48. Code Hygiene

The project-init preset applies to the AHỊA codebase.

Therefore:

``` text
NO EMOJIS IN CODE
NO EMOJIS IN COMMENTS
NO EMOJIS IN DOCSTRINGS
NO EMOJIS IN LOGS
NO EMOJIS IN ERROR STRINGS
NO EMOJIS IN COMMIT MESSAGES
NO ASCII ART IN ENGINEERING OUTPUT
```

This does not prohibit Unicode in actual user-generated business data.

For example, the product must correctly support:

``` text
AHỊA
Igbo names
customer names
product descriptions
```

The engineering-artifact restriction is separate from runtime user data.

------------------------------------------------------------------------

# 49. No Generic Utility Dump

Do not create:

``` text
utils.py
helpers.py
common.py
misc.py
manager.py
```

unless the file represents a clearly defined cross-cutting
responsibility allowed by the architecture.

If functionality belongs to:

``` text
security
logging
resilience
configuration
storage
```

put it there.

If functionality belongs to:

``` text
inventory
sales
customers
```

put it in the appropriate domain slice.

------------------------------------------------------------------------

# 50. Docker

The backend should be containerized.

The image should:

``` text
install locked dependencies
run as a non-root user where practical
expose the application port
run Uvicorn
receive configuration through environment variables
```

Do not put secrets in the image.

Production command should be conceptually:

``` text
uvicorn ahia.main:app --host 0.0.0.0 --port $PORT
```

The exact process configuration can be adapted for Northflank.

------------------------------------------------------------------------

# 51. Local Development

The first local setup should support:

``` text
Python
PostgreSQL
FastAPI
Alembic
pytest
linting
architecture check
secret scanning
```

No Redis is required for the initial architecture.

No local AI model is required.

No external paid service is required to run the core backend.

------------------------------------------------------------------------

# 52. Environment Profiles

Use:

``` text
development
test
production
```

Do not scatter:

``` python
if os.getenv("ENV") == ...
```

throughout the application.

Configuration decides environment behavior centrally.

------------------------------------------------------------------------

# 53. Health Endpoints

Keep health checks intentionally narrow.

Recommended:

``` text
GET /health
GET /ready
```

Liveness should answer:

``` text
is the process alive?
```

Readiness may verify critical infrastructure such as the database.

Never expose:

``` text
database URL
dependency secrets
tenant counts
internal hostnames
stack traces
```

------------------------------------------------------------------------

# 54. API Versioning

Reserve the API namespace for future evolution.

Recommended:

``` text
/api/v1/...
```

Public storefront URLs do not need to mirror internal API versioning.

This allows the API contract to evolve without changing public links.

------------------------------------------------------------------------

# 55. Response Conventions

Successful endpoints should return predictable schemas.

Errors should use one standard envelope:

``` json
{
  "error": {
    "code": "SOME_ERROR_CODE",
    "message": "Safe message.",
    "correlation_id": "..."
  }
}
```

Do not return arbitrary dictionaries from different routers.

------------------------------------------------------------------------

# 56. Pagination

Collection endpoints should not return unlimited rows.

Use a consistent pagination strategy.

Initial options:

``` text
limit + cursor
```

or:

``` text
limit + offset
```

Cursor pagination is preferable for large/changeable datasets.

The implementation should standardize this before many list endpoints
are created.

------------------------------------------------------------------------

# 57. Soft Deactivation

For entities that need historical references:

``` text
is_active
```

or an explicit lifecycle state should be preferred over hard deletion.

Especially:

``` text
products
customers
users
memberships
```

Financial and audit records should normally be append-only or
compensating-event based.

------------------------------------------------------------------------

# 58. Observability

Initial observability should include:

``` text
structured logs
correlation IDs
request duration
error counts
authorization denials
external dependency failures
circuit breaker state
sync failures
```

Avoid logging raw business payloads.

Metrics can be expanded later.

------------------------------------------------------------------------

# 59. Initial API Surface

Foundation:

``` text
GET    /api/v1/users/me

POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout
```

Tenant:

``` text
POST   /api/v1/tenants
GET    /api/v1/tenants
GET    /api/v1/tenants/{tenant_id}
PATCH  /api/v1/tenants/{tenant_id}
```

Membership/staff:

``` text
POST   /api/v1/tenants/{tenant_id}/members
GET    /api/v1/tenants/{tenant_id}/members
PATCH  /api/v1/tenants/{tenant_id}/members/{membership_id}
DELETE /api/v1/tenants/{tenant_id}/members/{membership_id}
```

Catalog:

``` text
POST   /api/v1/tenants/{tenant_id}/products
GET    /api/v1/tenants/{tenant_id}/products
GET    /api/v1/tenants/{tenant_id}/products/{product_id}
PATCH  /api/v1/tenants/{tenant_id}/products/{product_id}
```

These are illustrative contracts. Exact routes should be finalized when
schemas are implemented.

------------------------------------------------------------------------

# 60. What Not To Build in the Scaffold

Do not prematurely build:

``` text
AI agents
community feed
supplier marketplace
advanced accounting
payment gateway integration
complex analytics
real-time WebSockets
microservices
Kubernetes
Redis
event broker
```

The architecture must be capable of growing into these systems without
requiring them now.

------------------------------------------------------------------------

# 61. Provider Portability

AHỊA should not become structurally dependent on:

``` text
Northflank
Neon
Cloudflare
OpenRouter
Paystack
Flutterwave
```

These are infrastructure/provider choices.

The domain should remain:

``` text
AHỊA
```

The adapter layer knows:

``` text
R2
payment provider
LLM provider
```

The service knows:

``` text
storage capability
payment capability
AI capability
```

not provider-specific implementation details.

------------------------------------------------------------------------

# 62. Build/Check Command

The project should expose one developer command that runs:

``` text
tests
architecture check
secret scan
lint
```

The exact tool runner can be:

``` text
make check
```

or a Python task runner.

The important requirement is one reproducible local command.

------------------------------------------------------------------------

# 63. Initialization Procedure

The actual implementation run should follow this order.

## Step 1 --- Inspect

Read:

``` text
existing repository
existing pyproject.toml
existing source tree
existing environment files
existing migrations
existing tests
```

Do not overwrite existing target files.

## Step 2 --- Resolve profile

Confirm:

``` text
Python
FastAPI
SQLAlchemy 2.x
Alembic
pytest
async PostgreSQL driver
```

## Step 3 --- Create skeleton

Create the architecture directories.

## Step 4 --- Create User slice

Create:

``` text
UserModel
UserSchema
UserCrud
UserService
UserRouter
```

## Step 5 --- Create core

Implement:

``` text
config
database
errors
logging
resilience
security
tenant context
container
```

## Step 6 --- Create middleware

Implement:

``` text
correlation
security headers
rate limiting
error handling
```

## Step 7 --- Wire application

Register:

``` text
UserRouter
middleware
exception handlers
startup/shutdown
```

## Step 8 --- Create enforcement

Add:

``` text
import-linter
secret scanning
dependency scanning
pre-commit
```

## Step 9 --- Tests

Mirror the architecture.

## Step 10 --- Run checks

Run:

``` text
pytest
architecture check
secret scan
lint
```

Do not report success unless the checks actually pass.

------------------------------------------------------------------------

# 64. Adding Future Entities

When adding `Product`:

1.  Read the User vertical slice.

2.  Copy its exact architectural shape.

3.  Create:

    ``` text
    product_model.py
    product_schema.py
    product_crud.py
    product_service.py
    product_router.py
    ```

4.  Add tests.

5.  Wire dependencies.

6.  Add migration.

7.  Run architecture/security checks.

Do not invent a second architecture for Product.

------------------------------------------------------------------------

# 65. Architecture Rule for Cross-Entity Workflows

The "one file per entity" rule does NOT mean every operation must belong
to an entity service.

If the business operation naturally spans entities, the service should
represent the use case.

Examples:

``` text
complete_sale
receive_stock
invite_staff_member
publish_storefront
synchronize_operations
```

The rule is:

> One responsibility per file, not one database table per business
> operation.

This prevents both giant entity services and giant repositories.

------------------------------------------------------------------------

# 66. Decision: No Generic `repository.py`

AHỊA will not create one giant repository abstraction containing every
entity.

Use:

``` text
user_crud.py
tenant_crud.py
product_crud.py
inventory_crud.py
sale_crud.py
```

This keeps persistence ownership explicit and satisfies the preset's
one-file-per-entity rule.

A small transaction/unit-of-work abstraction is allowed only for
coordinating atomic use cases.

------------------------------------------------------------------------

# 67. Decision: No Business Logic in SQLAlchemy Models

SQLAlchemy persistence records should not become a second business-logic
system.

Domain invariants belong to:

``` text
models/entities/
```

Business workflows belong to:

``` text
services/
```

Database constraints belong to:

``` text
PostgreSQL/Alembic
```

This creates three distinct enforcement levels:

``` text
Domain invariant
Business use-case rule
Database integrity constraint
```

------------------------------------------------------------------------

# 68. Decision: PostgreSQL Is Not Optional for Core Development

AHỊA's architecture is designed around PostgreSQL from the beginning.

Do not develop against:

``` text
SQLite as a fake production database
```

and later attempt a migration.

SQLite may still be useful for isolated mobile local storage, but the
server-side business database is PostgreSQL.

------------------------------------------------------------------------

# 69. Decision: Offline Is a Client Capability, Not a Server Shortcut

The backend remains authoritative.

The client may:

``` text
store locally
queue operations
optimistically update UI
sync periodically
```

The server must:

``` text
authenticate
authorize
validate
deduplicate
apply transaction
record changes
return reconciliation result
```

Offline support therefore does not weaken tenant isolation or
authorization.

------------------------------------------------------------------------

# 70. Final Scaffold Contract

The AHỊA backend is considered correctly scaffolded only when:

``` text
[OK] Five-layer architecture exists.
[OK] User vertical slice is complete.
[OK] Entities are framework-independent.
[OK] CRUD owns persistence.
[OK] Services own business logic.
[OK] Routers are thin.
[OK] TenantContext exists.
[OK] Authorization is deny-by-default.
[OK] Errors have internal/external views.
[OK] Correlation IDs are propagated.
[OK] Outbound resilience primitives exist.
[OK] Feature flags are centralized.
[OK] Security controls are never feature flagged.
[OK] PostgreSQL/Alembic are wired.
[OK] Architecture checks are executable.
[OK] Secret scanning is executable.
[OK] Tests mirror the layers.
[OK] No secrets are committed.
[OK] No engineering-artifact emojis/decorative symbols exist.
```

The next implementation step after this document is the actual backend
repository scaffold.

It should begin with the `User` demonstrative vertical slice, then
expand into the AHỊA foundation entities.
