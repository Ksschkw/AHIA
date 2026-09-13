"""Transport contracts: request and response schemas, one module per entity.

File naming: ``<entity>_schema.py``.

These are the only place where wire-format validation happens. A schema may
enforce an allowlist of known-good shapes, field lengths, formats and required
fields. It must not encode business decisions such as "only an owner may do
this", "stock may not go negative" or "this sale needs a payment" - those belong
to the service layer, and domain invariants belong to the entity layer.

Response schemas are explicit. A router never returns an arbitrary dictionary,
because an untyped response is how internal fields leak.
"""
