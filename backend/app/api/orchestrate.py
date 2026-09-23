import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.generation.providers import GenerationError
from app.orchestration.graph import build_graph
from app.orchestration.models import (
    GraphState,
    OrchestrationRequest,
    OrchestrationResponse,
    Route,
    Status,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_response(request_id: str, result: dict) -> OrchestrationResponse:
    policy = result.get("policy_result")
    structured = result.get("structured_result")
    return OrchestrationResponse(
        request_id=request_id,
        route=result.get("route") or Route.ABSTAIN,
        status=result.get("status") or Status.ERROR,
        answer=policy.get("answer") if policy else None,
        citations=policy.get("citations") if policy else None,
        tool=result.get("tool_name"),
        source_dataset=structured.get("source_dataset") if structured else None,
        record_count=structured.get("record_count") if structured else None,
        data=structured.get("data") if structured else None,
        abstention_reason=result.get("abstention_reason"),
        error=result.get("error"),
    )


@router.post(
    "/orchestrate",
    response_model=OrchestrationResponse,
    responses={
        502: {"description": "Generation failed or returned malformed output"},
        503: {"description": "Retrieval, provider, or database unavailable"},
        504: {"description": "Generation provider timed out"},
    },
)
async def orchestrate(request: OrchestrationRequest):
    request_id = str(uuid4())
    settings = get_settings()
    state: GraphState = {
        "request_id": request_id,
        "question": request.question,
        "requested_route": request.route,
        "requested_tool": request.tool,
        "requested_tool_arguments": request.tool_arguments,
    }
    started = perf_counter()
    try:
        result = await build_graph(settings).ainvoke(state)
    except GenerationError as exc:
        _log(request_id, error_category=exc.code, duration_ms=(perf_counter() - started) * 1000)
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code}})
    except Exception as exc:
        # A genuine infrastructure failure (e.g. database unavailable), not a
        # semantic abstention — never expose exception internals.
        _log(
            request_id,
            error_category=type(exc).__name__,
            duration_ms=(perf_counter() - started) * 1000,
        )
        return JSONResponse(
            status_code=503, content={"error": {"code": "orchestration_unavailable"}}
        )
    duration_ms = (perf_counter() - started) * 1000
    structured = result.get("structured_result")
    _log(
        request_id,
        route=result.get("route"),
        tool=result.get("tool_name"),
        duration_ms=duration_ms,
        status=result.get("status"),
        record_count=structured.get("record_count") if structured else None,
        abstention_reason=result.get("abstention_reason"),
        error_category=result.get("error"),
    )
    return _to_response(request_id, result)


def _log(request_id: str, **fields) -> None:
    # Deliberately no patient/claim record contents — only routing/tool
    # metadata and counts.
    logger.info(
        "%s",
        json.dumps(
            {"event": "orchestration_complete", "request_id": request_id, **fields}, default=str
        ),
    )
