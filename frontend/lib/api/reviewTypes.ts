/**
 * Phase 11 human-in-the-loop review contract (Phase 14 Slice 6). Derived
 * directly from backend/app/review/models.py,
 * backend/db/migrations/0004_review_workflow.sql, and
 * backend/app/api/reviews.py -- re-audited from current source, not
 * assumed. Reuses `WorkflowDecision`/`ValidationIssueCode` from
 * ./multiAgentTypes and `Route`/`AbstentionReason` from
 * ./orchestrationTypes rather than redefining them, exactly as the backend
 * itself imports Phase 10's own types instead of duplicating them.
 */

import type { MultiAgentRequest, MultiAgentResponse } from "./multiAgentTypes";

// backend/app/review/models.py::ReviewStatus. Only PENDING is
// non-terminal -- every decision targets a terminal status, and nothing in
// Phase 11 ever transitions out of a terminal one (confirmed from
// is_valid_transition: valid exactly when current_status == PENDING).
export type ReviewStatus = "pending" | "approved" | "rejected" | "revision_requested";

// backend/app/review/models.py::ReviewDecisionType
export type ReviewDecisionType = "approve" | "reject" | "request_revision";

// backend/app/review/models.py::ReviewEventType
export type ReviewEventType = "review_created" | "review_approved" | "review_rejected" | "revision_requested";

// backend/app/review/models.py::ActorType -- reviewer_id is always
// caller-supplied and non-authoritative; this type only distinguishes
// "the system created this" from "a reviewer decided this", never a claim
// of authentication.
export type ActorType = "system" | "reviewer";

// backend/app/review/models.py::EXPLICIT_REVIEW_REQUESTED -- the one
// Phase 11-specific trigger reason. Every other trigger reason reuses a
// ValidationIssueCode value directly (VALID_TRIGGER_REASON_CODES =
// ValidationIssueCode values | {EXPLICIT_REVIEW_REQUESTED}), so no
// parallel vocabulary is defined here either.
export const EXPLICIT_REVIEW_REQUESTED = "explicit_review_requested" as const;

// backend/app/review/models.py::{DEFAULT,MAX}_REVIEW_QUEUE_LIMIT
export const DEFAULT_REVIEW_QUEUE_LIMIT = 20;
export const MAX_REVIEW_QUEUE_LIMIT = 100;

export interface ReviewCase {
  review_id: string;
  request_id: string;
  workflow: string;
  status: ReviewStatus;
  trigger_reason_codes: string[];
  evidence_snapshot: MultiAgentResponse;
  evidence_fingerprint: string;
  version: number;
  previous_review_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReviewEvent {
  event_id: string;
  review_id: string;
  event_type: ReviewEventType;
  actor_id: string;
  actor_type: ActorType;
  previous_status: ReviewStatus | null;
  new_status: ReviewStatus;
  reason: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ReviewDetail {
  case: ReviewCase;
  events: ReviewEvent[];
}

export interface ReviewQueuePage {
  reviews: ReviewCase[];
  next_cursor: string | null;
}

export interface ReviewDecisionRequest {
  reviewer_id: string;
  decision: ReviewDecisionType;
  reason?: string;
  expected_version: number;
}

/** backend/app/review/models.py::ReviewableQueryRequest -- everything
 * MultiAgentRequest accepts, plus two Phase 11-only fields. This page
 * never sends `previous_review_id` (that belongs to a deliberate future
 * resubmission action, out of this slice's scope per its own directive). */
export interface ReviewableQueryRequest extends MultiAgentRequest {
  explicit_review_requested?: boolean;
  previous_review_id?: string;
}

/** backend/app/review/models.py::ReviewableQueryResponse -- the exact
 * MultiAgentResponse shape plus the review outcome. When no review was
 * required, review_id/review_status are null and reason_codes is empty. */
export interface ReviewableQueryResponse extends MultiAgentResponse {
  review_required: boolean;
  review_reason_codes: string[];
  review_id: string | null;
  review_status: ReviewStatus | null;
}

/** Shared `{error: {code}}` shape every review endpoint's error body uses. */
export interface ReviewErrorBody {
  error: {
    code: string;
  };
}

/** The 409 body's shape specifically -- backend/app/api/reviews.py's
 * decide_review returns the CURRENT review case directly in the conflict
 * response, so the frontend never needs a second fetch just to show the
 * up-to-date state after a conflict. */
export interface ReviewConflictBody extends ReviewErrorBody {
  review: ReviewCase;
}
