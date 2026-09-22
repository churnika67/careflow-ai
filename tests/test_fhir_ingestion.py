import os
from pathlib import Path

import pytest
from app.core.config import get_settings

from ingestion.synthea.loader import ingest_synthea
from ingestion.synthea.normalize import (
    US_CORE_ETHNICITY,
    US_CORE_RACE,
    build_reference_index,
    normalize_bundle,
    normalize_condition,
    normalize_encounter,
    normalize_medication_request,
    normalize_observation,
    normalize_patient,
    normalize_procedure,
)
from ingestion.synthea.source import load_bundles

ZIP_PATH = Path("data/raw/synthea/fhir_r4_nov2021.zip")
PROFILE = Path("docs/cms_inspection/synthea_profile.json")
SUBSET = Path("docs/cms_inspection/synthea_dev_subset.json")

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_STRUCTURED_INTEGRATION") != "1",
    reason="Set CAREFLOW_STRUCTURED_INTEGRATION=1 with Compose running to test real Postgres",
)


def _patient_resource(**overrides) -> dict:
    resource = {
        "resourceType": "Patient",
        "id": "patient-1",
        "birthDate": "1980-01-01",
        "gender": "female",
        "name": [{"use": "official", "family": "Doe", "given": ["Jane"]}],
        "extension": [
            {
                "url": US_CORE_RACE,
                "extension": [
                    {"url": "ombCategory", "valueCoding": {"code": "2106-3", "display": "White"}},
                    {"url": "text", "valueString": "White"},
                ],
            },
            {
                "url": US_CORE_ETHNICITY,
                "extension": [
                    {
                        "url": "ombCategory",
                        "valueCoding": {"code": "2186-5", "display": "Not Hispanic or Latino"},
                    }
                ],
            },
        ],
    }
    resource.update(overrides)
    return resource


def _bundle(*resources: dict) -> dict:
    return {
        "resourceType": "Bundle",
        "entry": [{"fullUrl": f"urn:uuid:{r['id']}", "resource": r} for r in resources],
    }


def _encounter_resource(**overrides) -> dict:
    resource = {
        "resourceType": "Encounter",
        "id": "encounter-1",
        "status": "finished",
        "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB"},
        "type": [
            {
                "coding": [
                    {"system": "http://snomed.info/sct", "code": "185349003", "display": "Visit"}
                ]
            }
        ],
        "subject": {"reference": "urn:uuid:patient-1"},
        "period": {"start": "2020-01-01T10:00:00-05:00", "end": "2020-01-01T10:30:00-05:00"},
    }
    resource.update(overrides)
    return resource


def _condition_resource(**overrides) -> dict:
    resource = {
        "resourceType": "Condition",
        "id": "condition-1",
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": "active",
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "code": {
            "coding": [
                {"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes"}
            ]
        },
        "subject": {"reference": "urn:uuid:patient-1"},
        "encounter": {"reference": "urn:uuid:encounter-1"},
        "onsetDateTime": "2019-05-01T00:00:00-05:00",
        "recordedDate": "2019-05-01T00:00:00-05:00",
    }
    resource.update(overrides)
    return resource


def test_normalize_patient_extracts_race_and_ethnicity():
    patient = normalize_patient(_patient_resource())
    assert patient.patient_id == "patient-1"
    assert patient.family_name == "Doe"
    assert patient.given_name == "Jane"
    assert patient.race_code == "2106-3"
    assert patient.ethnicity_code == "2186-5"


def test_normalize_patient_rejects_missing_gender():
    with pytest.raises(ValueError, match="gender"):
        normalize_patient(_patient_resource(gender=""))


def test_normalize_encounter_resolves_patient_subject():
    bundle = _bundle(_patient_resource(), _encounter_resource())
    index = build_reference_index(bundle)
    encounter = normalize_encounter(_encounter_resource(), index)
    assert encounter.patient_id == "patient-1"
    assert encounter.class_code == "AMB"
    assert encounter.period_start is not None


def test_normalize_encounter_rejects_unresolved_subject():
    bundle = _bundle(_encounter_resource())  # no Patient entry
    index = build_reference_index(bundle)
    with pytest.raises(ValueError, match="subject"):
        normalize_encounter(_encounter_resource(), index)


def test_normalize_condition_preserves_multiple_codings():
    resource = _condition_resource(
        code={
            "coding": [
                {"system": "http://snomed.info/sct", "code": "44054006", "display": "Diabetes"},
                {"system": "http://hl7.org/fhir/sid/icd-9-cm", "code": "250.00", "display": "DM"},
            ]
        }
    )
    bundle = _bundle(_patient_resource(), _encounter_resource(), resource)
    index = build_reference_index(bundle)
    condition = normalize_condition(resource, index, {"patient-1"}, {"encounter-1"})
    assert condition.coding.code == "44054006"
    assert condition.coding.code_system == "http://snomed.info/sct"
    assert len(condition.coding.codings) == 2


def test_normalize_condition_absent_encounter_reference_is_null_not_rejected():
    resource = _condition_resource()
    del resource["encounter"]
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    condition = normalize_condition(resource, index, {"patient-1"}, set())
    assert condition.encounter_id is None


def test_normalize_condition_unresolved_encounter_reference_is_null_not_rejected():
    resource = (
        _condition_resource()
    )  # references encounter-1, which is not a known/accepted encounter
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    condition = normalize_condition(resource, index, {"patient-1"}, known_encounters=set())
    assert condition.encounter_id is None


def test_normalize_condition_rejects_unresolved_subject():
    resource = _condition_resource()
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    with pytest.raises(ValueError, match="subject"):
        normalize_condition(resource, index, known_patients=set(), known_encounters=set())


def test_normalize_procedure_supports_performed_period_and_datetime():
    period_resource = {
        "resourceType": "Procedure",
        "id": "proc-1",
        "status": "completed",
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "1", "display": "X"}]},
        "subject": {"reference": "urn:uuid:patient-1"},
        "performedPeriod": {
            "start": "2020-01-01T00:00:00-05:00",
            "end": "2020-01-01T01:00:00-05:00",
        },
    }
    datetime_resource = {
        **period_resource,
        "id": "proc-2",
        "performedDateTime": "2020-01-01T00:00:00-05:00",
    }
    del datetime_resource["performedPeriod"]
    bundle = _bundle(_patient_resource(), period_resource, datetime_resource)
    index = build_reference_index(bundle)
    p1 = normalize_procedure(period_resource, index, {"patient-1"}, set())
    p2 = normalize_procedure(datetime_resource, index, {"patient-1"}, set())
    assert p1.performed_start is not None and p1.performed_end is not None
    assert p2.performed_start == p2.performed_end


def test_normalize_procedure_rejects_unsupported_performed_shape():
    resource = {
        "resourceType": "Procedure",
        "id": "proc-3",
        "status": "completed",
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": "1", "display": "X"}]},
        "subject": {"reference": "urn:uuid:patient-1"},
        "performedString": "sometime in 2020",
    }
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    with pytest.raises(ValueError, match="performed"):
        normalize_procedure(resource, index, {"patient-1"}, set())


def _observation_base(**overrides) -> dict:
    resource = {
        "resourceType": "Observation",
        "id": "obs-1",
        "status": "final",
        "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5", "display": "Temp"}]},
        "subject": {"reference": "urn:uuid:patient-1"},
        "effectiveDateTime": "2020-01-01T00:00:00-05:00",
    }
    resource.update(overrides)
    return resource


@pytest.mark.parametrize(
    "value_field,value,expected_type",
    [
        ("valueQuantity", {"value": 37.1, "unit": "Cel"}, "quantity"),
        (
            "valueCodeableConcept",
            {"coding": [{"system": "http://snomed.info/sct", "code": "1", "display": "Yes"}]},
            "codeable_concept",
        ),
        ("valueString", "a free-text result", "string"),
    ],
)
def test_normalize_observation_supported_value_shapes(value_field, value, expected_type):
    resource = _observation_base(**{value_field: value})
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    observation = normalize_observation(resource, index, {"patient-1"}, set())
    assert observation.value_type == expected_type


def test_normalize_observation_component_shape_preserves_all_parts():
    resource = _observation_base()
    del resource["effectiveDateTime"]
    resource["component"] = [
        {
            "code": {
                "coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic"}]
            },
            "valueQuantity": {"value": 79, "unit": "mm[Hg]"},
        },
        {
            "code": {
                "coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic"}]
            },
            "valueQuantity": {"value": 116, "unit": "mm[Hg]"},
        },
    ]
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    observation = normalize_observation(resource, index, {"patient-1"}, set())
    assert observation.value_type == "component"
    assert len(observation.components) == 2
    assert observation.components[0].value_quantity == 79


def test_normalize_observation_marks_unrecognized_value_shape_unsupported_not_rejected():
    resource = _observation_base(valueBoolean=True)
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    observation = normalize_observation(resource, index, {"patient-1"}, set())
    assert observation.value_type == "unsupported"
    assert observation.value_quantity is None
    assert observation.value_string is None


def test_normalize_medication_request_supports_codeable_concept():
    resource = {
        "resourceType": "MedicationRequest",
        "id": "mr-1",
        "status": "active",
        "intent": "order",
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "code": "313782",
                    "display": "Acetaminophen",
                }
            ]
        },
        "subject": {"reference": "urn:uuid:patient-1"},
    }
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    request = normalize_medication_request(resource, index, {"patient-1"}, set())
    assert request.coding.code == "313782"


def test_normalize_medication_request_rejects_medication_reference_shape():
    resource = {
        "resourceType": "MedicationRequest",
        "id": "mr-2",
        "status": "active",
        "intent": "order",
        "medicationReference": {"reference": "urn:uuid:medication-1"},
        "subject": {"reference": "urn:uuid:patient-1"},
    }
    bundle = _bundle(_patient_resource(), resource)
    index = build_reference_index(bundle)
    with pytest.raises(ValueError, match="medicationReference|medication"):
        normalize_medication_request(resource, index, {"patient-1"}, set())


def test_normalize_bundle_counts_unsupported_resource_types_without_dropping_silently():
    bundle = _bundle(
        _patient_resource(),
        _encounter_resource(),
        _condition_resource(),
        {"resourceType": "Claim", "id": "claim-1"},
        {"resourceType": "Immunization", "id": "imm-1"},
    )
    result = normalize_bundle(bundle)
    assert len(result["patients"]) == 1
    assert len(result["conditions"]) == 1
    assert result["unsupported_resource_counts"] == {"Claim": 1, "Immunization": 1}
    assert result["resource_type_counts"]["Patient"] == 1


def test_normalize_bundle_quarantines_but_continues_on_bad_resource():
    bad_condition = _condition_resource(id="bad-condition", code={"coding": []})  # no valid coding
    bundle = _bundle(
        _patient_resource(), _encounter_resource(), bad_condition, _condition_resource()
    )
    result = normalize_bundle(bundle)
    assert len(result["conditions"]) == 1
    assert len(result["rejected"]) == 1
    assert result["rejected"][0].resource_type == "Condition"


def test_load_bundles_rejects_tampered_bundle_content(tmp_path):
    import hashlib
    import json as json_module
    import zipfile

    good_bundle = _bundle(_patient_resource())
    good_bytes = json_module.dumps(good_bundle).encode()
    zip_path = tmp_path / "release.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("fhir/patient.json", good_bytes)
    zip_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json_module.dumps({"zip_sha256": zip_sha256}))
    subset_path = tmp_path / "subset.json"
    subset_path.write_text(
        json_module.dumps(
            {
                "zip_sha256": zip_sha256,
                "bundle_files": ["fhir/patient.json"],
                # A recorded checksum that does not match the real file content.
                "bundle_sha256": {"fhir/patient.json": "0" * 64},
            }
        )
    )
    with pytest.raises(ValueError, match="checksum"):
        load_bundles(zip_path, profile_path, subset_path)


def test_load_bundles_rejects_non_bundle_resource_type(tmp_path):
    import hashlib
    import json as json_module
    import zipfile

    not_a_bundle = {"resourceType": "Patient", "id": "x"}
    content = json_module.dumps(not_a_bundle).encode()
    content_sha = hashlib.sha256(content).hexdigest()
    zip_path = tmp_path / "release.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("fhir/not-a-bundle.json", content)
    zip_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json_module.dumps({"zip_sha256": zip_sha256}))
    subset_path = tmp_path / "subset.json"
    subset_path.write_text(
        json_module.dumps(
            {
                "zip_sha256": zip_sha256,
                "bundle_files": ["fhir/not-a-bundle.json"],
                "bundle_sha256": {"fhir/not-a-bundle.json": content_sha},
            }
        )
    )
    with pytest.raises(ValueError, match="Bundle"):
        load_bundles(zip_path, profile_path, subset_path)


@pytestmark_live
def test_load_bundles_against_real_files():
    if not ZIP_PATH.exists():
        pytest.skip("Download the reviewed Synthea FHIR R4 release to run this test")
    bundles = load_bundles(ZIP_PATH, PROFILE, SUBSET)
    assert len(bundles) == 5
    assert all(b["bundle"]["resourceType"] == "Bundle" for b in bundles)


@pytestmark_live
async def test_ingest_synthea_idempotent_against_live_postgres():
    if not ZIP_PATH.exists():
        pytest.skip("Download the reviewed Synthea FHIR R4 release to run this test")
    settings = get_settings()
    first = await ingest_synthea(settings)
    assert first["resource_counts"]["patients"] == 5
    second = await ingest_synthea(settings)
    assert all(v == 0 for v in second["inserted"].values())
    assert second["resource_counts"] == first["resource_counts"]
    assert second["rejected_records"] == first["rejected_records"]
