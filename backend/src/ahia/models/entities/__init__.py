"""Pure domain entities, one module per entity.

File naming: ``<entity>_model.py``. The suffix is redundant with the folder and
is kept on purpose: it makes fuzzy-find and grep reliable and makes the layer
obvious in a diff.

Rules for every module in this package:

1. Standard library only. No framework, ORM, HTTP client or driver import.
2. The entity is the source of truth for its own invariants: value ranges,
   normalization, lifecycle transitions and the relationships it is allowed to
   assume.
3. Validation here is domain validation. Wire-format validation belongs to
   ``ahia.schemas``; integrity enforcement that the database can express
   belongs to constraints and migrations.
4. Frozen dataclasses by default; state transitions return new instances.
"""
