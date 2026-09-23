"""The structured-data tool registry. Every entry wraps one real Phase 8
repository function (backend/app/repository/{synpuf,fhir,analytics}.py) —
nothing here writes new SQL, and nothing accepts arbitrary SQL, table names,
or column names. There is deliberately no execute_sql/run_query/query_database
tool, and never will be in this module.

Argument validation always goes through the tool's own StrictModel
(extra="forbid") before any repository call — a raw request dict is never
passed to a repository function directly.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

import psycopg
from pydantic import Field, ValidationError, field_validator

from app.orchestration.models import Route, StrictModel
from app.repository import analytics, fhir, synpuf

SourceDataset = Literal["cms_desynpuf", "synthea_fhir"]


class PatientIdArgs(StrictModel):
    patient_id: str = Field(min_length=1, max_length=64)


class PatientObservationArgs(StrictModel):
    patient_id: str = Field(min_length=1, max_length=64)
    code: str | None = Field(default=None, min_length=1, max_length=64)


class BeneficiaryIdArgs(StrictModel):
    beneficiary_id: str = Field(min_length=1, max_length=32)


class ClaimRowIdArgs(StrictModel):
    # synpuf_claims.claim_row_id is a native Postgres UUID column (Phase 8
    # migration 0002), so a value fetched from get_claims_for_beneficiary and
    # passed straight back into this tool arrives as a uuid.UUID, not a str.
    # An API caller sending JSON always sends a string. Both are accepted and
    # normalized to str before the length check, matching real call shapes
    # instead of a value type that can't actually occur.
    claim_row_id: str = Field(min_length=1, max_length=64)

    @field_validator("claim_row_id", mode="before")
    @classmethod
    def _accept_uuid_object(cls, value: object) -> object:
        return str(value) if isinstance(value, UUID) else value


class TopNArgs(StrictModel):
    top_n: int = Field(default=10, ge=1, le=100)


class NoArgs(StrictModel):
    pass


async def _get_patient_summary(connection, args: PatientIdArgs):
    return await fhir.get_patient_summary(connection, args.patient_id)


async def _get_patient_encounters(connection, args: PatientIdArgs):
    return await fhir.get_patient_encounters(connection, args.patient_id)


async def _get_patient_conditions(connection, args: PatientIdArgs):
    return await fhir.get_patient_conditions(connection, args.patient_id)


async def _get_patient_procedures(connection, args: PatientIdArgs):
    return await fhir.get_patient_procedures(connection, args.patient_id)


async def _get_patient_observations(connection, args: PatientObservationArgs):
    return await fhir.get_observations(connection, args.patient_id, args.code)


async def _get_patient_medication_requests(connection, args: PatientIdArgs):
    return await fhir.get_medication_requests(connection, args.patient_id)


async def _fhir_encounter_counts(connection, args: NoArgs):
    return await analytics.fhir_encounter_counts_by_class(connection)


async def _fhir_condition_frequency(connection, args: TopNArgs):
    return await analytics.fhir_condition_frequency(connection, args.top_n)


async def _fhir_procedure_frequency(connection, args: TopNArgs):
    return await analytics.fhir_procedure_frequency(connection, args.top_n)


async def _fhir_medication_frequency(connection, args: TopNArgs):
    return await analytics.fhir_medication_frequency(connection, args.top_n)


async def _get_beneficiary_summary(connection, args: BeneficiaryIdArgs):
    return await synpuf.get_beneficiary_summary(connection, args.beneficiary_id)


async def _get_claims_for_beneficiary(connection, args: BeneficiaryIdArgs):
    return await synpuf.get_claims_for_beneficiary(connection, args.beneficiary_id)


async def _get_claim_details(connection, args: ClaimRowIdArgs):
    # Phase 8's repository names this parameter claim_row_id — the
    # deterministic uuid5(claim_type, claim_id, segment) primary key, not
    # the source CLM_ID (which is not globally unique; see
    # docs/phase8_structured_health_data.md). The tool argument keeps that
    # same name deliberately, so callers are not misled about what value is
    # required.
    return await synpuf.get_claim_details(connection, args.claim_row_id)


async def _synpuf_claim_counts(connection, args: NoArgs):
    return await analytics.synpuf_claim_counts_by_type(connection)


async def _synpuf_payment_totals(connection, args: NoArgs):
    return await analytics.synpuf_payment_totals_by_type(connection)


async def _synpuf_diagnosis_frequency(connection, args: TopNArgs):
    return await analytics.synpuf_diagnosis_frequency(connection, args.top_n)


async def _synpuf_procedure_frequency(connection, args: TopNArgs):
    return await analytics.synpuf_procedure_frequency(connection, args.top_n)


async def _synpuf_hcpcs_frequency(connection, args: TopNArgs):
    return await analytics.synpuf_hcpcs_frequency(connection, args.top_n)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    route: Route
    argument_schema: type[StrictModel]
    source_dataset: SourceDataset
    implementation: Callable[[psycopg.AsyncConnection, StrictModel], Awaitable[Any]]


_TOOL_SPECS = (
    ToolSpec(
        name="get_patient_summary",
        route=Route.FHIR,
        argument_schema=PatientIdArgs,
        source_dataset="synthea_fhir",
        implementation=_get_patient_summary,
    ),
    ToolSpec(
        name="get_patient_encounters",
        route=Route.FHIR,
        argument_schema=PatientIdArgs,
        source_dataset="synthea_fhir",
        implementation=_get_patient_encounters,
    ),
    ToolSpec(
        name="get_patient_conditions",
        route=Route.FHIR,
        argument_schema=PatientIdArgs,
        source_dataset="synthea_fhir",
        implementation=_get_patient_conditions,
    ),
    ToolSpec(
        name="get_patient_procedures",
        route=Route.FHIR,
        argument_schema=PatientIdArgs,
        source_dataset="synthea_fhir",
        implementation=_get_patient_procedures,
    ),
    ToolSpec(
        name="get_patient_observations",
        route=Route.FHIR,
        argument_schema=PatientObservationArgs,
        source_dataset="synthea_fhir",
        implementation=_get_patient_observations,
    ),
    ToolSpec(
        name="get_patient_medication_requests",
        route=Route.FHIR,
        argument_schema=PatientIdArgs,
        source_dataset="synthea_fhir",
        implementation=_get_patient_medication_requests,
    ),
    ToolSpec(
        name="fhir_encounter_counts",
        route=Route.FHIR,
        argument_schema=NoArgs,
        source_dataset="synthea_fhir",
        implementation=_fhir_encounter_counts,
    ),
    ToolSpec(
        name="fhir_condition_frequency",
        route=Route.FHIR,
        argument_schema=TopNArgs,
        source_dataset="synthea_fhir",
        implementation=_fhir_condition_frequency,
    ),
    ToolSpec(
        name="fhir_procedure_frequency",
        route=Route.FHIR,
        argument_schema=TopNArgs,
        source_dataset="synthea_fhir",
        implementation=_fhir_procedure_frequency,
    ),
    ToolSpec(
        name="fhir_medication_frequency",
        route=Route.FHIR,
        argument_schema=TopNArgs,
        source_dataset="synthea_fhir",
        implementation=_fhir_medication_frequency,
    ),
    ToolSpec(
        name="get_beneficiary_summary",
        route=Route.SYNPUF,
        argument_schema=BeneficiaryIdArgs,
        source_dataset="cms_desynpuf",
        implementation=_get_beneficiary_summary,
    ),
    ToolSpec(
        name="get_claims_for_beneficiary",
        route=Route.SYNPUF,
        argument_schema=BeneficiaryIdArgs,
        source_dataset="cms_desynpuf",
        implementation=_get_claims_for_beneficiary,
    ),
    ToolSpec(
        name="get_claim_details",
        route=Route.SYNPUF,
        argument_schema=ClaimRowIdArgs,
        source_dataset="cms_desynpuf",
        implementation=_get_claim_details,
    ),
    ToolSpec(
        name="synpuf_claim_counts",
        route=Route.SYNPUF,
        argument_schema=NoArgs,
        source_dataset="cms_desynpuf",
        implementation=_synpuf_claim_counts,
    ),
    ToolSpec(
        name="synpuf_payment_totals",
        route=Route.SYNPUF,
        argument_schema=NoArgs,
        source_dataset="cms_desynpuf",
        implementation=_synpuf_payment_totals,
    ),
    ToolSpec(
        name="synpuf_diagnosis_frequency",
        route=Route.SYNPUF,
        argument_schema=TopNArgs,
        source_dataset="cms_desynpuf",
        implementation=_synpuf_diagnosis_frequency,
    ),
    ToolSpec(
        name="synpuf_procedure_frequency",
        route=Route.SYNPUF,
        argument_schema=TopNArgs,
        source_dataset="cms_desynpuf",
        implementation=_synpuf_procedure_frequency,
    ),
    ToolSpec(
        name="synpuf_hcpcs_frequency",
        route=Route.SYNPUF,
        argument_schema=TopNArgs,
        source_dataset="cms_desynpuf",
        implementation=_synpuf_hcpcs_frequency,
    ),
)

TOOL_REGISTRY: dict[str, ToolSpec] = {spec.name: spec for spec in _TOOL_SPECS}


@dataclass(frozen=True)
class ToolExecutionResult:
    tool: str
    success: bool
    data: Any
    record_count: int | None
    source_dataset: SourceDataset | None
    error: str | None = None


async def execute_tool(
    connection: psycopg.AsyncConnection,
    route: Route,
    tool_name: str | None,
    raw_arguments: dict[str, Any] | None,
) -> ToolExecutionResult:
    """Validate and dispatch one structured-data tool call. Never executes
    arbitrary SQL: the only path to the database is a registered ToolSpec's
    fixed implementation, called with arguments that already passed strict
    Pydantic validation. Returns unsupported_tool for an unknown name or a
    tool whose registered route does not match the current route (this is
    what rejects e.g. route=FHIR combined with a SYNPUF-only tool)."""
    if not tool_name:
        return ToolExecutionResult("", False, None, None, None, error="missing_tool_name")
    spec = TOOL_REGISTRY.get(tool_name)
    if spec is None or spec.route != route:
        return ToolExecutionResult(tool_name, False, None, None, None, error="unsupported_tool")
    try:
        args = spec.argument_schema.model_validate(raw_arguments or {})
    except ValidationError:
        return ToolExecutionResult(
            tool_name, False, None, None, spec.source_dataset, error="invalid_tool_arguments"
        )
    data = await spec.implementation(connection, args)
    record_count = len(data) if isinstance(data, list) else (0 if data is None else 1)
    return ToolExecutionResult(tool_name, True, data, record_count, spec.source_dataset)
