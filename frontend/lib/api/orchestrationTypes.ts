/**
 * POST /orchestrate + the Phase 9 structured-data tool registry (Phase 14
 * Slices 3-4). Derived directly from backend/app/orchestration/models.py
 * and backend/app/orchestration/tools.py -- the registry is the
 * authoritative source for tool names/arguments/output shape, not prior
 * documentation.
 *
 * Slice 3's Patient Data/Claims pages only ever send route="fhir" or
 * route="synpuf" explicitly (never "policy", never omitted). Slice 4's
 * /assistant page sends `question` only and lets the backend's
 * deterministic classifier choose the route -- see
 * docs/phase14_frontend_design.md's "Route/tool strategy" and "Router
 * request" sections for each.
 */

import type { Citation } from "./types";

export type Route = "policy" | "synpuf" | "fhir" | "abstain";
export type OrchestrationStatus = "ok" | "abstained" | "error";

/** backend/app/orchestration/models.py::AbstentionReason -- the full enum,
 * though this slice's own explicit, pre-validated requests only ever
 * realistically produce a subset of these (unknown_patient/
 * unknown_beneficiary/unknown_claim primarily; the others are defensive). */
export type AbstentionReason =
  | "unsupported_request"
  | "ambiguous_route"
  | "cross_dataset_linkage_request"
  | "missing_required_identifier"
  | "unknown_patient"
  | "unknown_beneficiary"
  | "unknown_claim"
  | "unsupported_tool"
  | "invalid_tool_arguments"
  | "inconsistent_request"
  | "policy_abstained";

export type SourceDataset = "synthea_fhir" | "cms_desynpuf";

export interface OrchestrationRequest {
  question: string;
  route?: Route;
  tool?: string;
  tool_arguments?: Record<string, unknown>;
}

export interface OrchestrationResponse {
  request_id: string;
  route: Route;
  status: OrchestrationStatus;
  answer: string | null;
  // Exactly RAGAnswer.citations' shape when route=policy (both come from
  // the same Citation.model_dump() on the backend) -- confirmed from
  // backend/app/api/orchestrate.py::_to_response().
  citations: Citation[] | null;
  tool: string | null;
  source_dataset: SourceDataset | null;
  record_count: number | null;
  data: unknown;
  abstention_reason: AbstentionReason | null;
  error: string | null;
}

export interface OrchestrationErrorBody {
  error: {
    code: string;
  };
}

// --- FHIR tool names (backend/app/orchestration/tools.py TOOL_REGISTRY,
// route=fhir, patient-ID-scoped only -- the 4 population-level aggregate
// tools (fhir_encounter_counts, fhir_condition_frequency,
// fhir_procedure_frequency, fhir_medication_frequency) are deliberately
// out of scope for this per-patient page; see the design doc) ------------

export type FhirToolName =
  | "get_patient_summary"
  | "get_patient_encounters"
  | "get_patient_conditions"
  | "get_patient_procedures"
  | "get_patient_observations"
  | "get_patient_medication_requests";

export interface Coding {
  system: string;
  code: string;
  display: string | null;
}

/** fhir_patients (backend/app/db/migrations/0003_fhir.sql) */
export interface FhirPatientSummary {
  patient_id: string;
  family_name: string | null;
  given_name: string | null;
  birth_date: string | null; // DATE, "YYYY-MM-DD"
  gender: string | null;
  race_code: string | null;
  race_display: string | null;
  ethnicity_code: string | null;
  ethnicity_display: string | null;
  run_id: string;
  source_bundle_sha256: string;
}

export interface FhirEncounter {
  encounter_id: string;
  patient_id: string;
  status: string;
  class_code: string | null;
  type_code: string | null;
  type_system: string | null;
  type_display: string | null;
  period_start: string | null; // TIMESTAMPTZ, ISO-8601
  period_end: string | null;
  run_id: string;
}

export interface FhirCondition {
  condition_id: string;
  patient_id: string;
  encounter_id: string | null;
  clinical_status: string | null;
  verification_status: string | null;
  code: string;
  code_system: string;
  code_display: string | null;
  codings: Coding[];
  onset_datetime: string | null;
  recorded_date: string | null;
  run_id: string;
}

export interface FhirProcedure {
  procedure_id: string;
  patient_id: string;
  encounter_id: string | null;
  status: string;
  code: string;
  code_system: string;
  code_display: string | null;
  codings: Coding[];
  performed_start: string | null;
  performed_end: string | null;
  run_id: string;
}

export interface FhirObservationComponent {
  component_index: number;
  code: string;
  code_system: string;
  code_display: string | null;
  value_quantity: number | null;
  value_unit: string | null;
}

export interface FhirObservation {
  observation_id: string;
  patient_id: string;
  encounter_id: string | null;
  status: string;
  code: string;
  code_system: string;
  code_display: string | null;
  codings: Coding[];
  value_type: "quantity" | "codeable_concept" | "string" | "component" | "unsupported";
  value_quantity: number | null;
  value_unit: string | null;
  value_code: string | null;
  value_code_system: string | null;
  value_code_display: string | null;
  value_string: string | null;
  effective_datetime: string | null;
  run_id: string;
  components?: FhirObservationComponent[]; // only present when value_type === "component"
}

export interface FhirMedicationRequest {
  medication_request_id: string;
  patient_id: string;
  encounter_id: string | null;
  status: string;
  intent: string;
  code: string;
  code_system: string;
  code_display: string | null;
  codings: Coding[];
  authored_on: string | null;
  run_id: string;
}

// --- SynPUF tool names (route=synpuf, per-beneficiary/per-claim only --
// the 5 population-level aggregate tools (synpuf_claim_counts,
// synpuf_payment_totals, synpuf_diagnosis_frequency,
// synpuf_procedure_frequency, synpuf_hcpcs_frequency) are out of scope for
// the same reason as FHIR's aggregate tools) ------------------------------

export type SynpufToolName = "get_beneficiary_summary" | "get_claims_for_beneficiary" | "get_claim_details";

/** synpuf_beneficiaries (backend/app/db/migrations/0002_synpuf.sql) */
export interface SynpufBeneficiarySummary {
  beneficiary_id: string;
  birth_date: string; // DATE
  death_date: string | null;
  sex_code: string;
  race_code: string;
  esrd_indicator: string;
  state_code: string;
  county_code: string;
  hi_coverage_months: number;
  smi_coverage_months: number;
  hmo_coverage_months: number;
  plan_coverage_months: number;
  chronic_alzheimers: number;
  chronic_heart_failure: number;
  chronic_kidney_disease: number;
  chronic_cancer: number;
  chronic_copd: number;
  chronic_depression: number;
  chronic_diabetes: number;
  chronic_ischemic_heart: number;
  chronic_osteoporosis: number;
  chronic_ra_oa: number;
  chronic_stroke_tia: number;
  reimb_inpatient: number;
  benres_inpatient: number;
  pppymt_inpatient: number;
  reimb_outpatient: number;
  benres_outpatient: number;
  pppymt_outpatient: number;
  reimb_carrier: number;
  benres_carrier: number;
  pppymt_carrier: number;
}

export interface SynpufClaim {
  claim_row_id: string;
  claim_type: "inpatient" | "outpatient";
  claim_id: string;
  segment: number;
  beneficiary_id: string;
  from_date: string; // DATE
  thru_date: string;
  admission_date: string | null;
  discharge_date: string | null;
  provider_number: string | null;
  claim_payment_amount: number;
  primary_payer_paid_amount: number;
  attending_physician_npi: string | null;
  operating_physician_npi: string | null;
  other_physician_npi: string | null;
  drg_code: string | null;
  admitting_diagnosis_code: string | null;
}

export interface SynpufDiagnosis {
  sequence: number;
  icd9_code: string;
}

export interface SynpufProcedureCode {
  sequence: number;
  icd9_procedure_code: string;
}

export interface SynpufClaimLine {
  line_number: number;
  hcpcs_code: string;
}

export interface SynpufClaimDetails extends SynpufClaim {
  diagnoses: SynpufDiagnosis[];
  procedures: SynpufProcedureCode[];
  lines: SynpufClaimLine[];
}
