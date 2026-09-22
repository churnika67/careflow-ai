"""Defense-in-depth: confirm the database itself refuses bad data, independent
of the application-level validation in ingestion/cms_synpuf and
ingestion/synthea (which already rejects these cases before they reach SQL).
"""

import os
from datetime import date
from uuid import uuid4

import psycopg
import pytest
from app.core.config import get_settings
from app.db.connection import connect

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_STRUCTURED_INTEGRATION") != "1",
    reason="Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running to test real Postgres",
)


@pytest.fixture
async def connection():
    conn = await connect(get_settings())
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def run_id(connection):
    async with connection.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO ingestion_runs (source, started_at, status, records_read, "
            "records_accepted, records_rejected) VALUES ('test', now(), 'completed', 0, 0, 0) "
            "RETURNING run_id"
        )
        (value,) = await cursor.fetchone()
    return value


async def test_claim_rejects_unknown_beneficiary_foreign_key(connection, run_id):
    async with connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await cursor.execute(
                "INSERT INTO synpuf_claims (claim_row_id, claim_type, claim_id, segment, "
                "beneficiary_id, from_date, thru_date, claim_payment_amount, "
                "primary_payer_paid_amount, run_id, source_row_sha256) "
                "VALUES (%s, 'outpatient', 'X', 1, 'NOT_A_REAL_BENEFICIARY', %s, %s, 1.00, 0.00, "
                "%s, %s)",
                (str(uuid4()), date(2020, 1, 1), date(2020, 1, 1), run_id, "0" * 64),
            )


async def test_beneficiary_rejects_negative_reimbursement_check_constraint(connection, run_id):
    async with connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.CheckViolation):
            await cursor.execute(
                "INSERT INTO synpuf_beneficiaries (beneficiary_id, birth_date, sex_code, "
                "race_code, esrd_indicator, state_code, county_code, hi_coverage_months, "
                "smi_coverage_months, hmo_coverage_months, plan_coverage_months, "
                "chronic_alzheimers, chronic_heart_failure, chronic_kidney_disease, "
                "chronic_cancer, chronic_copd, chronic_depression, chronic_diabetes, "
                "chronic_ischemic_heart, chronic_osteoporosis, chronic_ra_oa, "
                "chronic_stroke_tia, reimb_inpatient, benres_inpatient, pppymt_inpatient, "
                "reimb_outpatient, benres_outpatient, pppymt_outpatient, reimb_carrier, "
                "benres_carrier, pppymt_carrier, run_id, source_row_sha256) "
                "VALUES ('NEG_TEST', %s, '1', '1', '0', '01', '001', 12, 12, 0, 12, "
                "2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, -1.00, 0, 0, 0, 0, 0, 0, 0, 0, %s, %s)",
                (date(1950, 1, 1), run_id, "0" * 64),
            )


async def test_duplicate_beneficiary_id_rejected_by_primary_key(connection, run_id):
    columns_values = (
        "'DUP_TEST', %s, '1', '1', '0', '01', '001', 12, 12, 0, 12, "
        "2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, %s, %s"
    )
    async with connection.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO synpuf_beneficiaries (beneficiary_id, birth_date, sex_code, "
            "race_code, esrd_indicator, state_code, county_code, hi_coverage_months, "
            "smi_coverage_months, hmo_coverage_months, plan_coverage_months, "
            "chronic_alzheimers, chronic_heart_failure, chronic_kidney_disease, "
            "chronic_cancer, chronic_copd, chronic_depression, chronic_diabetes, "
            "chronic_ischemic_heart, chronic_osteoporosis, chronic_ra_oa, "
            "chronic_stroke_tia, reimb_inpatient, benres_inpatient, pppymt_inpatient, "
            "reimb_outpatient, benres_outpatient, pppymt_outpatient, reimb_carrier, "
            f"benres_carrier, pppymt_carrier, run_id, source_row_sha256) VALUES ({columns_values})",
            (date(1950, 1, 1), run_id, "0" * 64),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            await cursor.execute(
                "INSERT INTO synpuf_beneficiaries (beneficiary_id, birth_date, sex_code, "
                "race_code, esrd_indicator, state_code, county_code, hi_coverage_months, "
                "smi_coverage_months, hmo_coverage_months, plan_coverage_months, "
                "chronic_alzheimers, chronic_heart_failure, chronic_kidney_disease, "
                "chronic_cancer, chronic_copd, chronic_depression, chronic_diabetes, "
                "chronic_ischemic_heart, chronic_osteoporosis, chronic_ra_oa, "
                "chronic_stroke_tia, reimb_inpatient, benres_inpatient, pppymt_inpatient, "
                "reimb_outpatient, benres_outpatient, pppymt_outpatient, reimb_carrier, "
                "benres_carrier, pppymt_carrier, run_id, source_row_sha256) "
                f"VALUES ({columns_values})",
                (date(1960, 1, 1), run_id, "1" * 64),
            )
    await connection.rollback()


async def test_condition_rejects_unknown_patient_foreign_key(connection, run_id):
    async with connection.cursor() as cursor:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            await cursor.execute(
                "INSERT INTO fhir_conditions (condition_id, patient_id, code, code_system, "
                "codings, run_id) VALUES (%s, 'NOT_A_REAL_PATIENT', 'x', 'http://snomed.info/sct', "
                "'[]', %s)",
                (str(uuid4()), run_id),
            )


async def test_observation_quantity_type_requires_value_quantity_check_constraint(
    connection, run_id
):
    patient_id = str(uuid4())
    async with connection.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO fhir_patients (patient_id, birth_date, gender, run_id, "
            "source_bundle_sha256) VALUES (%s, %s, 'female', %s, %s)",
            (patient_id, date(1980, 1, 1), run_id, "0" * 64),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            await cursor.execute(
                "INSERT INTO fhir_observations (observation_id, patient_id, status, code, "
                "code_system, codings, value_type, run_id) "
                "VALUES (%s, %s, 'final', 'x', 'http://loinc.org', '[]', 'quantity', %s)",
                (str(uuid4()), patient_id, run_id),
            )
