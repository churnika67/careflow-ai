/**
 * Whether Evidence Workflow's combined-request submission should be
 * allowed, derived from Slice 1's SystemStatus.
 *
 * Deliberately NOT a reuse of Slice 4's permissive lib/assistantReadiness.ts
 * policy. That page allows any degraded state because its eventual route
 * is unknown until the backend classifies the question -- gating on one
 * dependency would incorrectly block requests the *other* dependency could
 * still serve. This page is different: every submission is always BOTH a
 * policy request (backend/app/agents/graph.py::policy_node -> Phase 9's
 * call_policy() -> Qdrant retrieval) AND a structured request
 * (backend/app/agents/structured_specialist.py -> db/connection.py ->
 * Postgres) in the same call, every time -- so either dependency being
 * down would make the *whole* combined request fail, not just half of it.
 * Blocking proactively on either one avoids surfacing that as a raw
 * GenerationError/multi_agent_unavailable HTTP error.
 *
 * Redis is never considered, consistent with the rest of the project
 * (backend/app/services/health.py::check_readiness() never lets a Redis
 * failure affect ReadinessResponse.status).
 */

import type { SystemStatus } from "./api/systemStatus";

export function isWorkflowSubmissionAllowed(status: SystemStatus): boolean {
  if (status.state === "checking" || status.state === "unavailable") return false;
  if (status.state === "degraded") {
    if (status.readiness?.dependencies.qdrant.status === "unavailable") return false;
    if (status.readiness?.dependencies.postgresql.status === "unavailable") return false;
  }
  return true;
}

export function workflowSubmissionBlockedReason(status: SystemStatus): string | null {
  if (status.state === "checking") {
    return "Checking CareFlow backend availability…";
  }
  if (status.state === "unavailable") {
    return "CareFlow backend is currently unavailable.";
  }
  if (status.state === "degraded") {
    const qdrantDown = status.readiness?.dependencies.qdrant.status === "unavailable";
    const postgresDown = status.readiness?.dependencies.postgresql.status === "unavailable";
    if (qdrantDown && postgresDown) {
      return "Evidence workflows are temporarily unavailable because both the policy search index and the database cannot be reached.";
    }
    if (qdrantDown) {
      return "Evidence workflows are temporarily unavailable because the policy search index cannot be reached.";
    }
    if (postgresDown) {
      return "Evidence workflows are temporarily unavailable because the database cannot be reached.";
    }
  }
  return null;
}
