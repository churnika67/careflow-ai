import os

import pytest
from app.analytics import snapshot as snapshot_module
from app.main import app
from fastapi.testclient import TestClient

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_ANALYTICS_INTEGRATION") != "1",
    reason="Set CAREFLOW_ANALYTICS_INTEGRATION=1 with Compose running to exercise "
    "GET /analytics/structured/overview against the real Postgres instance",
)


def test_evaluation_snapshot_returns_the_real_canonical_evidence():
    with TestClient(app) as client:
        response = client.get("/analytics/evaluation/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "phase12_artifact_snapshot"
    assert body["claim_matrix"] == {
        "supported": 6,
        "partially_supported": 10,
        "not_evaluated": 11,
        "out_of_scope": 3,
        "total": 30,
        "source": "docs/evaluation/phase12_claim_matrix.md",
    }
    assert body["cost_tokens"]["status"] == "not_evaluated"
    assert body["threshold"]["production_threshold"] == 0.60


def test_evaluation_snapshot_returns_503_when_an_artifact_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(snapshot_module, "_ARTIFACT_ROOT", tmp_path / "missing")
    with TestClient(app) as client:
        response = client.get("/analytics/evaluation/snapshot")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "evaluation_snapshot_unavailable"}}


def test_evaluation_snapshot_is_read_only_get():
    with TestClient(app) as client:
        response = client.post("/analytics/evaluation/snapshot")
    assert response.status_code == 405


def test_structured_overview_returns_503_when_the_database_is_unreachable(monkeypatch):
    async def _fail_connect(settings):
        raise ConnectionRefusedError("no database here")

    monkeypatch.setattr("app.api.analytics.connect", _fail_connect)
    with TestClient(app) as client:
        response = client.get("/analytics/structured/overview")
    assert response.status_code == 503
    assert response.json() == {"error": {"code": "structured_overview_unavailable"}}


def test_structured_overview_is_read_only_get():
    with TestClient(app) as client:
        response = client.post("/analytics/structured/overview")
    assert response.status_code == 405


@pytestmark_live
def test_structured_overview_returns_real_fhir_and_synpuf_aggregates_without_linkage():
    with TestClient(app) as client:
        response = client.get("/analytics/structured/overview")
    assert response.status_code == 200
    body = response.json()

    assert body["fhir"]["dataset"] == "synthea_fhir"
    assert body["synpuf"]["dataset"] == "cms_desynpuf"
    assert sum(body["synpuf"]["claim_counts_by_type"].values()) == 219
    assert sum(body["fhir"]["encounter_counts_by_class"].values()) == 177

    # No shared identifier anywhere -- neither block contains a patient_id
    # or beneficiary_id field, and each names its own distinct dataset.
    assert body["fhir"]["dataset"] != body["synpuf"]["dataset"]
    for block in (body["fhir"], body["synpuf"]):
        serialized = str(block)
        assert "patient_id" not in serialized
        assert "beneficiary_id" not in serialized


@pytestmark_live
def test_structured_overview_exposes_real_dataset_context_and_top_n():
    """Phase 15 Slice 3: patient_count/beneficiary_count/top_n were added
    so the dashboard can state real sample-size context instead of
    guessing or hardcoding it."""
    with TestClient(app) as client:
        response = client.get("/analytics/structured/overview")
    assert response.status_code == 200
    body = response.json()

    assert body["fhir"]["patient_count"] == 5
    assert body["fhir"]["top_n"] == 5
    assert body["synpuf"]["beneficiary_count"] == 15
    assert body["synpuf"]["top_n"] == 5

    # Every top-N frequency list actually respects the reported top_n.
    for key in ("top_conditions", "top_procedures", "top_medications"):
        assert len(body["fhir"][key]) <= body["fhir"]["top_n"]
    for key in ("top_diagnoses", "top_procedures", "top_hcpcs"):
        assert len(body["synpuf"][key]) <= body["synpuf"]["top_n"]

    # FHIR frequency rows preserve code, code_system, and code_display.
    for row in body["fhir"]["top_conditions"]:
        assert {"code", "code_system", "code_display", "occurrences"} <= set(row)

    # SynPUF frequency rows carry no description field -- the backend
    # genuinely has none, and the API must not invent one.
    for row in body["synpuf"]["top_diagnoses"]:
        assert set(row) == {"icd9_code", "occurrences"}


@pytestmark_live
def test_structured_overview_does_not_mutate_production_invariants():
    from app.core.config import get_settings
    from app.db.connection import connect

    async def _counts():
        conn = await connect(get_settings())
        try:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT count(*) FROM synpuf_claims")
                claims = (await cursor.fetchone())[0]
                await cursor.execute("SELECT count(*) FROM fhir_patients")
                patients = (await cursor.fetchone())[0]
            return claims, patients
        finally:
            await conn.close()

    import asyncio

    before = asyncio.run(_counts())
    with TestClient(app) as client:
        client.get("/analytics/structured/overview")
        client.get("/analytics/structured/overview")
    after = asyncio.run(_counts())
    assert before == after == (219, 5)


# --- Phase 16 Slice 2: security regression -- no client-controlled -------
# artifact path / experiment selector on either analytics endpoint.
#
# There is no vulnerable parameter to add here -- the actual security
# property (from backend/app/analytics/snapshot.py's own docstring) is
# that neither route accepts ANY request parameter at all, so there is
# nothing for a caller to inject a path/experiment_id through. These
# tests document and lock in that property directly, via the app's own
# OpenAPI schema (the authoritative description of what each route
# accepts) plus a live request proving an attempted injection is simply
# ignored, never interpreted as a file-selecting argument.


def test_evaluation_snapshot_route_declares_zero_parameters_in_its_openapi_schema():
    schema = app.openapi()
    operation = schema["paths"]["/analytics/evaluation/snapshot"]["get"]
    assert operation.get("parameters", []) == []
    assert "requestBody" not in operation


def test_structured_overview_route_declares_zero_parameters_in_its_openapi_schema():
    schema = app.openapi()
    operation = schema["paths"]["/analytics/structured/overview"]["get"]
    assert operation.get("parameters", []) == []
    assert "requestBody" not in operation


def test_evaluation_snapshot_ignores_an_attempted_path_traversal_query_param():
    """FastAPI silently ignores a query parameter no route function
    declares -- so a caller attempting `?experiment_id=../../etc/passwd`
    or `?path=../../` cannot influence which artifact is read; the
    response is byte-identical to a plain request."""
    with TestClient(app) as client:
        plain = client.get("/analytics/evaluation/snapshot")
        with_injection_attempt = client.get(
            "/analytics/evaluation/snapshot",
            params={
                "experiment_id": "../../../../etc/passwd",
                "path": "../../secrets.json",
                "artifact_path": "/etc/shadow",
            },
        )
    assert plain.status_code == with_injection_attempt.status_code
    assert plain.json() == with_injection_attempt.json()


# (The structural "no public function accepts a path/experiment_id
# argument" check already exists in tests/test_analytics_snapshot.py --
# not duplicated here.)
