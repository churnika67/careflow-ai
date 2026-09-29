/**
 * Shared FieldSpec[] definitions for every structured record shape
 * rendered via RecordFields -- extracted in Phase 14 Slice 4 so /assistant
 * (POST /orchestrate's route=fhir/synpuf, always the default
 * get_patient_summary/get_beneficiary_summary tool) renders identically to
 * /patient-data and /claims (explicit tool selection) without a second
 * set of field definitions. Field keys/labels are unchanged from Slice 3.
 */
import type { FieldSpec } from "./fieldTypes";

export const PATIENT_SUMMARY_FIELDS: FieldSpec[] = [
  { key: "patient_id", label: "Patient ID" },
  { key: "given_name", label: "Given Name" },
  { key: "family_name", label: "Family Name" },
  { key: "birth_date", label: "Birth Date", kind: "date" },
  { key: "gender", label: "Gender" },
  { key: "race_code", label: "Race Code" },
  { key: "race_display", label: "Race" },
  { key: "ethnicity_code", label: "Ethnicity Code" },
  { key: "ethnicity_display", label: "Ethnicity" },
];

export const ENCOUNTER_FIELDS: FieldSpec[] = [
  { key: "status", label: "Status" },
  { key: "class_code", label: "Class" },
  { key: "type_display", label: "Type" },
  { key: "period_start", label: "Start", kind: "timestamp" },
  { key: "period_end", label: "End", kind: "timestamp" },
];

export const BENEFICIARY_IDENTITY_FIELDS: FieldSpec[] = [
  { key: "beneficiary_id", label: "Beneficiary ID" },
  { key: "birth_date", label: "Birth Date", kind: "date" },
  { key: "death_date", label: "Death Date", kind: "date" },
  { key: "sex_code", label: "Sex Code" },
  { key: "race_code", label: "Race Code" },
  { key: "esrd_indicator", label: "ESRD Indicator" },
  { key: "state_code", label: "State Code" },
  { key: "county_code", label: "County Code" },
];

export const BENEFICIARY_COVERAGE_FIELDS: FieldSpec[] = [
  { key: "hi_coverage_months", label: "HI Coverage (months)" },
  { key: "smi_coverage_months", label: "SMI Coverage (months)" },
  { key: "hmo_coverage_months", label: "HMO Coverage (months)" },
  { key: "plan_coverage_months", label: "Plan Coverage (months)" },
];

// Raw SP_* indicator values, shown exactly as returned -- never reinterpreted
// as booleans (the source codebook's 1/2 scale is not assumed here, matching
// backend/app/db/migrations/0002_synpuf.sql's own explicit caution).
export const BENEFICIARY_CHRONIC_FIELDS: FieldSpec[] = [
  { key: "chronic_alzheimers", label: "Alzheimer's Indicator" },
  { key: "chronic_heart_failure", label: "Heart Failure Indicator" },
  { key: "chronic_kidney_disease", label: "Kidney Disease Indicator" },
  { key: "chronic_cancer", label: "Cancer Indicator" },
  { key: "chronic_copd", label: "COPD Indicator" },
  { key: "chronic_depression", label: "Depression Indicator" },
  { key: "chronic_diabetes", label: "Diabetes Indicator" },
  { key: "chronic_ischemic_heart", label: "Ischemic Heart Indicator" },
  { key: "chronic_osteoporosis", label: "Osteoporosis Indicator" },
  { key: "chronic_ra_oa", label: "RA/OA Indicator" },
  { key: "chronic_stroke_tia", label: "Stroke/TIA Indicator" },
];

export const BENEFICIARY_PAYMENT_FIELDS: FieldSpec[] = [
  { key: "reimb_inpatient", label: "Inpatient Reimbursement", kind: "money" },
  { key: "benres_inpatient", label: "Inpatient Beneficiary Responsibility", kind: "money" },
  { key: "pppymt_inpatient", label: "Inpatient PPS Payment", kind: "money" },
  { key: "reimb_outpatient", label: "Outpatient Reimbursement", kind: "money" },
  { key: "benres_outpatient", label: "Outpatient Beneficiary Responsibility", kind: "money" },
  { key: "pppymt_outpatient", label: "Outpatient PPS Payment", kind: "money" },
  { key: "reimb_carrier", label: "Carrier Reimbursement", kind: "money" },
  { key: "benres_carrier", label: "Carrier Beneficiary Responsibility", kind: "money" },
  { key: "pppymt_carrier", label: "Carrier PPS Payment", kind: "money" },
];

export const CLAIM_FIELDS: FieldSpec[] = [
  { key: "claim_type", label: "Claim Type" },
  { key: "from_date", label: "From Date", kind: "date" },
  { key: "thru_date", label: "Thru Date", kind: "date" },
  { key: "admission_date", label: "Admission Date", kind: "date" },
  { key: "discharge_date", label: "Discharge Date", kind: "date" },
  { key: "provider_number", label: "Provider Number" },
  { key: "claim_payment_amount", label: "Claim Payment Amount", kind: "money" },
  { key: "primary_payer_paid_amount", label: "Primary Payer Paid Amount", kind: "money" },
  { key: "drg_code", label: "DRG Code" },
  { key: "admitting_diagnosis_code", label: "Admitting Diagnosis Code" },
];
