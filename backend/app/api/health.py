from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.core.config import Settings, get_settings
from app.services.health import HealthResponse, check_dependencies

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health(
    response: Response, settings: Annotated[Settings, Depends(get_settings)]
) -> HealthResponse:
    result = await check_dependencies(settings)
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 200 if result.status == "ok" else 503
    return result
