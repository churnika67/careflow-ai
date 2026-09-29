"""The Phase 9 orchestration graph: a small, acyclic StateGraph matching

    START -> route -> {policy | synpuf | fhir | abstain} -> validate -> END

No checkpointing, no memory, no persistence, no agent loop. `settings` is
captured in a closure by build_graph(settings), never stored in GraphState
(per the explicit constraint against framework/config objects in state).
"""

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.db.connection import connect
from app.orchestration.classify import classify
from app.orchestration.models import AbstentionReason, GraphState, Route, Status
from app.orchestration.policy_adapter import call_policy
from app.orchestration.tools import execute_tool, precheck_tool_call

_TOOL_ERROR_TO_ABSTENTION = {
    "unsupported_tool": AbstentionReason.UNSUPPORTED_TOOL,
    "invalid_tool_arguments": AbstentionReason.INVALID_TOOL_ARGUMENTS,
    "missing_tool_name": AbstentionReason.MISSING_REQUIRED_IDENTIFIER,
}
# Tools that look up exactly one record by identifier: an empty result means
# that identifier is unknown, not merely "no rows" (unlike list/frequency
# tools, where an empty list is a legitimate successful result).
_UNKNOWN_RECORD_REASON = {
    "get_beneficiary_summary": AbstentionReason.UNKNOWN_BENEFICIARY,
    "get_claim_details": AbstentionReason.UNKNOWN_CLAIM,
    "get_patient_summary": AbstentionReason.UNKNOWN_PATIENT,
}
_DEFAULT_TOOL_BY_ROUTE = {
    Route.SYNPUF: ("get_beneficiary_summary", "beneficiary_id"),
    Route.FHIR: ("get_patient_summary", "patient_id"),
}


def route_node(state: GraphState) -> dict:
    """Resolve `route`. An explicit `requested_route` (the preferred,
    strongest interface) is honored directly, with one consistency check:
    POLICY combined with a requested tool is a contradictory request, not
    silently corrected. Otherwise falls back to the deterministic free-text
    classifier — never to a live LLM, and never defaulting unmatched text
    to POLICY."""
    requested_route = state.get("requested_route")
    requested_tool = state.get("requested_tool")
    if requested_route is not None:
        if requested_route == Route.POLICY and requested_tool is not None:
            return {
                "route": Route.ABSTAIN,
                "abstention_reason": AbstentionReason.INCONSISTENT_REQUEST,
            }
        if requested_route == Route.ABSTAIN:
            return {
                "route": Route.ABSTAIN,
                "abstention_reason": AbstentionReason.UNSUPPORTED_REQUEST,
            }
        return {"route": requested_route}
    result = classify(state.get("question", ""))
    update: dict = {"route": result.route}
    if result.abstention_reason is not None:
        update["abstention_reason"] = result.abstention_reason
    return update


def policy_node(state: GraphState) -> dict:
    """Thin call into the existing, verified Phase 1-7 RAG pipeline. Phase
    4's own abstention_reason (e.g. "no_eligible_evidence") is preserved
    verbatim inside policy_result; POLICY_ABSTAINED marks, at the
    orchestration layer only, that the policy pipeline itself abstained.

    A GenerationError here is a genuine infrastructure/provider failure
    (retrieval unavailable, provider timeout, ...), not a semantic
    abstention — per the abstention/error separation, it is deliberately
    left to propagate rather than converted into a state field, so the API
    layer can preserve its specific status code exactly as POST /query
    already does."""
    answer = call_policy(state.get("question", ""))
    result = answer.model_dump(mode="json")
    if answer.insufficient_evidence:
        return {
            "status": Status.ABSTAINED,
            "abstention_reason": AbstentionReason.POLICY_ABSTAINED,
            "policy_result": result,
        }
    return {"status": Status.OK, "policy_result": result}


async def _run_structured_route(state: GraphState, settings: Settings, route: Route) -> dict:
    """Shared by synpuf_node and fhir_node — the only difference between the
    two domains is which route/default tool applies, not the execution
    logic itself."""
    tool_name = state.get("requested_tool")
    tool_arguments = state.get("requested_tool_arguments")
    if tool_name is None:
        if state.get("requested_route") is not None:
            # Explicit route with no explicit tool: nothing to dispatch —
            # the classifier's extracted-ID fallback only applies when the
            # classifier itself chose this route.
            return {
                "status": Status.ABSTAINED,
                "abstention_reason": AbstentionReason.MISSING_REQUIRED_IDENTIFIER,
            }
        result = classify(state.get("question", ""))
        if result.extracted_id is None:
            return {
                "status": Status.ABSTAINED,
                "abstention_reason": AbstentionReason.MISSING_REQUIRED_IDENTIFIER,
            }
        default_tool, id_field = _DEFAULT_TOOL_BY_ROUTE[route]
        tool_name = default_tool
        tool_arguments = {id_field: result.extracted_id}

    # Validate before ever connecting -- an unsupported tool name or invalid
    # arguments must abstain without opening a database connection at all
    # (see tools.py::precheck_tool_call's own docstring for why: this used
    # to connect unconditionally, which meant every rejected tool call still
    # paid for a real database round trip, and a genuinely unreachable
    # database turned a clean abstention into an unhandled connection
    # error).
    precheck = precheck_tool_call(route, tool_name, tool_arguments)
    if precheck is not None:
        outcome = precheck
    else:
        connection = await connect(settings)
        try:
            outcome = await execute_tool(connection, route, tool_name, tool_arguments)
        finally:
            await connection.close()

    if not outcome.success:
        reason = _TOOL_ERROR_TO_ABSTENTION.get(outcome.error, AbstentionReason.UNSUPPORTED_REQUEST)
        return {"status": Status.ABSTAINED, "abstention_reason": reason, "tool_name": tool_name}
    if outcome.data is None and tool_name in _UNKNOWN_RECORD_REASON:
        return {
            "status": Status.ABSTAINED,
            "abstention_reason": _UNKNOWN_RECORD_REASON[tool_name],
            "tool_name": tool_name,
        }
    return {
        "status": Status.OK,
        "tool_name": tool_name,
        "structured_result": {
            "tool": outcome.tool,
            "source_dataset": outcome.source_dataset,
            "record_count": outcome.record_count,
            "data": outcome.data,
        },
    }


def abstain_node(state: GraphState) -> dict:
    reason = state.get("abstention_reason") or AbstentionReason.UNSUPPORTED_REQUEST
    return {"status": Status.ABSTAINED, "abstention_reason": reason}


def validate_node(state: GraphState) -> dict:
    """Final structural check before END: every path must leave a definite
    status, an abstained result must carry its reason, and a success result
    must carry a payload. This does not re-validate tool/policy correctness
    — only that the graph did not leave state inconsistent."""
    status = state.get("status")
    if status is None:
        return {"status": Status.ERROR, "error": "no_status_set"}
    if status == Status.ABSTAINED and state.get("abstention_reason") is None:
        return {"status": Status.ERROR, "error": "abstained_without_reason"}
    if (
        status == Status.OK
        and state.get("policy_result") is None
        and state.get("structured_result") is None
    ):
        return {"status": Status.ERROR, "error": "ok_status_without_result"}
    return {}


def _select_branch(state: GraphState) -> str:
    route = state.get("route")
    if route == Route.POLICY:
        return "policy"
    if route == Route.SYNPUF:
        return "synpuf"
    if route == Route.FHIR:
        return "fhir"
    return "abstain"


def build_graph(settings: Settings):
    async def synpuf_node(state: GraphState) -> dict:
        return await _run_structured_route(state, settings, Route.SYNPUF)

    async def fhir_node(state: GraphState) -> dict:
        return await _run_structured_route(state, settings, Route.FHIR)

    graph = StateGraph(GraphState)
    graph.add_node("route", route_node)
    graph.add_node("policy", policy_node)
    graph.add_node("synpuf", synpuf_node)
    graph.add_node("fhir", fhir_node)
    graph.add_node("abstain", abstain_node)
    graph.add_node("validate", validate_node)

    graph.add_edge(START, "route")
    graph.add_conditional_edges(
        "route",
        _select_branch,
        {"policy": "policy", "synpuf": "synpuf", "fhir": "fhir", "abstain": "abstain"},
    )
    graph.add_edge("policy", "validate")
    graph.add_edge("synpuf", "validate")
    graph.add_edge("fhir", "validate")
    graph.add_edge("abstain", "validate")
    graph.add_edge("validate", END)
    return graph.compile()
