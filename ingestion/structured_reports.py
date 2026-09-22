"""Read-only reporting used by the Phase 8 CLI commands: source validation
without touching the database, a summary of past ingestion runs, and a
data-quality check over what is actually loaded. Kept separate from
ingestion/cli.py so the logic itself is directly unit/live-testable."""

from pathlib import Path

from app.core.config import Settings
from app.db.connection import connect
from psycopg.rows import dict_row

from ingestion.cms_synpuf.source import load_source_tables
from ingestion.synthea.source import load_bundles

SYNPUF_RAW_DIR = Path("data/raw/cms_synpuf")
SYNPUF_PROFILE = Path("docs/cms_inspection/desynpuf_profile.json")
SYNPUF_SUBSET = Path("docs/cms_inspection/desynpuf_dev_subset.json")
SYNTHEA_ZIP = Path("data/raw/synthea/fhir_r4_nov2021.zip")
SYNTHEA_PROFILE = Path("docs/cms_inspection/synthea_profile.json")
SYNTHEA_SUBSET = Path("docs/cms_inspection/synthea_dev_subset.json")


def validate_sources() -> dict:
    """Checksum-gate and structurally validate both reviewed source snapshots
    without writing anything to the database. Reports a clear error per
    source rather than raising, so one missing/changed source does not hide
    the status of the other."""
    report = {}
    try:
        tables = load_source_tables(SYNPUF_RAW_DIR, SYNPUF_PROFILE, SYNPUF_SUBSET)
        report["cms_synpuf"] = {
            "status": "ok",
            "row_counts": {name: len(rows) for name, rows in tables.items()},
        }
    except (FileNotFoundError, OSError, ValueError) as exc:
        report["cms_synpuf"] = {"status": "error", "reason": str(exc)}
    try:
        bundles = load_bundles(SYNTHEA_ZIP, SYNTHEA_PROFILE, SYNTHEA_SUBSET)
        report["synthea_fhir"] = {"status": "ok", "bundle_count": len(bundles)}
    except (FileNotFoundError, OSError, ValueError) as exc:
        report["synthea_fhir"] = {"status": "error", "reason": str(exc)}
    return report


async def ingestion_summary(settings: Settings, limit: int = 10) -> dict:
    """The most recent ingestion runs and per-source file provenance, read
    directly from ingestion_runs/source_files."""
    connection = await connect(settings)
    async with connection:
        async with connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT run_id, source, started_at, completed_at, status, "
                "records_read, records_accepted, records_rejected, source_fingerprint "
                "FROM ingestion_runs ORDER BY started_at DESC LIMIT %s",
                (limit,),
            )
            runs = await cursor.fetchall()
            await cursor.execute(
                "SELECT source, count(*) AS file_count, sum(byte_size) AS total_bytes "
                "FROM source_files GROUP BY source ORDER BY source"
            )
            files = await cursor.fetchall()
    return {"recent_runs": runs, "source_files_by_source": files}


async def quality_check(settings: Settings) -> dict:
    """Data-quality checks over what is actually loaded. Several of these
    (duplicate natural IDs, orphan claims/references) are already enforced
    by primary/foreign key and UNIQUE constraints at write time — this
    command re-checks and reports them explicitly rather than only trusting
    the constraints silently, and also reports what the constraints cannot
    express: how many observations fell back to value_type='unsupported',
    and how many clinical resources have no encounter link."""
    connection = await connect(settings)
    async with connection:
        async with connection.cursor(row_factory=dict_row) as cursor:
            checks: dict = {}

            await cursor.execute(
                "SELECT count(*) AS total, count(DISTINCT beneficiary_id) AS distinct_ids "
                "FROM synpuf_beneficiaries"
            )
            row = await cursor.fetchone()
            checks["synpuf_duplicate_beneficiary_ids"] = row["total"] - row["distinct_ids"]

            await cursor.execute(
                "SELECT count(*) AS orphans FROM synpuf_claims c "
                "LEFT JOIN synpuf_beneficiaries b ON b.beneficiary_id = c.beneficiary_id "
                "WHERE b.beneficiary_id IS NULL"
            )
            checks["synpuf_orphan_claims"] = (await cursor.fetchone())["orphans"]

            await cursor.execute(
                "SELECT claim_type, count(*) AS claim_count FROM synpuf_claims GROUP BY claim_type"
            )
            checks["synpuf_claim_counts_by_type"] = {
                row["claim_type"]: row["claim_count"] for row in await cursor.fetchall()
            }

            await cursor.execute(
                "SELECT count(*) AS negative FROM synpuf_claims WHERE claim_payment_amount < 0"
            )
            checks["synpuf_negative_payment_amounts"] = (await cursor.fetchone())["negative"]

            # Table names below are a fixed local tuple, never user input.
            fhir_tables = (
                "fhir_conditions",
                "fhir_procedures",
                "fhir_observations",
                "fhir_medication_requests",
            )
            orphan_patient_refs = {}
            null_encounter_counts = {}
            for table in fhir_tables:
                await cursor.execute(
                    f"SELECT count(*) AS orphans FROM {table} t "
                    "LEFT JOIN fhir_patients p ON p.patient_id = t.patient_id "
                    "WHERE p.patient_id IS NULL"
                )
                orphan_patient_refs[table] = (await cursor.fetchone())["orphans"]
                await cursor.execute(
                    "SELECT count(*) FILTER (WHERE encounter_id IS NULL) AS null_encounter, "
                    f"count(*) AS total FROM {table}"
                )
                null_encounter_counts[table] = await cursor.fetchone()
            checks["fhir_orphan_patient_references"] = orphan_patient_refs
            checks["fhir_null_encounter_reference_counts"] = null_encounter_counts

            await cursor.execute(
                "SELECT value_type, count(*) AS value_count FROM fhir_observations "
                "GROUP BY value_type"
            )
            checks["fhir_observation_value_type_distribution"] = {
                row["value_type"]: row["value_count"] for row in await cursor.fetchall()
            }

            await cursor.execute(
                "SELECT source, status, records_read, records_accepted, records_rejected, "
                "started_at FROM ingestion_runs WHERE run_id IN "
                "(SELECT DISTINCT ON (source) run_id FROM ingestion_runs "
                "ORDER BY source, started_at DESC)"
            )
            checks["latest_run_per_source"] = await cursor.fetchall()
    return checks
