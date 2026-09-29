import os

import pytest
from app.agents.graph import _select_branches, build_multi_agent_graph
from app.agents.models import AbstentionReason, Status, WorkflowDecision
from app.core.config import get_settings
from app.orchestration.models import Route
from langgraph.graph import END, START, StateGraph

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_MULTI_AGENT_INTEGRATION") != "1",
    reason="Set CAREFLOW_MULTI_AGENT_INTEGRATION=1 with Compose running (Qdrant) to exercise "
    "the real policy node",
)


@pytest.fixture(scope="module")
def graph():
    return build_multi_agent_graph(get_settings())


def test_graph_compiles():
    assert build_multi_agent_graph(get_settings()) is not None


@pytest.mark.parametrize(
    "workflow,expected_branches",
    [
        (WorkflowDecision.POLICY_ONLY, ["policy"]),
        (WorkflowDecision.STRUCTURED_ONLY, ["structured"]),
        (WorkflowDecision.POLICY_AND_STRUCTURED, ["policy", "structured"]),
        (WorkflowDecision.ABSTAIN, ["abstain"]),
    ],
)
def test_select_branches_matches_workflow(workflow, expected_branches):
    assert _select_branches({"workflow": workflow}) == expected_branches


def test_select_branches_defaults_to_abstain_for_missing_workflow():
    assert _select_branches({}) == ["abstain"]


class TestFanOutFanInProof:
    """Dedicated, isolated proof (not the real graph, to isolate the LangGraph
    mechanic itself from Phase 10's business logic) that a supervisor-style
    conditional edge returning two branch names schedules both nodes in one
    superstep, that disjoint-key writes merge without conflict, and that the
    downstream node runs exactly once. This was run manually against
    real LangGraph before any Phase 10 node was written — see graph.py's
    module docstring — and is captured here as a permanent regression test."""

    async def test_disjoint_keys_merge_and_downstream_runs_once(self):
        from typing import TypedDict

        class ProbeState(TypedDict, total=False):
            branch_a_result: dict
            branch_b_result: dict

        calls = {"downstream": 0}

        def branch_a(state):
            return {"branch_a_result": {"x": 1}}

        def branch_b(state):
            return {"branch_b_result": {"y": 2}}

        def fan(state):
            return ["a", "b"]

        def downstream(state):
            calls["downstream"] += 1
            return {}

        graph = StateGraph(ProbeState)
        graph.add_node("start", lambda s: {})
        graph.add_node("a", branch_a)
        graph.add_node("b", branch_b)
        graph.add_node("downstream", downstream)
        graph.add_edge(START, "start")
        graph.add_conditional_edges("start", fan, {"a": "a", "b": "b"})
        graph.add_edge("a", "downstream")
        graph.add_edge("b", "downstream")
        graph.add_edge("downstream", END)
        compiled = graph.compile()

        result = await compiled.ainvoke({})
        assert result == {"branch_a_result": {"x": 1}, "branch_b_result": {"y": 2}}
        assert calls["downstream"] == 1

    async def test_concurrent_writes_to_the_same_key_raise_not_silently_resolve(self):
        from typing import TypedDict

        from langgraph.errors import InvalidUpdateError

        class ConflictState(TypedDict, total=False):
            shared: str

        def branch_a(state):
            return {"shared": "from_a"}

        def branch_b(state):
            return {"shared": "from_b"}

        def fan(state):
            return ["a", "b"]

        graph = StateGraph(ConflictState)
        graph.add_node("start", lambda s: {})
        graph.add_node("a", branch_a)
        graph.add_node("b", branch_b)
        graph.add_edge(START, "start")
        graph.add_conditional_edges("start", fan, {"a": "a", "b": "b"})
        graph.add_edge("a", END)
        graph.add_edge("b", END)
        compiled = graph.compile()

        with pytest.raises(InvalidUpdateError):
            await compiled.ainvoke({})


@pytestmark_live
async def test_combined_workflow_merges_policy_and_structured_in_the_real_graph(graph):
    # The real Phase 10 graph, confirming policy_node and the structured
    # specialist — which by design write only their own disjoint keys — both
    # land in the state validate_node receives, with no InvalidUpdateError
    # and no double execution artifacts. Uses real inputs that can actually
    # succeed on both sides (an unanswerable "x" would make both branches
    # abstain, which is correct real validator behavior but would not
    # demonstrate a genuine merge of two successful results).
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_workflow": WorkflowDecision.POLICY_AND_STRUCTURED,
            "requested_policy_question": "Does Medicare cover hospital beds?",
            "requested_structured_route": Route.SYNPUF,
            "requested_tools": [
                {
                    "tool": "get_beneficiary_summary",
                    "arguments": {"beneficiary_id": "00013D2EFD8E45D1"},
                }
            ],
        }
    )
    assert result["policy_result"] is not None
    assert result["structured_results"] is not None
    assert result["status"] == Status.OK


@pytestmark_live
async def test_policy_only_never_populates_structured_results(graph):
    result = await graph.ainvoke(
        {"question": "x", "requested_workflow": WorkflowDecision.POLICY_ONLY}
    )
    assert result["policy_result"] is not None
    assert result.get("structured_results") is None


async def test_structured_only_never_populates_policy_result(graph):
    result = await graph.ainvoke(
        {"question": "x", "requested_workflow": WorkflowDecision.STRUCTURED_ONLY}
    )
    assert result["structured_results"] is not None
    assert result.get("policy_result") is None


async def test_supervisor_resolves_structured_route_from_explicit_request(graph):
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_workflow": WorkflowDecision.STRUCTURED_ONLY,
            "requested_structured_route": Route.SYNPUF,
        }
    )
    assert result["structured_route"] == Route.SYNPUF


@pytestmark_live
async def test_supervisor_via_classifier_resolves_structured_route():
    # No requested_workflow: exercises the real classify_workflow() fallback
    # through the real graph. STRUCTURED_ONLY still reaches the real
    # structured specialist node (Phase 10's own implementation, not a
    # placeholder), which opens a real Postgres connection to resolve the
    # classifier-extracted beneficiary id -- gated behind
    # CAREFLOW_MULTI_AGENT_INTEGRATION like the graph's other live paths,
    # not "live-free" as an earlier phase's stale comment here claimed.
    graph = build_multi_agent_graph(get_settings())
    result = await graph.ainvoke(
        {"question": "What claims does beneficiary 00013D2EFD8E45D1 have?"}
    )
    assert result["workflow"] == WorkflowDecision.STRUCTURED_ONLY
    assert result["structured_route"] == Route.SYNPUF


@pytestmark_live
async def test_supervisor_via_classifier_resolves_combined_workflow():
    graph = build_multi_agent_graph(get_settings())
    result = await graph.ainvoke(
        {
            "question": "What does Medicare policy say about hospital beds, and what "
            "hospital-bed-related information exists for patient "
            "31a2e8ec-69fc-8a71-3ab6-36cbdd508713?"
        }
    )
    assert result["workflow"] == WorkflowDecision.POLICY_AND_STRUCTURED
    assert result["structured_route"] == Route.FHIR
    assert result["policy_result"] is not None
    assert result["structured_results"] is not None


async def test_abstain_populates_neither_result(graph):
    result = await graph.ainvoke({"question": "x", "requested_workflow": WorkflowDecision.ABSTAIN})
    assert result["status"] == Status.ABSTAINED
    assert result["abstention_reason"] == AbstentionReason.UNSUPPORTED_REQUEST
    assert result.get("policy_result") is None
    assert result.get("structured_results") is None


async def test_graph_execution_is_deterministic(graph):
    request = {"question": "x", "requested_workflow": WorkflowDecision.STRUCTURED_ONLY}
    first = await graph.ainvoke(request)
    second = await graph.ainvoke(request)
    assert first["status"] == second["status"]
    assert first["structured_results"] == second["structured_results"]


# Detailed validate_node unit tests live in tests/test_agents_validator.py —
# these graph-level tests only need to confirm end-to-end wiring, not
# re-verify the validator's own logic.


async def test_full_graph_surfaces_a_bad_explicit_tool_as_a_clean_abstention(graph):
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_workflow": WorkflowDecision.STRUCTURED_ONLY,
            "requested_structured_route": Route.SYNPUF,
            "requested_tools": [{"tool": "not_a_real_tool", "arguments": {}}],
        }
    )
    assert result["structured_results"] is not None
    assert result["status"] == Status.ABSTAINED
    assert result["abstention_reason"] == AbstentionReason.UNSUPPORTED_TOOL
    assert result["validation"]["passed"] is True
