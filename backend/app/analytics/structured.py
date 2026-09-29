"""Live, bounded population-level aggregate queries -- reuses Phase 9's
existing app.repository.analytics functions unchanged for all 9 registered
aggregate tools (4 FHIR, 5 SynPUF; see backend/app/orchestration/tools.py).
Every one of those 9 calls below is the exact same fixed, parameterized
SQL already exercised by the orchestration tool registry.

Two additional, analytics-only queries (`_fhir_patient_count`,
`_synpuf_beneficiary_count`) were added in Phase 15 Slice 3 to give the
dashboard basic dataset-size context ("this sample has 5 patients"), a
value none of the 9 registered tools returns. They are deliberately kept
local to this module rather than added to app/repository/analytics.py or
the orchestration TOOL_REGISTRY -- that registry's 9-tool count is a
documented fact (see docs/phase15_analytics_design.md) this change must
not disturb. Both are a plain, fixed `count(*)` with no parameters, no
filter, and no identifier column selected -- the same read-only,
no-arbitrary-SQL discipline as every other query in this module.

FHIR and SynPUF are queried entirely independently in this module -- there
is no shared identifier, no join, and no function here ever receives both
datasets' data at once before returning. Keeping them separate here is
what keeps the "no cross-dataset linkage" property true of this endpoint,
not a runtime check bolted on afterward."""

import psycopg

from app.analytics.models import (
    FhirAggregateOverview,
    StructuredAnalyticsOverview,
    SynpufAggregateOverview,
)
from app.repository import analytics as analytics_repository

_TOP_N = 5


async def _fhir_patient_count(connection: psycopg.AsyncConnection) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT count(*) FROM fhir_patients")
        row = await cursor.fetchone()
        return row[0]


async def _synpuf_beneficiary_count(connection: psycopg.AsyncConnection) -> int:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT count(*) FROM synpuf_beneficiaries")
        row = await cursor.fetchone()
        return row[0]


async def _load_fhir_overview(connection: psycopg.AsyncConnection) -> FhirAggregateOverview:
    return FhirAggregateOverview(
        source="live_structured_query",
        dataset="synthea_fhir",
        patient_count=await _fhir_patient_count(connection),
        top_n=_TOP_N,
        encounter_counts_by_class=await analytics_repository.fhir_encounter_counts_by_class(
            connection
        ),
        top_conditions=await analytics_repository.fhir_condition_frequency(connection, _TOP_N),
        top_procedures=await analytics_repository.fhir_procedure_frequency(connection, _TOP_N),
        top_medications=await analytics_repository.fhir_medication_frequency(connection, _TOP_N),
    )


async def _load_synpuf_overview(connection: psycopg.AsyncConnection) -> SynpufAggregateOverview:
    return SynpufAggregateOverview(
        source="live_structured_query",
        dataset="cms_desynpuf",
        beneficiary_count=await _synpuf_beneficiary_count(connection),
        top_n=_TOP_N,
        claim_counts_by_type=await analytics_repository.synpuf_claim_counts_by_type(connection),
        payment_totals_by_type=await analytics_repository.synpuf_payment_totals_by_type(connection),
        top_diagnoses=await analytics_repository.synpuf_diagnosis_frequency(connection, _TOP_N),
        top_procedures=await analytics_repository.synpuf_procedure_frequency(connection, _TOP_N),
        top_hcpcs=await analytics_repository.synpuf_hcpcs_frequency(connection, _TOP_N),
    )


async def load_structured_overview(
    connection: psycopg.AsyncConnection,
) -> StructuredAnalyticsOverview:
    return StructuredAnalyticsOverview(
        fhir=await _load_fhir_overview(connection),
        synpuf=await _load_synpuf_overview(connection),
    )
