"""Health endpoints.

Liveness answers one question: is this process alive? Readiness answers a
different one: can this process serve traffic right now, which for AHIA means
"can it reach its database".

They are separate on purpose. A dependency outage must not cause an orchestrator
to kill a healthy process: killing it removes the instance that would recover
first, and turns a database blip into a restart loop.

Neither endpoint exposes anything about the internals: no connection string, no
host name, no version of a dependency, no tenant count, no error detail. A health
endpoint is usually unauthenticated and often public, and it is a favourite
reconnaissance target precisely because teams forget that.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, Request, Response, status

HEALTH_PATH: Final[str] = "/health"
READINESS_PATH: Final[str] = "/ready"

router = APIRouter(tags=["health"])


@router.get(HEALTH_PATH, summary="Liveness probe")
async def liveness(request: Request) -> dict[str, Any]:
    """Report that the process is running.

    Deliberately dependency-free. A liveness probe that checks the database turns
    a dependency outage into a restart loop.
    """
    settings = request.app.state.settings
    return {
        "status": "ok",
        "name": settings.app_name,
        "version": settings.app_version,
    }


@router.get(READINESS_PATH, summary="Readiness probe")
async def readiness(request: Request, response: Response) -> dict[str, Any]:
    """Report whether the process can serve traffic.

    Checks only critical infrastructure: the database. Object storage, AI
    providers and messaging are optional dependencies by design, so their
    unavailability must not take an instance out of rotation.
    """
    container = request.app.state.container
    database_is_reachable = await container.database.check_connectivity()

    if not database_is_reachable:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "not_ready"}

    return {"status": "ready"}
