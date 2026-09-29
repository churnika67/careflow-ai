import os

import pytest
from app.core.config import get_settings
from app.db.connection import connect
from app.orchestration.models import Route
from app.orchestration.tools import (
    TOOL_REGISTRY,
    BeneficiaryIdArgs,
    ClaimRowIdArgs,
    NoArgs,
    PatientIdArgs,
    PatientObservationArgs,
    TopNArgs,
    execute_tool,
)
from pydantic import ValidationError

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_STRUCTURED_INTEGRATION") != "1",
    reason="Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running and the Phase 8 "
    "dev-subset ingestion already applied to test tool execution",
)

KNOWN_BENEFICIARY_ID = "00013D2EFD8E45D1"
KNOWN_PATIENT_ID = "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"


# --- argument schema validation (pure, no DB) ---


def test_patient_id_args_accepts_valid_id():
    assert PatientIdArgs(patient_id="abc").patient_id == "abc"


def test_patient_id_args_rejects_empty_string():
    with pytest.raises(ValidationError):
        PatientIdArgs(patient_id="")


def test_patient_id_args_rejects_missing_required_field():
    with pytest.raises(ValidationError):
        PatientIdArgs()


def test_patient_id_args_rejects_extra_unexpected_fields():
    with pytest.raises(ValidationError):
        PatientIdArgs(patient_id="abc", beneficiary_id="unexpected")


def test_beneficiary_id_args_accepts_valid_id():
    assert BeneficiaryIdArgs(beneficiary_id=KNOWN_BENEFICIARY_ID).beneficiary_id == (
        KNOWN_BENEFICIARY_ID
    )


def test_beneficiary_id_args_rejects_empty_string():
    with pytest.raises(ValidationError):
        BeneficiaryIdArgs(beneficiary_id="")


def test_beneficiary_id_args_rejects_over_length_value():
    with pytest.raises(ValidationError):
        BeneficiaryIdArgs(beneficiary_id="X" * 33)


def test_claim_row_id_args_uses_claim_row_id_name_not_claim_id():
    args = ClaimRowIdArgs(claim_row_id="00000000-0000-0000-0000-000000000000")
    assert args.claim_row_id == "00000000-0000-0000-0000-000000000000"
    with pytest.raises(ValidationError):
        ClaimRowIdArgs(claim_id="00000000-0000-0000-0000-000000000000")  # wrong field name


def test_claim_row_id_args_accepts_a_real_uuid_object_not_only_str():
    # Regression: synpuf_claims.claim_row_id is a native Postgres UUID
    # column, so a value round-tripped from get_claims_for_beneficiary is a
    # uuid.UUID, not a str — caught live before this test existed.
    from uuid import UUID

    value = UUID("37f7abe8-d7a9-55ea-9e92-4a5e7a3be911")
    args = ClaimRowIdArgs(claim_row_id=value)
    assert args.claim_row_id == str(value)


@pytest.mark.parametrize("top_n", [1, 50, 100])
def test_top_n_args_accepts_bounded_values(top_n):
    assert TopNArgs(top_n=top_n).top_n == top_n


@pytest.mark.parametrize("top_n", [0, -1, 101])
def test_top_n_args_rejects_out_of_range_values(top_n):
    with pytest.raises(ValidationError):
        TopNArgs(top_n=top_n)


def test_patient_observation_args_code_is_optional():
    assert PatientObservationArgs(patient_id="abc").code is None
    assert PatientObservationArgs(patient_id="abc", code="8310-5").code == "8310-5"


def test_no_args_rejects_any_field():
    NoArgs()
    with pytest.raises(ValidationError):
        NoArgs(anything="x")


# --- registry integrity (pure, no DB) ---


def test_registry_contains_only_the_approved_tool_names():
    expected = {
        "get_patient_summary",
        "get_patient_encounters",
        "get_patient_conditions",
        "get_patient_procedures",
        "get_patient_observations",
        "get_patient_medication_requests",
        "fhir_encounter_counts",
        "fhir_condition_frequency",
        "fhir_procedure_frequency",
        "fhir_medication_frequency",
        "get_beneficiary_summary",
        "get_claims_for_beneficiary",
        "get_claim_details",
        "synpuf_claim_counts",
        "synpuf_payment_totals",
        "synpuf_diagnosis_frequency",
        "synpuf_procedure_frequency",
        "synpuf_hcpcs_frequency",
    }
    assert set(TOOL_REGISTRY) == expected


def test_no_tool_in_the_registry_accepts_raw_sql_or_table_names():
    for spec in TOOL_REGISTRY.values():
        fields = spec.argument_schema.model_fields
        assert not any(name in fields for name in ("sql", "query", "table", "column"))


def test_every_fhir_tool_is_route_fhir_and_source_synthea():
    for name, spec in TOOL_REGISTRY.items():
        if name.startswith("fhir_") or name.startswith("get_patient"):
            assert spec.route == Route.FHIR
            assert spec.source_dataset == "synthea_fhir"


def test_every_synpuf_tool_is_route_synpuf_and_source_cms_desynpuf():
    for name, spec in TOOL_REGISTRY.items():
        if name.startswith("synpuf_") or name in (
            "get_beneficiary_summary",
            "get_claims_for_beneficiary",
            "get_claim_details",
        ):
            assert spec.route == Route.SYNPUF
            assert spec.source_dataset == "cms_desynpuf"


# --- execute_tool dispatch semantics (pure, no DB needed for these cases) ---


async def test_execute_tool_unknown_tool_name_is_unsupported_tool():
    result = await execute_tool(None, Route.FHIR, "not_a_real_tool", {})
    assert result.success is False
    assert result.error == "unsupported_tool"


async def test_execute_tool_missing_tool_name():
    result = await execute_tool(None, Route.FHIR, None, {})
    assert result.success is False
    assert result.error == "missing_tool_name"


async def test_execute_tool_domain_mismatch_synpuf_tool_under_fhir_route():
    result = await execute_tool(None, Route.FHIR, "get_beneficiary_summary", {})
    assert result.success is False
    assert result.error == "unsupported_tool"


async def test_execute_tool_domain_mismatch_fhir_tool_under_synpuf_route():
    result = await execute_tool(None, Route.SYNPUF, "get_patient_summary", {})
    assert result.success is False
    assert result.error == "unsupported_tool"


# --- Phase 16 Slice 2: cross-dataset identity-linkage regression ---------
#
# backend/app/agents/structured_specialist.py resolves a multi-agent
# structured-only request against exactly ONE Route for its whole tools
# list (MultiAgentRequest.structured_route is a single value, never a
# list -- see backend/app/agents/models.py). There is no request shape
# that lets a caller name both a FHIR patient_id and a SynPUF
# beneficiary_id and have them treated as the same identity: whichever
# tool doesn't match the request's single declared route is rejected
# independently, per call, and never merged with any other call's result.
# This test proves that directly, using both an FHIR-shaped and a
# SynPUF-shaped identifier in the same attempted (mismatched) call --
# current Phase 9/10 semantics, not a new policy invented for this test.


async def test_a_synpuf_beneficiary_identifier_is_never_resolved_under_an_fhir_route():
    """Simulates the exact shape of a cross-dataset linkage attempt: a
    caller declares route=FHIR (as a multi-agent structured_route would
    resolve to) but supplies a SynPUF beneficiary_id-shaped tool call.
    The beneficiary identifier is never looked up, and the result carries
    no FHIR data alongside it -- there is nothing here that could be
    mistaken for a linked patient/beneficiary profile."""
    result = await execute_tool(
        None, Route.FHIR, "get_beneficiary_summary", {"beneficiary_id": "00013D2EFD8E45D1"}
    )
    assert result.success is False
    assert result.error == "unsupported_tool"
    assert result.data is None
    assert result.source_dataset is None


async def test_an_fhir_patient_identifier_is_never_resolved_under_a_synpuf_route():
    """The reverse direction of the same property."""
    result = await execute_tool(
        None,
        Route.SYNPUF,
        "get_patient_summary",
        {"patient_id": "31a2e8ec-69fc-8a71-3ab6-36cbdd508713"},
    )
    assert result.success is False
    assert result.error == "unsupported_tool"
    assert result.data is None
    assert result.source_dataset is None


def test_multi_agent_request_schema_cannot_express_two_structured_routes_at_once():
    """Structural proof that a combined-dataset request is inexpressible,
    not merely rejected at runtime: MultiAgentRequest.structured_route is
    a single Route (or None), never a list -- so there is no way to
    construct a request naming both 'fhir' and 'synpuf' as the target of
    one structured_only/policy_and_structured call in the first place."""
    from app.agents.models import MultiAgentRequest

    field = MultiAgentRequest.model_fields["structured_route"]
    assert "list" not in str(field.annotation).lower()
    with pytest.raises(ValidationError):
        MultiAgentRequest.model_validate(
            {
                "question": "x",
                "workflow": "structured_only",
                "structured_route": ["fhir", "synpuf"],
                "tools": [{"tool": "get_patient_summary", "arguments": {"patient_id": "x"}}],
            }
        )


async def test_execute_tool_invalid_arguments_reported_not_raised():
    result = await execute_tool(None, Route.FHIR, "get_patient_summary", {})  # missing patient_id
    assert result.success is False
    assert result.error == "invalid_tool_arguments"


# --- live tool execution against the real ingested Phase 8 dev subset ---


@pytest.fixture
async def connection():
    conn = await connect(get_settings())
    try:
        yield conn
    finally:
        await conn.close()


@pytestmark_live
async def test_fhir_tools_against_real_patient(connection):
    for tool, expect_list in (
        ("get_patient_summary", False),
        ("get_patient_encounters", True),
        ("get_patient_conditions", True),
        ("get_patient_procedures", True),
        ("get_patient_observations", True),
        ("get_patient_medication_requests", True),
    ):
        result = await execute_tool(connection, Route.FHIR, tool, {"patient_id": KNOWN_PATIENT_ID})
        assert result.success is True, (tool, result.error)
        assert result.source_dataset == "synthea_fhir"
        if expect_list:
            assert isinstance(result.data, list)
            assert result.record_count == len(result.data)
        else:
            assert result.data is not None


@pytestmark_live
async def test_fhir_tool_unknown_patient_returns_success_with_no_data(connection):
    result = await execute_tool(
        connection, Route.FHIR, "get_patient_summary", {"patient_id": "not-a-real-patient"}
    )
    assert result.success is True
    assert result.data is None
    assert result.record_count == 0


@pytestmark_live
async def test_synpuf_tools_against_real_beneficiary(connection):
    summary = await execute_tool(
        connection,
        Route.SYNPUF,
        "get_beneficiary_summary",
        {"beneficiary_id": KNOWN_BENEFICIARY_ID},
    )
    assert summary.success is True
    assert summary.data is not None
    assert summary.source_dataset == "cms_desynpuf"

    claims = await execute_tool(
        connection,
        Route.SYNPUF,
        "get_claims_for_beneficiary",
        {"beneficiary_id": KNOWN_BENEFICIARY_ID},
    )
    assert claims.success is True
    assert isinstance(claims.data, list) and len(claims.data) > 0

    details = await execute_tool(
        connection,
        Route.SYNPUF,
        "get_claim_details",
        {"claim_row_id": claims.data[0]["claim_row_id"]},
    )
    assert details.success is True
    assert details.data is not None
    assert "diagnoses" in details.data


@pytestmark_live
async def test_synpuf_tool_unknown_beneficiary_returns_success_with_no_data(connection):
    result = await execute_tool(
        connection, Route.SYNPUF, "get_beneficiary_summary", {"beneficiary_id": "NOT_A_REAL_ID"}
    )
    assert result.success is True
    assert result.data is None


@pytestmark_live
async def test_synpuf_tool_unknown_claim_returns_success_with_no_data(connection):
    result = await execute_tool(
        connection,
        Route.SYNPUF,
        "get_claim_details",
        {"claim_row_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert result.success is True
    assert result.data is None


@pytestmark_live
async def test_analytics_tools_live(connection):
    for route, tool, args in (
        (Route.SYNPUF, "synpuf_claim_counts", {}),
        (Route.SYNPUF, "synpuf_payment_totals", {}),
        (Route.SYNPUF, "synpuf_diagnosis_frequency", {"top_n": 5}),
        (Route.SYNPUF, "synpuf_procedure_frequency", {"top_n": 5}),
        (Route.SYNPUF, "synpuf_hcpcs_frequency", {"top_n": 5}),
        (Route.FHIR, "fhir_encounter_counts", {}),
        (Route.FHIR, "fhir_condition_frequency", {"top_n": 5}),
        (Route.FHIR, "fhir_procedure_frequency", {"top_n": 5}),
        (Route.FHIR, "fhir_medication_frequency", {"top_n": 5}),
    ):
        result = await execute_tool(connection, route, tool, args)
        assert result.success is True, (tool, result.error)
        assert result.data is not None
