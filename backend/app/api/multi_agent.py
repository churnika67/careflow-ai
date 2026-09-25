import logging
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.agents.graph import build_multi_agent_graph
from app.agents.graph import build_response as _to_response
from app.agents.models import MultiAgentRequest, MultiAgentResponse, MultiAgentState
from app.core.config import get_settings
from app.generation.providers import GenerationError
from app.observability.logging import get_request_id, log_event

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/multi-agent",
    response_model=MultiAgentResponse,
    responses={
        502: {"description": "Generation failed or returned malformed output"},
        503: {"description": "Retrieval, provider, or database unavailable"},
        504: {"description": "Generation provider timed out"},
    },
)
async def multi_agent(request: MultiAgentRequest):
    # Sourced from RequestContextMiddleware (one ID per HTTP request) with a
    # defensive fallback for callers that invoke this handler directly
    # without going through the app's middleware stack (e.g. a bare unit
    # test) -- never a second, unrelated ID generated alongside the
    # middleware's when middleware IS present.
    request_id = get_request_id() or str(uuid4())
    settings = get_settings()
    state: MultiAgentState = {
        "request_id": request_id,
        "question": request.question,
        "requested_workflow": request.workflow,
        "requested_policy_question": request.policy_question,
        "requested_structured_route": request.structured_route,
        "requested_tools": [tool.model_dump() for tool in request.tools] if request.tools else None,
    }
    started = perf_counter()
    try:
        result = await build_multi_agent_graph(settings).ainvoke(state)
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
        return JSONResponse(status_code=503, content={"error": {"code": "multi_agent_unavailable"}})
    duration_ms = (perf_counter() - started) * 1000
    structured_results = result.get("structured_results") or []
    record_count = sum(item.get("record_count") or 0 for item in structured_results)
    _log(
        request_id,
        workflow=result.get("workflow"),
        duration_ms=duration_ms,
        status=result.get("status"),
        record_count=record_count or None,
        validation_issue=[
            issue["code"] for issue in (result.get("validation") or {}).get("issues", [])
        ],
        abstention_reason=result.get("abstention_reason"),
        error_category=result.get("error"),
    )
    return _to_response(request_id, result)


def _log(request_id: str, **fields) -> None:
    # Thin, signature-preserving shim over the central helper -- see
    # agents/graph.py's identical shim for the same rationale. Deliberately
    # no patient/beneficiary/claim record contents — only routing/tool
    # metadata, counts, and reason codes, exactly as before this migration.
    log_event(logger, "multi_agent_complete", request_id=request_id, **fields)
