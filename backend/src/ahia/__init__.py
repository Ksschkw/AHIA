"""AHIA backend package.

AHIA is a multi-tenant, offline-first business operating system for informal
commerce. This package contains the FastAPI backend, organised as strict
five-layer vertical slices.

Layer order, outermost first:

    routers      transport: parse, call one service, respond
    services     business logic, orchestration, transactions, authorization
    crud         persistence for exactly one entity
    schemas      transport contracts and edge validation
    models       pure domain entities and invariants

Cross-cutting modules sit underneath every layer and depend on none of them:
``core``, ``middleware`` and ``integrations``.

Dependencies point inward only. The rule is enforced mechanically by the
contracts in ``import-linter.ini``, which run inside the test suite.
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
