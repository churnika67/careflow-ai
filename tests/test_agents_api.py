import os

import pytest
from app.main import app
from fastapi.testclient import TestClient

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_MULTI_AGENT_INTEGRATION") != "1",
    reason="Set CAREFLOW_MULTI_AGENT_INTEGRATION=1 with Compose running and the Phase 8 "
    "dev-subset ingestion already applied to exercise POST /multi-agent end to end",
)

KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"
KNOWN_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"


def test_blank_question_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post("/multi-agent", json={"question": ""})
    assert response.status_code == 422


def test_missing_question_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post("/multi-agent", json={})
    assert response.status_code == 422


def test_unknown_extra_field_is_rejected():
    with TestClient(app) as client:
        response = client.post("/multi-agent", json={"question": "x", "not_a_real_field": 1})
    assert response.status_code == 422


def test_invalid_workflow_string_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent", json={"question": "x", "workflow": "not_a_real_workflow"}
        )
    assert response.status_code == 422


def test_policy_only_with_structured_route_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent",
            json={"question": "x", "workflow": "policy_only", "structured_route": "synpuf"},
        )
    assert response.status_code == 422


def test_combined_workflow_without_structured_route_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent", json={"question": "x", "workflow": "policy_and_structured"}
        )
    assert response.status_code == 422


def test_more_than_five_tools_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent",
            json={
                "question": "x",
                "structured_route": "synpuf",
                "tools": [{"tool": "get_beneficiary_summary", "arguments": {}}] * 6,
            },
        )
    assert response.status_code == 422


def test_unrelated_question_abstains_with_200():
    with TestClient(app) as client:
        response = client.post("/multi-agent", json={"question": "what is the weather"})
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"] == "abstain"
    assert body["status"] == "abstained"
    assert body["abstention_reason"] == "unsupported_request"
    assert body["policy"] is None
    assert body["structured"] is None


def test_explicit_structured_only_unknown_tool_abstains_with_200_not_500():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent",
            json={
                "question": "x",
                "workflow": "structured_only",
                "structured_route": "synpuf",
                "tools": [{"tool": "not_a_real_tool", "arguments": {}}],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "abstained"
    assert body["abstention_reason"] == "unsupported_tool"
    assert body["structured"]["route"] == "synpuf"


@pytestmark_live
def test_valid_policy_only_request_returns_answer_and_citations():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent",
            json={
                "question": "x",
                "workflow": "policy_only",
                "policy_question": "Does Medicare cover hospital beds?",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"] == "policy_only"
    assert body["structured"] is None
    if body["status"] == "ok":
        assert body["policy"]["answer"]
        assert isinstance(body["policy"]["citations"], list)
    else:
        assert body["abstention_reason"] == "policy_abstained"


@pytestmark_live
def test_valid_structured_only_synpuf_request_returns_real_data():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent",
            json={
                "question": "x",
                "workflow": "structured_only",
                "structured_route": "synpuf",
                "tools": [
                    {
                        "tool": "get_beneficiary_summary",
                        "arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
                    }
                ],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["policy"] is None
    result = body["structured"]["results"][0]
    assert result["source_dataset"] == "cms_desynpuf"
    assert result["data"]["beneficiary_id"] == KNOWN_BENEFICIARY_ID


@pytestmark_live
def test_valid_combined_workflow_returns_both_policy_and_structured():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent",
            json={
                "question": "x",
                "workflow": "policy_and_structured",
                "policy_question": "Does Medicare cover hospital beds?",
                "structured_route": "fhir",
                "tools": [
                    {"tool": "get_patient_summary", "arguments": {"patient_id": KNOWN_PATIENT_ID}}
                ],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"] == "policy_and_structured"
    assert body["policy"] is not None
    assert body["structured"] is not None
    assert body["validation"] is not None


@pytestmark_live
def test_unknown_beneficiary_abstains_with_200():
    with TestClient(app) as client:
        response = client.post(
            "/multi-agent",
            json={
                "question": "x",
                "workflow": "structured_only",
                "structured_route": "synpuf",
                "tools": [
                    {
                        "tool": "get_beneficiary_summary",
                        "arguments": {"beneficiary_id": "NOT_A_REAL_ID"},
                    }
                ],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "abstained"
    assert body["abstention_reason"] == "unknown_beneficiary"


@pytestmark_live
def test_existing_query_endpoint_contract_is_unchanged():
    with TestClient(app) as client:
        response = client.post("/query", json={"question": "Does Medicare cover hospital beds?"})
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body and "citations" in body
    assert "workflow" not in body


@pytestmark_live
def test_existing_orchestrate_endpoint_contract_is_unchanged():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "what is the weather"})
    assert response.status_code == 200
    body = response.json()
    # POST /orchestrate's own response shape (route/tool, no "workflow") is untouched.
    assert body["route"] == "abstain"
    assert "workflow" not in body


# --- Phase 16 Slice 2: API-level route-boundary exception mapping ---------
# Mirrors tests/test_orchestration_api.py's equivalent pair for /orchestrate
# -- proves backend/app/api/multi_agent.py's own route handler maps
# GenerationError/unexpected exceptions to the right HTTP response,
# without needing a live Postgres/Qdrant/generation provider.


def test_generation_error_maps_to_its_declared_status_code_through_the_route(monkeypatch):
    from app.generation.providers import GenerationError

    class _FakeGraph:
        async def ainvoke(self, state):
            raise GenerationError("provider_timeout", status_code=504)

    monkeypatch.setattr(
        "app.api.multi_agent.build_multi_agent_graph", lambda settings: _FakeGraph()
    )
    with TestClient(app) as client:
        response = client.post("/multi-agent", json={"question": "does this time out"})
    assert response.status_code == 504
    assert response.json() == {"error": {"code": "provider_timeout"}}


def test_unexpected_infrastructure_failure_maps_to_503_never_exposing_internals(monkeypatch):
    class _FakeGraph:
        async def ainvoke(self, state):
            raise RuntimeError("connection refused: internal detail that must never leak")

    monkeypatch.setattr(
        "app.api.multi_agent.build_multi_agent_graph", lambda settings: _FakeGraph()
    )
    with TestClient(app) as client:
        response = client.post("/multi-agent", json={"question": "does this fail"})
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "multi_agent_unavailable"}}
    assert "connection refused" not in response.text
