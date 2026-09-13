"""HTTP transport, one module per entity.

File naming: ``<entity>_router.py``.

A handler in this package does exactly three things:

1. parse the request through a schema (and resolve injected dependencies);
2. call one service method;
3. return a response schema.

Everything else belongs elsewhere. No database access, no inventory
calculation, no permission decision, no tenant lookup, no business validation,
no outbound HTTP call, no error conversion - typed errors are mapped centrally
by ``ahia.middleware.error_handler_middleware``.

If a handler contains an ``if`` that is not dependency wiring, the logic belongs
in a service.
"""
