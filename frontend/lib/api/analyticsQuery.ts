/**
 * Typed helpers for Phase 15 Slice 1's two read-only analytics endpoints.
 * Same apiGet/ApiClientError foundation as every other query module in
 * this codebase -- no second fetch abstraction. Neither endpoint takes a
 * body or a path/query parameter that selects a file or experiment, so
 * these wrappers take no arguments beyond an optional AbortSignal.
 */

import { apiGet } from "./client";
import { ApiClientError } from "./errors";
import type {
  AnalyticsErrorBody,
  EvaluationSnapshotResponse,
  StructuredAnalyticsOverview,
} from "./analyticsTypes";

export type AnalyticsErrorCategory = "network" | "timeout" | "unavailable" | "unexpected";

function isAnalyticsErrorBody(value: unknown): value is AnalyticsErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  );
}

function categorizeClientError(err: ApiClientError): AnalyticsErrorCategory {
  if (err.category === "network") return "network";
  if (err.category === "timeout") return "timeout";
  return "unexpected";
}

export type EvaluationSnapshotOutcome =
  | { kind: "ok"; snapshot: EvaluationSnapshotResponse; requestId: string | null }
  | { kind: "error"; category: AnalyticsErrorCategory; requestId: string | null };

export async function getEvaluationSnapshot(signal?: AbortSignal): Promise<EvaluationSnapshotOutcome> {
  try {
    const result = await apiGet<EvaluationSnapshotResponse | AnalyticsErrorBody>(
      "/analytics/evaluation/snapshot",
      { signal },
    );
    if (result.status === 503) {
      return { kind: "error", category: "unavailable", requestId: result.requestId };
    }
    if (!result.ok || isAnalyticsErrorBody(result.data)) {
      return { kind: "error", category: "unexpected", requestId: result.requestId };
    }
    return { kind: "ok", snapshot: result.data, requestId: result.requestId };
  } catch (err) {
    if (err instanceof ApiClientError) {
      return { kind: "error", category: categorizeClientError(err), requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}

export type StructuredAnalyticsOutcome =
  | { kind: "ok"; overview: StructuredAnalyticsOverview; requestId: string | null }
  | { kind: "error"; category: AnalyticsErrorCategory; requestId: string | null };

export async function getStructuredAnalyticsOverview(
  signal?: AbortSignal,
): Promise<StructuredAnalyticsOutcome> {
  try {
    const result = await apiGet<StructuredAnalyticsOverview | AnalyticsErrorBody>(
      "/analytics/structured/overview",
      { signal },
    );
    if (result.status === 503) {
      return { kind: "error", category: "unavailable", requestId: result.requestId };
    }
    if (!result.ok || isAnalyticsErrorBody(result.data)) {
      return { kind: "error", category: "unexpected", requestId: result.requestId };
    }
    return { kind: "ok", overview: result.data, requestId: result.requestId };
  } catch (err) {
    if (err instanceof ApiClientError) {
      return { kind: "error", category: categorizeClientError(err), requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}
