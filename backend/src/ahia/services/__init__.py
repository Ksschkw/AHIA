"""Business logic, one module per entity or per use case.

File naming: ``<entity>_service.py`` for entity-owned behaviour, or
``<use_case>_service.py`` when a workflow genuinely spans entities.

Rules:

1. All business behaviour lives here. Authorization, orchestration,
   transaction boundaries, cross-entity rules and calls to external ports.
2. Services never import a database driver and never build a query. They
   express transactional intent through the unit of work port.
3. Every use case that touches protected data performs its own authorization
   check with ``require_permission``. A check in a router can be bypassed by a
   scheduled job, a CLI command or another service.
4. A service must be callable from HTTP, a scheduled job, a CLI, a worker or a
   test without duplicating a rule.
5. Services return domain entities or typed results, never database rows.

Naming: name the use case, not the table. ``complete_sale``,
``receive_stock``, ``invite_tenant_member`` - never ``process``, ``handle`` or
``manage``.
"""
