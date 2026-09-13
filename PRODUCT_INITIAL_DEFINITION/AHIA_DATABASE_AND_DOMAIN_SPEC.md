# AHỊA --- Database & Domain Specification

**Document status:** Architecture baseline\
**Product:** AHỊA --- Multitenant Business Operating System for Informal
Commerce\
**Primary market:** Alaba International Market / Lagos / Nigeria\
**Backend:** Python + FastAPI\
**Database:** PostgreSQL\
**Object storage:** Cloudflare R2\
**Architecture:** Multi-tenant, offline-capable, permission-driven

------------------------------------------------------------------------

## 1. Purpose

This document translates the AHỊA product requirements into a concrete
database and domain model.

It defines:

-   core entities
-   relationships
-   tenant ownership
-   identifiers
-   constraints
-   indexes
-   permissions
-   inventory/event semantics
-   sales transaction boundaries
-   offline synchronization records
-   audit records
-   public/shareable identifiers
-   decisions that should remain flexible

This is an architecture document, not merely a list of SQL tables. The
schema must support the actual workflows described in the AHỊA PRD and
Project Specification.

------------------------------------------------------------------------

# 2. Architectural Principles

## 2.1 Every business is a tenant

A business/store is represented by a `tenant`.

A user is not a tenant.

A user may eventually belong to multiple tenants.

A tenant may have multiple users through memberships.

``` text
User
  │
  ├── Membership ──> Tenant
  │                     │
  │                     ├── Products
  │                     ├── Inventory
  │                     ├── Sales
  │                     ├── Customers
  │                     └── ...
```

## 2.2 Tenant ownership is explicit

Tenant-owned records should normally contain:

``` text
tenant_id UUID NOT NULL
```

This should not be inferred indirectly through another table whenever
direct ownership materially improves isolation and query safety.

Examples:

``` text
products.tenant_id
customers.tenant_id
sales.tenant_id
inventory_movements.tenant_id
audit_events.tenant_id
devices.tenant_id
```

## 2.3 Backend authorization is authoritative

Frontend permission checks are only UX.

The API must enforce:

1.  authenticated user
2.  active tenant membership
3.  permission
4.  tenant ownership
5.  record-level rules where applicable

Never trust:

``` text
tenant_id supplied by frontend
role supplied by frontend
permission supplied by frontend
device identity supplied without verification
```

## 2.4 Operational facts should be append-oriented

Sales, payments and inventory changes are business events.

Do not make the system depend on repeatedly overwriting a single
quantity field without preserving how that quantity changed.

Inventory therefore uses a movement ledger.

## 2.5 IDs

Use UUIDs for internal identifiers.

Recommended:

``` text
UUIDv4 or UUIDv7
```

UUIDv7 is preferable where supported because its time ordering can
improve index locality.

Public/shareable resources should additionally have non-guessable public
tokens or slugs.

------------------------------------------------------------------------

# 3. Domain Map

``` text
                         ┌──────────────┐
                         │     User     │
                         └──────┬───────┘
                                │
                         TenantMembership
                                │
                                ▼
                         ┌──────────────┐
                         │    Tenant    │
                         └──────┬───────┘
                                │
       ┌────────────────────────┼────────────────────────┐
       │                        │                        │
       ▼                        ▼                        ▼
   Storefront               Products                 Customers
       │                        │
       │                        ▼
       │                    Inventory
       │                        │
       │                 InventoryMovement
       │
       ▼
 Public Catalog

Tenant
  │
  ├── Sales ──> SaleItems ──> Products
  │     │
  │     └──> Payments
  │
  ├── Expenses ──> LedgerEntries
  │
  ├── Devices ──> SyncOperations
  │
  └── AuditEvents
```

------------------------------------------------------------------------

# 4. Identity Domain

## 4.1 User

Represents a person using AHỊA.

### Fields

  Field               Type        Constraints
  ------------------- ----------- -------------------------------------------
  id                  UUID        PK
  email               VARCHAR     nullable initially; unique when present
  phone               VARCHAR     nullable initially; normalized
  password_hash       VARCHAR     nullable for future OAuth/passkey options
  first_name          VARCHAR     NOT NULL
  last_name           VARCHAR     nullable
  is_active           BOOLEAN     NOT NULL, default true
  email_verified_at   TIMESTAMP   nullable
  phone_verified_at   TIMESTAMP   nullable
  created_at          TIMESTAMP   NOT NULL
  updated_at          TIMESTAMP   NOT NULL
  last_login_at       TIMESTAMP   nullable

### Rules

-   Never store plaintext passwords.
-   Normalize phone numbers before uniqueness checks.
-   Authentication identity is separate from tenant membership.
-   Deactivating a user must not delete their historical business
    activity.

------------------------------------------------------------------------

# 5. Tenant Domain

## 5.1 Tenant

Represents a business/workspace.

### Fields

  Field           Type        Constraints
  --------------- ----------- ---------------------------
  id              UUID        PK
  name            VARCHAR     NOT NULL
  slug            VARCHAR     NOT NULL, globally unique
  business_type   VARCHAR     nullable
  phone           VARCHAR     nullable
  email           VARCHAR     nullable
  address         TEXT        nullable
  city            VARCHAR     nullable
  state           VARCHAR     nullable
  country         VARCHAR     default `NG`
  currency        CHAR(3)     default `NGN`
  timezone        VARCHAR     default `Africa/Lagos`
  is_active       BOOLEAN     default true
  created_at      TIMESTAMP   NOT NULL
  updated_at      TIMESTAMP   NOT NULL

### Constraints

``` text
UNIQUE(slug)
```

The slug is used for public storefront URLs.

------------------------------------------------------------------------

# 6. Membership Domain

## 6.1 TenantMembership

Connects a user to a tenant.

### Fields

  Field        Type        Constraints
  ------------ ----------- ----------------------------------
  id           UUID        PK
  tenant_id    UUID        FK, NOT NULL
  user_id      UUID        FK, NOT NULL
  role_id      UUID        FK, NOT NULL
  status       ENUM        active/invited/suspended/removed
  joined_at    TIMESTAMP   nullable
  created_at   TIMESTAMP   NOT NULL
  updated_at   TIMESTAMP   NOT NULL

### Constraint

``` text
UNIQUE(tenant_id, user_id)
```

This is the fundamental tenant-access relationship.

------------------------------------------------------------------------

# 7. Roles & Permissions

AHỊA uses permission-based authorization.

Roles are bundles of permissions.

## 7.1 Permission

Permissions are stable application capabilities.

Examples:

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

staff.read
staff.invite
staff.update
staff.remove

storefront.read
storefront.manage

reports.read
```

### Permission fields

  Field         Type
  ------------- ----------------
  id            UUID
  code          VARCHAR UNIQUE
  description   TEXT
  module        VARCHAR

Permissions are application-defined rather than arbitrary strings
entered by tenants.

## 7.2 Role

  Field            Type
  ---------------- ---------------
  id               UUID
  tenant_id        UUID nullable
  name             VARCHAR
  description      TEXT
  is_system_role   BOOLEAN
  created_at       TIMESTAMP
  updated_at       TIMESTAMP

System roles may include:

``` text
OWNER
SALES
INVENTORY
MANAGER
```

Tenant-specific custom roles can be supported later.

## 7.3 RolePermission

Many-to-many relation:

``` text
role_id
permission_id
```

Constraint:

``` text
UNIQUE(role_id, permission_id)
```

### Important rule

Do not write:

``` python
if user.role == "owner":
    ...
```

throughout the application.

Instead:

``` python
require_permission("inventory.adjust")
```

The OWNER role gets broad permissions through role configuration.

------------------------------------------------------------------------

# 8. Device Domain

## 8.1 Device

A device is an identity for synchronization, security and auditing.

It does NOT determine what the user is allowed to do.

### Fields

  Field               Type
  ------------------- --------------------
  id                  UUID
  tenant_id           UUID
  user_id             UUID
  device_identifier   VARCHAR
  device_name         VARCHAR nullable
  platform            VARCHAR
  app_version         VARCHAR nullable
  last_seen_at        TIMESTAMP
  revoked_at          TIMESTAMP nullable
  created_at          TIMESTAMP

### Constraint

``` text
UNIQUE(tenant_id, device_identifier)
```

A user can therefore use:

-   phone
-   tablet
-   laptop
-   desktop
-   another phone

without changing their role.

------------------------------------------------------------------------

# 9. Storefront Domain

## 9.1 Storefront

One tenant initially has one public storefront.

### Fields

  Field               Type
  ------------------- --------------------
  id                  UUID
  tenant_id           UUID UNIQUE
  display_name        VARCHAR
  description         TEXT nullable
  logo_object_key     VARCHAR nullable
  banner_object_key   VARCHAR nullable
  theme               VARCHAR nullable
  is_published        BOOLEAN
  published_at        TIMESTAMP nullable
  created_at          TIMESTAMP
  updated_at          TIMESTAMP

Object keys point to R2.

The database does not store image binaries.

## 9.2 Product public identity

Products should have:

``` text
id UUID
slug VARCHAR
public_token UUID/random token
```

The slug is human-readable.

The public token prevents enumeration where appropriate.

------------------------------------------------------------------------

# 10. Catalog Domain

## 10.1 Category

  Field         Type
  ------------- ---------------
  id            UUID
  tenant_id     UUID
  name          VARCHAR
  slug          VARCHAR
  description   TEXT nullable
  created_at    TIMESTAMP
  updated_at    TIMESTAMP

Constraint:

``` text
UNIQUE(tenant_id, slug)
```

## 10.2 Product

  Field                 Type            Notes
  --------------------- --------------- ---------------
  id                    UUID            PK
  tenant_id             UUID            required
  category_id           UUID            nullable
  name                  VARCHAR         required
  slug                  VARCHAR         tenant-scoped
  description           TEXT            nullable
  sku                   VARCHAR         nullable
  barcode               VARCHAR         nullable
  selling_price         NUMERIC(18,2)   required
  cost_price            NUMERIC(18,2)   nullable
  low_stock_threshold   NUMERIC(18,3)   default 0
  is_active             BOOLEAN         default true
  is_published          BOOLEAN         default false
  public_token          VARCHAR         unique
  created_at            TIMESTAMP       required
  updated_at            TIMESTAMP       required

### Constraints

``` text
UNIQUE(tenant_id, slug)
UNIQUE(tenant_id, sku) WHERE sku IS NOT NULL
UNIQUE(tenant_id, barcode) WHERE barcode IS NOT NULL
UNIQUE(public_token)
```

Prices should use numeric types, never floating point.

------------------------------------------------------------------------

# 11. Product Images

## 11.1 ProductImage

  Field          Type
  -------------- -----------
  id             UUID
  tenant_id      UUID
  product_id     UUID
  object_key     VARCHAR
  content_type   VARCHAR
  file_size      BIGINT
  sort_order     INTEGER
  is_primary     BOOLEAN
  created_at     TIMESTAMP

The actual file lives in R2.

### Storage path convention

``` text
tenants/{tenant_id}/products/{product_id}/{image_id}
```

Never allow arbitrary client-provided object keys.

------------------------------------------------------------------------

# 12. Inventory Domain

Inventory is ledger-driven.

## 12.1 Inventory

This is the current materialized inventory state for a product.

  Field               Type
  ------------------- ---------------------------
  id                  UUID
  tenant_id           UUID
  product_id          UUID UNIQUE within tenant
  quantity_on_hand    NUMERIC(18,3)
  reserved_quantity   NUMERIC(18,3)
  version             BIGINT
  created_at          TIMESTAMP
  updated_at          TIMESTAMP

The quantity is a projection.

The authoritative history is the movement ledger.

## 12.2 InventoryMovement

  Field             Type
  ----------------- ------------------
  id                UUID
  tenant_id         UUID
  product_id        UUID
  movement_type     ENUM
  quantity_delta    NUMERIC(18,3)
  quantity_before   NUMERIC(18,3)
  quantity_after    NUMERIC(18,3)
  reference_type    VARCHAR nullable
  reference_id      UUID nullable
  actor_id          UUID
  device_id         UUID nullable
  operation_id      UUID nullable
  occurred_at       TIMESTAMP
  created_at        TIMESTAMP
  note              TEXT nullable

Movement types:

``` text
STOCK_INITIALIZED
STOCK_RECEIVED
SALE
RETURN
DAMAGE
ADJUSTMENT
TRANSFER
SHIPMENT_OUT
SHIPMENT_IN
```

### Critical invariant

For a movement:

``` text
quantity_after = quantity_before + quantity_delta
```

The service must calculate and validate this inside the database
transaction.

------------------------------------------------------------------------

# 13. Inventory Concurrency

Two workers may sell offline at the same time.

Example:

``` text
Server inventory = 10

Worker A offline:
SALE -3

Worker B offline:
SALE -4
```

After synchronization:

``` text
10 - 3 - 4 = 3
```

The system must not resolve this by blindly choosing the latest
quantity.

Each sale becomes an operation/movement.

If the resulting quantity violates a business rule, such as disallowing
negative stock, the sync service returns a business conflict.

Possible policies:

``` text
ALLOW_NEGATIVE_STOCK
BLOCK_NEGATIVE_STOCK
ALLOW_WITH_WARNING
```

This should be tenant-configurable later.

------------------------------------------------------------------------

# 14. Sales Domain

## 14.1 Sale

Represents one completed or cancelled transaction.

  Field             Type
  ----------------- ---------------
  id                UUID
  tenant_id         UUID
  receipt_number    VARCHAR
  customer_id       UUID nullable
  subtotal          NUMERIC(18,2)
  discount_amount   NUMERIC(18,2)
  total_amount      NUMERIC(18,2)
  status            ENUM
  payment_status    ENUM
  seller_id         UUID
  device_id         UUID nullable
  operation_id      UUID nullable
  occurred_at       TIMESTAMP
  created_at        TIMESTAMP
  updated_at        TIMESTAMP

Suggested statuses:

``` text
COMPLETED
CANCELLED
```

Suggested payment statuses:

``` text
UNPAID
PARTIALLY_PAID
PAID
```

## 14.2 SaleItem

  Field                   Type
  ----------------------- ---------------
  id                      UUID
  tenant_id               UUID
  sale_id                 UUID
  product_id              UUID
  product_name_snapshot   VARCHAR
  unit_price              NUMERIC(18,2)
  quantity                NUMERIC(18,3)
  discount_amount         NUMERIC(18,2)
  line_total              NUMERIC(18,2)

### Why snapshot product name?

If a product is renamed tomorrow, an old receipt should still show what
was sold at the time.

Historical sales should not depend on today's product metadata.

------------------------------------------------------------------------

# 15. Payment Domain

## 15.1 Payment

  Field         Type
  ------------- ------------------
  id            UUID
  tenant_id     UUID
  sale_id       UUID
  amount        NUMERIC(18,2)
  method        ENUM
  reference     VARCHAR nullable
  status        ENUM
  received_at   TIMESTAMP
  created_at    TIMESTAMP

Initial methods:

``` text
CASH
BANK_TRANSFER
OTHER
```

Future:

``` text
PAYSTACK
FLUTTERWAVE
CARD
```

External payment integrations are optional.

Core sales must not depend on them.

------------------------------------------------------------------------

# 16. Sale Transaction Boundary

Completing a sale should be one database transaction.

Conceptually:

``` text
BEGIN

validate tenant
validate permission
validate products
validate inventory
create sale
create sale items
create payment(s)
create inventory movement(s)
update inventory projection
create ledger entry if applicable
create audit event

COMMIT
```

If any critical operation fails:

``` text
ROLLBACK
```

Never create a sale successfully while its inventory movement silently
fails.

------------------------------------------------------------------------

# 17. Customer Domain

## 17.1 Customer

  Field              Type
  ------------------ ------------------
  id                 UUID
  tenant_id          UUID
  name               VARCHAR
  phone              VARCHAR nullable
  email              VARCHAR nullable
  address            TEXT nullable
  notes              TEXT nullable
  marketing_opt_in   BOOLEAN
  is_active          BOOLEAN
  created_at         TIMESTAMP
  updated_at         TIMESTAMP

Customer data belongs to the tenant.

A customer record in one tenant is not automatically visible to another
tenant.

------------------------------------------------------------------------

# 18. Expense Domain

## 18.1 Expense

  Field            Type
  ---------------- ---------------
  id               UUID
  tenant_id        UUID
  category         VARCHAR
  amount           NUMERIC(18,2)
  description      TEXT nullable
  payment_method   ENUM
  incurred_at      TIMESTAMP
  actor_id         UUID
  device_id        UUID nullable
  operation_id     UUID nullable
  created_at       TIMESTAMP

Examples:

``` text
TRANSPORT
ELECTRICITY
RENT
STAFF
PACKAGING
OTHER
```

Do not overbuild accounting before operational sales/inventory workflows
work.

------------------------------------------------------------------------

# 19. Ledger Domain

## 19.1 LedgerEntry

A normalized financial record can be introduced to support reports.

  Field            Type
  ---------------- ---------------
  id               UUID
  tenant_id        UUID
  entry_type       VARCHAR
  direction        ENUM
  amount           NUMERIC(18,2)
  reference_type   VARCHAR
  reference_id     UUID
  occurred_at      TIMESTAMP
  created_at       TIMESTAMP

Examples:

``` text
SALE_REVENUE
EXPENSE
REFUND
```

The ledger should be derived from transactional facts where possible
rather than manually edited.

------------------------------------------------------------------------

# 20. Offline Synchronization Domain

Offline support is not simply "save locally and upload later."

The client maintains a durable operation queue.

## 20.1 SyncOperation

  Field            Type
  ---------------- --------------------
  id               UUID
  tenant_id        UUID
  actor_id         UUID
  device_id        UUID
  operation_id     UUID UNIQUE
  operation_type   VARCHAR
  entity_type      VARCHAR
  entity_id        UUID
  payload          JSONB
  occurred_at      TIMESTAMP
  received_at      TIMESTAMP nullable
  processed_at     TIMESTAMP nullable
  status           ENUM
  retry_count      INTEGER
  error_code       VARCHAR nullable
  error_message    TEXT nullable

Statuses:

``` text
PENDING
PROCESSING
APPLIED
REJECTED
CONFLICT
```

## 20.2 Idempotency

Every mutating client operation receives a unique:

``` text
operation_id
```

If the same operation arrives twice:

``` text
first request  -> apply
second request -> return existing result
```

This prevents duplicate sales caused by retries or flaky connections.

------------------------------------------------------------------------

# 21. Sync Semantics

## 21.1 Transactional operations

These should be operation-based:

``` text
SALE
PAYMENT
STOCK_RECEIVED
RETURN
DAMAGE
EXPENSE
```

Do not use simple LWW.

## 21.2 Mutable metadata

LWW/versioned merging can be appropriate for lower-risk fields:

``` text
product.description
product.name
storefront.description
customer.notes
```

Metadata should carry enough information to identify:

``` text
version
updated_at
actor_id
device_id
```

## 21.3 High-value conflicts

For fields where silent overwrite is dangerous:

``` text
selling_price
cost_price
bank/payment references
business settings
```

the service may return an explicit conflict requiring user resolution.

------------------------------------------------------------------------

# 22. Sync Protocol

Recommended conceptual API:

``` text
POST /sync/push
POST /sync/pull
```

Push:

``` text
client operations
    ↓
authenticate
    ↓
resolve tenant membership
    ↓
check permission
    ↓
check operation_id
    ↓
validate payload
    ↓
execute transaction
    ↓
return operation result
```

Pull:

``` text
client cursor
    ↓
server returns changes after cursor
    ↓
client applies changes
    ↓
client advances cursor
```

## 22.1 Sync Cursor

Per-device cursor:

  Field                  Type
  ---------------------- -----------
  id                     UUID
  tenant_id              UUID
  device_id              UUID
  last_server_sequence   BIGINT
  updated_at             TIMESTAMP

A monotonically increasing server sequence is preferable to relying only
on timestamps.

------------------------------------------------------------------------

# 23. Server Change Feed

For reliable pull synchronization, server-side changes should have an
ordering mechanism.

Recommended:

``` text
change_sequence BIGINT
```

on a change/outbox table.

Example:

``` text
change_sequence = 1001
change_sequence = 1002
change_sequence = 1003
```

The client asks:

``` text
give me changes after 1000
```

The server returns:

``` text
1001...
```

This avoids clock-skew problems.

------------------------------------------------------------------------

# 24. Audit Domain

## 24.1 AuditEvent

Audit events record important actions.

  Field          Type
  -------------- ---------------
  id             UUID
  tenant_id      UUID
  actor_id       UUID nullable
  device_id      UUID nullable
  action         VARCHAR
  entity_type    VARCHAR
  entity_id      UUID nullable
  operation_id   UUID nullable
  metadata       JSONB
  ip_address     INET nullable
  user_agent     TEXT nullable
  created_at     TIMESTAMP

Examples:

``` text
PRODUCT_CREATED
PRODUCT_UPDATED
STOCK_ADJUSTED
SALE_CREATED
SALE_CANCELLED
STAFF_INVITED
STAFF_ROLE_CHANGED
STOREfront_PUBLISHED
DEVICE_REVOKED
```

Audit records should generally be append-only.

------------------------------------------------------------------------

# 25. Public Sharing Domain

Public resources must be separated from private resource access.

Examples:

``` text
/shop/{tenant_slug}
/shop/{tenant_slug}/product/{product_slug}
/share/invoice/{public_token}
/share/shipment/{public_token}
/share/report/{public_token}
```

Public URLs must not expose:

``` text
internal UUID enumeration
private customer information
private inventory levels
staff permissions
internal audit data
private financial data
```

Use opaque public tokens for sensitive-but-shareable artifacts.

------------------------------------------------------------------------

# 26. QR Codes

QR codes should encode stable URLs or public identifiers.

Example:

``` text
https://ahia.app/shop/example/product/iphone-15
```

or:

``` text
https://ahia.app/share/shipment/<opaque-token>
```

Do not put sensitive raw database state into the QR payload.

The QR is a transport mechanism, not an authorization mechanism.

------------------------------------------------------------------------

# 27. R2 Object Storage

PostgreSQL stores metadata.

Cloudflare R2 stores:

``` text
product images
store logos
store banners
receipts
invoices
reports
documents
future attachments
```

Suggested object-key hierarchy:

``` text
tenants/
  {tenant_id}/
    storefront/
    products/
      {product_id}/
    documents/
    reports/
    receipts/
```

The API must validate:

-   MIME type
-   extension
-   file size
-   tenant ownership
-   upload authorization

Never trust a client-supplied object path.

------------------------------------------------------------------------

# 28. PostgreSQL Constraints

Every tenant-owned foreign key should be evaluated for cross-tenant
safety.

Example problem:

``` text
sale.tenant_id = A
sale_item.product_id = product belonging to B
```

Application code must prevent this.

Where practical, composite uniqueness/foreign-key patterns can reinforce
the invariant.

Example:

``` text
products:
UNIQUE(id, tenant_id)

sale_items:
(product_id, tenant_id)
    → products(id, tenant_id)
```

This is stronger than relying exclusively on application logic.

------------------------------------------------------------------------

# 29. Index Strategy

Initial indexes should focus on real access patterns.

## Tenant

``` text
UNIQUE(slug)
```

## Membership

``` text
INDEX(user_id)
INDEX(tenant_id)
UNIQUE(tenant_id, user_id)
```

## Products

``` text
INDEX(tenant_id)
INDEX(tenant_id, category_id)
INDEX(tenant_id, is_active)
INDEX(tenant_id, is_published)
UNIQUE(tenant_id, slug)
```

## Inventory

``` text
UNIQUE(tenant_id, product_id)
INDEX(tenant_id)
```

## InventoryMovement

``` text
INDEX(tenant_id, product_id, occurred_at)
INDEX(tenant_id, occurred_at)
INDEX(operation_id)
```

## Sales

``` text
INDEX(tenant_id, occurred_at)
INDEX(tenant_id, seller_id, occurred_at)
INDEX(tenant_id, customer_id)
UNIQUE(tenant_id, receipt_number)
```

## Customers

``` text
INDEX(tenant_id)
INDEX(tenant_id, phone)
```

## SyncOperation

``` text
UNIQUE(operation_id)
INDEX(tenant_id, device_id, status)
INDEX(tenant_id, created_at)
```

## AuditEvent

``` text
INDEX(tenant_id, created_at)
INDEX(tenant_id, actor_id, created_at)
INDEX(tenant_id, entity_type, entity_id)
```

------------------------------------------------------------------------

# 30. PostgreSQL Row-Level Security

Application-level tenant filtering is mandatory.

PostgreSQL RLS can provide another isolation layer.

The design should leave room for policies such as:

``` sql
tenant_id = current_setting('app.current_tenant_id')::uuid
```

RLS should be introduced deliberately.

Do not enable RLS everywhere before the connection/session architecture
is correctly designed.

The invariant is:

``` text
application authorization
+
tenant-scoped repository queries
+
database-level safeguards where appropriate
```

not "RLS magically solves multitenancy."

------------------------------------------------------------------------

# 31. Tenant Context

Every authenticated request should resolve a tenant context.

Conceptually:

``` text
Authenticated User
       ↓
Requested Tenant
       ↓
Membership lookup
       ↓
Active membership?
       ↓
Permission evaluation
       ↓
TenantContext
```

A service should receive an explicit tenant context rather than querying
global data blindly.

Example conceptual object:

``` text
TenantContext
├── user_id
├── tenant_id
├── membership_id
├── role_id
├── permissions
└── device_id
```

------------------------------------------------------------------------

# 32. Repository / CRUD Rules

CRUD/repository modules are persistence adapters.

They may:

-   query
-   insert
-   update
-   delete where allowed
-   load relationships
-   persist transaction state

They must not decide:

``` text
whether user is allowed
whether a sale is valid
whether stock may go negative
whether a storefront can publish
how a sync conflict is resolved
```

Those decisions belong in services/domain logic.

------------------------------------------------------------------------

# 33. Service Rules

Services orchestrate business operations.

Examples:

``` text
AuthService
TenantService
MembershipService
PermissionService
ProductService
InventoryService
SalesService
CustomerService
StorefrontService
SyncService
AuditService
```

A service may coordinate multiple repositories.

Example:

``` text
SalesService.complete_sale()

    ProductRepository
    InventoryRepository
    SaleRepository
    PaymentRepository
    AuditRepository
```

inside one transaction.

------------------------------------------------------------------------

# 34. Router Rules

Routers should remain thin.

Good:

``` text
POST /sales
    ↓
authenticate
    ↓
authorize
    ↓
SalesService.complete_sale()
    ↓
response
```

Bad:

``` text
POST /sales
    ↓
query product
    ↓
calculate inventory
    ↓
create sale
    ↓
create payment
    ↓
write audit
    ↓
handle conflicts
    ↓
...
```

That logic belongs in services.

------------------------------------------------------------------------

# 35. Deletion Strategy

Business-critical historical data should rarely be hard-deleted.

Examples:

``` text
Sale
Payment
InventoryMovement
AuditEvent
LedgerEntry
```

Prefer statuses/tombstones where appropriate.

Products and customers may be deactivated:

``` text
is_active = false
```

rather than destroying historical references.

------------------------------------------------------------------------

# 36. Cancellation Semantics

A sale cancellation must not simply delete the sale.

Instead:

``` text
Sale status → CANCELLED
```

and create compensating inventory/financial events where required.

Example:

``` text
SALE
quantity -2

CANCELLATION
quantity +2
```

The original sale remains auditable.

------------------------------------------------------------------------

# 37. Referential Integrity

Use foreign keys for internal relationships.

Important examples:

``` text
membership.tenant_id → tenant.id
membership.user_id → user.id

product.tenant_id → tenant.id
product.category_id → category.id

inventory.product_id → product.id
inventory.tenant_id → tenant.id

sale.customer_id → customer.id
sale.tenant_id → tenant.id

sale_item.sale_id → sale.id
sale_item.product_id → product.id

payment.sale_id → sale.id
```

Do not casually use cascading deletes for financial/history tables.

------------------------------------------------------------------------

# 38. Initial Database Boundary

The first production schema should contain:

``` text
users
tenants
tenant_memberships
roles
permissions
role_permissions
devices

storefronts

categories
products
product_images

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

This is enough to support the initial operational core without
prematurely creating every future module.

------------------------------------------------------------------------

# 39. Future Tables

Later modules can introduce:

``` text
suppliers
supplier_contacts
purchase_orders
purchase_order_items

shipments
shipment_items
shipment_events

notifications

reports

community_groups
community_posts
community_replies
classified_listings

reputation_profiles
reputation_events
```

Do not create these merely because the PRD mentions them.

Create them when their workflows are ready.

------------------------------------------------------------------------

# 40. Initial Module Dependency Graph

``` text
AUTH
  ↓
TENANT
  ↓
MEMBERSHIP
  ↓
ROLES/PERMISSIONS
  ↓
DEVICES
  ↓
PRODUCTS
  ↓
INVENTORY
  ↓
CUSTOMERS
  ↓
SALES
  ↓
PAYMENTS
  ↓
LEDGER
```

Storefront can consume:

``` text
TENANT
PRODUCTS
PRODUCT_IMAGES
```

Sync cuts across operational modules:

``` text
PRODUCTS
INVENTORY
CUSTOMERS
SALES
EXPENSES
```

Audit cuts across almost everything.

------------------------------------------------------------------------

# 41. Initial API Resource Boundaries

Suggested routers:

``` text
/auth
/tenants
/memberships
/roles
/permissions
/devices

/products
/categories
/inventory
/sales
/customers
/expenses

/storefront
/sync
```

Public:

``` text
/shop/{slug}
/shop/{slug}/products/{product_slug}
/share/{resource}/{token}
```

The exact URL structure can change without changing the domain model.

------------------------------------------------------------------------

# 42. Transaction Boundaries

The following operations must be transactional:

### Complete sale

``` text
sale
+ sale items
+ payment
+ inventory movements
+ inventory projection
+ ledger
```

### Stock receipt

``` text
inventory movement
+ inventory projection
+ audit
```

### Sale cancellation

``` text
sale status
+ compensating inventory movement
+ financial reversal
+ audit
```

### Staff role change

``` text
membership role
+ audit
```

### Sync operation

``` text
idempotency check
+ domain operation
+ change record
+ audit
```

------------------------------------------------------------------------

# 43. Outbox / Change Capture

For reliable synchronization, the architecture should eventually use an
outbox/change table.

Conceptually:

``` text
Business transaction
      │
      ├── domain state
      │
      └── change event
```

Both commit together.

This prevents:

``` text
database updated
BUT
sync change forgotten
```

The change feed can then publish committed changes to clients.

------------------------------------------------------------------------

# 44. Conflict Resolution Matrix

  Entity                   Strategy
  ------------------------ ----------------------------------
  Sale                     operation-based
  Payment                  operation-based + idempotency
  Inventory movement       operation-based
  Expense                  operation-based
  Product metadata         version/LWW where safe
  Product price            versioned conflict handling
  Customer notes           version/LWW acceptable initially
  Storefront description   version/LWW
  Staff permissions        server-authoritative
  Tenant settings          versioned conflict handling
  Audit event              append-only

------------------------------------------------------------------------

# 45. Security Invariants

The system must enforce:

``` text
A user cannot access a tenant they are not a member of.

A user cannot access another tenant's records by changing an ID.

A device cannot grant permissions.

A frontend cannot grant permissions.

A public token cannot expose private tenant data.

A failed transaction cannot partially create a sale.

A retried operation cannot duplicate a sale.

A cancelled sale cannot disappear from history.

An inventory quantity cannot change without an auditable movement.
```

These should become automated tests.

------------------------------------------------------------------------

# 46. Multi-Tenant Test Cases

Before production, tests should explicitly attempt:

### Cross-tenant product access

``` text
User A
Tenant A
requests Product B
→ 404/403
```

### Cross-tenant sale modification

``` text
User A
Tenant A
requests Sale B
→ rejected
```

### Cross-tenant customer access

``` text
User A
Tenant A
requests Customer B
→ rejected
```

### Permission bypass

``` text
SALES user
POST /inventory/adjust
→ rejected
```

### Device spoofing

``` text
unknown/revoked device
sync
→ rejected
```

### Duplicate sync

``` text
same operation_id twice
→ one business operation
```

### Concurrent stock operations

``` text
two offline sales
→ both represented as operations
→ deterministic resulting inventory
```

------------------------------------------------------------------------

# 47. Data Lifecycle

## Active

Normal operational records.

## Archived

Optional future state for old data.

## Deleted/deactivated

Only where safe.

Historical financial and inventory records should remain available for
audit.

------------------------------------------------------------------------

# 48. What Is Deliberately Not Locked Yet

These decisions should remain open until implementation requires them:

### Authentication methods

Possible:

``` text
email/password
phone/password
OTP
passkeys
OAuth
```

The identity model supports future expansion.

### Custom roles

System roles are enough initially.

Custom tenant roles can follow.

### Accounting depth

The initial ledger should support operational reporting without
pretending to be a complete accounting package.

### Payment integrations

Paystack/Flutterwave should be adapters, not core dependencies.

### RLS rollout

The schema should support it, but implementation should follow the
actual DB session architecture.

### Sync transport

HTTP push/pull is sufficient initially.

WebSocket/realtime can be added later if justified.

------------------------------------------------------------------------

# 49. Architecture Decisions --- Locked

The following are considered baseline decisions:

1.  PostgreSQL is the primary transactional database.
2.  AHỊA is multitenant from the beginning.
3.  Tenant ownership is explicit on tenant-owned records.
4.  UUIDs are used for internal IDs.
5.  Money uses `NUMERIC`, never floating point.
6.  Inventory is movement/ledger based.
7.  Sales are transactional.
8.  Sync uses unique operation IDs for idempotency.
9.  Transactional operations are merged by operation/event semantics,
    not naive LWW.
10. Permissions are modular and backend-enforced.
11. Roles are permission bundles.
12. Devices are for identity/sync/security/audit, not authorization.
13. R2 stores binaries; PostgreSQL stores metadata.
14. Historical financial/inventory records are not casually deleted.
15. Public sharing uses stable slugs/tokens and never bypasses private
    authorization.
16. Core operations do not depend on AI or third-party payment
    providers.

------------------------------------------------------------------------

# 50. Implementation Order

The database implementation should proceed in this order:

## Phase 1 --- Foundation

``` text
User
Tenant
TenantMembership
Role
Permission
RolePermission
Device
```

## Phase 2 --- Catalog

``` text
Category
Product
ProductImage
Storefront
```

## Phase 3 --- Inventory

``` text
Inventory
InventoryMovement
```

## Phase 4 --- Customers & Sales

``` text
Customer
Sale
SaleItem
Payment
```

## Phase 5 --- Financial records

``` text
Expense
LedgerEntry
```

## Phase 6 --- Offline synchronization

``` text
SyncOperation
SyncCursor
Change/Outbox table
```

## Phase 7 --- Auditing

``` text
AuditEvent
```

## Phase 8 --- Future operational modules

``` text
Supplier
Procurement
Shipment
Tracking
CRM expansion
Reports
Network
```

------------------------------------------------------------------------

# 51. Final Domain Invariant

The most important architectural rule is:

> AHỊA should treat the server database as the authoritative shared
> business state while allowing clients to optimistically perform safe
> work offline through durable operations that can be replayed,
> deduplicated, validated and merged.

That gives AHỊA:

``` text
MULTITENANCY
+
PERMISSIONED ACCESS
+
AUDITABILITY
+
OFFLINE OPERATION
+
SAFE SYNCHRONIZATION
+
TRANSACTIONAL SALES
+
LEDGER-BASED INVENTORY
```

without forcing the first release to become an unnecessarily distributed
system.

------------------------------------------------------------------------

# 52. Next Engineering Artifact

Before generating the full application implementation, the next concrete
artifact should be:

``` text
AHIA_BACKEND_SCAFFOLD_SPEC.md
```

It should define:

-   exact backend directory tree
-   Python package boundaries
-   SQLAlchemy base setup
-   Alembic configuration
-   configuration/environment variables
-   database session lifecycle
-   dependency injection
-   authentication dependencies
-   TenantContext
-   permission dependency design
-   repository interfaces
-   service interfaces
-   exception hierarchy
-   API response/error conventions
-   logging/request IDs
-   test structure
-   Docker setup
-   initial migration strategy

After that, implementation can begin with the foundation domain rather
than rewriting architecture later.
