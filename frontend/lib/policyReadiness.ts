/**
 * Whether Ask CareFlow's policy-question submission should be allowed,
 * derived from Slice 1's SystemStatus -- see
 * docs/phase14_frontend_design.md's "System readiness integration".
 *
 * Rule (Phase 13's own architecture, not invented here): Qdrant backs
 * every policy/RAG retrieval path; Postgres backs structured (non-policy)
 * workflows; Redis is an optional performance dependency. So submission is
 * blocked only when the backend is unreachable, still being checked, or
 * reachable-but-explicitly-reports-Qdrant-unavailable. A Postgres-only or
 * Redis-only degradation never blocks Ask CareFlow.
 */

import type { SystemStatus } from "./api/systemStatus";

export function isPolicySubmissionAllowed(status: SystemStatus): boolean {
  if (status.state === "checking" || status.state === "unavailable") return false;
  if (status.state === "degraded" && status.readiness?.dependencies.qdrant.status === "unavailable") {
    return false;
  }
  return true;
}

export function policySubmissionBlockedReason(status: SystemStatus): string | null {
  if (status.state === "checking") {
    return "Checking CareFlow backend availability…";
  }
  if (status.state === "unavailable") {
    return "CareFlow backend is currently unavailable.";
  }
  if (status.state === "degraded" && status.readiness?.dependencies.qdrant.status === "unavailable") {
    return "Policy search is temporarily unavailable because the search index cannot be reached.";
  }
  return null;
}
