"""The Phase 10 multi-agent graph: a small DAG coordinating independently
bounded, distinctly-permissioned capabilities —

    START -> supervisor -> {policy, structured (either or both), abstain}
                         -> validate -> END

No cycles, no planner/executor loop, no autonomous retry loop, no
checkpointing/memory/persistence, no new LLM reasoning path.

Empirically verified (not assumed) before this file was written: LangGraph
raises InvalidUpdateError — loudly, not silently — if two nodes scheduled in
the same superstep write the same state key without a reducer. This is why
`policy` and `structured` (which may both run in parallel for
POLICY_AND_STRUCTURED) write ONLY their own disjoint keys (`policy_result`,
`structured_results`) and never touch `status`/`abstention_reason`/`error` —
those are computed exclusively by `validate_node`, which is guaranteed by
this same test to run exactly once per request, after both branches (when
both run) have completed.
"""

import json
import logging
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.models import AbstentionReason, MultiAgentState, WorkflowDecision
from app.agents.structured_specialist import run_structured_specialist
from app.agents.supervisor import classify_workflow
from app.agents.validator import validate_node
from app.core.config import Settings
from app.orchestration.graph import policy_node as _phase9_policy_node

logger = logging.getLogger(__name__)


def _log_event(request_id: str | None, **fields: object) -> None:
    # Deliberately no patient/beneficiary/claim record contents — only
    # routing/tool metadata, counts, and reason codes.
    logger.info(
        "%s", json.dumps({"event": "agent_node_complete", "request_id": request_id, **fields})
    )


def supervisor_node(state: MultiAgentState) -> dict:
    """Resolve `workflow` (and, for structured workflows, `structured_route`).
    An explicit `requested_workflow` (the preferred, strongest interface) is
    honored directly — MultiAgentRequest already rejected any contradictory
    combination before this node ever runs. Otherwise falls back to the
    deterministic classify_workflow(). Never executes DB queries, retrieval,
    tools, SQL, or generation — it only chooses among the bounded
    WorkflowDecision values."""
    requested_workflow = state.get("requested_workflow")
    if requested_workflow is not None:
        update: dict = {"workflow": requested_workflow}
        requested_route = state.get("requested_structured_route")
        if requested_route is not None:
            update["structured_route"] = requested_route
        _log_event(
            state.get("request_id"),
            node="supervisor",
            action="use_requested_workflow",
            workflow=str(update["workflow"]),
        )
        return update
    result = classify_workflow(state.get("question", ""))
    update = {"workflow": result.workflow}
    if result.structured_route is not None:
        update["structured_route"] = result.structured_route
    if result.extracted_id is not None:
        update["classified_identifier"] = result.extracted_id
    if result.abstention_reason is not None:
        update["abstention_reason"] = result.abstention_reason
    _log_event(
        state.get("request_id"),
        node="supervisor",
        action="classify_workflow",
        workflow=str(result.workflow),
        abstention_reason=result.abstention_reason.value if result.abstention_reason else None,
    )
    return update


def policy_node(state: MultiAgentState) -> dict:
    """Reused directly from Phase 9 — not reimplemented. The only new logic
    is resolving which question text to send (an explicit policy_question
    override, else the general question); everything else (retrieval, RRF,
    reranking, evidence eligibility, citation validation, abstention) is
    Phase 9's call_policy()/policy_node, unchanged. Writes only
    policy_result — never status/abstention_reason/error, since this node
    may run concurrently with `structured` in a combined workflow."""
    question = state.get("requested_policy_question") or state.get("question", "")
    started = perf_counter()
    raw = _phase9_policy_node({"question": question})
    duration_ms = (perf_counter() - started) * 1000
    policy_result = raw.get("policy_result") or {}
    _log_event(
        state.get("request_id"),
        node="policy",
        action="call_policy",
        duration_ms=duration_ms,
        status=raw["status"],
        abstention_reason=raw.get("abstention_reason"),
        citation_count=len(policy_result.get("citations") or []),
    )
    return {
        "policy_result": {
            "status": raw["status"],
            "abstention_reason": raw.get("abstention_reason"),
            **policy_result,
        }
    }


async def _structured_node(state: MultiAgentState, settings: Settings) -> dict:
    """Delegates entirely to the structured specialist (bounded multi-tool
    execution reusing Phase 9's execute_tool()/TOOL_REGISTRY). `settings` is
    threaded through via the closure in build_multi_agent_graph below —
    matching Phase 9's own pattern — since a DB connection is needed. Writes
    only structured_results, for the same fan-out-safety reason as
    policy_node."""
    return await run_structured_specialist(state, settings)


def abstain_node(state: MultiAgentState) -> dict:
    # A single-node path (never runs alongside policy/structured), so it may
    # safely set abstention_reason directly.
    reason = state.get("abstention_reason") or AbstentionReason.UNSUPPORTED_REQUEST
    return {"abstention_reason": reason}


def _select_branches(state: MultiAgentState) -> list[str]:
    workflow = state.get("workflow")
    if workflow == WorkflowDecision.POLICY_ONLY:
        return ["policy"]
    if workflow == WorkflowDecision.STRUCTURED_ONLY:
        return ["structured"]
    if workflow == WorkflowDecision.POLICY_AND_STRUCTURED:
        return ["policy", "structured"]
    return ["abstain"]


def build_multi_agent_graph(settings: Settings) -> Any:
    async def structured_node(state: MultiAgentState) -> dict:
        return await _structured_node(state, settings)

    graph = StateGraph(MultiAgentState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("policy", policy_node)
    graph.add_node("structured", structured_node)
    graph.add_node("abstain", abstain_node)
    graph.add_node("validate", validate_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _select_branches,
        {"policy": "policy", "structured": "structured", "abstain": "abstain"},
    )
    graph.add_edge("policy", "validate")
    graph.add_edge("structured", "validate")
    graph.add_edge("abstain", "validate")
    graph.add_edge("validate", END)
    return graph.compile()
