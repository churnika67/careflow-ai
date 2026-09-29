/**
 * Whether the review queue/detail/decision surfaces (/reviews,
 * /reviews/[reviewId]) should be usable, derived from Slice 1's
 * SystemStatus.
 *
 * Deliberately Postgres-only, the same rule as Slice 3's
 * lib/structuredReadiness.ts: backend/app/api/reviews.py's
 * list_pending_reviews/get_review_detail/decide_review all go straight to
 * backend/app/review/repository.py's parameterized Postgres queries via
 * db/connection.py -- none of them ever touch Qdrant, the policy
 * retrieval path, or any generation provider. This is intentionally NOT
 * the same policy as lib/workflowReadiness.ts (which also gates on
 * Qdrant): that policy is for *submitting* a reviewable combined-workflow
 * request (which does need both dependencies), not for reading/deciding
 * an already-persisted review case.
 *
 * Redis is never considered, consistent with the rest of the project.
 */

import type { SystemStatus } from "./api/systemStatus";

export function isReviewSurfaceAllowed(status: SystemStatus): boolean {
  if (status.state === "checking" || status.state === "unavailable") return false;
  if (status.state === "degraded" && status.readiness?.dependencies.postgresql.status === "unavailable") {
    return false;
  }
  return true;
}

export function reviewSurfaceBlockedReason(status: SystemStatus): string | null {
  if (status.state === "checking") {
    return "Checking CareFlow backend availability…";
  }
  if (status.state === "unavailable") {
    return "CareFlow backend is currently unavailable.";
  }
  if (status.state === "degraded" && status.readiness?.dependencies.postgresql.status === "unavailable") {
    return "Review data is temporarily unavailable because the database cannot be reached.";
  }
  return null;
}
