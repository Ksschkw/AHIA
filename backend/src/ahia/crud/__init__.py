"""Persistence, one module per entity.

File naming: ``<entity>_crud.py``.

Each module owns exactly one entity's storage and nothing else. It may contain:

* the SQLAlchemy declarative ``*Record`` class that represents the table;
* the mapper between ``*Record`` and the domain entity;
* query functions: ``get_by_id``, ``list``, ``create``, ``update``,
  ``deactivate``, plus entity-specific finders.

It must not contain business decisions, coordinate more than one entity's
storage, or return a database row across a layer boundary. Functions return
domain entities.

Tenant-owned data is always queried with an explicit ``tenant_id`` obtained from
the authorized context; a lookup that could return another tenant's row is a
defect, not a convenience.
"""
