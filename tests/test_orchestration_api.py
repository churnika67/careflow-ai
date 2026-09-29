import os

import pytest
from app.main import app
from fastapi.testclient import TestClient

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_ORCHESTRATION_INTEGRATION") != "1",
    reason="Set CAREFLOW_ORCHESTRATION_INTEGRATION=1 with Compose running and the Phase 8 "
    "dev-subset ingestion already applied to exercise POST /orchestrate end to end",
)

KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"
KNOWN_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"


def test_blank_question_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": ""})
    assert response.status_code == 422


def test_missing_question_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={})
    assert response.status_code == 422


def test_unknown_extra_field_is_rejected():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "x", "not_a_real_field": 1})
    assert response.status_code == 422


def test_invalid_route_string_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "x", "route": "not_a_real_route"})
    assert response.status_code == 422


def test_policy_route_with_a_tool_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/orchestrate",
            json={"question": "x", "route": "policy", "tool": "get_beneficiary_summary"},
        )
    assert response.status_code == 422


def test_tool_without_an_explicit_route_is_a_validation_error():
    with TestClient(app) as client:
        response = client.post(
            "/orchestrate", json={"question": "x", "tool": "get_beneficiary_summary"}
        )
    assert response.status_code == 422


def test_unrelated_question_abstains_with_200():
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "what is the weather"})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "abstain"
    assert body["status"] == "abstained"
    assert body["abstention_reason"] == "unsupported_request"


def test_domain_mismatch_route_and_tool_abstains_with_200_not_500():
    with TestClient(app) as client:
        response = client.post(
            "/orchestrate",
            json={
                "question": "x",
                "route": "fhir",
                "tool": "get_beneficiary_summary",
                "tool_arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "abstained"
    assert body["abstention_reason"] == "unsupported_tool"


@pytestmark_live
def test_valid_policy_request_returns_answer_and_citations():
    with TestClient(app) as client:
        response = client.post(
            "/orchestrate", json={"question": "Does Medicare cover hospital beds?"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "policy"
    if body["status"] == "ok":
        assert body["answer"]
        assert isinstance(body["citations"], list)
    else:
        assert body["abstention_reason"] == "policy_abstained"


@pytestmark_live
def test_valid_structured_synpuf_request_returns_real_data():
    with TestClient(app) as client:
        response = client.post(
            "/orchestrate",
            json={
                "question": "x",
                "route": "synpuf",
                "tool": "get_beneficiary_summary",
                "tool_arguments": {"beneficiary_id": KNOWN_BENEFICIARY_ID},
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["source_dataset"] == "cms_desynpuf"
    assert body["record_count"] == 1
    assert body["data"]["beneficiary_id"] == KNOWN_BENEFICIARY_ID


@pytestmark_live
def test_valid_structured_fhir_request_returns_real_data():
    with TestClient(app) as client:
        response = client.post(
            "/orchestrate",
            json={
                "question": "x",
                "route": "fhir",
                "tool": "get_patient_conditions",
                "tool_arguments": {"patient_id": KNOWN_PATIENT_ID},
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["source_dataset"] == "synthea_fhir"
    assert isinstance(body["data"], list)
    assert body["record_count"] == len(body["data"])


@pytestmark_live
def test_unknown_beneficiary_abstains_with_200():
    with TestClient(app) as client:
        response = client.post(
            "/orchestrate",
            json={
                "question": "x",
                "route": "synpuf",
                "tool": "get_beneficiary_summary",
                "tool_arguments": {"beneficiary_id": "NOT_A_REAL_ID"},
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
    # POST /query's own response shape (no "route"/"tool" fields) is untouched.
    assert "answer" in body and "citations" in body
    assert "route" not in body


# --- Phase 16 Slice 2: API-level route-boundary exception mapping ---------
#
# The lower-layer graph/generation tests already exercise GenerationError
# handling in isolation. These two tests instead prove the *route handler
# itself* (backend/app/api/orchestrate.py) maps it to the right HTTP
# response -- the one boundary no existing test drove through TestClient.
# No live Postgres/Qdrant/generation provider is needed: build_graph is
# monkeypatched at the point orchestrate.py imports it, so this is a pure,
# unconditional unit test of the route, never live-gated.


def test_generation_error_maps_to_its_declared_status_code_through_the_route(monkeypatch):
    from app.generation.providers import GenerationError

    class _FakeGraph:
        async def ainvoke(self, state):
            raise GenerationError("provider_timeout", status_code=504)

    monkeypatch.setattr("app.api.orchestrate.build_graph", lambda settings: _FakeGraph())
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "does this time out"})
    assert response.status_code == 504
    assert response.json() == {"error": {"code": "provider_timeout"}}


def test_unexpected_infrastructure_failure_maps_to_503_never_exposing_internals(monkeypatch):
    class _FakeGraph:
        async def ainvoke(self, state):
            raise RuntimeError("connection refused: internal detail that must never leak")

    monkeypatch.setattr("app.api.orchestrate.build_graph", lambda settings: _FakeGraph())
    with TestClient(app) as client:
        response = client.post("/orchestrate", json={"question": "does this fail"})
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "orchestration_unavailable"}}
    assert "connection refused" not in response.text
