/**
 * Typed helpers for Phase 11's review persistence endpoints -- GET
 * /reviews, GET /reviews/{review_id}, POST /reviews/{review_id}/decision.
 * Built on the same apiGet/apiPost/ApiResponse this whole frontend already
 * uses; no second fetch abstraction. Preserves X-Request-ID via the same
 * `requestId` field every other outcome type in this codebase already
 * carries.
 */

import { apiGet, apiPost } from "./client";
import { ApiClientError } from "./errors";
import type {
  ReviewCase,
  ReviewConflictBody,
  ReviewDecisionRequest,
  ReviewDetail,
  ReviewErrorBody,
  ReviewQueuePage,
  ReviewStatus,
} from "./reviewTypes";

export type ReviewApiErrorCategory = "network" | "timeout" | "not_found" | "invalid" | "unexpected";

function isReviewErrorBody(value: unknown): value is ReviewErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  );
}

function categorizeClientError(err: ApiClientError): ReviewApiErrorCategory {
  if (err.category === "network") return "network";
  if (err.category === "timeout") return "timeout";
  return "unexpected";
}

// --- GET /reviews ------------------------------------------------------

export interface ReviewQueueParams {
  status?: ReviewStatus;
  limit?: number;
  cursor?: string;
}

export type ReviewQueueOutcome =
  | { kind: "ok"; page: ReviewQueuePage; requestId: string | null }
  | { kind: "error"; category: ReviewApiErrorCategory; requestId: string | null };

export async function getReviewQueue(
  params: ReviewQueueParams = {},
  signal?: AbortSignal,
): Promise<ReviewQueueOutcome> {
  const query = new URLSearchParams();
  if (params.status) query.set("status", params.status);
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.cursor) query.set("cursor", params.cursor);
  const queryString = query.toString();
  const path = queryString ? `/reviews?${queryString}` : "/reviews";

  try {
    const result = await apiGet<ReviewQueuePage>(path, { signal });
    if (!result.ok) {
      return { kind: "error", category: "unexpected", requestId: result.requestId };
    }
    return { kind: "ok", page: result.data, requestId: result.requestId };
  } catch (err) {
    if (err instanceof ApiClientError) {
      return { kind: "error", category: categorizeClientError(err), requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}

// --- GET /reviews/{review_id} -------------------------------------------

export type ReviewDetailOutcome =
  | { kind: "ok"; detail: ReviewDetail; requestId: string | null }
  | { kind: "not_found"; requestId: string | null }
  | { kind: "error"; category: ReviewApiErrorCategory; requestId: string | null };

export async function getReviewDetail(reviewId: string, signal?: AbortSignal): Promise<ReviewDetailOutcome> {
  try {
    const result = await apiGet<ReviewDetail | ReviewErrorBody>(`/reviews/${encodeURIComponent(reviewId)}`, {
      signal,
    });
    if (result.status === 404) {
      return { kind: "not_found", requestId: result.requestId };
    }
    if (!result.ok || isReviewErrorBody(result.data)) {
      const code = isReviewErrorBody(result.data) ? result.data.error.code : null;
      return {
        kind: "error",
        category: code === "malformed_review_id" ? "invalid" : "unexpected",
        requestId: result.requestId,
      };
    }
    return { kind: "ok", detail: result.data, requestId: result.requestId };
  } catch (err) {
    if (err instanceof ApiClientError) {
      return { kind: "error", category: categorizeClientError(err), requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}

// --- POST /reviews/{review_id}/decision ----------------------------------

export type ReviewDecisionOutcome =
  | { kind: "ok"; case: ReviewCase; requestId: string | null }
  | { kind: "not_found"; requestId: string | null }
  | { kind: "conflict"; current: ReviewCase; requestId: string | null }
  | { kind: "error"; category: ReviewApiErrorCategory; requestId: string | null };

function isReviewConflictBody(value: unknown): value is ReviewConflictBody {
  return isReviewErrorBody(value) && "review" in value;
}

export async function decideReview(
  reviewId: string,
  request: ReviewDecisionRequest,
  signal?: AbortSignal,
): Promise<ReviewDecisionOutcome> {
  try {
    const result = await apiPost<ReviewCase | ReviewConflictBody | ReviewErrorBody>(
      `/reviews/${encodeURIComponent(reviewId)}/decision`,
      request,
      { signal },
    );
    if (result.status === 404) {
      return { kind: "not_found", requestId: result.requestId };
    }
    if (result.status === 409 && isReviewConflictBody(result.data)) {
      return { kind: "conflict", current: result.data.review, requestId: result.requestId };
    }
    if (!result.ok || isReviewErrorBody(result.data)) {
      const code = isReviewErrorBody(result.data) ? result.data.error.code : null;
      return {
        kind: "error",
        category: code === "malformed_review_id" ? "invalid" : "unexpected",
        requestId: result.requestId,
      };
    }
    return { kind: "ok", case: result.data, requestId: result.requestId };
  } catch (err) {
    if (err instanceof ApiClientError) {
      return { kind: "error", category: categorizeClientError(err), requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}
