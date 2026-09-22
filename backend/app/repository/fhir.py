"""Deterministic, parameterized read access to the Synthea FHIR domain tables.
Same no-arbitrary-SQL rule as backend/app/repository/synpuf.py."""

import psycopg
from psycopg.rows import dict_row


async def get_patient_summary(connection: psycopg.AsyncConnection, patient_id: str) -> dict | None:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute("SELECT * FROM fhir_patients WHERE patient_id = %s", (patient_id,))
        return await cursor.fetchone()


async def get_patient_encounters(
    connection: psycopg.AsyncConnection, patient_id: str
) -> list[dict]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT * FROM fhir_encounters WHERE patient_id = %s ORDER BY period_start NULLS LAST",
            (patient_id,),
        )
        return await cursor.fetchall()


async def get_patient_conditions(
    connection: psycopg.AsyncConnection, patient_id: str
) -> list[dict]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT * FROM fhir_conditions WHERE patient_id = %s "
            "ORDER BY onset_datetime NULLS LAST",
            (patient_id,),
        )
        return await cursor.fetchall()


async def get_patient_procedures(
    connection: psycopg.AsyncConnection, patient_id: str
) -> list[dict]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT * FROM fhir_procedures WHERE patient_id = %s "
            "ORDER BY performed_start NULLS LAST",
            (patient_id,),
        )
        return await cursor.fetchall()


async def get_observations(
    connection: psycopg.AsyncConnection, patient_id: str, code: str | None = None
) -> list[dict]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        if code is None:
            await cursor.execute(
                "SELECT * FROM fhir_observations WHERE patient_id = %s "
                "ORDER BY effective_datetime NULLS LAST",
                (patient_id,),
            )
        else:
            await cursor.execute(
                "SELECT * FROM fhir_observations WHERE patient_id = %s AND code = %s "
                "ORDER BY effective_datetime NULLS LAST",
                (patient_id, code),
            )
        observations = await cursor.fetchall()
        for observation in observations:
            if observation["value_type"] == "component":
                await cursor.execute(
                    "SELECT component_index, code, code_system, code_display, "
                    "value_quantity, value_unit FROM fhir_observation_components "
                    "WHERE observation_id = %s ORDER BY component_index",
                    (observation["observation_id"],),
                )
                observation["components"] = await cursor.fetchall()
        return observations


async def get_medication_requests(
    connection: psycopg.AsyncConnection, patient_id: str
) -> list[dict]:
    async with connection.cursor(row_factory=dict_row) as cursor:
        await cursor.execute(
            "SELECT * FROM fhir_medication_requests WHERE patient_id = %s "
            "ORDER BY authored_on NULLS LAST",
            (patient_id,),
        )
        return await cursor.fetchall()
