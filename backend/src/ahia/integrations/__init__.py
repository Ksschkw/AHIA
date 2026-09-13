"""Provider adapters.

Everything provider-specific lives here and nowhere else. A service depends on
a capability (store an object, build an inquiry link), not on R2, WhatsApp or
any future provider's SDK.

Each adapter:

1. is constructed in the composition root, never at module import time;
2. receives its credentials from configuration, never from the environment
   directly;
3. applies the resilience policy - explicit timeout, circuit breaker per
   dependency, bulkhead concurrency limit, bounded retry only for idempotent
   operations, and a typed degraded result when the provider is unavailable;
4. logs failure with full internal context and returns nothing internal to the
   caller's client.

Adapters never leak a provider exception type across the boundary; they
translate to the shared error hierarchy.
"""
