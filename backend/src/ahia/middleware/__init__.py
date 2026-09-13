"""ASGI middleware.

Middleware is registered on the application, never inside a router. Each module
owns exactly one cross-cutting concern:

``correlation_middleware``
    Reads or generates the correlation ID, validates inbound format, binds it
    into the logging context and returns it on the response.
``security_headers_middleware``
    Applies HSTS, Content-Security-Policy, X-Content-Type-Options,
    X-Frame-Options and Referrer-Policy to every response, including errors.
``rate_limit_middleware``
    Protects authentication, password reset, writes and expensive endpoints.
    This is a security control: it is never disabled by a feature flag.
``error_handler_middleware``
    Maps typed application errors to the single external envelope. The only
    place an exception becomes an HTTP response.
"""
