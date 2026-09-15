"""The metrics endpoint.

`GET /metrics`, in the Prometheus exposition format, unversioned like the health endpoints: a
scraper is infrastructure rather than a client, and a version prefix on it would mean reconfiguring
every scraper when the API contract changes.

**It is not public, and it is not open by default.** Metrics describe the shape of the deployment -
route names, error codes, which permissions are being refused - and a monitoring system's retention
is not a place to publish a service's internals. The endpoint answers only when
`METRICS_AUTH_TOKEN` is configured, and then only to a caller presenting it as a bearer token. With
no token configured the route answers as if it did not exist, which is the safe default: a
deployment that has not decided who may scrape has not decided to be scraped.

**The comparison is constant-time.** A token compared with `==` leaks its prefix through timing,
which is enough to recover a secret one byte at a time. `hmac.compare_digest` is the one line that
removes that, and it costs nothing.

**Nothing in the response is a client's.** No correlation ID, no tenant, no user, no query string:
the labels are a method, a normalised route, a status class, an error code and a dependency name,
all of which are this product's own vocabulary.
"""

from __future__ import annotations

import hmac
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Header, Request, Response

from ahia.core.config import Settings
from ahia.core.errors import NotFoundError, UnauthenticatedError
from ahia.core.metrics import MetricsRegistry

router = APIRouter(tags=["ops"])

_AUTHORIZATION_SCHEME: Final[str] = "bearer"


def get_metrics_registry(request: Request) -> MetricsRegistry:
    """Return the registry this process records into."""
    registry: MetricsRegistry = request.app.state.metrics
    return registry


def require_metrics_access(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Refuse unless the caller presents the configured scraping token.

    Raises not-found when no token is configured, so an unconfigured deployment looks exactly like
    one
    that never had the endpoint. A configured token that is missing or wrong is an authentication
    failure, which is the honest answer once the endpoint exists.
    """
    settings: Settings = request.app.state.settings
    configured = settings.metrics_auth_token
    if configured is None:
        raise NotFoundError(
            operation="read_metrics",
            entity="metrics_endpoint",
            detail="metrics are not exposed by this deployment",
        )
    presented = _presented_token(authorization)
    if presented is None or not hmac.compare_digest(
        presented.encode("utf-8"), configured.get_secret_value().encode("utf-8")
    ):
        raise UnauthenticatedError(
            operation="read_metrics",
            entity="metrics_endpoint",
            detail="the scraping token is missing or wrong",
        )


def _presented_token(header: str | None) -> str | None:
    """Return the bearer token from an Authorization header, or None."""
    if header is None:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != _AUTHORIZATION_SCHEME or not value.strip():
        return None
    return value.strip()


MetricsRegistryDependency = Annotated[MetricsRegistry, Depends(get_metrics_registry)]


@router.get(
    "/metrics",
    summary="Scrape this process's metrics",
    dependencies=[Depends(require_metrics_access)],
    response_class=Response,
)
async def read_metrics(registry: MetricsRegistryDependency) -> Response:
    """Return the counters and totals in the exposition format."""
    body = registry.render()
    return Response(content=body, media_type=registry.content_type)
