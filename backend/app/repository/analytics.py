"""Deterministic aggregate analytics over the structured domain tables.

These are plain counts, sums and frequency tables — not clinical judgments.
Nothing here scores, ranks or labels a patient/beneficiary as high-risk; no
validated risk model exists in this phase, so none is implied. All queries
are fixed and parameterized; no user- or LLM-supplied SQL is ever built."""

import psycopg
from psycopg.rows import dict_row


def _bounded_top_n(top_n: int) -> int:
    if not 1 <= top_n <= 100:
        raise ValueError("top_n must be between 1 and 100")
    return top_n


async def synpuf_claim_counts_by_type(connection: psycopg.AsyncConnection) -> dict[str, int]:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT claim_type, count(*) FROM synpuf_claims GROUP BY claim_type")
        return dict(await cursor.fetchall())


async def synpuf_payment_totals_by_type(connection: psycopg.AsyncConnection) -> dict[str, dict]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT claim_type, sum(claim_payment_amount) AS total_payment, "
            "count(*) AS claim_count FROM synpuf_claims GROUP BY claim_type"
        )
        rows = await cursor.fetchall()
        return {row["claim_type"]: row for row in rows}


async def synpuf_diagnosis_frequency(
    connection: psycopg.AsyncConnection, top_n: int = 10
) -> list[dict]:
    top_n = _bounded_top_n(top_n)
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT icd9_code, count(*) AS occurrences FROM synpuf_claim_diagnoses "
            "GROUP BY icd9_code ORDER BY occurrences DESC, icd9_code LIMIT %s",
            (top_n,),
        )
        return await cursor.fetchall()


async def synpuf_procedure_frequency(
    connection: psycopg.AsyncConnection, top_n: int = 10
) -> list[dict]:
    top_n = _bounded_top_n(top_n)
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT icd9_procedure_code, count(*) AS occurrences FROM synpuf_claim_procedures "
            "GROUP BY icd9_procedure_code ORDER BY occurrences DESC, icd9_procedure_code LIMIT %s",
            (top_n,),
        )
        return await cursor.fetchall()


async def synpuf_hcpcs_frequency(
    connection: psycopg.AsyncConnection, top_n: int = 10
) -> list[dict]:
    top_n = _bounded_top_n(top_n)
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT hcpcs_code, count(*) AS occurrences FROM synpuf_claim_lines "
            "GROUP BY hcpcs_code ORDER BY occurrences DESC, hcpcs_code LIMIT %s",
            (top_n,),
        )
        return await cursor.fetchall()


async def fhir_encounter_counts_by_class(connection: psycopg.AsyncConnection) -> dict[str, int]:
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT class_code, count(*) FROM fhir_encounters GROUP BY class_code")
        return dict(await cursor.fetchall())


async def fhir_condition_frequency(
    connection: psycopg.AsyncConnection, top_n: int = 10
) -> list[dict]:
    top_n = _bounded_top_n(top_n)
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT code, code_system, code_display, count(*) AS occurrences "
            "FROM fhir_conditions GROUP BY code, code_system, code_display "
            "ORDER BY occurrences DESC, code LIMIT %s",
            (top_n,),
        )
        return await cursor.fetchall()


async def fhir_procedure_frequency(
    connection: psycopg.AsyncConnection, top_n: int = 10
) -> list[dict]:
    top_n = _bounded_top_n(top_n)
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT code, code_system, code_display, count(*) AS occurrences "
            "FROM fhir_procedures GROUP BY code, code_system, code_display "
            "ORDER BY occurrences DESC, code LIMIT %s",
            (top_n,),
        )
        return await cursor.fetchall()


async def fhir_medication_frequency(
    connection: psycopg.AsyncConnection, top_n: int = 10
) -> list[dict]:
    top_n = _bounded_top_n(top_n)
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT code, code_system, code_display, count(*) AS occurrences "
            "FROM fhir_medication_requests GROUP BY code, code_system, code_display "
            "ORDER BY occurrences DESC, code LIMIT %s",
            (top_n,),
        )
        return await cursor.fetchall()
