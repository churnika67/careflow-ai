import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.db.connection import connect

from ingestion.synthea.normalize import (
    Condition,
    Encounter,
    MedicationRequest,
    Observation,
    Patient,
    Procedure,
    normalize_bundle,
)
from ingestion.synthea.source import load_bundles


async def _insert_patient(cursor, run_id: str, bundle_sha256: str, patient: Patient) -> bool:
    await cursor.execute(
        """
        INSERT INTO fhir_patients (
            patient_id, family_name, given_name, birth_date, gender,
            race_code, race_display, ethnicity_code, ethnicity_display,
            run_id, source_bundle_sha256
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (patient_id) DO NOTHING
        """,
        (
            patient.patient_id,
            patient.family_name,
            patient.given_name,
            patient.birth_date,
            patient.gender,
            patient.race_code,
            patient.race_display,
            patient.ethnicity_code,
            patient.ethnicity_display,
            run_id,
            bundle_sha256,
        ),
    )
    return cursor.rowcount == 1


async def _insert_encounter(cursor, run_id: str, encounter: Encounter) -> bool:
    await cursor.execute(
        """
        INSERT INTO fhir_encounters (
            encounter_id, patient_id, status, class_code,
            type_code, type_system, type_display, period_start, period_end, run_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (encounter_id) DO NOTHING
        """,
        (
            encounter.encounter_id,
            encounter.patient_id,
            encounter.status,
            encounter.class_code,
            encounter.type_code,
            encounter.type_system,
            encounter.type_display,
            encounter.period_start,
            encounter.period_end,
            run_id,
        ),
    )
    return cursor.rowcount == 1


async def _insert_condition(cursor, run_id: str, condition: Condition) -> bool:
    await cursor.execute(
        """
        INSERT INTO fhir_conditions (
            condition_id, patient_id, encounter_id, clinical_status, verification_status,
            code, code_system, code_display, codings, onset_datetime, recorded_date, run_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (condition_id) DO NOTHING
        """,
        (
            condition.condition_id,
            condition.patient_id,
            condition.encounter_id,
            condition.clinical_status,
            condition.verification_status,
            condition.coding.code,
            condition.coding.code_system,
            condition.coding.code_display,
            json.dumps(list(condition.coding.codings)),
            condition.onset_datetime,
            condition.recorded_date,
            run_id,
        ),
    )
    return cursor.rowcount == 1


async def _insert_procedure(cursor, run_id: str, procedure: Procedure) -> bool:
    await cursor.execute(
        """
        INSERT INTO fhir_procedures (
            procedure_id, patient_id, encounter_id, status,
            code, code_system, code_display, codings, performed_start, performed_end, run_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (procedure_id) DO NOTHING
        """,
        (
            procedure.procedure_id,
            procedure.patient_id,
            procedure.encounter_id,
            procedure.status,
            procedure.coding.code,
            procedure.coding.code_system,
            procedure.coding.code_display,
            json.dumps(list(procedure.coding.codings)),
            procedure.performed_start,
            procedure.performed_end,
            run_id,
        ),
    )
    return cursor.rowcount == 1


async def _insert_observation(cursor, run_id: str, observation: Observation) -> bool:
    await cursor.execute(
        """
        INSERT INTO fhir_observations (
            observation_id, patient_id, encounter_id, status,
            code, code_system, code_display, codings, value_type,
            value_quantity, value_unit, value_code, value_code_system, value_code_display,
            value_string, effective_datetime, run_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (observation_id) DO NOTHING
        """,
        (
            observation.observation_id,
            observation.patient_id,
            observation.encounter_id,
            observation.status,
            observation.coding.code,
            observation.coding.code_system,
            observation.coding.code_display,
            json.dumps(list(observation.coding.codings)),
            observation.value_type,
            observation.value_quantity,
            observation.value_unit,
            observation.value_code,
            observation.value_code_system,
            observation.value_code_display,
            observation.value_string,
            observation.effective_datetime,
            run_id,
        ),
    )
    if cursor.rowcount != 1:
        return False
    if observation.components:
        await cursor.executemany(
            "INSERT INTO fhir_observation_components "
            "(observation_id, component_index, code, code_system, code_display, "
            "value_quantity, value_unit) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            [
                (
                    observation.observation_id,
                    c.index,
                    c.code,
                    c.code_system,
                    c.code_display,
                    c.value_quantity,
                    c.value_unit,
                )
                for c in observation.components
            ],
        )
    return True


async def _insert_medication_request(cursor, run_id: str, request: MedicationRequest) -> bool:
    await cursor.execute(
        """
        INSERT INTO fhir_medication_requests (
            medication_request_id, patient_id, encounter_id, status, intent,
            code, code_system, code_display, codings, authored_on, run_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (medication_request_id) DO NOTHING
        """,
        (
            request.medication_request_id,
            request.patient_id,
            request.encounter_id,
            request.status,
            request.intent,
            request.coding.code,
            request.coding.code_system,
            request.coding.code_display,
            json.dumps(list(request.coding.codings)),
            request.authored_on,
            run_id,
        ),
    )
    return cursor.rowcount == 1


async def ingest_synthea(
    settings: Settings,
    zip_path: Path = Path("data/raw/synthea/fhir_r4_nov2021.zip"),
    profile_path: Path = Path("docs/cms_inspection/synthea_profile.json"),
    subset_path: Path = Path("docs/cms_inspection/synthea_dev_subset.json"),
) -> dict:
    """Idempotent end-to-end Synthea FHIR ingestion for the reviewed dev subset:
    checksum-gate the archive and each selected bundle, normalize each bundle's
    supported resources in FK dependency order with per-resource quarantine, and
    write everything inside one transaction. A second run inserts zero new rows."""
    profile = json.loads(profile_path.read_text())
    bundles = load_bundles(zip_path, profile_path, subset_path)

    all_patients, all_encounters, all_conditions = [], [], []
    all_procedures, all_observations, all_medication_requests = [], [], []
    all_rejected, per_bundle_counts, unsupported_totals = [], [], {}
    bundle_sha_by_resource: dict[str, str] = {}
    for entry in bundles:
        result = normalize_bundle(entry["bundle"])
        for patient in result["patients"]:
            bundle_sha_by_resource[patient.patient_id] = entry["sha256"]
        all_patients += result["patients"]
        all_encounters += result["encounters"]
        all_conditions += result["conditions"]
        all_procedures += result["procedures"]
        all_observations += result["observations"]
        all_medication_requests += result["medication_requests"]
        all_rejected += [
            {
                "file": entry["file"],
                "resource_type": r.resource_type,
                "natural_key": r.natural_key,
                "reason": r.reason,
            }
            for r in result["rejected"]
        ]
        per_bundle_counts.append({"file": entry["file"], **result["resource_type_counts"]})
        for rtype, count in result["unsupported_resource_counts"].items():
            unsupported_totals[rtype] = unsupported_totals.get(rtype, 0) + count

    records_read = sum(sum(c for k, c in bc.items() if k != "file") for bc in per_bundle_counts)
    started_at = datetime.now(UTC)
    connection = await connect(settings)
    inserted = {
        "patients": 0,
        "encounters": 0,
        "conditions": 0,
        "procedures": 0,
        "observations": 0,
        "medication_requests": 0,
    }
    async with connection:
        async with connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO ingestion_runs (source, started_at, status) "
                "VALUES (%s, %s, 'running') RETURNING run_id",
                ("synthea_fhir", started_at),
            )
            (run_id,) = await cursor.fetchone()
            for entry in bundles:
                await cursor.execute(
                    "INSERT INTO source_files "
                    "(run_id, source, origin_url, sha256, byte_size, downloaded_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (
                        run_id,
                        f"synthea_fhir:{entry['file']}",
                        f"{profile['origin_url']}#{entry['file']}",
                        entry["sha256"],
                        len(json.dumps(entry["bundle"])),
                        started_at,
                    ),
                )
            for patient in all_patients:
                if await _insert_patient(
                    cursor, run_id, bundle_sha_by_resource[patient.patient_id], patient
                ):
                    inserted["patients"] += 1
            for encounter in all_encounters:
                if await _insert_encounter(cursor, run_id, encounter):
                    inserted["encounters"] += 1
            for condition in all_conditions:
                if await _insert_condition(cursor, run_id, condition):
                    inserted["conditions"] += 1
            for procedure in all_procedures:
                if await _insert_procedure(cursor, run_id, procedure):
                    inserted["procedures"] += 1
            for observation in all_observations:
                if await _insert_observation(cursor, run_id, observation):
                    inserted["observations"] += 1
            for request in all_medication_requests:
                if await _insert_medication_request(cursor, run_id, request):
                    inserted["medication_requests"] += 1
            records_accepted = (
                len(all_patients)
                + len(all_encounters)
                + len(all_conditions)
                + len(all_procedures)
                + len(all_observations)
                + len(all_medication_requests)
            )
            completed_at = datetime.now(UTC)
            await cursor.execute(
                "UPDATE ingestion_runs SET completed_at = %s, status = 'completed', "
                "records_read = %s, records_accepted = %s, records_rejected = %s, "
                "source_fingerprint = %s WHERE run_id = %s",
                (
                    completed_at,
                    records_read,
                    records_accepted,
                    len(all_rejected),
                    profile["zip_sha256"],
                    run_id,
                ),
            )
    return {
        "run_id": str(run_id),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "status": "completed",
        "bundles": len(bundles),
        "resource_counts": {
            "patients": len(all_patients),
            "encounters": len(all_encounters),
            "conditions": len(all_conditions),
            "procedures": len(all_procedures),
            "observations": len(all_observations),
            "medication_requests": len(all_medication_requests),
        },
        "inserted": inserted,
        "records_read": records_read,
        "records_accepted": records_accepted,
        "records_rejected": len(all_rejected),
        "rejected_records": all_rejected,
        "unsupported_resource_counts": unsupported_totals,
    }
