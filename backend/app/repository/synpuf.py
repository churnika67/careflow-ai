"""Deterministic, parameterized read access to the DE-SynPUF domain tables.

Every function here takes a live connection and fixed arguments and issues one
or more parameterized queries — there is no string-built or LLM-generated SQL
anywhere in this module, by design (Phase 8 explicitly excludes that)."""

import psycopg
from psycopg.rows import dict_row


async def get_beneficiary_summary(
    connection: psycopg.AsyncConnection, beneficiary_id: str
) -> dict | None:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT * FROM synpuf_beneficiaries WHERE beneficiary_id = %s", (beneficiary_id,)
        )
        return await cursor.fetchone()


async def get_claims_for_beneficiary(
    connection: psycopg.AsyncConnection, beneficiary_id: str
) -> list[dict]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT * FROM synpuf_claims WHERE beneficiary_id = %s "
            "ORDER BY from_date, claim_row_id",
            (beneficiary_id,),
        )
        return await cursor.fetchall()


async def get_claim_details(connection: psycopg.AsyncConnection, claim_row_id: str) -> dict | None:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute("SELECT * FROM synpuf_claims WHERE claim_row_id = %s", (claim_row_id,))
        claim = await cursor.fetchone()
        if claim is None:
            return None
        await cursor.execute(
            "SELECT sequence, icd9_code FROM synpuf_claim_diagnoses "
            "WHERE claim_row_id = %s ORDER BY sequence",
            (claim_row_id,),
        )
        claim["diagnoses"] = await cursor.fetchall()
        await cursor.execute(
            "SELECT sequence, icd9_procedure_code FROM synpuf_claim_procedures "
            "WHERE claim_row_id = %s ORDER BY sequence",
            (claim_row_id,),
        )
        claim["procedures"] = await cursor.fetchall()
        await cursor.execute(
            "SELECT line_number, hcpcs_code FROM synpuf_claim_lines "
            "WHERE claim_row_id = %s ORDER BY line_number",
            (claim_row_id,),
        )
        claim["lines"] = await cursor.fetchall()
    return claim
