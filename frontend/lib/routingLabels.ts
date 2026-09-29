/**
 * Human-readable labels for backend route/tool enum values -- Phase 14
 * Slice 4's "make orchestration visible" goal, never a reinterpretation of
 * what each route/tool actually means. The exact backend value is always
 * still available (as a technical detail) alongside the label.
 */
import type { Route } from "./api/orchestrationTypes";

export const ROUTE_LABELS: Record<Route, string> = {
  policy: "Medicare Policy",
  fhir: "Synthea FHIR · Synthetic",
  synpuf: "CMS DE-SynPUF · Synthetic",
  abstain: "No supported route",
};

// The full registry (backend/app/orchestration/tools.py::TOOL_REGISTRY),
// even though CareFlow Assistant's own natural-language routing only ever
// reaches the two default tools (get_patient_summary/
// get_beneficiary_summary) -- see backend/app/orchestration/
// graph.py::_run_structured_route's _DEFAULT_TOOL_BY_ROUTE. Kept complete
// so this map stays correct if a future slice ever surfaces the others
// here too.
export const TOOL_LABELS: Record<string, string> = {
  get_patient_summary: "Patient Summary",
  get_patient_encounters: "Patient Encounters",
  get_patient_conditions: "Patient Conditions",
  get_patient_procedures: "Patient Procedures",
  get_patient_observations: "Patient Observations",
  get_patient_medication_requests: "Patient Medications",
  get_beneficiary_summary: "Beneficiary Summary",
  get_claims_for_beneficiary: "Beneficiary Claims",
  get_claim_details: "Claim Details",
};

export function routeLabel(route: Route): string {
  return ROUTE_LABELS[route];
}

export function toolLabel(tool: string): string {
  return TOOL_LABELS[tool] ?? tool;
}
