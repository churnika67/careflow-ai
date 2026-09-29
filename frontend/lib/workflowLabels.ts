/**
 * Human-readable labels for Phase 10 multi-agent concepts -- mirrors Slice
 * 4's lib/routingLabels.ts (human label first, raw backend value available
 * as a technical detail alongside it, never LangGraph/Python internals).
 */
import type { WorkflowDecision, ValidationIssueCode } from "./api/multiAgentTypes";

export const WORKFLOW_LABELS: Record<WorkflowDecision, string> = {
  policy_only: "Medicare Policy Only",
  structured_only: "Synthetic Data Only",
  policy_and_structured: "Medicare Policy + Synthetic Data",
  abstain: "No supported workflow",
};

export function workflowLabel(workflow: WorkflowDecision): string {
  return WORKFLOW_LABELS[workflow];
}

// backend/app/agents/models.py::ValidationIssueCode -- calm, human
// explanations. cross_dataset_identity_violation and
// workflow_result_mismatch are not currently reachable through this page's
// own request construction (see docs/phase14_frontend_design.md's Slice 5
// "Dataset boundary"/validator notes) but are still mapped, since they are
// part of the real, current contract.
export const VALIDATION_ISSUE_MESSAGES: Record<ValidationIssueCode, string> = {
  missing_policy_result: "The policy evidence step did not return a result.",
  missing_policy_citations: "The policy answer was returned without supporting citations.",
  missing_structured_result: "The structured data step did not return a result.",
  source_mismatch: "The structured data did not come from the expected dataset.",
  specialist_failure: "Part of this request's evidence gathering did not complete successfully.",
  cross_dataset_identity_violation:
    "This request attempted to link identities across datasets, which CareFlow does not support.",
  workflow_result_mismatch: "The workflow result did not match the expected shape for this request.",
};

export function validationIssueMessage(code: ValidationIssueCode): string {
  return VALIDATION_ISSUE_MESSAGES[code] ?? code;
}
