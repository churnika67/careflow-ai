import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.agents.graph import build_multi_agent_graph
from app.agents.models import (
    MultiAgentRequest,
    MultiAgentResponse,
    MultiAgentState,
    WorkflowDecision,
)
from app.core.config import get_settings
from app.generation.providers import GenerationError
from app.orchestration.models import Status

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_response(request_id: str, result: dict) -> MultiAgentResponse:
    structured_results = result.get("structured_results")
    structured = None
    if structured_results is not None:
        route = result.get("structured_route")
        structured = {"route": route.value if route else None, "results": structured_results}
    return MultiAgentResponse(
        request_id=request_id,
        workflow=result.get("workflow") or WorkflowDecision.ABSTAIN,
        status=result.get("status") or Status.ERROR,
        policy=result.get("policy_result"),
        structured=structured,
        validation=result.get("validation"),
        final_summary=None,
        abstention_reason=result.get("abstention_reason"),
        error=result.get("error"),
    )


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
    request_id = str(uuid4())
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
    # Deliberately no patient/beneficiary/claim record contents — only
    # routing/tool metadata, counts, and reason codes.
    logger.info(
        "%s",
        json.dumps(
            {"event": "multi_agent_complete", "request_id": request_id, **fields}, default=str
        ),
    )
