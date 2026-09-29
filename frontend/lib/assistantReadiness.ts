/**
 * Whether CareFlow Assistant's submission should be allowed, derived from
 * Slice 1's SystemStatus. Deliberately different from both
 * lib/policyReadiness.ts (blocks on Qdrant-down) and
 * lib/structuredReadiness.ts (blocks on Postgres-down): this page's router
 * can resolve to EITHER the policy path (needs Qdrant) OR a structured path
 * (needs Postgres) depending on the question itself, which is not known
 * until the backend classifies it. Blocking submission on any single
 * dependency being down would incorrectly prevent requests the *other*
 * dependency could still serve.
 *
 * So: allowed whenever the API process itself is reachable (`ready` or
 * `degraded`, regardless of which dependency is degraded) -- blocked only
 * while `checking` or fully `unavailable`. Redis is never even considered
 * here, consistent with it never gating readiness anywhere in this
 * project. If the classifier picks a route whose one dependency actually
 * is down, the backend's own existing bounded failure (e.g.
 * `retrieval_unavailable`, `orchestration_unavailable`) surfaces normally
 * through lib/api/orchestrateQuery.ts -- this function does not try to
 * predict that in advance.
 */

import type { SystemStatus } from "./api/systemStatus";

export function isAssistantSubmissionAllowed(status: SystemStatus): boolean {
  return status.state !== "checking" && status.state !== "unavailable";
}

export function assistantSubmissionBlockedReason(status: SystemStatus): string | null {
  if (status.state === "checking") {
    return "Checking CareFlow backend availability…";
  }
  if (status.state === "unavailable") {
    return "CareFlow backend is currently unavailable.";
  }
  return null;
}
