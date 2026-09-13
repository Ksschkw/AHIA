"""Capability ports.

A port is an interface the domain depends on and infrastructure implements. It
lives in `core` because every layer may import `core`, while only the
composition root and the adapters may touch `integrations`.

That placement is what keeps the dependency direction clean: a service declares
"I need a storage capability", the container injects whichever adapter the
configuration selected, and the service never learns which one it received. The
ports themselves name no vendor: a test asserts it, so a contract file cannot
quietly acquire a provider-shaped parameter.

Ports defined here:

``storage_port``
    Object storage: upload, delete, exists, delivery URL.
``media_port``
    Server-side image validation and optimization.
"""
