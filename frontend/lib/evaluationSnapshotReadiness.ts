/**
 * Whether the Analytics page's evaluation-snapshot panel should attempt to
 * load, derived from Slice 1's SystemStatus.
 *
 * Deliberately NOT gated on Qdrant or Postgres: GET
 * /analytics/evaluation/snapshot (backend/app/api/analytics.py) reads
 * static Phase 12 artifact files from disk -- it never touches Qdrant,
 * Postgres, or Redis. The only real dependency is the API process itself
 * being reachable, the same permissive rule as lib/assistantReadiness.ts.
 * A Qdrant or Postgres outage must not hide evaluation evidence that has
 * nothing to do with either dependency.
 */

import type { SystemStatus } from "./api/systemStatus";

export function isEvaluationSnapshotAllowed(status: SystemStatus): boolean {
  return status.state !== "checking" && status.state !== "unavailable";
}

export function evaluationSnapshotBlockedReason(status: SystemStatus): string | null {
  if (status.state === "checking") {
    return "Checking CareFlow backend availability…";
  }
  if (status.state === "unavailable") {
    return "CareFlow backend is currently unavailable.";
  }
  return null;
}
