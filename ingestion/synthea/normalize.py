from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from ingestion.synthea.source import RejectedRecord

US_CORE_RACE = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
US_CORE_ETHNICITY = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"


@dataclass(frozen=True)
class Patient:
    patient_id: str
    family_name: str | None
    given_name: str | None
    birth_date: date
    gender: str
    race_code: str | None
    race_display: str | None
    ethnicity_code: str | None
    ethnicity_display: str | None


@dataclass(frozen=True)
class Encounter:
    encounter_id: str
    patient_id: str
    status: str
    class_code: str | None
    type_code: str | None
    type_system: str | None
    type_display: str | None
    period_start: datetime | None
    period_end: datetime | None


@dataclass(frozen=True)
class ClinicalCoding:
    code: str
    code_system: str
    code_display: str | None
    codings: tuple[dict, ...]


@dataclass(frozen=True)
class Condition:
    condition_id: str
    patient_id: str
    encounter_id: str | None
    clinical_status: str | None
    verification_status: str | None
    coding: ClinicalCoding
    onset_datetime: datetime | None
    recorded_date: datetime | None


@dataclass(frozen=True)
class Procedure:
    procedure_id: str
    patient_id: str
    encounter_id: str | None
    status: str
    coding: ClinicalCoding
    performed_start: datetime | None
    performed_end: datetime | None


@dataclass(frozen=True)
class ObservationComponent:
    index: int
    code: str
    code_system: str
    code_display: str | None
    value_quantity: Decimal | None
    value_unit: str | None


@dataclass(frozen=True)
class Observation:
    observation_id: str
    patient_id: str
    encounter_id: str | None
    status: str
    coding: ClinicalCoding
    value_type: str
    value_quantity: Decimal | None
    value_unit: str | None
    value_code: str | None
    value_code_system: str | None
    value_code_display: str | None
    value_string: str | None
    effective_datetime: datetime | None
    components: tuple[ObservationComponent, ...]


@dataclass(frozen=True)
class MedicationRequest:
    medication_request_id: str
    patient_id: str
    encounter_id: str | None
    status: str
    intent: str
    coding: ClinicalCoding
    authored_on: datetime | None


def _codings(concept: dict | None) -> tuple[dict, ...]:
    if not concept:
        return ()
    return tuple(
        {"system": c["system"], "code": c["code"], "display": c.get("display")}
        for c in concept.get("coding", [])
        if c.get("system") and c.get("code")
    )


def _clinical_coding(concept: dict | None) -> ClinicalCoding:
    codings = _codings(concept)
    if not codings:
        raise ValueError("no coding with both system and code present")
    primary = codings[0]
    return ClinicalCoding(primary["code"], primary["system"], primary.get("display"), codings)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def build_reference_index(bundle: dict) -> dict[str, dict]:
    return {
        entry["fullUrl"]: entry["resource"]
        for entry in bundle.get("entry", [])
        if "fullUrl" in entry
    }


def _resolve(index: dict[str, dict], resource: dict, field: str) -> dict | None:
    ref = resource.get(field, {}).get("reference")
    return index.get(ref) if ref else None


def normalize_patient(resource: dict) -> Patient:
    patient_id = resource["id"]
    if not patient_id:
        raise ValueError("missing Patient.id")
    birth_date = date.fromisoformat(resource["birthDate"])
    gender = resource["gender"]
    if not gender.strip():
        raise ValueError("missing Patient.gender")
    names = resource.get("name", [])
    official = next((n for n in names if n.get("use") == "official"), names[0] if names else {})
    family_name = official.get("family")
    given_name = " ".join(official.get("given", [])) or None

    def race_ethnicity(url: str) -> tuple[str | None, str | None]:
        for ext in resource.get("extension", []):
            if ext.get("url") == url:
                for sub in ext.get("extension", []):
                    if sub.get("url") == "ombCategory":
                        coding = sub.get("valueCoding", {})
                        return coding.get("code"), coding.get("display")
        return None, None

    race_code, race_display = race_ethnicity(US_CORE_RACE)
    ethnicity_code, ethnicity_display = race_ethnicity(US_CORE_ETHNICITY)
    return Patient(
        patient_id,
        family_name,
        given_name,
        birth_date,
        gender,
        race_code,
        race_display,
        ethnicity_code,
        ethnicity_display,
    )


def normalize_encounter(resource: dict, index: dict[str, dict]) -> Encounter:
    encounter_id = resource["id"]
    status = resource["status"]
    subject = _resolve(index, resource, "subject")
    if subject is None or subject.get("resourceType") != "Patient":
        raise ValueError("unresolved or missing Encounter.subject")
    type_codings = _codings(resource.get("type", [{}])[0]) if resource.get("type") else ()
    type_primary = type_codings[0] if type_codings else {}
    period = resource.get("period", {})
    return Encounter(
        encounter_id,
        subject["id"],
        status,
        resource.get("class", {}).get("code"),
        type_primary.get("code"),
        type_primary.get("system"),
        type_primary.get("display"),
        _parse_datetime(period.get("start")),
        _parse_datetime(period.get("end")),
    )


def _resolve_patient_id(index: dict[str, dict], resource: dict, known_patients: set[str]) -> str:
    subject = _resolve(index, resource, "subject")
    if (
        subject is None
        or subject.get("resourceType") != "Patient"
        or subject["id"] not in known_patients
    ):
        raise ValueError("unresolved or missing subject reference")
    return subject["id"]


def _resolve_encounter_id(
    index: dict[str, dict], resource: dict, known_encounters: set[str]
) -> str | None:
    """An absent or unresolved encounter reference is not an error: it is stored
    as NULL, since encounter is an optional relationship for these resources."""
    encounter = _resolve(index, resource, "encounter")
    if encounter is None or encounter.get("resourceType") != "Encounter":
        return None
    encounter_id = encounter.get("id")
    return encounter_id if encounter_id in known_encounters else None


def normalize_condition(
    resource: dict, index: dict[str, dict], known_patients: set[str], known_encounters: set[str]
) -> Condition:
    condition_id = resource["id"]
    patient_id = _resolve_patient_id(index, resource, known_patients)
    encounter_id = _resolve_encounter_id(index, resource, known_encounters)
    coding = _clinical_coding(resource.get("code"))
    clinical_status_codings = _codings(resource.get("clinicalStatus"))
    verification_status_codings = _codings(resource.get("verificationStatus"))
    return Condition(
        condition_id,
        patient_id,
        encounter_id,
        clinical_status_codings[0]["code"] if clinical_status_codings else None,
        verification_status_codings[0]["code"] if verification_status_codings else None,
        coding,
        _parse_datetime(resource.get("onsetDateTime")),
        _parse_datetime(resource.get("recordedDate")),
    )


def normalize_procedure(
    resource: dict, index: dict[str, dict], known_patients: set[str], known_encounters: set[str]
) -> Procedure:
    procedure_id = resource["id"]
    status = resource["status"]
    patient_id = _resolve_patient_id(index, resource, known_patients)
    encounter_id = _resolve_encounter_id(index, resource, known_encounters)
    coding = _clinical_coding(resource.get("code"))
    if "performedPeriod" in resource:
        period = resource["performedPeriod"]
        start = _parse_datetime(period.get("start"))
        end = _parse_datetime(period.get("end"))
    elif "performedDateTime" in resource:
        start = end = _parse_datetime(resource["performedDateTime"])
    else:
        raise ValueError(
            "performed[x] shape not supported (only performedPeriod/performedDateTime)"
        )
    return Procedure(procedure_id, patient_id, encounter_id, status, coding, start, end)


def _extract_observation_value(resource: dict) -> tuple:
    """Returns (value_type, quantity, unit, code, code_system, code_display, string, components).
    Any value[x] representation this loader has not verified against real data
    (valueBoolean, valueInteger, valuePeriod, valueRatio, ...), and any Observation
    with neither a value[x] nor a component array, is marked 'unsupported' and
    inserted with all value columns null — never silently dropped."""
    if "valueQuantity" in resource:
        q = resource["valueQuantity"]
        if "value" not in q:
            raise ValueError("valueQuantity missing numeric value")
        return ("quantity", Decimal(str(q["value"])), q.get("unit"), None, None, None, None, ())
    if "valueCodeableConcept" in resource:
        coding = _clinical_coding(resource["valueCodeableConcept"])
        return (
            "codeable_concept",
            None,
            None,
            coding.code,
            coding.code_system,
            coding.code_display,
            None,
            (),
        )
    if "valueString" in resource:
        text = resource["valueString"]
        if not text.strip():
            raise ValueError("valueString is blank")
        return ("string", None, None, None, None, None, text, ())
    if "component" in resource:
        components = []
        for idx, comp in enumerate(resource["component"]):
            coding = _clinical_coding(comp.get("code"))
            cq = comp.get("valueQuantity")
            components.append(
                ObservationComponent(
                    idx,
                    coding.code,
                    coding.code_system,
                    coding.code_display,
                    Decimal(str(cq["value"])) if cq and "value" in cq else None,
                    cq.get("unit") if cq else None,
                )
            )
        if not components:
            raise ValueError("component array is empty")
        return ("component", None, None, None, None, None, None, tuple(components))
    return ("unsupported", None, None, None, None, None, None, ())


def normalize_observation(
    resource: dict, index: dict[str, dict], known_patients: set[str], known_encounters: set[str]
) -> Observation:
    observation_id = resource["id"]
    status = resource["status"]
    patient_id = _resolve_patient_id(index, resource, known_patients)
    encounter_id = _resolve_encounter_id(index, resource, known_encounters)
    coding = _clinical_coding(resource.get("code"))
    value_type, qty, unit, vcode, vsystem, vdisplay, text, components = _extract_observation_value(
        resource
    )
    return Observation(
        observation_id,
        patient_id,
        encounter_id,
        status,
        coding,
        value_type,
        qty,
        unit,
        vcode,
        vsystem,
        vdisplay,
        text,
        _parse_datetime(resource.get("effectiveDateTime")),
        components,
    )


def normalize_medication_request(
    resource: dict, index: dict[str, dict], known_patients: set[str], known_encounters: set[str]
) -> MedicationRequest:
    medication_request_id = resource["id"]
    status = resource["status"]
    intent = resource["intent"]
    patient_id = _resolve_patient_id(index, resource, known_patients)
    encounter_id = _resolve_encounter_id(index, resource, known_encounters)
    if "medicationCodeableConcept" not in resource:
        raise ValueError(
            "medication[x] shape not supported (e.g. medicationReference); "
            "Medication resource is out of scope for Phase 8"
        )
    coding = _clinical_coding(resource["medicationCodeableConcept"])
    return MedicationRequest(
        medication_request_id,
        patient_id,
        encounter_id,
        status,
        intent,
        coding,
        _parse_datetime(resource.get("authoredOn")),
    )


def normalize_bundle(bundle: dict) -> dict:
    """Normalize one Synthea Bundle's supported resources in FK dependency order
    (Patient -> Encounter -> clinical resources), with per-resource quarantine.
    Unsupported resource types are counted, not silently ignored."""
    index = build_reference_index(bundle)
    entries = [e["resource"] for e in bundle.get("entry", []) if "resource" in e]
    resource_type_counts: dict[str, int] = {}
    for resource in entries:
        resource_type_counts[resource["resourceType"]] = (
            resource_type_counts.get(resource["resourceType"], 0) + 1
        )

    rejected: list[RejectedRecord] = []
    patients: list[Patient] = []
    for resource in (r for r in entries if r["resourceType"] == "Patient"):
        try:
            patients.append(normalize_patient(resource))
        except (KeyError, ValueError) as exc:
            rejected.append(RejectedRecord("Patient", resource.get("id", "<blank>"), str(exc)))
    known_patients = {p.patient_id for p in patients}

    encounters: list[Encounter] = []
    for resource in (r for r in entries if r["resourceType"] == "Encounter"):
        try:
            encounters.append(normalize_encounter(resource, index))
        except (KeyError, ValueError) as exc:
            rejected.append(RejectedRecord("Encounter", resource.get("id", "<blank>"), str(exc)))
    known_encounters = {e.encounter_id for e in encounters}

    conditions, procedures, observations, medication_requests = [], [], [], []
    for resource in (r for r in entries if r["resourceType"] == "Condition"):
        try:
            conditions.append(
                normalize_condition(resource, index, known_patients, known_encounters)
            )
        except (KeyError, ValueError) as exc:
            rejected.append(RejectedRecord("Condition", resource.get("id", "<blank>"), str(exc)))
    for resource in (r for r in entries if r["resourceType"] == "Procedure"):
        try:
            procedures.append(
                normalize_procedure(resource, index, known_patients, known_encounters)
            )
        except (KeyError, ValueError) as exc:
            rejected.append(RejectedRecord("Procedure", resource.get("id", "<blank>"), str(exc)))
    for resource in (r for r in entries if r["resourceType"] == "Observation"):
        try:
            observations.append(
                normalize_observation(resource, index, known_patients, known_encounters)
            )
        except (KeyError, ValueError) as exc:
            rejected.append(RejectedRecord("Observation", resource.get("id", "<blank>"), str(exc)))
    for resource in (r for r in entries if r["resourceType"] == "MedicationRequest"):
        try:
            medication_requests.append(
                normalize_medication_request(resource, index, known_patients, known_encounters)
            )
        except (KeyError, ValueError) as exc:
            rejected.append(
                RejectedRecord("MedicationRequest", resource.get("id", "<blank>"), str(exc))
            )

    unsupported_counts = {
        rtype: count
        for rtype, count in resource_type_counts.items()
        if rtype
        not in (
            "Patient",
            "Encounter",
            "Condition",
            "Procedure",
            "Observation",
            "MedicationRequest",
        )
    }
    return {
        "patients": patients,
        "encounters": encounters,
        "conditions": conditions,
        "procedures": procedures,
        "observations": observations,
        "medication_requests": medication_requests,
        "rejected": rejected,
        "resource_type_counts": resource_type_counts,
        "unsupported_resource_counts": unsupported_counts,
    }
