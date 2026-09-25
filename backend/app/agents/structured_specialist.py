"""The bounded tool-using specialist. Reuses Phase 9's execute_tool()/
TOOL_REGISTRY directly — there is no second tool implementation layer here,
no arbitrary SQL, no dynamically generated tool names, no dynamic imports,
no tool creation. Every attempted tool call's outcome — success or failure —
is preserved in the returned list; a failed tool call never silently
disappears from the result."""

import logging
from time import perf_counter
from typing import Any

from app.agents.models import MAX_STRUCTURED_TOOL_CALLS, MultiAgentState
from app.core.config import Settings
from app.db.connection import connect
from app.observability.logging import log_event
from app.orchestration.models import AbstentionReason, Route
from app.orchestration.tools import execute_tool

logger = logging.getLogger(__name__)


def _log_event(request_id: str | None, **fields: object) -> None:
    # Thin, signature-preserving shim over the central helper -- see
    # agents/graph.py's identical shim for the same rationale. Deliberately
    # no patient/beneficiary/claim record contents — only routing/tool
    # metadata, counts, and reason codes, exactly as before this migration.
    log_event(logger, "agent_node_complete", request_id=request_id, **fields)


_DEFAULT_TOOL_BY_ROUTE = {
    Route.SYNPUF: ("get_beneficiary_summary", "beneficiary_id"),
    Route.FHIR: ("get_patient_summary", "patient_id"),
}
# Single-record lookup tools: a successful call that finds nothing means the
# identifier is unknown, not merely "no rows" — same distinction Phase 9's
# _run_structured_route makes for the single-tool case.
_UNKNOWN_RECORD_REASON = {
    "get_beneficiary_summary": AbstentionReason.UNKNOWN_BENEFICIARY,
    "get_claim_details": AbstentionReason.UNKNOWN_CLAIM,
    "get_patient_summary": AbstentionReason.UNKNOWN_PATIENT,
}


def _empty_attempt(reason: AbstentionReason | None = None, error: str | None = None) -> dict:
    return {
        "tool": None,
        "success": False,
        "source_dataset": None,
        "data": None,
        "record_count": None,
        "error": error,
        "abstention_reason": reason.value if reason else None,
    }


def _resolve_calls(state: MultiAgentState) -> list[tuple[str, dict[str, Any]]] | dict | None:
    """Returns either a list of (tool, arguments) calls to make, or a dict
    (an already-final structured_results update) when no valid resolution
    exists. Never invents an identifier: only an explicit request or the
    supervisor's own classified_identifier may supply one."""
    requested_tools = state.get("requested_tools")
    if requested_tools:
        return [(item["tool"], item.get("arguments") or {}) for item in requested_tools]

    route = state.get("structured_route")
    if state.get("requested_workflow") is not None:
        # Explicit workflow with no explicit tools: nothing to dispatch —
        # the classifier's default-tool fallback only applies when the
        # classifier itself chose this workflow (mirrors Phase 9's
        # _run_structured_route rule for the single-route case).
        return {
            "structured_results": [_empty_attempt(AbstentionReason.MISSING_REQUIRED_IDENTIFIER)]
        }

    identifier = state.get("classified_identifier")
    if identifier is None or route is None:
        return {
            "structured_results": [_empty_attempt(AbstentionReason.MISSING_REQUIRED_IDENTIFIER)]
        }
    default_tool, id_field = _DEFAULT_TOOL_BY_ROUTE[route]
    return [(default_tool, {id_field: identifier})]


async def run_structured_specialist(state: MultiAgentState, settings: Settings) -> dict:
    request_id = state.get("request_id")
    route = state.get("structured_route")
    if route is None:
        _log_event(request_id, node="structured", action="resolve_calls", status="abstained")
        return {
            "structured_results": [_empty_attempt(AbstentionReason.MISSING_REQUIRED_IDENTIFIER)]
        }

    calls = _resolve_calls(state)
    if isinstance(calls, dict):
        _log_event(request_id, node="structured", action="resolve_calls", status="abstained")
        return calls
    if len(calls) > MAX_STRUCTURED_TOOL_CALLS:
        # Defense in depth: MultiAgentRequest already rejects this at the API
        # boundary (422); this guards any other caller of the graph directly.
        _log_event(
            request_id,
            node="structured",
            action="resolve_calls",
            status="error",
            error_category="too_many_tool_calls",
        )
        return {"structured_results": [_empty_attempt(error="too_many_tool_calls")]}

    connection = await connect(settings)
    results = []
    try:
        for tool_name, arguments in calls:
            started = perf_counter()
            outcome = await execute_tool(connection, route, tool_name, arguments)
            duration_ms = (perf_counter() - started) * 1000
            abstention_reason = None
            if outcome.success and outcome.data is None and tool_name in _UNKNOWN_RECORD_REASON:
                abstention_reason = _UNKNOWN_RECORD_REASON[tool_name].value
            results.append(
                {
                    "tool": outcome.tool,
                    "success": outcome.success,
                    "source_dataset": outcome.source_dataset,
                    "data": outcome.data,
                    "record_count": outcome.record_count,
                    "error": outcome.error,
                    "abstention_reason": abstention_reason,
                }
            )
            _log_event(
                request_id,
                node="structured",
                action="execute_tool",
                tool=tool_name,
                duration_ms=duration_ms,
                status="success" if outcome.success else "error",
                record_count=outcome.record_count,
                abstention_reason=abstention_reason,
                error_category=outcome.error,
            )
    finally:
        await connection.close()
    return {"structured_results": results}
