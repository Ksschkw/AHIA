"""Object storage adapters.

Cloudflare R2 is the initial object store. PostgreSQL stores metadata and
object keys; binaries live here.

The capability exposed to services is deliberately narrow: the domain asks for
a scoped upload target, a signed download target, or a deletion. It never sees
a bucket, a region or an S3 client.

Object keys are constructed by this package from server-side identifiers using
the documented hierarchy:

    tenants/{tenant_id}/storefront/...
    tenants/{tenant_id}/products/{product_id}/...
    tenants/{tenant_id}/receipts/{receipt_id}/...
    tenants/{tenant_id}/invoices/{invoice_id}/...
    tenants/{tenant_id}/documents/{document_id}/...

A client-supplied object key is never trusted, because that is how one tenant
writes into another tenant's prefix.
"""
