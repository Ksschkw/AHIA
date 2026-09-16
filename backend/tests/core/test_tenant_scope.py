"""Tests for the tenant scope the unit of work binds.

The scope is request-scoped state, and the failures it can have are all of the same kind: a value
that is present when it should not be, or absent when it must be. Both directions are tested here,
including the concurrent case, because a scope that leaks between two requests sharing one event
loop is exactly how one business comes to read another's rows.
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from ahia.core.tenant_scope import (
    clear_tenant_scope,
    current_tenant_id,
    set_tenant_scope,
    tenant_scope,
)


@pytest.mark.unit
def test_no_scope_is_the_default() -> None:
    """Unscoped is the starting state, and it means "no rows" rather than "all rows"."""
    assert current_tenant_id() is None


@pytest.mark.unit
def test_a_bound_scope_is_readable() -> None:
    tenant_id = uuid4()

    set_tenant_scope(tenant_id)

    assert current_tenant_id() == tenant_id


@pytest.mark.unit
def test_clearing_removes_the_scope() -> None:
    """A stale scope is worse than no scope: the query succeeds and reads the wrong business."""
    set_tenant_scope(uuid4())

    clear_tenant_scope()

    assert current_tenant_id() is None


@pytest.mark.unit
def test_the_context_manager_restores_the_previous_scope() -> None:
    """Restoring rather than clearing is what makes nesting safe.

    A per-business loop around a call that is already scoped must not widen the outer scope when the
    inner block ends, or the rest of the run would execute against the wrong business.
    """
    outer = uuid4()
    inner = uuid4()

    with tenant_scope(outer):
        assert current_tenant_id() == outer
        with tenant_scope(inner):
            assert current_tenant_id() == inner
        assert current_tenant_id() == outer


@pytest.mark.unit
def test_the_context_manager_clears_what_it_bound_when_nothing_was_bound() -> None:
    """A job that binds one business must leave the process unscoped after it finishes."""
    with tenant_scope(uuid4()):
        pass

    assert current_tenant_id() is None


@pytest.mark.unit
def test_the_scope_is_not_shared_between_concurrent_tasks() -> None:
    """Two requests handled concurrently must not see each other's business.

    A context variable is copied into each task, and this is the assertion that the copy is what the
    unit of work actually reads - the failure mode is silent, and it is a cross-tenant read.
    """
    first = uuid4()
    second = uuid4()

    async def bind_and_read(tenant_id: UUID) -> UUID | None:
        with tenant_scope(tenant_id):
            await asyncio.sleep(0)
            return current_tenant_id()

    async def run_both() -> list[UUID | None]:
        return list(await asyncio.gather(bind_and_read(first), bind_and_read(second)))

    observed = asyncio.run(run_both())

    assert observed == [first, second]
    assert current_tenant_id() is None
