"""Cross-cutting core.

Everything in this package may be imported by any layer. Nothing in this
package may import an application layer (schemas, crud, services, routers,
middleware, integrations).

Modules and their single responsibilities:

``config``
    Typed settings and the feature flag registry. The only module in the
    codebase permitted to read environment variables.
``errors``
    The error hierarchy, the correlation ID context and the mapping from typed
    error to external envelope.
``logging``
    Structured logging and redaction. Call sites never redact by hand.
``resilience``
    Timeout, circuit breaker, bulkhead, bounded retry and typed fallback for
    outbound boundaries.
``security``
    Password hashing, token issuance and verification, secure token
    generation. No hand-rolled cryptography.
``database``
    The async engine, session lifecycle, declarative base and the unit of work
    port. The only place a database driver is constructed.
``tenant_context``
    The authorized tenant context: user, tenant, membership, role, permissions
    and device.
"""
