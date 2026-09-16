"""The business whose rows this unit of work is allowed to touch.

Row-Level Security is only as good as the value it compares against. A policy
reads ``app.current_tenant`` from the session, and somebody has to set it. That
somebody is the unit of work, reading this module, so that no call site passes a
tenant into the database layer by hand: the same authorized context that decides
*whether* a request may proceed also decides *which business's rows exist* for
it.

Three properties make this safe, and each is deliberate:

**It is request-scoped state, like the correlation ID.** A context variable,
because the value must travel from whoever authorized the caller down to the
first database statement without being threaded through every function in
between. Threading it by hand is how a query ends up with no scope at all.

**Absence is meaningful.** No scope means no rows, not all rows. A missing scope
is a bug in the caller, and the database answers it by returning nothing rather
than everything - which is the whole reason this is not an optional filter.

**A scope never outlives its block.** ``tenant_scope`` restores the previous
value on exit, so a job that evaluates a hundred businesses cannot leave the
hundredth one's scope behind and write the next report into it.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

_tenant_scope_context: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "ahia_tenant_scope",
    default=None,
)


def set_tenant_scope(tenant_id: UUID) -> None:
    """Bind a business to the current context.

    Called after the caller's membership has been resolved, never from a request
    parameter: a scope taken from a URL would make the database enforce the
    caller's claim instead of its authorization.
    """
    _tenant_scope_context.set(tenant_id)


def clear_tenant_scope() -> None:
    """Unbind the business from the current context.

    Used by worker wrappers and by test isolation. A stale scope is worse than
    no scope in one specific way: the query succeeds and returns another
    business's data, which is the failure this entire mechanism exists to make
    impossible.
    """
    _tenant_scope_context.set(None)


def current_tenant_id() -> UUID | None:
    """Return the business bound to the current context, if any."""
    return _tenant_scope_context.get()


@contextmanager
def tenant_scope(tenant_id: UUID) -> Iterator[None]:
    """Run a block with one business bound, and restore the previous scope after.

    Restoring rather than clearing matters for the nested case: a job wrapping a
    per-business loop around a call that is itself already scoped must not widen
    the outer scope when the inner block ends.
    """
    previous = _tenant_scope_context.get()
    _tenant_scope_context.set(tenant_id)
    try:
        yield
    finally:
        _tenant_scope_context.set(previous)
