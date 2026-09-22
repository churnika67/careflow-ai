-- CMS DE-SynPUF domain tables (Phase 8, Part A).
-- Scope: Beneficiary Summary, Inpatient Claims, Outpatient Claims only.
-- Carrier Claims and Prescription Drug Events are explicitly out of scope.
--
-- claim_row_id is a deterministic uuid5 of (claim_type, claim_id, segment),
-- not CLM_ID alone: CLM_ID repeats across SEGMENT rows for the same claim
-- (verified against the real Sample 1 files: 68 inpatient and 10,975
-- outpatient claims have more than one SEGMENT), so (claim_type, claim_id,
-- segment) is the real natural key. The synthetic PK keeps child-table
-- foreign keys single-column while UNIQUE(claim_type, claim_id, segment)
-- preserves and enforces the natural key.

CREATE TABLE IF NOT EXISTS synpuf_beneficiaries (
    beneficiary_id TEXT PRIMARY KEY,               -- DESYNPUF_ID
    birth_date DATE NOT NULL,
    death_date DATE,
    sex_code TEXT NOT NULL,
    race_code TEXT NOT NULL,
    esrd_indicator TEXT NOT NULL,
    state_code TEXT NOT NULL,
    county_code TEXT NOT NULL,
    hi_coverage_months SMALLINT NOT NULL CHECK (hi_coverage_months BETWEEN 0 AND 12),
    smi_coverage_months SMALLINT NOT NULL CHECK (smi_coverage_months BETWEEN 0 AND 12),
    hmo_coverage_months SMALLINT NOT NULL CHECK (hmo_coverage_months BETWEEN 0 AND 12),
    plan_coverage_months SMALLINT NOT NULL CHECK (plan_coverage_months BETWEEN 0 AND 12),
    -- Raw SP_* chronic-condition indicator codes, preserved as the source encodes them
    -- (not reinterpreted as booleans; the codebook's 1/2 scale is not assumed here).
    chronic_alzheimers SMALLINT NOT NULL,
    chronic_heart_failure SMALLINT NOT NULL,
    chronic_kidney_disease SMALLINT NOT NULL,
    chronic_cancer SMALLINT NOT NULL,
    chronic_copd SMALLINT NOT NULL,
    chronic_depression SMALLINT NOT NULL,
    chronic_diabetes SMALLINT NOT NULL,
    chronic_ischemic_heart SMALLINT NOT NULL,
    chronic_osteoporosis SMALLINT NOT NULL,
    chronic_ra_oa SMALLINT NOT NULL,
    chronic_stroke_tia SMALLINT NOT NULL,
    reimb_inpatient NUMERIC(12, 2) NOT NULL CHECK (reimb_inpatient >= 0),
    benres_inpatient NUMERIC(12, 2) NOT NULL CHECK (benres_inpatient >= 0),
    pppymt_inpatient NUMERIC(12, 2) NOT NULL CHECK (pppymt_inpatient >= 0),
    reimb_outpatient NUMERIC(12, 2) NOT NULL CHECK (reimb_outpatient >= 0),
    benres_outpatient NUMERIC(12, 2) NOT NULL CHECK (benres_outpatient >= 0),
    pppymt_outpatient NUMERIC(12, 2) NOT NULL CHECK (pppymt_outpatient >= 0),
    reimb_carrier NUMERIC(12, 2) NOT NULL CHECK (reimb_carrier >= 0),
    benres_carrier NUMERIC(12, 2) NOT NULL CHECK (benres_carrier >= 0),
    pppymt_carrier NUMERIC(12, 2) NOT NULL CHECK (pppymt_carrier >= 0),
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id),
    source_row_sha256 TEXT NOT NULL CHECK (source_row_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE IF NOT EXISTS synpuf_claims (
    claim_row_id UUID PRIMARY KEY,
    claim_type TEXT NOT NULL CHECK (claim_type IN ('inpatient', 'outpatient')),
    claim_id TEXT NOT NULL,                        -- CLM_ID (not unique alone)
    segment SMALLINT NOT NULL,                      -- SEGMENT
    beneficiary_id TEXT NOT NULL REFERENCES synpuf_beneficiaries (beneficiary_id),
    from_date DATE NOT NULL,
    thru_date DATE NOT NULL,
    admission_date DATE,                             -- inpatient only
    discharge_date DATE,                              -- inpatient only
    provider_number TEXT,
    claim_payment_amount NUMERIC(12, 2) NOT NULL CHECK (claim_payment_amount >= 0),
    primary_payer_paid_amount NUMERIC(12, 2) NOT NULL CHECK (primary_payer_paid_amount >= 0),
    attending_physician_npi TEXT,
    operating_physician_npi TEXT,
    other_physician_npi TEXT,
    drg_code TEXT,                                    -- inpatient only
    admitting_diagnosis_code TEXT,
    run_id UUID NOT NULL REFERENCES ingestion_runs (run_id),
    source_row_sha256 TEXT NOT NULL CHECK (source_row_sha256 ~ '^[a-f0-9]{64}$'),
    UNIQUE (claim_type, claim_id, segment),
    CHECK (thru_date >= from_date),
    CHECK (claim_type = 'inpatient' OR (admission_date IS NULL AND discharge_date IS NULL AND drg_code IS NULL))
);

CREATE INDEX IF NOT EXISTS synpuf_claims_beneficiary_id_idx ON synpuf_claims (beneficiary_id);
CREATE INDEX IF NOT EXISTS synpuf_claims_dates_idx ON synpuf_claims (from_date, thru_date);

CREATE TABLE IF NOT EXISTS synpuf_claim_diagnoses (
    claim_row_id UUID NOT NULL REFERENCES synpuf_claims (claim_row_id),
    sequence SMALLINT NOT NULL CHECK (sequence >= 1),
    icd9_code TEXT NOT NULL,
    PRIMARY KEY (claim_row_id, sequence)
);

CREATE INDEX IF NOT EXISTS synpuf_claim_diagnoses_code_idx ON synpuf_claim_diagnoses (icd9_code);

CREATE TABLE IF NOT EXISTS synpuf_claim_procedures (
    claim_row_id UUID NOT NULL REFERENCES synpuf_claims (claim_row_id),
    sequence SMALLINT NOT NULL CHECK (sequence >= 1),
    icd9_procedure_code TEXT NOT NULL,
    PRIMARY KEY (claim_row_id, sequence)
);

CREATE INDEX IF NOT EXISTS synpuf_claim_procedures_code_idx ON synpuf_claim_procedures (icd9_procedure_code);

CREATE TABLE IF NOT EXISTS synpuf_claim_lines (
    claim_row_id UUID NOT NULL REFERENCES synpuf_claims (claim_row_id),
    line_number SMALLINT NOT NULL CHECK (line_number >= 1),
    hcpcs_code TEXT NOT NULL,
    PRIMARY KEY (claim_row_id, line_number)
);

CREATE INDEX IF NOT EXISTS synpuf_claim_lines_code_idx ON synpuf_claim_lines (hcpcs_code);
