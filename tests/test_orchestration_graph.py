import os

import pytest
from app.core.config import get_settings
from app.orchestration.graph import _select_branch, build_graph, validate_node
from app.orchestration.models import AbstentionReason, GraphState, Route, Status

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_ORCHESTRATION_INTEGRATION") != "1",
    reason="Set CAREFLOW_ORCHESTRATION_INTEGRATION=1 with Compose running (Postgres, Qdrant) "
    "and the Phase 8 dev-subset ingestion already applied to exercise real policy/synpuf/fhir "
    "node execution",
)

KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"
KNOWN_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"


@pytest.fixture(scope="module")
def graph():
    # A real Settings object is required to build the graph (it's captured
    # in the synpuf/fhir node closures), but constructing it needs no I/O —
    # only tests that actually reach those nodes need live services.
    return build_graph(get_settings())


def test_graph_compiles():
    assert build_graph(get_settings()) is not None


@pytest.mark.parametrize("route", [Route.POLICY, Route.SYNPUF, Route.FHIR, Route.ABSTAIN])
def test_select_branch_maps_each_route_to_its_own_node(route):
    assert _select_branch({"route": route}) == route.value


def test_select_branch_defaults_to_abstain_for_missing_route():
    assert _select_branch({}) == "abstain"


# --- paths that never reach a live service (route_node resolves directly to
# ABSTAIN, so abstain_node -> validate_node -> END runs with no I/O) ---


async def test_explicit_abstain_route_reaches_abstain_node_and_validate(graph):
    result = await graph.ainvoke({"question": "x", "requested_route": Route.ABSTAIN})
    assert result["route"] == Route.ABSTAIN
    assert result["status"] == Status.ABSTAINED
    assert result["abstention_reason"] == AbstentionReason.UNSUPPORTED_REQUEST


async def test_explicit_policy_route_with_a_tool_is_an_inconsistent_request(graph):
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_route": Route.POLICY,
            "requested_tool": "get_beneficiary_summary",
        }
    )
    assert result["route"] == Route.ABSTAIN
    assert result["abstention_reason"] == AbstentionReason.INCONSISTENT_REQUEST


async def test_no_requested_route_unsupported_text_abstains_without_touching_any_service(graph):
    result = await graph.ainvoke({"question": "what is the weather"})
    assert result["route"] == Route.ABSTAIN
    assert result["abstention_reason"] == AbstentionReason.UNSUPPORTED_REQUEST


async def test_structured_route_without_tool_or_identifier_abstains_before_any_db_call(graph):
    # requested_route=SYNPUF with no tool: route_node lets it through, but
    # _run_structured_route abstains before opening a connection.
    result = await graph.ainvoke({"question": "x", "requested_route": Route.SYNPUF})
    assert result["route"] == Route.SYNPUF
    assert result["status"] == Status.ABSTAINED
    assert result["abstention_reason"] == AbstentionReason.MISSING_REQUIRED_IDENTIFIER


async def test_execute_tool_unsupported_tool_becomes_graph_abstention(graph):
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_route": Route.SYNPUF,
            "requested_tool": "not_a_real_tool",
            "requested_tool_arguments": {},
        }
    )
    assert result["status"] == Status.ABSTAINED
    assert result["abstention_reason"] == AbstentionReason.UNSUPPORTED_TOOL


async def test_execute_tool_invalid_arguments_becomes_graph_abstention(graph):
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_route": Route.SYNPUF,
            "requested_tool": "get_beneficiary_summary",
            "requested_tool_arguments": {},  # missing beneficiary_id
        }
    )
    assert result["status"] == Status.ABSTAINED
    assert result["abstention_reason"] == AbstentionReason.INVALID_TOOL_ARGUMENTS


# --- paths that genuinely exercise policy/synpuf/fhir nodes (live services) ---


@pytestmark_live
async def test_policy_route_reaches_the_real_rag_pipeline_and_preserves_citations(graph):
    result = await graph.ainvoke({"question": "Does Medicare cover hospital beds?"})
    assert result["route"] == Route.POLICY
    assert result["status"] in (Status.OK, Status.ABSTAINED)
    if result["status"] == Status.OK:
        assert "citations" in result["policy_result"]
    else:
        assert result["abstention_reason"] == AbstentionReason.POLICY_ABSTAINED
        assert "abstention_reason" in result["policy_result"]  # Phase 4's own reason preserved


@pytestmark_live
async def test_synpuf_route_explicit_tool_reaches_the_real_repository(graph):
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_route": Route.SYNPUF,
            "requested_tool": "get_beneficiary_summary",
            "requested_tool_arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
        }
    )
    assert result["route"] == Route.SYNPUF
    assert result["status"] == Status.OK
    assert result["structured_result"]["source_dataset"] == "cms_desynpuf"
    assert result["structured_result"]["record_count"] == 1


@pytestmark_live
async def test_fhir_route_via_classifier_default_tool_reaches_the_real_repository(graph):
    result = await graph.ainvoke({"question": f"show conditions for patient {KNOWN_PATIENT_ID}"})
    assert result["route"] == Route.FHIR
    assert result["status"] == Status.OK
    assert result["tool_name"] == "get_patient_summary"
    assert result["structured_result"]["source_dataset"] == "synthea_fhir"


@pytestmark_live
async def test_synpuf_route_unknown_beneficiary_abstains(graph):
    result = await graph.ainvoke(
        {
            "question": "x",
            "requested_route": Route.SYNPUF,
            "requested_tool": "get_beneficiary_summary",
            "requested_tool_arguments": {"beneficiary_id": "NOT_A_REAL_ID"},
        }
    )
    assert result["status"] == Status.ABSTAINED
    assert result["abstention_reason"] == AbstentionReason.UNKNOWN_BENEFICIARY


@pytestmark_live
async def test_graph_execution_is_deterministic_for_a_live_route(graph):
    request = {
        "question": "x",
        "requested_route": Route.SYNPUF,
        "requested_tool": "get_beneficiary_summary",
        "requested_tool_arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
    }
    first = await graph.ainvoke(request)
    second = await graph.ainvoke(request)
    assert first["status"] == second["status"]
    assert first["structured_result"] == second["structured_result"]


# --- validate_node unit tests (pure, no service or graph needed) ---


def test_validate_node_catches_missing_status():
    state: GraphState = {"question": "x"}
    update = validate_node(state)
    assert update["status"] == Status.ERROR
    assert update["error"] == "no_status_set"


def test_validate_node_catches_abstained_without_reason():
    state: GraphState = {"status": Status.ABSTAINED}
    update = validate_node(state)
    assert update["status"] == Status.ERROR
    assert update["error"] == "abstained_without_reason"


def test_validate_node_catches_ok_status_without_any_result():
    state: GraphState = {"status": Status.OK}
    update = validate_node(state)
    assert update["status"] == Status.ERROR
    assert update["error"] == "ok_status_without_result"


def test_validate_node_passes_through_a_well_formed_ok_state():
    state: GraphState = {"status": Status.OK, "policy_result": {"answer": "x"}}
    assert validate_node(state) == {}


def test_validate_node_passes_through_a_well_formed_abstained_state():
    state: GraphState = {
        "status": Status.ABSTAINED,
        "abstention_reason": AbstentionReason.UNSUPPORTED_REQUEST,
    }
    assert validate_node(state) == {}
