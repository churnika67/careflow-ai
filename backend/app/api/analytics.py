"""Phase 15 Slice 1: read-only analytics/evaluation endpoints.

Both endpoints below are GET-only and take no request body or path/query
parameter that selects a file, experiment, or table -- see
app/analytics/snapshot.py and app/analytics/structured.py's module
docstrings for why that is a deliberate security property, not an
oversight. Nothing in this router can execute an experiment, change a
threshold, or write to any table."""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.analytics.models import EvaluationSnapshotResponse, StructuredAnalyticsOverview
from app.analytics.snapshot import (
    EvaluationArtifactMalformedError,
    EvaluationArtifactMissingError,
    load_evaluation_snapshot,
)
from app.analytics.structured import load_structured_overview
from app.core.config import get_settings
from app.db.connection import connect
from app.observability.logging import get_request_id, log_event

router = APIRouter(tags=["analytics"])
logger = logging.getLogger(__name__)


@router.get(
    "/analytics/evaluation/snapshot",
    response_model=EvaluationSnapshotResponse,
    responses={
        503: {"description": "A canonical Phase 12 evaluation artifact is missing or malformed"}
    },
)
async def evaluation_snapshot():
    try:
        return load_evaluation_snapshot()
    except (EvaluationArtifactMissingError, EvaluationArtifactMalformedError) as exc:
        log_event(
            logger,
            "analytics_evaluation_snapshot_unavailable",
            request_id=get_request_id(),
            error=str(exc),
        )
        return JSONResponse(
            status_code=503, content={"error": {"code": "evaluation_snapshot_unavailable"}}
        )


@router.get(
    "/analytics/structured/overview",
    response_model=StructuredAnalyticsOverview,
    responses={503: {"description": "The structured database is unavailable"}},
)
async def structured_overview():
    settings = get_settings()
    try:
        connection = await connect(settings)
    except Exception as exc:
        log_event(
            logger,
            "analytics_structured_overview_unavailable",
            request_id=get_request_id(),
            error_category=type(exc).__name__,
        )
        return JSONResponse(
            status_code=503, content={"error": {"code": "structured_overview_unavailable"}}
        )
    try:
        return await load_structured_overview(connection)
    finally:
        await connection.close()
