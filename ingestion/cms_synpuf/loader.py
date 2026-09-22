import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.db.connection import connect

from ingestion.cms_synpuf.normalize import (
    Beneficiary,
    Claim,
    normalize_beneficiaries,
    normalize_claims,
)
from ingestion.cms_synpuf.source import load_source_tables

BENEFICIARY_COLUMNS = (
    "beneficiary_id",
    "birth_date",
    "death_date",
    "sex_code",
    "race_code",
    "esrd_indicator",
    "state_code",
    "county_code",
    "hi_coverage_months",
    "smi_coverage_months",
    "hmo_coverage_months",
    "plan_coverage_months",
    "chronic_alzheimers",
    "chronic_heart_failure",
    "chronic_kidney_disease",
    "chronic_cancer",
    "chronic_copd",
    "chronic_depression",
    "chronic_diabetes",
    "chronic_ischemic_heart",
    "chronic_osteoporosis",
    "chronic_ra_oa",
    "chronic_stroke_tia",
    "reimb_inpatient",
    "benres_inpatient",
    "pppymt_inpatient",
    "reimb_outpatient",
    "benres_outpatient",
    "pppymt_outpatient",
    "reimb_carrier",
    "benres_carrier",
    "pppymt_carrier",
)
CLAIM_COLUMNS = (
    "claim_row_id",
    "claim_type",
    "claim_id",
    "segment",
    "beneficiary_id",
    "from_date",
    "thru_date",
    "admission_date",
    "discharge_date",
    "provider_number",
    "claim_payment_amount",
    "primary_payer_paid_amount",
    "attending_physician_npi",
    "operating_physician_npi",
    "other_physician_npi",
    "drg_code",
    "admitting_diagnosis_code",
)


async def _insert_beneficiary(cursor, run_id: str, beneficiary: Beneficiary) -> bool:
    values = [getattr(beneficiary, field) for field in BENEFICIARY_COLUMNS]
    values += [run_id, beneficiary.source_row_sha256]
    placeholders = ", ".join(["%s"] * len(values))
    columns = ", ".join((*BENEFICIARY_COLUMNS, "run_id", "source_row_sha256"))
    await cursor.execute(
        f"INSERT INTO synpuf_beneficiaries ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT (beneficiary_id) DO NOTHING",
        values,
    )
    return cursor.rowcount == 1


async def _insert_claim(cursor, run_id: str, claim: Claim) -> bool:
    values = [getattr(claim, field) for field in CLAIM_COLUMNS]
    values += [run_id, claim.source_row_sha256]
    placeholders = ", ".join(["%s"] * len(values))
    columns = ", ".join((*CLAIM_COLUMNS, "run_id", "source_row_sha256"))
    await cursor.execute(
        f"INSERT INTO synpuf_claims ({columns}) VALUES ({placeholders}) "
        "ON CONFLICT (claim_row_id) DO NOTHING",
        values,
    )
    if cursor.rowcount != 1:
        return False
    if claim.diagnoses:
        await cursor.executemany(
            "INSERT INTO synpuf_claim_diagnoses (claim_row_id, sequence, icd9_code) "
            "VALUES (%s, %s, %s)",
            [(claim.claim_row_id, seq, code) for seq, code in claim.diagnoses],
        )
    if claim.procedures:
        await cursor.executemany(
            "INSERT INTO synpuf_claim_procedures (claim_row_id, sequence, icd9_procedure_code) "
            "VALUES (%s, %s, %s)",
            [(claim.claim_row_id, seq, code) for seq, code in claim.procedures],
        )
    if claim.lines:
        await cursor.executemany(
            "INSERT INTO synpuf_claim_lines (claim_row_id, line_number, hcpcs_code) "
            "VALUES (%s, %s, %s)",
            [(claim.claim_row_id, num, code) for num, code in claim.lines],
        )
    return True


async def ingest_synpuf(
    settings: Settings,
    raw_dir: Path = Path("data/raw/cms_synpuf"),
    profile_path: Path = Path("docs/cms_inspection/desynpuf_profile.json"),
    subset_path: Path = Path("docs/cms_inspection/desynpuf_dev_subset.json"),
) -> dict:
    """Idempotent end-to-end DE-SynPUF ingestion for the reviewed dev subset:
    load+checksum-gate the three source files, validate/normalize the subset's
    rows with per-row quarantine, and write beneficiaries/claims/diagnoses/
    procedures/lines inside one transaction. A second run against the same
    subset inserts zero new rows (ON CONFLICT DO NOTHING on natural/deterministic
    keys) — existing rows are left exactly as first written, never updated."""
    profile = json.loads(profile_path.read_text())
    subset = json.loads(subset_path.read_text())
    allowed_ids = set(subset["beneficiary_ids"])
    tables = load_source_tables(raw_dir, profile_path, subset_path)

    beneficiaries, rejected_beneficiaries = normalize_beneficiaries(
        tables["beneficiary_2008"], allowed_ids
    )
    known_beneficiaries = {b.beneficiary_id for b in beneficiaries}
    inpatient, rejected_inpatient = normalize_claims(
        tables["inpatient_sample1"], "inpatient", allowed_ids, known_beneficiaries
    )
    outpatient, rejected_outpatient = normalize_claims(
        tables["outpatient_sample1"], "outpatient", allowed_ids, known_beneficiaries
    )
    claims = inpatient + outpatient
    rejected = rejected_beneficiaries + rejected_inpatient + rejected_outpatient
    records_read = sum(1 for r in tables["beneficiary_2008"] if r["DESYNPUF_ID"] in allowed_ids)
    records_read += sum(1 for r in tables["inpatient_sample1"] if r["DESYNPUF_ID"] in allowed_ids)
    records_read += sum(1 for r in tables["outpatient_sample1"] if r["DESYNPUF_ID"] in allowed_ids)

    started_at = datetime.now(UTC)
    connection = await connect(settings)
    beneficiaries_inserted = claims_inserted = 0
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO ingestion_runs (source, started_at, status) "
                "VALUES (%s, %s, 'running') RETURNING run_id",
                ("cms_synpuf", started_at),
            )
            (run_id,) = await cursor.fetchone()
            for name, spec in profile["files"].items():
                await cursor.execute(
                    "INSERT INTO source_files "
                    "(run_id, source, origin_url, sha256, byte_size, downloaded_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        run_id,
                        f"cms_synpuf:{name}",
                        spec["origin_url"],
                        spec["zip_sha256"],
                        spec["zip_bytes"],
                        started_at,
                    ),
                )
            for beneficiary in beneficiaries:
                if await _insert_beneficiary(cursor, run_id, beneficiary):
                    beneficiaries_inserted += 1
            for claim in claims:
                if await _insert_claim(cursor, run_id, claim):
                    claims_inserted += 1
            completed_at = datetime.now(UTC)
            await cursor.execute(
                "UPDATE ingestion_runs SET completed_at = %s, status = 'completed', "
                "records_read = %s, records_accepted = %s, records_rejected = %s, "
                "source_fingerprint = %s WHERE run_id = %s",
                (
                    completed_at,
                    records_read,
                    len(beneficiaries) + len(claims),
                    len(rejected),
                    profile["files"]["beneficiary_2008"]["zip_sha256"],
                    run_id,
                ),
            )
    return {
        "run_id": str(run_id),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "status": "completed",
        "beneficiaries": {
            "selected": len(beneficiaries),
            "inserted": beneficiaries_inserted,
            "rejected": len(rejected_beneficiaries),
        },
        "claims": {
            "selected": len(claims),
            "inserted": claims_inserted,
            "rejected": len(rejected_inpatient) + len(rejected_outpatient),
            "inpatient": len(inpatient),
            "outpatient": len(outpatient),
        },
        "records_read": records_read,
        "records_accepted": len(beneficiaries) + len(claims),
        "records_rejected": len(rejected),
        "rejected_records": [
            {"file": r.file, "natural_key": r.natural_key, "reason": r.reason} for r in rejected
        ],
    }
