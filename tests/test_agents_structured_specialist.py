import os

import pytest
from app.agents.models import MAX_STRUCTURED_TOOL_CALLS
from app.agents.structured_specialist import _resolve_calls, run_structured_specialist
from app.core.config import get_settings
from app.orchestration.models import Route

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_MULTI_AGENT_INTEGRATION") != "1",
    reason="Set CAREFLOW_MULTI_AGENT_INTEGRATION=1 with Compose running and the Phase 8 "
    "dev-subset ingestion already applied to exercise real tool execution",
)

KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"
KNOWN_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"


# --- _resolve_calls (pure, no DB) ---


def test_resolve_calls_uses_explicit_tools_list():
    state = {
        "requested_tools": [
            {"tool": "get_beneficiary_summary", "arguments": {"beneficiary_id": "x"}},
            {"tool": "get_claims_for_beneficiary", "arguments": {"beneficiary_id": "x"}},
        ]
    }
    calls = _resolve_calls(state)
    assert calls == [
        ("get_beneficiary_summary", {"beneficiary_id": "x"}),
        ("get_claims_for_beneficiary", {"beneficiary_id": "x"}),
    ]


def test_resolve_calls_explicit_workflow_without_tools_is_final_abstention():
    state = {"requested_workflow": "structured_only", "structured_route": Route.SYNPUF}
    result = _resolve_calls(state)
    assert isinstance(result, dict)
    assert result["structured_results"][0]["abstention_reason"] == "missing_required_identifier"


def test_resolve_calls_uses_classified_identifier_as_default_tool():
    state = {"structured_route": Route.FHIR, "classified_identifier": "abc-123"}
    calls = _resolve_calls(state)
    assert calls == [("get_patient_summary", {"patient_id": "abc-123"})]


def test_resolve_calls_synpuf_default_tool():
    state = {"structured_route": Route.SYNPUF, "classified_identifier": KNOWN_BENEFICIARY_ID}
    calls = _resolve_calls(state)
    assert calls == [("get_beneficiary_summary", {"beneficiary_id": KNOWN_BENEFICIARY_ID})]


def test_resolve_calls_no_identifier_no_tools_is_final_abstention():
    state = {"structured_route": Route.FHIR}
    result = _resolve_calls(state)
    assert isinstance(result, dict)
    assert result["structured_results"][0]["abstention_reason"] == "missing_required_identifier"


# --- bound enforcement (pure — happens before any DB connection) ---


async def test_more_than_max_tools_is_rejected_before_any_db_connection():
    state = {
        "structured_route": Route.SYNPUF,
        "requested_tools": [{"tool": "get_beneficiary_summary", "arguments": {}}]
        * (MAX_STRUCTURED_TOOL_CALLS + 1),
    }
    # settings=None proves no connection is attempted: this would raise if
    # the bound check happened after connect(settings).
    result = await run_structured_specialist(state, None)
    assert result["structured_results"][0]["error"] == "too_many_tool_calls"


async def test_missing_structured_route_is_rejected_before_any_db_connection():
    result = await run_structured_specialist({}, None)
    assert result["structured_results"][0]["abstention_reason"] == "missing_required_identifier"


# --- live tool execution ---


@pytestmark_live
async def test_exactly_max_tools_is_accepted_and_all_preserved():
    settings = get_settings()
    state = {
        "structured_route": Route.FHIR,
        "requested_tools": [
            {"tool": "get_patient_summary", "arguments": {"patient_id": KNOWN_PATIENT_ID}}
        ]
        * MAX_STRUCTURED_TOOL_CALLS,
    }
    result = await run_structured_specialist(state, settings)
    assert len(result["structured_results"]) == MAX_STRUCTURED_TOOL_CALLS
    assert all(item["success"] for item in result["structured_results"])


@pytestmark_live
async def test_bounded_multi_tool_execution_on_real_patient():
    settings = get_settings()
    state = {
        "structured_route": Route.FHIR,
        "requested_tools": [
            {"tool": "get_patient_summary", "arguments": {"patient_id": KNOWN_PATIENT_ID}},
            {"tool": "get_patient_conditions", "arguments": {"patient_id": KNOWN_PATIENT_ID}},
            {
                "tool": "get_patient_medication_requests",
                "arguments": {"patient_id": KNOWN_PATIENT_ID},
            },
        ],
    }
    result = await run_structured_specialist(state, settings)
    tools = {item["tool"]: item for item in result["structured_results"]}
    assert set(tools) == {
        "get_patient_summary",
        "get_patient_conditions",
        "get_patient_medication_requests",
    }
    assert all(item["success"] for item in tools.values())
    assert all(item["source_dataset"] == "synthea_fhir" for item in tools.values())


@pytestmark_live
async def test_unknown_beneficiary_produces_success_true_with_abstention_reason():
    settings = get_settings()
    state = {
        "structured_route": Route.SYNPUF,
        "requested_tools": [
            {"tool": "get_beneficiary_summary", "arguments": {"beneficiary_id": "NOT_A_REAL_ID"}}
        ],
    }
    result = await run_structured_specialist(state, settings)
    item = result["structured_results"][0]
    assert item["success"] is True
    assert item["data"] is None
    assert item["abstention_reason"] == "unknown_beneficiary"


@pytestmark_live
async def test_partial_failure_preserves_both_successful_and_failed_attempts():
    settings = get_settings()
    state = {
        "structured_route": Route.SYNPUF,
        "requested_tools": [
            {
                "tool": "get_beneficiary_summary",
                "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            },
            {"tool": "not_a_real_tool", "arguments": {}},
        ],
    }
    result = await run_structured_specialist(state, settings)
    assert len(result["structured_results"]) == 2
    successful = [r for r in result["structured_results"] if r["success"]]
    failed = [r for r in result["structured_results"] if not r["success"]]
    assert len(successful) == 1
    assert len(failed) == 1
    assert failed[0]["error"] == "unsupported_tool"


@pytestmark_live
async def test_classified_identifier_default_tool_end_to_end():
    settings = get_settings()
    state = {"structured_route": Route.SYNPUF, "classified_identifier": KNOWN_BENEFICIARY_ID}
    result = await run_structured_specialist(state, settings)
    assert result["structured_results"][0]["tool"] == "get_beneficiary_summary"
    assert result["structured_results"][0]["success"] is True


def test_no_arbitrary_sql_path_exists_in_this_module():
    import app.agents.structured_specialist as module

    with open(module.__file__) as f:
        content = f.read()
    for forbidden in ("execute_sql", "run_query", "query_database", "cursor.execute"):
        assert forbidden not in content
