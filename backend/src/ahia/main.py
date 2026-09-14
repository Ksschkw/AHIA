"""The ASGI application.

Small on purpose. Everything the process does is constructed elsewhere and wired
here:

    create application
        load configuration            (core/config)
        register middleware           (middleware/)
        register exception handlers   (this module, mapping only)
        register routers              (routers/)
        startup: build the container  (bootstrap)
        shutdown: dispose it

The application object holds no configuration logic of its own. A reader who
wants to know what the system is made of reads `bootstrap`, and a reader who
wants to know what it exposes reads the routers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from ahia.bootstrap import (
    build_application_container,
    dispose_application_container,
)
from ahia.core.config import Settings, load_settings
from ahia.core.errors import (
    AhiaError,
    InvalidInputError,
    NotFoundError,
    internal_error_envelope,
    require_correlation_id,
)
from ahia.core.logging import get_logger
from ahia.middleware.correlation_middleware import CorrelationIdMiddleware
from ahia.middleware.error_handler_middleware import ErrorHandlerMiddleware
from ahia.middleware.rate_limit_middleware import RateLimitMiddleware, build_default_limiter
from ahia.middleware.security_headers_middleware import SecurityHeadersMiddleware
from ahia.routers import (
    auth_router,
    category_router,
    customer_router,
    device_router,
    health_router,
    inventory_router,
    permission_router,
    product_image_router,
    product_router,
    sale_router,
    tenant_membership_router,
    tenant_router,
    user_router,
)

_MAIN_LOGGER_NAME: Final[str] = "ahia.main"


@asynccontextmanager
async def application_lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Build every dependency at startup and dispose of it at shutdown.

    The container is built here rather than at import so that importing this
    module has no side effects: a test, a migration tool or a CLI can import it
    without opening a connection pool.
    """
    settings: Settings = application.state.settings
    logger = get_logger(_MAIN_LOGGER_NAME)

    container = build_application_container(settings)
    application.state.container = container
    logger.info("application_started")

    try:
        yield
    finally:
        await dispose_application_container(container)
        logger.info("application_stopped")


def create_application(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    Middleware is registered from the inside out: the last one added is the
    outermost, which is why correlation is added last. It must wrap everything,
    including the error handler, so that a failure anywhere still produces a
    response carrying a correlation ID the client can quote.
    """
    resolved_settings = settings or load_settings()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=application_lifespan,
        # Interactive documentation enumerates the attack surface and is
        # therefore not published in production.
        docs_url=None if resolved_settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if resolved_settings.is_production else "/openapi.json",
    )
    application.state.settings = resolved_settings

    if resolved_settings.cors_allowed_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_allowed_origin_list),
            allow_credentials=resolved_settings.cors_allow_credentials,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                resolved_settings.correlation_id_header,
            ],
            expose_headers=[resolved_settings.correlation_id_header],
            max_age=600,
        )

    # Order matters, and Starlette applies it from the inside out: the last
    # middleware added is the outermost. The intended nesting is
    #
    #     correlation -> security headers -> rate limit -> error handler -> routes
    #
    # which is why they are added in the reverse of that order.
    #
    # Two consequences of getting it wrong, both found by tests rather than by
    # review: an error handler outside the security headers produces error
    # responses with no security headers, and a correlation middleware that is not
    # outermost produces failures with no correlation ID for the client to quote.
    application.add_middleware(ErrorHandlerMiddleware)
    application.add_middleware(
        RateLimitMiddleware,
        limiter=build_default_limiter(
            authentication_per_minute=resolved_settings.rate_limit_auth_per_minute,
            password_reset_per_hour=resolved_settings.rate_limit_password_reset_per_hour,
            write_per_minute=resolved_settings.rate_limit_write_per_minute,
            global_per_minute=resolved_settings.rate_limit_global_per_minute,
        ),
        trusted_proxy_count=resolved_settings.trusted_proxy_count,
    )
    application.add_middleware(
        SecurityHeadersMiddleware,
        hsts_max_age_seconds=resolved_settings.hsts_max_age_seconds,
        content_security_policy=resolved_settings.content_security_policy,
        enabled=resolved_settings.security_headers_enabled,
        is_production=resolved_settings.is_production,
    )
    application.add_middleware(
        CorrelationIdMiddleware,
        header_name=resolved_settings.correlation_id_header,
    )

    register_exception_handlers(application)
    register_routers(application, resolved_settings)
    return application


def register_exception_handlers(application: FastAPI) -> None:
    """Map framework exceptions onto the one external envelope.

    FastAPI raises its own exceptions before a route runs. Without these, a
    validation failure would return FastAPI's own body shape and a 404 would
    return a plain text body, so a client would have to handle three error
    formats and one of them would leak field names and submitted values.
    """

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request, error: RequestValidationError
    ) -> Any:
        fields = sorted(
            {".".join(str(part) for part in item.get("loc", ())) for item in error.errors()}
        )
        typed_error = InvalidInputError(
            operation="validate_request",
            entity="request",
            detail=f"invalid fields: {', '.join(fields)}",
        )
        get_logger(_MAIN_LOGGER_NAME).warning(
            "request_validation_failed",
            http_route=request.url.path,
            http_method=request.method,
            invalid_fields=fields,
        )
        return _envelope_response(typed_error)

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, error: StarletteHTTPException) -> Any:
        if error.status_code == 404:
            typed_error: AhiaError = NotFoundError(
                operation="route_request",
                entity="route",
                detail=f"no route matched {request.method} {request.url.path}",
            )
        elif error.status_code == 405:
            typed_error = NotFoundError(
                operation="route_request",
                entity="route",
                detail=f"method not allowed for {request.url.path}",
            )
        else:  # pragma: no cover - framework-level statuses outside the mapped set
            typed_error = NotFoundError(
                operation="route_request",
                entity="route",
                detail=f"framework status {error.status_code}",
            )
        return _envelope_response(typed_error)

    @application.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, error: Exception) -> Any:
        envelope = internal_error_envelope()
        get_logger(_MAIN_LOGGER_NAME).exception(
            "request_failed_unexpectedly",
            error,
            http_route=request.url.path,
            http_method=request.method,
            error_type=type(error).__name__,
        )
        return _envelope_response_from_payload(envelope.to_payload(), status_code=500)


def _envelope_response(error: AhiaError) -> Any:
    return _envelope_response_from_payload(
        error.external().to_payload(), status_code=error.http_status
    )


def _envelope_response_from_payload(payload: dict[str, Any], *, status_code: int) -> Any:
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={"X-Correlation-ID": require_correlation_id()},
    )


def register_routers(application: FastAPI, settings: Settings) -> None:
    """Register the health endpoints and every versioned router.

    Health endpoints are unversioned: a probe must not need to know the API
    version, and they must keep working while the API contract evolves. Business
    routers are versioned under the configured prefix so the contract can change
    without republishing public links.
    """
    application.include_router(health_router.router)

    # Business routers live under the version prefix so the contract can evolve
    # without republishing public links, which do not carry a version.
    versioned_routers = [
        auth_router.router,
        user_router.router,
        tenant_router.router,
        tenant_membership_router.router,
        tenant_membership_router.invitation_router,
        permission_router.router,
        device_router.router,
        category_router.router,
        product_router.router,
        product_image_router.router,
        inventory_router.router,
        customer_router.router,
        sale_router.router,
    ]
    for versioned_router in versioned_routers:
        application.include_router(versioned_router, prefix=settings.api_v1_prefix)

    # The remaining slices register here as they land: tenant, membership,
    # permission, device, product, inventory, sales, customer, storefront, sync.
    application.state.api_v1_prefix = settings.api_v1_prefix


# The object uvicorn imports, built on first access rather than at import time.
#
# Why lazy: importing this module from a test, a migration tool or a CLI must not
# require a complete environment. Loading configuration at import time turns a
# missing variable into an ImportError, which is a confusing failure and makes
# the module untestable in isolation. Nothing is lost: uvicorn resolves the
# attribute once, and the container itself is still built in the lifespan.
_cached_application: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """Resolve module attributes that are built on demand.

    PEP 562 module-level attribute access, so `uvicorn ahia.main:app` keeps
    working while importing the module stays free of side effects. The cache is
    the documented pattern for this hook: building the application at import
    time is precisely what would make the module require a full environment.
    """
    global _cached_application  # noqa: PLW0603 - PEP 562 lazy module attribute
    if name == "app":
        if _cached_application is None:
            _cached_application = create_application()
        return _cached_application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
