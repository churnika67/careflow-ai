-- Synthea FHIR R4 domain tables (Phase 8, Part B).
-- Scope: Patient, Encounter, Condition, Procedure, Observation, MedicationRequest.
-- All other resource types present in the real sample bundles (DiagnosticReport,
-- Claim, ExplanationOfBenefit, DocumentReference, Immunization, SupplyDelivery,
-- CareTeam, CarePlan, Medication, MedicationAdministration, ImagingStudy,
-- AllergyIntolerance, Device, Provenance) are explicitly out of scope and are
-- counted, not silently dropped, by the loader's ingestion manifest.
--
-- Primary keys are the FHIR resource's own `id` (unique within a Synthea bundle
-- and, empirically, across the inspected sample set), not a synthetic UUID —
-- Synthea already generates these as UUIDs. `patient_id` and `encounter_id` are
-- an entirely independent identity space from synpuf_beneficiaries/synpuf_claims;
-- there is no foreign key between the CMS DE-SynPUF and Synthea domains.
--
-- Verified against the real Nov 2021 sample (30 inspected bundles):
--   * coding.system values observed: SNOMED CT, LOINC, RxNorm, CVX — never ICD-10.
--     `code`/`code_system`/`code_display` store the FIRST coding as the primary
--     one; `codings` preserves every Coding entry verbatim (multiple codings
--     for one concept, e.g. LOINC 8310-5 + 8331-1 for "temperature", are real
--     and observed — this column is why that fact is not lost).
--   * Observation.value[x] shapes observed: valueQuantity, valueCodeableConcept,
--     valueString, and multi-component (blood pressure-style, no top-level
--     value). All four are modeled; any other value[x] this loader has not
--     seen is inserted with value_type='unsupported' and null value columns,
--     never silently dropped, and counted in the ingestion manifest.
--   * No missing `encounter` references were observed in the inspected sample,
--     but encounter_id stays nullable and the loader tolerates an absent or
--     unresolved encounter reference by design, not by assumption.

CREATE TABLE IF NOT EXISTS fhir_patients (
    patient_id TEXT PRIMARY KEY,
    family_name TEXT,
    given_name TEXT,
    birth_date DATE,
    gender TEXT,
    race_code TEXT,
    race_display TEXT,
    ethnicity_code TEXT,
    ethnicity_display TEXT,
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id),
    source_bundle_sha256 TEXT NOT NULL CHECK (source_bundle_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE IF NOT EXISTS fhir_encounters (
    encounter_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES fhir_patients (patient_id),
    status TEXT NOT NULL,
    class_code TEXT,
    type_code TEXT,
    type_system TEXT,
    type_display TEXT,
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id)
);

CREATE INDEX IF NOT EXISTS fhir_encounters_patient_id_idx ON fhir_encounters (patient_id);

CREATE TABLE IF NOT EXISTS fhir_conditions (
    condition_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES fhir_patients (patient_id),
    encounter_id TEXT REFERENCES fhir_encounters (encounter_id),
    clinical_status TEXT,
    verification_status TEXT,
    code TEXT NOT NULL,
    code_system TEXT NOT NULL,
    code_display TEXT,
    codings JSONB NOT NULL,
    onset_datetime TIMESTAMPTZ,
    recorded_date TIMESTAMPTZ,
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id)
);

CREATE INDEX IF NOT EXISTS fhir_conditions_patient_id_idx ON fhir_conditions (patient_id);
CREATE INDEX IF NOT EXISTS fhir_conditions_encounter_id_idx ON fhir_conditions (encounter_id);
CREATE INDEX IF NOT EXISTS fhir_conditions_code_idx ON fhir_conditions (code, code_system);

CREATE TABLE IF NOT EXISTS fhir_procedures (
    procedure_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES fhir_patients (patient_id),
    encounter_id TEXT REFERENCES fhir_encounters (encounter_id),
    status TEXT NOT NULL,
    code TEXT NOT NULL,
    code_system TEXT NOT NULL,
    code_display TEXT,
    codings JSONB NOT NULL,
    performed_start TIMESTAMPTZ,
    performed_end TIMESTAMPTZ,
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id)
);

CREATE INDEX IF NOT EXISTS fhir_procedures_patient_id_idx ON fhir_procedures (patient_id);
CREATE INDEX IF NOT EXISTS fhir_procedures_encounter_id_idx ON fhir_procedures (encounter_id);
CREATE INDEX IF NOT EXISTS fhir_procedures_code_idx ON fhir_procedures (code, code_system);

CREATE TABLE IF NOT EXISTS fhir_observations (
    observation_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES fhir_patients (patient_id),
    encounter_id TEXT REFERENCES fhir_encounters (encounter_id),
    status TEXT NOT NULL,
    code TEXT NOT NULL,
    code_system TEXT NOT NULL,
    code_display TEXT,
    codings JSONB NOT NULL,
    value_type TEXT NOT NULL
        CHECK (value_type IN ('quantity', 'codeable_concept', 'string', 'component', 'unsupported')),
    value_quantity NUMERIC,
    value_unit TEXT,
    value_code TEXT,
    value_code_system TEXT,
    value_code_display TEXT,
    value_string TEXT,
    effective_datetime TIMESTAMPTZ,
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id),
    CHECK (value_type <> 'quantity' OR value_quantity IS NOT NULL),
    CHECK (value_type <> 'codeable_concept' OR value_code IS NOT NULL),
    CHECK (value_type <> 'string' OR value_string IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS fhir_observations_patient_id_idx ON fhir_observations (patient_id);
CREATE INDEX IF NOT EXISTS fhir_observations_encounter_id_idx ON fhir_observations (encounter_id);
CREATE INDEX IF NOT EXISTS fhir_observations_code_idx ON fhir_observations (code, code_system);

CREATE TABLE IF NOT EXISTS fhir_observation_components (
    observation_id TEXT NOT NULL REFERENCES fhir_observations (observation_id),
    component_index SMALLINT NOT NULL CHECK (component_index >= 0),
    code TEXT NOT NULL,
    code_system TEXT NOT NULL,
    code_display TEXT,
    value_quantity NUMERIC,
    value_unit TEXT,
    PRIMARY KEY (observation_id, component_index)
);

CREATE TABLE IF NOT EXISTS fhir_medication_requests (
    medication_request_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES fhir_patients (patient_id),
    encounter_id TEXT REFERENCES fhir_encounters (encounter_id),
    status TEXT NOT NULL,
    intent TEXT NOT NULL,
    code TEXT NOT NULL,
    code_system TEXT NOT NULL,
    code_display TEXT,
    codings JSONB NOT NULL,
    authored_on TIMESTAMPTZ,
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id)
);

CREATE INDEX IF NOT EXISTS fhir_medication_requests_patient_id_idx
    ON fhir_medication_requests (patient_id);
CREATE INDEX IF NOT EXISTS fhir_medication_requests_encounter_id_idx
    ON fhir_medication_requests (encounter_id);
CREATE INDEX IF NOT EXISTS fhir_medication_requests_code_idx
    ON fhir_medication_requests (code, code_system);
