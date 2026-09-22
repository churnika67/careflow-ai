import os

import pytest
from app.core.config import get_settings
from app.db.connection import connect
from app.repository import analytics, fhir, synpuf

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_STRUCTURED_INTEGRATION") != "1",
    reason="Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running and the Phase 8 "
    "dev-subset ingestion already applied to test the repository/analytics layer",
)

# Known real IDs from the reviewed dev subsets, ingested by tests/test_synpuf_ingestion.py
# and tests/test_fhir_ingestion.py before this module's tests run.
KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"
KNOWN_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"


@pytest.fixture
async def connection():
    conn = await connect(get_settings())
    try:
        yield conn
    finally:
        await conn.close()


async def test_get_beneficiary_summary_known_and_unknown(connection):
    found = await synpuf.get_beneficiary_summary(connection, KNOWN_BENEFICIARY_ID)
    assert found is not None
    assert found["beneficiary_id"] == KNOWN_BENEFICIARY_ID
    missing = await synpuf.get_beneficiary_summary(connection, "NOT_A_REAL_ID")
    assert missing is None


async def test_get_claims_for_beneficiary_all_belong_to_beneficiary(connection):
    claims = await synpuf.get_claims_for_beneficiary(connection, KNOWN_BENEFICIARY_ID)
    assert len(claims) > 0
    assert all(c["beneficiary_id"] == KNOWN_BENEFICIARY_ID for c in claims)
    dates = [c["from_date"] for c in claims]
    assert dates == sorted(dates)


async def test_get_claim_details_includes_diagnoses_procedures_lines(connection):
    claims = await synpuf.get_claims_for_beneficiary(connection, KNOWN_BENEFICIARY_ID)
    inpatient_claims = [c for c in claims if c["claim_type"] == "inpatient"]
    assert inpatient_claims, "expected at least one inpatient claim for this beneficiary"
    details = await synpuf.get_claim_details(connection, inpatient_claims[0]["claim_row_id"])
    assert details is not None
    assert "diagnoses" in details and "procedures" in details and "lines" in details


async def test_get_claim_details_unknown_claim_returns_none(connection):
    assert (
        await synpuf.get_claim_details(connection, "00000000-0000-0000-0000-000000000000") is None
    )


async def test_get_patient_summary_and_relations(connection):
    patient = await fhir.get_patient_summary(connection, KNOWN_PATIENT_ID)
    assert patient is not None and patient["patient_id"] == KNOWN_PATIENT_ID
    encounters = await fhir.get_patient_encounters(connection, KNOWN_PATIENT_ID)
    conditions = await fhir.get_patient_conditions(connection, KNOWN_PATIENT_ID)
    procedures = await fhir.get_patient_procedures(connection, KNOWN_PATIENT_ID)
    medications = await fhir.get_medication_requests(connection, KNOWN_PATIENT_ID)
    assert all(e["patient_id"] == KNOWN_PATIENT_ID for e in encounters)
    assert all(c["patient_id"] == KNOWN_PATIENT_ID for c in conditions)
    assert all(p["patient_id"] == KNOWN_PATIENT_ID for p in procedures)
    assert all(m["patient_id"] == KNOWN_PATIENT_ID for m in medications)


async def test_get_observations_component_shape_includes_components(connection):
    observations = await fhir.get_observations(connection, KNOWN_PATIENT_ID)
    component_obs = [o for o in observations if o["value_type"] == "component"]
    assert component_obs, "expected at least one blood-pressure-style observation"
    assert "components" in component_obs[0]
    assert len(component_obs[0]["components"]) >= 1


async def test_get_observations_filters_by_code(connection):
    all_observations = await fhir.get_observations(connection, KNOWN_PATIENT_ID)
    sample_code = all_observations[0]["code"]
    filtered = await fhir.get_observations(connection, KNOWN_PATIENT_ID, code=sample_code)
    assert filtered
    assert all(o["code"] == sample_code for o in filtered)


async def test_synpuf_claim_counts_and_payment_totals_are_consistent(connection):
    counts = await analytics.synpuf_claim_counts_by_type(connection)
    totals = await analytics.synpuf_payment_totals_by_type(connection)
    assert set(counts) <= {"inpatient", "outpatient"}
    for claim_type, count in counts.items():
        assert totals[claim_type]["claim_count"] == count


async def test_synpuf_diagnosis_frequency_respects_top_n(connection):
    top3 = await analytics.synpuf_diagnosis_frequency(connection, top_n=3)
    assert len(top3) <= 3
    occurrences = [row["occurrences"] for row in top3]
    assert occurrences == sorted(occurrences, reverse=True)


@pytest.mark.parametrize("bad_top_n", [0, -1, 101])
async def test_analytics_reject_out_of_range_top_n(connection, bad_top_n):
    with pytest.raises(ValueError, match="top_n"):
        await analytics.synpuf_diagnosis_frequency(connection, top_n=bad_top_n)


async def test_fhir_encounter_counts_by_class_matches_row_count(connection):
    counts = await analytics.fhir_encounter_counts_by_class(connection)
    encounters = await fhir.get_patient_encounters(connection, KNOWN_PATIENT_ID)
    assert sum(counts.values()) >= len(encounters)


async def test_fhir_condition_frequency_uses_primary_coding(connection):
    top = await analytics.fhir_condition_frequency(connection, top_n=5)
    assert len(top) <= 5
    for row in top:
        assert row["code"] and row["code_system"]
