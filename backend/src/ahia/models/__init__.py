"""Domain models.

This package holds the domain representation of AHIA, split into two kinds of
thing with different rules:

``ahia.models.entities``
    Pure domain entities: dataclasses and value objects that express the
    business vocabulary and its invariants. They import nothing outside the
    Python standard library. No Pydantic, no SQLAlchemy, no FastAPI.

Persistence representations are deliberately not here. A SQLAlchemy declarative
class is a storage detail and lives beside the queries that use it, in
``ahia.crud``, as a ``*Record`` class with an explicit mapper to the domain
entity. See docs/ARCHITECTURE.md, ADR-0001.
"""
