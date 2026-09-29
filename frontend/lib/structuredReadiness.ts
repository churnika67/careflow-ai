/**
 * Whether structured-data (Patient Data / Claims) submission should be
 * allowed, derived from Slice 1's SystemStatus.
 *
 * Deliberately different from lib/policyReadiness.ts's rule, per Phase
 * 9's actual architecture: FHIR/SynPUF tools go through
 * backend/app/db/connection.py -> Postgres directly (see
 * backend/app/orchestration/graph.py::_run_structured_route), never
 * Qdrant. So structured actions are blocked only when Postgres itself is
 * unavailable (or the backend is unreachable/still being checked) --
 * Qdrant-down-alone and Redis-down-alone must never block them.
 */

import type { SystemStatus } from "./api/systemStatus";

export function isStructuredSubmissionAllowed(status: SystemStatus): boolean {
  if (status.state === "checking" || status.state === "unavailable") return false;
  if (
    status.state === "degraded" &&
    status.readiness?.dependencies.postgresql.status === "unavailable"
  ) {
    return false;
  }
  return true;
}

export function structuredSubmissionBlockedReason(status: SystemStatus): string | null {
  if (status.state === "checking") {
    return "Checking CareFlow backend availability…";
  }
  if (status.state === "unavailable") {
    return "CareFlow backend is currently unavailable.";
  }
  if (
    status.state === "degraded" &&
    status.readiness?.dependencies.postgresql.status === "unavailable"
  ) {
    return "Structured data is temporarily unavailable because the database cannot be reached.";
  }
  return null;
}
