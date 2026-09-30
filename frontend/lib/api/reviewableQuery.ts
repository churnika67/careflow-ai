/**
 * CareFlow Evidence Workflow's "Request human review" path: POST
 * /reviewable-query with the same explicit, typed combined-workflow
 * request Slice 5's /workflow page already builds, plus
 * `explicit_review_requested`.
 *
 * Slice 6 integration decision (see docs/phase14_frontend_design.md's
 * Slice 6 "Reviewable workflow integration" section for the full
 * rationale): /workflow now always submits through this endpoint instead
 * of Slice 5's original POST /multi-agent, because /reviewable-query's
 * response is a strict superset of MultiAgentResponse (adding only
 * review_required/review_reason_codes/review_id/review_status) and is the
 * ONLY endpoint that can ever surface "a review case was automatically
 * created because validation found an issue" -- a real, always-on Phase 11
 * behavior (backend/app/review/policy.py::determine_review_requirement)
 * that Slice 5's original /multi-agent-only page could never make visible,
 * since /multi-agent itself never persists a review case. The "Request
 * human review" checkbox only controls `explicit_review_requested`; it
 * does not change which endpoint is used.
 */

import { apiPost, RAG_REQUEST_TIMEOUT_MS } from "./client";
import { ApiClientError } from "./errors";
import type { ReviewableQueryRequest, ReviewableQueryResponse, ReviewErrorBody } from "./reviewTypes";
import type { Route } from "./orchestrationTypes";

export type ReviewableQueryErrorCategory =
  | "network"
  | "timeout"
  | "retrieval_unavailable"
  | "workflow_unavailable"
  | "unexpected";

export type ReviewableQueryOutcome =
  | { kind: "ok"; response: ReviewableQueryResponse; requestId: string | null }
  | { kind: "error"; category: ReviewableQueryErrorCategory; requestId: string | null };

// Identical to lib/api/multiAgentQuery.ts's own code sets -- the policy
// branch goes through the exact same retrieve()/GenerationError path, and
// backend/app/api/reviews.py's own generic-exception fallback is
// "reviewable_query_unavailable" (the direct analog of /multi-agent's
// "multi_agent_unavailable").
const RETRIEVAL_CODES = new Set(["retrieval_unavailable", "reranking_unavailable", "rerank_query_too_long"]);
const WORKFLOW_UNAVAILABLE_CODES = new Set([
  "reviewable_query_unavailable",
  "provider_not_configured",
  "provider_unavailable",
  "provider_incomplete",
  "malformed_provider_response",
  "malformed_model_output",
  "invalid_evidence_output",
]);

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

function categorizeErrorResponse(data: unknown): ReviewableQueryErrorCategory {
  if (!isReviewErrorBody(data)) return "unexpected";
  const { code } = data.error;
  if (code === "provider_timeout") return "timeout";
  if (RETRIEVAL_CODES.has(code)) return "retrieval_unavailable";
  if (WORKFLOW_UNAVAILABLE_CODES.has(code)) return "workflow_unavailable";
  return "unexpected";
}

function categorizeClientError(err: ApiClientError): ReviewableQueryErrorCategory {
  if (err.category === "network") return "network";
  if (err.category === "timeout") return "timeout";
  return "unexpected";
}

export interface CombinedReviewableWorkflowInput {
  policyQuestion: string;
  structuredRoute: Route;
  tool: string;
  toolArguments: Record<string, unknown>;
  explicitReviewRequested: boolean;
}

/** Constructs the same single request shape Slice 5's runCombinedWorkflow()
 * built (workflow="policy_and_structured", one structured tool request --
 * never FHIR+SynPUF together), plus explicit_review_requested. */
export async function runReviewableCombinedWorkflow(
  input: CombinedReviewableWorkflowInput,
  signal?: AbortSignal,
): Promise<ReviewableQueryOutcome> {
  const request: ReviewableQueryRequest = {
    question: input.policyQuestion,
    workflow: "policy_and_structured",
    policy_question: input.policyQuestion,
    structured_route: input.structuredRoute,
    tools: [{ tool: input.tool, arguments: input.toolArguments }],
    explicit_review_requested: input.explicitReviewRequested,
  };
  return runReviewableQuery(request, signal);
}

export async function runReviewableQuery(
  request: ReviewableQueryRequest,
  signal?: AbortSignal,
): Promise<ReviewableQueryOutcome> {
  try {
    const result = await apiPost<ReviewableQueryResponse | ReviewErrorBody>("/reviewable-query", request, {
      signal,
      timeoutMs: RAG_REQUEST_TIMEOUT_MS,
    });
    if (!result.ok) {
      return { kind: "error", category: categorizeErrorResponse(result.data), requestId: result.requestId };
    }
    if (isReviewErrorBody(result.data)) {
      return { kind: "error", category: categorizeErrorResponse(result.data), requestId: result.requestId };
    }
    return { kind: "ok", response: result.data, requestId: result.requestId };
  } catch (err) {
    if (err instanceof ApiClientError) {
      return { kind: "error", category: categorizeClientError(err), requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}
