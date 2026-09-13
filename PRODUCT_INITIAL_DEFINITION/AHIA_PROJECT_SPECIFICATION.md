# AHỊA --- Product & Engineering Project Specification

**Status:** Living product specification\
**Product:** AHỊA\
**Primary market:** Informal and small-to-medium businesses in Nigeria,
starting with Alaba International Market, Lagos\
**Architecture:** Multi-tenant, offline-first, API-driven\
**Backend:** FastAPI + PostgreSQL\
**Trader mobile:** React Native + Expo\
**Web:** Next.js + TypeScript\
**Object storage:** Cloudflare R2\
**Initial API deployment:** Northflank\
**Database direction:** Neon PostgreSQL\
**Core principle:** The application must improve existing trading
workflows rather than forcing traders to abandon WhatsApp, cash, bank
transfers, or familiar operating habits.

------------------------------------------------------------------------

# 1. Product Overview

AHỊA is a multi-tenant business operating system designed for informal
traders and small businesses whose operations are currently distributed
across notebooks, WhatsApp chats, spreadsheets, memory, paper receipts,
and multiple phones.

The initial target is electronics and appliance traders in Alaba
International Market, Lagos.

The product is mobile-first, but **not mobile-only**. AHỊA will provide:

-   A full native-capable mobile application.
-   A full web application.
-   Public web storefronts that work without customer authentication.
-   Installable application experiences where appropriate.
-   A future desktop application option without making the web app a
    mere wrapper.
-   Offline-first operation with periodic synchronization.
-   Multi-user businesses where any authorized user can use any
    supported device.
-   Centralized permissions inspired by AWS IAM.
-   Strict tenant isolation.
-   Shareable business artifacts throughout the product.

AHỊA is not intended to replace WhatsApp. WhatsApp remains a major
communication channel. AHỊA becomes the operational system around the
conversations.

------------------------------------------------------------------------

# 2. Core Problem

Many informal businesses already have digital tools, but the tools are
fragmented.

A typical trader may use:

-   A physical notebook for stock.
-   WhatsApp for customer conversations.
-   WhatsApp groups for suppliers.
-   A calculator for prices.
-   Bank-transfer notifications for payment evidence.
-   Paper receipts.
-   Memory for customer history.
-   Another notebook for expenses.
-   A phone gallery for product pictures.
-   Verbal instructions for salesboys, inventory workers, and other
    staff.

The individual tools are not necessarily the problem.

The problem is that **business state is fragmented across them**.

This creates:

-   Stock-counting errors.
-   Forgotten sales.
-   Duplicate or missed records.
-   Difficulty knowing what is actually in stock.
-   Poor visibility into cash and transfer sales.
-   Lost customer relationships.
-   Difficulty tracking goods between shop, vehicle, warehouse, and
    customer.
-   Repeated questions between an oga and workers.
-   Poor visibility when multiple people sell simultaneously.
-   Difficulty operating when internet connectivity is unavailable.
-   No single source of truth.

AHỊA combines the relevant operational pieces into one system while
keeping WhatsApp as the communication bridge.

------------------------------------------------------------------------

# 3. Product Philosophy

## 3.1 Mobile-first, not mobile-only

Most day-to-day trader interactions are expected to happen on phones.

However, the same business must be usable from:

-   Android phones.
-   iPhones.
-   Tablets where appropriate.
-   Windows/macOS/Linux browsers.
-   Larger desktop screens.
-   Future native desktop clients if justified.

A user does not lose permissions merely because they changed devices.

------------------------------------------------------------------------

# 3.2 Offline-first

AHỊA should remain useful when connectivity disappears.

The client maintains local application state and a local operation
queue.

When connectivity returns:

1.  Pending operations are synchronized.
2.  The server validates authorization.
3.  Idempotency prevents duplicate operations.
4.  Transactional events are appended/applied.
5.  Remote changes are pulled.
6.  Conflicts are resolved according to entity-specific rules.
7.  Local state is reconciled.

Offline support is not an optional afterthought. It is part of the
architecture.

------------------------------------------------------------------------

# 3.3 WhatsApp-compatible, not WhatsApp-dependent

AHỊA will initially use WhatsApp Click-to-Chat rather than building a
full WhatsApp Business API integration.

The system generates links with contextual, pre-filled messages.

Example intent:

> Customer is viewing a specific product and wants to contact the
> seller.

AHỊA opens WhatsApp with:

-   Product name.
-   Price.
-   Product/store URL.
-   Optional inquiry text.

The actual negotiation and conversation happen in WhatsApp.

The trader later records the confirmed sale in AHỊA.

AHỊA does not assume that sending a WhatsApp message equals a sale.

------------------------------------------------------------------------

# 3.4 Shareability is a core product principle

Important AHỊA objects should be easy to share.

Examples:

-   Storefronts.
-   Products.
-   Product collections.
-   Invoices.
-   Reports.
-   Purchase orders.
-   Shipment status.
-   Delivery records.
-   QR codes.
-   Selected business artifacts.

Sharing should work particularly well through WhatsApp.

------------------------------------------------------------------------

# 3.5 PostgreSQL is the authoritative server source of truth

PostgreSQL is used from the beginning.

The mobile and web clients may maintain local state for offline
operation, but server-side PostgreSQL is the authoritative shared
business state.

------------------------------------------------------------------------

# 4. Target Users

## 4.1 Business Owner / Oga

The business owner controls the tenant.

The owner may:

-   Manage the business.
-   Add users.
-   Assign roles.
-   Manage permissions.
-   View sales.
-   View inventory.
-   View financial information.
-   Configure the storefront.
-   Revoke access.
-   Review audit history.

The owner is not required to use a laptop.

An owner may use:

-   Phone A today.
-   Phone B tomorrow.
-   A tablet later.
-   A desktop browser later.

Permissions belong to the user's membership/role within the tenant, not
to a particular physical device.

------------------------------------------------------------------------

## 4.2 Salesperson / Nwa Boy or Nwa Girl

A salesperson may:

-   View permitted products.
-   Create sales.
-   Record customers.
-   View permitted customer history.
-   View permitted inventory.
-   Perform other explicitly granted operations.

A salesperson must not automatically gain access to:

-   Business financial reports.
-   Staff administration.
-   Sensitive supplier information.
-   Other restricted operations.

------------------------------------------------------------------------

## 4.3 Inventory Worker

May:

-   View inventory.
-   Stock items in.
-   Record inventory movements.
-   Scan product/carton QR codes.
-   Perform authorized stock adjustments.

------------------------------------------------------------------------

## 4.4 Manager

A manager is a role with a configurable permission set rather than a
hard-coded super-user.

------------------------------------------------------------------------

## 4.5 Customer

Customers do not need AHỊA accounts to browse public storefronts.

Customer flow:

`Shared link → storefront/product → inquiry → WhatsApp`

------------------------------------------------------------------------

## 4.6 Platform Administrator

Platform-level administrators are separate from tenant users.

They may manage:

-   Tenants.
-   Platform configuration.
-   Abuse reports.
-   System health.
-   Operational administration.

Platform administration must not become a hidden tenant-data bypass.

------------------------------------------------------------------------

# 5. Multi-Tenancy

Every business is a tenant.

Example:

``` text
AHỊA
├── Tenant: Obi Electronics
│   ├── Obi
│   ├── Emeka
│   └── Ada
│
├── Tenant: Chukwu Appliances
│   ├── Chukwu
│   └── Ngozi
│
└── Tenant: XYZ Traders
    └── ...
```

Tenant-owned records carry a tenant identity.

Isolation is enforced through multiple layers:

1.  Authentication.
2.  Tenant membership resolution.
3.  Authorization.
4.  Service-layer tenant enforcement.
5.  Repository/CRUD filtering.
6.  Database constraints.
7.  PostgreSQL Row-Level Security where appropriate.
8.  Automated cross-tenant security tests.

A request must never be able to select another tenant merely by changing
a UUID in its URL or request body.

------------------------------------------------------------------------

# 6. Identity, Users, Roles, Permissions and Devices

## 6.1 User

A person has one AHỊA identity.

A user can belong to multiple businesses if the product eventually
supports that use case.

------------------------------------------------------------------------

## 6.2 Tenant Membership

The relationship between a user and a business defines:

-   Tenant.
-   Role(s).
-   Permission grants.
-   Permission restrictions.
-   Membership status.

------------------------------------------------------------------------

## 6.3 Device

Devices are separate from users.

Example:

``` text
User: Obi
├── Android phone
├── iPhone
└── Desktop browser

User: Emeka
├── Android phone
└── Tablet
```

No device is inherently an "oga device" or "salesboy device".

The user's permissions follow the authenticated user and tenant
membership.

Device identity exists primarily for:

-   Synchronization.
-   Auditability.
-   Offline operation.
-   Security.
-   Session management.
-   Device revocation if needed.

------------------------------------------------------------------------

# 7. AWS-IAM-Style Permission Architecture

Permissions must be modular and reusable.

Avoid scattering permission checks across routers.

Permissions should live in centralized, modular policy definitions.

Conceptual structure:

``` text
permissions/
├── product_permissions.py
├── inventory_permissions.py
├── sales_permissions.py
├── customer_permissions.py
├── expense_permissions.py
├── storefront_permissions.py
├── supplier_permissions.py
├── shipment_permissions.py
├── report_permissions.py
└── permissions_registry.py
```

Permission examples:

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

Roles are permission bundles.

Example:

``` text
OWNER
→ all tenant permissions

SALES
→ products.read
→ inventory.read
→ sales.read
→ sales.create
→ customers.read
→ customers.create

INVENTORY
→ products.read
→ inventory.read
→ inventory.stock_in
→ inventory.adjust
→ inventory.scan
```

Permissions should be data-driven where practical rather than embedded
throughout application code.

------------------------------------------------------------------------

# 8. Device and Access Principle

A user's role determines what they can do.

A device does not determine whether they are an owner, salesperson, or
inventory worker.

Example:

``` text
Obi logs into phone X
→ owner permissions

Obi logs into phone Y
→ owner permissions

Emeka logs into phone X
→ Emeka's assigned permissions
```

The server remains authoritative.

------------------------------------------------------------------------

# 9. Offline-First Synchronization

Offline synchronization is one of AHỊA's most important architectural
features.

## 9.1 Local state

The mobile client maintains a local SQLite database.

Potential local entities:

``` text
products
inventory_snapshots
customers
sales
sale_items
expenses
pending_operations
sync_metadata
```

The exact client schema may differ from the server schema.

------------------------------------------------------------------------

## 9.2 Operation Queue

Instead of treating a final mutable value as the only truth, the client
records meaningful operations.

Example:

``` text
operation_id
device_id
tenant_id
actor_id
operation_type
entity_type
entity_id
payload
occurred_at
created_at
sync_status
retry_count
```

------------------------------------------------------------------------

# 10. Inventory Synchronization

Inventory is especially sensitive to conflicts.

Do not synchronize only:

``` text
quantity = 7
```

because concurrent offline devices can overwrite each other.

Instead, record movements.

Example:

``` text
Initial stock: +10

Salesperson device:
SALE -2

Owner device:
SALE -3
```

Server result:

``` text
10 - 2 - 3 = 5
```

Both legitimate operations survive.

------------------------------------------------------------------------

# 11. Conflict Resolution Strategy

There is no universal "latest wins" rule.

Different data types use different merge strategies.

## 11.1 Transactional events

Examples:

-   Sales.
-   Payments.
-   Expenses.
-   Inventory movements.
-   Shipment scans.

Strategy:

**Append operation + idempotency.**

These represent facts that happened.

They must not simply overwrite one another.

------------------------------------------------------------------------

## 11.2 Mutable metadata

Examples:

-   Product description.
-   Store description.
-   Customer notes.
-   Theme configuration.

Strategy may use:

-   Version number.
-   Updated timestamp.
-   Actor/device metadata.
-   Last-write-wins where safe.
-   Explicit conflict resolution for high-value fields where needed.

------------------------------------------------------------------------

## 11.3 Idempotency

Every client operation receives a unique operation ID.

If the same request is retried:

``` text
operation_id = abc123
```

and the server has already processed `abc123`, the server does not
execute it again.

This prevents duplicate sales caused by:

-   Network timeouts.
-   Retries.
-   App restarts.
-   Repeated synchronization.

------------------------------------------------------------------------

# 12. Synchronization Flow

``` text
LOCAL APPLICATION
      │
      ├── user performs operation
      │
      ▼
LOCAL DATABASE
      │
      ├── update local state optimistically
      └── append pending operation
                  │
                  ▼
             SYNC ENGINE
                  │
          network available?
             /          \
           no            yes
           │              │
           │              ▼
           │        POST pending ops
           │              │
           │              ▼
           │        FastAPI validates
           │              │
           │              ├── authentication
           │              ├── tenant
           │              ├── permission
           │              ├── idempotency
           │              └── transaction
           │
           └──────────────┐
                          ▼
                    Pull changes
                          │
                          ▼
                  Reconcile local DB
```

------------------------------------------------------------------------

# 13. Optimistic UI

AHỊA should feel fast.

For safe operations, the UI can update immediately while synchronization
happens in the background.

The interface should clearly distinguish:

-   Local/pending.
-   Synced.
-   Failed.
-   Conflict requiring attention.

A trader should not have to wait several seconds for a server round trip
to see a locally recorded sale.

------------------------------------------------------------------------

# 14. Initial Module Ecosystem

AHỊA has eight major product modules.

## Module 1 --- Storefront

Customer-facing digital catalog.

Core capabilities:

-   Business storefront.
-   Public URL.
-   Store branding.
-   Product catalog.
-   Product photos.
-   Categories.
-   Search/filter.
-   Product detail pages.
-   WhatsApp inquiry.
-   Share buttons.
-   QR/shareable links.
-   Basic storefront analytics.

------------------------------------------------------------------------

## Module 2 --- Inventory

Internal stock management.

Capabilities:

-   Products.
-   Categories.
-   Stock quantities.
-   Stock-in.
-   Stock-out.
-   Adjustments.
-   Inventory movement history.
-   Low-stock thresholds.
-   Search.
-   Bulk import.
-   QR/barcode scanning.
-   Offline operation.
-   Audit history.

------------------------------------------------------------------------

## Module 3 --- Sales & Accounting

Sales and financial records.

Sales:

-   Create sale.
-   Sale items.
-   Payment type.
-   Customer.
-   Discounts where supported.
-   Sale cancellation with authorization.
-   Receipt/invoice generation.

Payment methods initially:

-   Cash.
-   Bank transfer.
-   Other/manual.

Accounting later expands into:

-   Expenses.
-   Ledger.
-   Profit/loss.
-   Reports.
-   Invoice documents.
-   Export.

AHỊA does not force digital payment.

------------------------------------------------------------------------

## Module 4 --- Tracking & Logistics

Goods movement.

Capabilities:

-   Carton/item QR codes.
-   Scanning.
-   Stock movement.
-   Shipment records.
-   Status updates.
-   Delivery status sharing.
-   Shipment history.
-   Offline scanning.

Future:

-   Route integrations.
-   More advanced logistics.

------------------------------------------------------------------------

## Module 5 --- Suppliers & Procurement

Upstream business operations.

Capabilities:

-   Supplier directory.
-   Supplier contacts.
-   Supplier notes.
-   RFQs.
-   Purchase orders.
-   Supplier payment records.
-   Receiving stock from purchase orders.

Flow:

``` text
Supplier
→ RFQ
→ Quote
→ Purchase Order
→ Shipment
→ Receive
→ Inventory
```

------------------------------------------------------------------------

## Module 6 --- CRM / Customers

Customer relationship management.

Capabilities:

-   Customer profiles.
-   Sales history.
-   Notes.
-   Segmentation.
-   Repeat-customer identification.
-   Follow-up reminders.
-   Promotional sharing.
-   Privacy/opt-out handling.

WhatsApp remains the primary communication channel initially.

------------------------------------------------------------------------

## Module 7 --- Insights

Business analytics and later AI.

Potential capabilities:

-   Sales trends.
-   Product performance.
-   Inventory turnover.
-   Expense trends.
-   Low-stock intelligence.
-   Demand forecasting.
-   Anomaly detection.
-   Business recommendations.

AI is not allowed to become a dependency for core operations.

If AI is unavailable:

``` text
Sales still work.
Inventory still works.
Storefront still works.
```

------------------------------------------------------------------------

## Module 8 --- Network

Business community layer.

Potential capabilities:

-   Groups.
-   Posts.
-   Replies.
-   Classifieds.
-   Supplier discovery.
-   Excess-stock listings.
-   Peer recommendations.
-   Trust/reputation mechanisms.
-   Moderation.

This module is deliberately downstream of the operational core.

------------------------------------------------------------------------

# 15. First Build Scope

The first complete product slice consists of:

``` text
Authentication
+
Tenant/business creation
+
Membership
+
Roles/permissions
+
Products
+
Inventory
+
Sales
+
Customers
+
Storefront
+
WhatsApp sharing
+
QR/share links
+
Offline local state
+
Synchronization
```

This is not a throwaway demo.

The foundation must support the later modules without requiring
architectural replacement.

------------------------------------------------------------------------

# 16. First-Time Trader Journey

``` text
Open AHỊA
    ↓
Create account
    ↓
Create business
    ↓
Business name
    ↓
Business category
    ↓
Phone/contact information
    ↓
Choose storefront slug
    ↓
Dashboard
    ↓
Add first product
    ↓
Product becomes available in inventory
    ↓
Storefront becomes shareable
```

------------------------------------------------------------------------

# 17. Staff Onboarding Journey

Owner:

``` text
Dashboard
→ Staff
→ Invite/add worker
→ Select role
→ Review permissions
→ Create/send access
```

Worker:

``` text
Receive invitation
→ Create/login to account
→ Join business
→ Receive assigned permissions
→ Use any supported device
```

The owner does not need to hand over their password.

------------------------------------------------------------------------

# 18. Daily Sales Journey

``` text
Open AHỊA
    ↓
Dashboard
    ↓
+ Sale
    ↓
Search/select product
    ↓
Choose quantity
    ↓
Select/create customer (optional)
    ↓
Select payment method
    ↓
Confirm sale
    ↓
Local sale recorded immediately
    ↓
Inventory movement created
    ↓
Ledger/accounting event created
    ↓
Sync when connected
```

The server transaction should maintain consistency between:

-   Sale.
-   Sale items.
-   Inventory movement.
-   Payment.
-   Financial record where applicable.

------------------------------------------------------------------------

# 19. Stock-In Journey

``` text
Inventory
    ↓
Stock In
    ↓
Select product / scan QR
    ↓
Quantity
    ↓
Optional supplier
    ↓
Optional cost/reference
    ↓
Confirm
    ↓
Inventory movement created
    ↓
Local state updated
    ↓
Sync
```

------------------------------------------------------------------------

# 20. Storefront Journey

Owner:

``` text
Storefront
→ Configure
→ Add branding
→ Add products
→ Preview
→ Publish
→ Share
```

Customer:

``` text
WhatsApp / social / QR
        ↓
Public AHỊA URL
        ↓
Storefront
        ↓
Product
        ↓
Message Seller
        ↓
WhatsApp
```

Customer authentication is not required.

------------------------------------------------------------------------

# 21. Product Share Journey

Trader taps:

``` text
Share Product
```

AHỊA provides:

-   Copy link.
-   WhatsApp share.
-   QR code.
-   Other platform share options supported by the device/browser.

Example:

``` text
https://ahia.app/shop/obi-electronics/product/lg-55-smart-tv
```

------------------------------------------------------------------------

# 22. Dashboard Philosophy

The dashboard should prioritize operations.

Example:

``` text
Good morning, Obi

Today's Sales
₦842,500

Sales
37

Low Stock
12

[ + Sale ]
[ + Product ]
[ Stock In ]
[ Expense ]

Recent Sales
...
```

Avoid filling the home screen with vanity analytics.

The first question should be:

> What does the trader need to do right now?

------------------------------------------------------------------------

# 23. Shareability Model

Shareable resources should have stable public identifiers.

Examples:

``` text
/shop/{store_slug}

/shop/{store_slug}/product/{product_slug}

/share/invoice/{public_token}

/share/shipment/{public_token}

/share/report/{public_token}
```

Sensitive internal resources must never become public simply because
they have a URL.

Public sharing uses separate, non-guessable public tokens where
required.

------------------------------------------------------------------------

# 24. Security

Security requirements include:

-   Secure authentication.
-   Short-lived access tokens where appropriate.
-   Secure refresh/session handling.
-   Tenant isolation.
-   Permission enforcement.
-   Audit logs.
-   Device/session management.
-   Secure file upload.
-   File type/size validation.
-   Signed/private object URLs where appropriate.
-   Rate limiting.
-   Input validation.
-   Idempotency.
-   Database transactions.
-   No client-side authorization as the authority.

The client may hide unavailable buttons for UX, but the backend must
always enforce authorization.

------------------------------------------------------------------------

# 25. Backend Architecture

FastAPI is the primary backend framework.

Preferred conceptual structure:

``` text
backend/
├── app/
│   ├── main.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   └── dependencies.py
│   │
│   ├── database/
│   │   ├── connection.py
│   │   ├── session.py
│   │   └── base.py
│   │
│   ├── models/
│   │   └── entities/
│   │       ├── user_model.py
│   │       ├── tenant_model.py
│   │       ├── membership_model.py
│   │       ├── role_model.py
│   │       ├── device_model.py
│   │       ├── product_model.py
│   │       ├── inventory_model.py
│   │       ├── inventory_movement_model.py
│   │       ├── sale_model.py
│   │       ├── sale_item_model.py
│   │       ├── payment_model.py
│   │       ├── customer_model.py
│   │       └── ...
│   │
│   ├── schemas/
│   │   ├── user_schema.py
│   │   ├── tenant_schema.py
│   │   ├── product_schema.py
│   │   ├── inventory_schema.py
│   │   ├── sale_schema.py
│   │   └── ...
│   │
│   ├── permissions/
│   │   ├── product_permissions.py
│   │   ├── inventory_permissions.py
│   │   ├── sales_permissions.py
│   │   ├── customer_permissions.py
│   │   ├── storefront_permissions.py
│   │   └── permissions_registry.py
│   │
│   ├── crud/
│   │   ├── user_crud.py
│   │   ├── tenant_crud.py
│   │   ├── product_crud.py
│   │   ├── inventory_crud.py
│   │   ├── sale_crud.py
│   │   └── ...
│   │
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── tenant_service.py
│   │   ├── permission_service.py
│   │   ├── product_service.py
│   │   ├── inventory_service.py
│   │   ├── sales_service.py
│   │   ├── customer_service.py
│   │   ├── storefront_service.py
│   │   ├── sync_service.py
│   │   └── ...
│   │
│   ├── integrations/
│   │   ├── storage/
│   │   │   └── r2_client.py
│   │   ├── whatsapp/
│   │   │   └── click_to_chat.py
│   │   └── ...
│   │
│   ├── middleware/
│   │   ├── request_id.py
│   │   └── ...
│   │
│   └── routers/
│       ├── auth_router.py
│       ├── tenant_router.py
│       ├── product_router.py
│       ├── inventory_router.py
│       ├── sales_router.py
│       ├── customer_router.py
│       ├── storefront_router.py
│       └── sync_router.py
│
├── alembic/
├── tests/
├── Dockerfile
└── pyproject.toml
```

------------------------------------------------------------------------

# 26. Separation of Concerns

The architecture deliberately keeps responsibilities separate.

## Models

Represent persistence/domain entities.

## Pydantic schemas

Represent API input/output contracts.

Examples:

``` text
CreateProductRequest
UpdateProductRequest
ProductResponse
```

## CRUD

Database operations.

CRUD should not contain business decisions.

## Services

Business logic and orchestration.

Services coordinate:

-   Authorization.
-   Validation.
-   CRUD.
-   Transactions.
-   External integrations.
-   Domain operations.

## Routers

HTTP transport layer only.

A router should be intentionally boring.

Conceptually:

``` text
request
→ authenticate
→ authorize
→ validate
→ service call
→ response
```

Routers should not contain business workflows.

------------------------------------------------------------------------

# 27. Dependency Direction

Preferred dependency flow:

``` text
Router
  ↓
Service
  ↓
CRUD / repository boundary
  ↓
Database
```

External systems:

``` text
Service
  ↓
Integration / adapter
  ↓
External provider
```

Avoid circular dependencies.

------------------------------------------------------------------------

# 28. Transactions

Business-critical operations must be atomic.

Example sale:

``` text
Create sale
+
Create sale items
+
Create inventory movements
+
Create payment
+
Create ledger entry
```

These should be committed as one database transaction when they
represent one business operation.

If any required part fails:

``` text
rollback
```

No half-created sale.

------------------------------------------------------------------------

# 29. Circuit Breakers and Resilience

Circuit breakers are primarily for external dependencies.

Good candidates:

-   Cloudflare R2.
-   AI providers.
-   SMS.
-   Email.
-   Payment gateways.
-   Maps.
-   External supplier APIs.

Internal database operations should use appropriate:

-   Timeouts.
-   Connection pooling.
-   Transaction handling.
-   Retry policies only where safe.

Do not blindly retry non-idempotent operations.

------------------------------------------------------------------------

# 30. External Dependency Failure Principle

Core business operations should not depend unnecessarily on optional
services.

Example:

``` text
R2 unavailable
→ image upload may fail
→ sale still works

AI unavailable
→ AI insight unavailable
→ inventory still works

SMS unavailable
→ notification unavailable
→ sales still work
```

The system should degrade gracefully.

------------------------------------------------------------------------

# 31. Object Storage

Cloudflare R2 is the initial object storage layer.

Use R2 for:

-   Product images.
-   Store logos.
-   Store banners.
-   Receipt images.
-   Generated invoices.
-   Reports.
-   Shipment documents.
-   Other non-relational files.

PostgreSQL stores metadata/references, not large binary objects.

Suggested object-key strategy:

``` text
tenants/{tenant_id}/products/{product_id}/...
tenants/{tenant_id}/receipts/{receipt_id}/...
tenants/{tenant_id}/invoices/{invoice_id}/...
tenants/{tenant_id}/documents/{document_id}/...
```

Uploads must validate:

-   Size.
-   MIME type.
-   Extension.
-   Ownership.
-   Tenant.

------------------------------------------------------------------------

# 32. Database Direction

Initial database:

**PostgreSQL**

Preferred initial managed provider:

**Neon**

Alternative:

**Supabase PostgreSQL**

The application must remain PostgreSQL-standard enough that moving
providers is practical.

No vendor-specific database dependency should become fundamental to the
business domain.

------------------------------------------------------------------------

# 33. Frontend Architecture

## Mobile

React Native + Expo + TypeScript.

Responsibilities:

-   Trader UI.
-   Local SQLite state.
-   Offline operation.
-   Sync engine.
-   Camera.
-   QR scanning.
-   Notifications.
-   Native sharing.
-   Device capabilities.

------------------------------------------------------------------------

## Web

Next.js + TypeScript.

Responsibilities:

-   Trader web experience.
-   Public storefronts.
-   Public product pages.
-   Shareable pages.
-   Search/indexability where appropriate.
-   Larger-screen workflows.

------------------------------------------------------------------------

## Desktop

The web application must be fully usable on desktop.

A native desktop shell such as Tauri may be introduced later if AHỊA
requires:

-   Deeper filesystem integration.
-   Native printing.
-   Specialized peripherals.
-   Background capabilities.
-   Other desktop-specific functionality.

The web application must not depend on Tauri to function.

------------------------------------------------------------------------

# 34. PWA Position

AHỊA is **not defined as a PWA-only product**.

A web application may still provide normal browser installability where
useful, but this does not replace the native mobile application.

The native mobile app is responsible for capabilities where browser
limitations would be unacceptable.

------------------------------------------------------------------------

# 35. Technology Stack

## Backend

-   Python.
-   FastAPI.
-   Pydantic.
-   SQLAlchemy.
-   Alembic.
-   PostgreSQL.

## Mobile

-   React Native.
-   Expo.
-   TypeScript.
-   SQLite/local persistence.
-   Native device APIs through Expo/native modules where appropriate.

## Web

-   Next.js.
-   TypeScript.

## Storage

-   Cloudflare R2.

## Deployment

-   Northflank initially for the API.
-   Web deployment can use a suitable managed frontend platform.
-   Deployment must remain portable.

## Communication

-   WhatsApp Click-to-Chat initially.

------------------------------------------------------------------------

# 36. Initial Infrastructure

``` text
Git repository
    │
    ├── backend
    │       ↓
    │   Northflank
    │       ↓
    │    FastAPI
    │
    ├── mobile
    │       ↓
    │   Expo build/distribution
    │
    └── web
            ↓
        Next.js deployment

FastAPI
    ├── Neon PostgreSQL
    └── Cloudflare R2
```

------------------------------------------------------------------------

# 37. Core Data Entities

Initial domain entities include:

``` text
User
Tenant
TenantMembership
Role
Permission
Device

Storefront
Product
ProductImage
Category

Inventory
InventoryMovement

Sale
SaleItem
Payment

Customer

Expense
LedgerEntry

SyncOperation
SyncCursor

AuditEvent
```

Later:

``` text
Supplier
PurchaseOrder
PurchaseOrderItem
Shipment
ShipmentItem
ShipmentEvent

Notification
Report
CommunityPost
CommunityGroup
ClassifiedListing
```

------------------------------------------------------------------------

# 38. Inventory as a Ledger, Not Just a Number

The application should avoid treating inventory quantity as an
unexplained mutable number.

Every meaningful change should have a movement/event.

Examples:

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

This provides:

-   Auditability.
-   Synchronization safety.
-   Historical reporting.
-   Debugging.
-   Better analytics.

------------------------------------------------------------------------

# 39. Accounting Direction

The first release can keep financial tracking simple.

Sales generate financial records.

Expenses are entered manually.

Payment type can be:

``` text
cash
transfer
other
```

Later the accounting module can provide:

-   Daily sales.
-   Expenses.
-   Profit.
-   Ledger.
-   P&L.
-   Invoices.
-   Exports.
-   Reports.

AHỊA does not initially promise tax compliance or automated bank
reconciliation.

------------------------------------------------------------------------

# 40. Payment Philosophy

AHỊA does not force traders into online checkout.

Existing payment methods remain valid:

-   Cash.
-   Bank transfer.
-   Other agreed methods.

Optional payment gateway integrations can be introduced later.

The system records what happened; it does not dictate how the trader
must collect money.

------------------------------------------------------------------------

# 41. Offline and Network Failure Requirements

The application should tolerate:

-   Temporary internet loss.
-   Slow connections.
-   Request timeouts.
-   API downtime.
-   Storage-provider downtime.
-   App restarts during pending sync.
-   Repeated sync attempts.

Core local actions should remain available where technically safe.

------------------------------------------------------------------------

# 42. Observability

The backend should have:

-   Structured logging.
-   Request IDs.
-   Error classification.
-   Health endpoints.
-   Metrics where practical.
-   Audit events.
-   Synchronization diagnostics.

Every difficult synchronization problem should be traceable to:

``` text
tenant
user
device
operation
timestamp
request
result
```

without logging sensitive secrets.

------------------------------------------------------------------------

# 43. Auditability

Business-critical actions should be auditable.

Examples:

``` text
Sale created
Sale cancelled
Inventory adjusted
Product deleted
Staff invited
Permission changed
Expense created
Shipment scanned
```

Audit records should include:

-   Actor.
-   Tenant.
-   Device where applicable.
-   Operation.
-   Entity.
-   Timestamp.
-   Relevant metadata.

------------------------------------------------------------------------

# 44. UX Principles

AHỊA should be:

-   Mobile-first.
-   Fast.
-   Simple.
-   Highly actionable.
-   Low-friction.
-   Icon-supported.
-   Clear for users with varying levels of technical literacy.
-   English-first initially.
-   Designed to support Pidgin/localization later.
-   Dark-mode capable.
-   Share-oriented.

The product should avoid unnecessary enterprise jargon.

Instead of:

> "Create inventory adjustment transaction"

the interface may say:

> "Adjust Stock"

------------------------------------------------------------------------

# 45. Voice Input

Voice input may be introduced for selected fields.

Good candidates:

-   Expense notes.
-   Customer notes.
-   Product descriptions.
-   Search.
-   Quick entries.

Voice is an input mechanism, not a core dependency.

------------------------------------------------------------------------

# 46. QR Codes

QR codes can represent:

-   Products.
-   Cartons.
-   Inventory units.
-   Shipments.
-   Public links.
-   Shareable business artifacts.

Scanning should work offline when the relevant data is already available
locally.

------------------------------------------------------------------------

# 47. Notifications

Potential notification channels:

-   In-app.
-   Native push.
-   SMS later.
-   Email later.

WhatsApp notifications are not initially implemented through the
WhatsApp API.

------------------------------------------------------------------------

# 48. Analytics

Initial analytics should answer useful business questions:

-   How many sales today?
-   Which products sell most?
-   Which products are low-stock?
-   How much revenue was recorded?
-   Which customers buy repeatedly?
-   How are sales changing over time?

Advanced forecasting comes later.

------------------------------------------------------------------------

# 49. Future AI

AI may eventually provide:

-   Demand forecasts.
-   Product recommendations.
-   Sales anomaly detection.
-   Natural-language business queries.
-   Stock suggestions.
-   Supplier intelligence.

But AI must remain an enhancement.

Core operations must not depend on an AI provider being online.

------------------------------------------------------------------------

# 50. Potential Growth Loop

AHỊA naturally creates shareable artifacts.

Example:

``` text
Trader creates storefront
        ↓
Shares storefront on WhatsApp
        ↓
Customer opens product
        ↓
Customer shares product with another buyer
        ↓
Buyer contacts trader
        ↓
Trader records sale
        ↓
More products become available
        ↓
Storefront becomes more useful
```

This gives the product an organic distribution mechanism.

------------------------------------------------------------------------

# 51. Expansion Markets

After establishing the Alaba electronics use case, AHỊA can expand to:

-   Computer Village.
-   Balogun/Fashion.
-   Auto parts.
-   Spare parts.
-   Building materials.
-   Beauty/cosmetics.
-   Agriculture.
-   General retail.
-   Other African informal-market businesses.

The architecture should remain category-agnostic.

------------------------------------------------------------------------

# 52. What AHỊA Does Not Promise

AHỊA does not automatically solve:

-   Bad roads.
-   Power outages.
-   Customs problems.
-   Fraud by itself.
-   Dishonest employees by itself.
-   Bad purchasing decisions.
-   Government regulation.
-   Physical theft.
-   International logistics complexity.
-   Every accounting/tax requirement.
-   Enterprise-scale ERP requirements.

It provides information, controls, records, and workflows.

It cannot enforce human behavior.

------------------------------------------------------------------------

# 53. Business Model Direction

Initial direction:

**Free-first.**

The immediate objective is not aggressive monetization.

The product should first become useful enough that businesses depend on
it operationally.

Possible future monetization:

-   Premium storage.
-   Advanced analytics.
-   Additional staff seats.
-   Advanced accounting.
-   Supplier/procurement features.
-   Business automation.
-   Priority support.
-   Payment/logistics integrations.

Monetization decisions should be made after observing actual usage.

------------------------------------------------------------------------

# 54. Development Principles

1.  Build the real system, not a disposable prototype.
2.  PostgreSQL from the beginning.
3.  Multi-tenancy from the beginning.
4.  Permissions from the beginning.
5.  Offline architecture from the beginning.
6.  Synchronization is designed before dependent features are built.
7.  Business logic belongs in services.
8.  Routers remain thin.
9.  CRUD remains persistence-focused.
10. External integrations remain isolated.
11. Core operations should survive optional dependency failures.
12. Never trust the frontend for authorization.
13. Use database transactions for atomic business operations.
14. Use idempotency for retriable operations.
15. Prefer domain events/movements over destructive overwrites for
    transactional state.
16. Keep providers replaceable.
17. Avoid premature abstraction that provides no value.
18. Do not introduce unnecessary infrastructure merely because it looks
    sophisticated.

------------------------------------------------------------------------

# 55. Development Order

## Foundation

``` text
Repository
→ configuration
→ PostgreSQL
→ migrations
→ base models
→ authentication
→ tenant
→ membership
→ roles
→ permissions
→ devices
```

## Core business

``` text
Products
→ inventory
→ inventory movements
→ sales
→ payments
→ customers
```

## Offline

``` text
Local database
→ operation queue
→ sync protocol
→ idempotency
→ pull/push synchronization
→ conflict resolution
```

## Storefront

``` text
Store
→ public products
→ public URLs
→ product sharing
→ WhatsApp Click-to-Chat
→ QR sharing
```

## Operational polish

``` text
Audit
→ reports
→ notifications
→ low-stock alerts
→ exports
```

## Later modules

``` text
Accounting expansion
→ Suppliers
→ Tracking
→ CRM
→ Insights
→ Network
```

------------------------------------------------------------------------

# 56. Definition of a Successful Core System

AHỊA's core system is successful when a real trader can:

1.  Create a business.
2.  Add workers.
3.  Assign their permissions.
4.  Use AHỊA from multiple devices.
5.  Add products.
6.  Record stock.
7.  Sell products.
8.  Record cash or transfer payment.
9.  See inventory update.
10. Continue basic operations while offline.
11. Reconnect and synchronize safely.
12. Publish a storefront.
13. Share a product through WhatsApp.
14. Receive an inquiry through WhatsApp.
15. Record the eventual sale.
16. Review the business history.
17. Never see another tenant's data.

That is the foundation of AHỊA.

------------------------------------------------------------------------

# 57. Non-Goals for the First Core Release

Do not block the core system on:

-   AI forecasting.
-   Community features.
-   Supplier marketplace.
-   Fleet tracking.
-   Automated bank integrations.
-   Full WhatsApp Business API.
-   International payments.
-   Advanced tax engine.
-   Complex recommendation systems.
-   Native desktop-specific functionality.

These can be layered onto the architecture later.

------------------------------------------------------------------------

# 58. Architectural North Star

The system should ultimately behave like this:

``` text
                       AHỊA
                         │
          ┌──────────────┼──────────────┐
          │              │              │
       MOBILE           WEB          DESKTOP
    React Native       Next.js       Future Tauri
          │              │              │
          └──────────────┼──────────────┘
                         │
                       API
                         │
                      FastAPI
                         │
       ┌─────────────────┼─────────────────┐
       │                 │                 │
     Auth             Services           Sync
       │                 │                 │
 Permissions          CRUD/Repo       Operations
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
                    PostgreSQL
                         │
                  authoritative state
                         │
                   Cloudflare R2
                      file data
```

The product is therefore not "a FastAPI app with a frontend."

It is a **distributed, multi-user, multi-device business system** whose
clients happen to include mobile and web applications.

------------------------------------------------------------------------

# 59. Immediate Engineering Task

Before implementing Storefront UI, the first engineering work should be:

``` text
1. Repository structure
2. Configuration
3. PostgreSQL connection
4. SQLAlchemy base
5. Alembic
6. User
7. Tenant
8. TenantMembership
9. Role
10. Permission
11. Device
12. Initial permission registry
13. Authentication
14. Tenant context
15. Authorization dependency/service
16. Audit foundation
17. Sync operation model
18. Inventory movement model
```

After these are stable, product/inventory/sales can be built on top of
them.

The first schema decisions should therefore be treated as architectural
decisions, not disposable scaffolding.

------------------------------------------------------------------------

# 60. Guiding User Scenario

A realistic AHỊA day:

``` text
8:00 AM
Oga opens AHỊA on his phone.

8:05 AM
Inventory worker receives 30 speakers.
He scans/records stock-in.

8:20 AM
Salesgirl receives a customer inquiry through WhatsApp.
She opens the product in AHỊA and confirms stock.

8:25 AM
She records a sale.
Inventory decreases.

10:00 AM
The oga is offline.
He records another sale.

10:20 AM
Internet returns.
His phone synchronizes.

10:21 AM
The server also receives the salesgirl's previously
offline operation.

Both legitimate operations remain.

12:00 PM
Oga opens the dashboard.
He sees today's sales and current stock.

2:00 PM
A customer asks for the product catalogue.
Oga shares the public storefront.

Customer opens it without an AHỊA account.

Customer taps a product.

WhatsApp opens with a pre-filled inquiry.

The customer and trader negotiate normally.

Later, the trader records the confirmed sale in AHỊA.
```

That is the product we are building.

------------------------------------------------------------------------

# 61. Product Boundary

AHỊA should feel like one coherent system rather than eight unrelated
applications.

The modules share a common business graph:

``` text
Storefront
    │
    ▼
Product
    │
    ├───────────────┐
    ▼               ▼
Inventory          Sale
    │               │
    ▼               ▼
Shipment         Customer
    │               │
    ▼               ▼
Supplier         CRM
                    │
                    ▼
                 Insights
```

Accounting and audit records connect the operational events.

Network sits around the business ecosystem rather than inside the
critical transaction path.

------------------------------------------------------------------------

# 62. Final Product Definition

AHỊA is a multi-tenant, offline-first business operating system for
informal commerce.

It combines:

-   Storefronts.
-   Products.
-   Inventory.
-   Sales.
-   Payments/financial records.
-   Customers.
-   Logistics.
-   Suppliers.
-   Analytics.
-   Community.

It is designed around the realities of Nigerian commerce:

-   Mobile phones.
-   Intermittent connectivity.
-   Cash.
-   Bank transfers.
-   WhatsApp.
-   Multiple workers.
-   Informal business structures.
-   Shared devices.
-   Rapid day-to-day transactions.
-   Heavy reliance on trust and relationships.

The first target is Alaba.

The architecture is designed for much more than Alaba.

------------------------------------------------------------------------

# 63. Living Specification Rule

This document is a living engineering/product specification.

When a significant architectural decision is made, update the
specification before implementation proceeds.

Decisions that affect:

-   Data ownership.
-   Multi-tenancy.
-   Synchronization.
-   Permissions.
-   Business transactions.
-   External dependencies.
-   Public/private data boundaries.

must be documented.

AHỊA should grow by extending the architecture, not by repeatedly
replacing it.
