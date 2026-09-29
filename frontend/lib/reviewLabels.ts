/**
 * Human-readable labels for Phase 11 review concepts -- mirrors Slice 4/5's
 * lib/routingLabels.ts / lib/workflowLabels.ts (human label first, raw
 * backend value available as a technical detail alongside it).
 */
import type { ReviewDecisionType, ReviewEventType, ReviewStatus } from "./api/reviewTypes";
import { EXPLICIT_REVIEW_REQUESTED } from "./api/reviewTypes";
import type { ValidationIssueCode } from "./api/multiAgentTypes";
import { validationIssueMessage } from "./workflowLabels";

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  revision_requested: "Revision Requested",
};

export function reviewStatusLabel(status: ReviewStatus): string {
  return REVIEW_STATUS_LABELS[status];
}

export const REVIEW_DECISION_LABELS: Record<ReviewDecisionType, string> = {
  approve: "Approve",
  reject: "Reject",
  request_revision: "Request Revision",
};

export function reviewDecisionLabel(decision: ReviewDecisionType): string {
  return REVIEW_DECISION_LABELS[decision];
}

export const REVIEW_EVENT_LABELS: Record<ReviewEventType, string> = {
  review_created: "Review created",
  review_approved: "Approved",
  review_rejected: "Rejected",
  revision_requested: "Revision requested",
};

export function reviewEventLabel(eventType: ReviewEventType): string {
  return REVIEW_EVENT_LABELS[eventType];
}

/** A review's `trigger_reason_codes` are exactly one Phase 11-specific
 * value (`explicit_review_requested`) or a `ValidationIssueCode` value --
 * backend/app/review/models.py::VALID_TRIGGER_REASON_CODES confirms this
 * is the complete set, so this function reuses Slice 5's own
 * validationIssueMessage() for every code except the one Phase 11 adds,
 * rather than a second, parallel message map. */
export function triggerReasonLabel(code: string): string {
  if (code === EXPLICIT_REVIEW_REQUESTED) {
    return "Human review was explicitly requested for this request.";
  }
  return validationIssueMessage(code as ValidationIssueCode);
}
