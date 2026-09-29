/**
 * Whether the Analytics page's structured-aggregates panel should attempt
 * to load, derived from Slice 1's SystemStatus.
 *
 * Postgres-only, the same rule as lib/reviewReadiness.ts and
 * lib/structuredReadiness.ts: GET /analytics/structured/overview
 * (backend/app/api/analytics.py) goes straight to
 * app.repository.analytics's parameterized Postgres queries -- it never
 * touches Qdrant or Redis. Redis is never considered, consistent with the
 * rest of this project.
 */

import type { SystemStatus } from "./api/systemStatus";

export function isStructuredAnalyticsAllowed(status: SystemStatus): boolean {
  if (status.state === "checking" || status.state === "unavailable") return false;
  if (status.state === "degraded" && status.readiness?.dependencies.postgresql.status === "unavailable") {
    return false;
  }
  return true;
}

export function structuredAnalyticsBlockedReason(status: SystemStatus): string | null {
  if (status.state === "checking") {
    return "Checking CareFlow backend availability…";
  }
  if (status.state === "unavailable") {
    return "CareFlow backend is currently unavailable.";
  }
  if (status.state === "degraded" && status.readiness?.dependencies.postgresql.status === "unavailable") {
    return "Structured analytics are temporarily unavailable because the database cannot be reached.";
  }
  return null;
}
