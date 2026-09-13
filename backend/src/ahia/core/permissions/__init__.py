"""Permission vocabulary.

Permissions are application capabilities, not tenant-defined strings. They are
declared once, as a closed set, with an owning module and a description, and the
database stores the same codes.

Why a registry rather than a string literal at each call site: a typo in a
permission string is a silent authorization bypass, and a code that appears in a
role bundle but nowhere in the registry is a permission nobody can ever be
granted. Both are caught by tests over this package rather than in production.

This package is cross-cutting and may be imported by any layer. Nothing here
imports an application layer.
"""
