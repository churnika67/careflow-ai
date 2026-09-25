from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.config import Settings, get_settings
from app.services.health import (
    HealthResponse,
    LivenessResponse,
    ReadinessResponse,
    check_dependencies,
    check_readiness,
)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> HealthResponse:
    """Legacy endpoint, preserved for backward compatibility (existing
    tests and the Dockerfile HEALTHCHECK both historically depend on its
    exact contract) -- unchanged by Phase 13 Slice 6. New code, and the
    container HEALTHCHECK as of this slice, should use /live or /ready
    instead; see docs/phase13_reliability_observability_design.md."""
    result = await check_dependencies(settings)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 200 if result.status == "ok" else 503
    return result


@router.get("/live", response_model=LivenessResponse)
async def live() -> LivenessResponse:
    """Phase 13 Slice 6: process liveness only. Touches no dependency --
    not Postgres, not Qdrant, not Redis, no embedding model load -- and
    returns immediately."""
    return LivenessResponse()


@router.get(
    "/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}}
)
async def ready(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> ReadinessResponse:
    """Phase 13 Slice 6: authoritative-dependency readiness. See
    check_readiness()'s docstring for the exact rule -- Postgres and
    Qdrant gate `status`; Redis is reported but never gates it."""
    result = await check_readiness(settings)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 200 if result.status == "ready" else 503
    return result
