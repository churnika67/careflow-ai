/**
 * Ask CareFlow: POST /query -> a bounded PolicyQueryOutcome.
 *
 * The backend (backend/app/api/query.py, backend/app/generation/service.py,
 * inspected directly for this slice) returns:
 *   - 200 with RAGAnswer, insufficient_evidence=false  -> a real answer.
 *   - 200 with RAGAnswer, insufficient_evidence=true   -> abstention. This
 *     is NOT an error -- it is CareFlow correctly declining to answer
 *     without adequate evidence, and must never be presented as a
 *     successful policy answer nor as a negative coverage determination.
 *   - non-2xx with {"error": {"code": "..."}} (GenerationError) for a
 *     retrieval/generation-layer failure -- see backend/app/generation/
 *     providers.py and backend/app/generation/runtime.py for the full set
 *     of codes this slice maps below.
 *
 * This module's only job is that mapping; see components/AskCareFlow.tsx
 * for how each outcome is rendered.
 */

import { apiPost } from "./client";
import { ApiClientError } from "./errors";
import type { QueryErrorBody, RAGAnswer } from "./types";

export type PolicyErrorCategory =
  | "network"
  | "timeout"
  | "retrieval_unavailable"
  | "generation_unavailable"
  | "unexpected";

export type PolicyQueryOutcome =
  | { kind: "answered"; answer: RAGAnswer; requestId: string | null }
  | { kind: "abstained"; answer: RAGAnswer; requestId: string | null }
  | { kind: "error"; category: PolicyErrorCategory; requestId: string | null };

// backend/app/generation/runtime.py::retrieve()'s GenerationError codes.
const RETRIEVAL_CODES = new Set([
  "retrieval_unavailable",
  "reranking_unavailable",
  "rerank_query_too_long",
]);

// backend/app/generation/providers.py + generation/service.py's
// GenerationError codes for provider/model-output failures.
const GENERATION_CODES = new Set([
  "provider_not_configured",
  "provider_unavailable",
  "provider_incomplete",
  "malformed_provider_response",
  "malformed_model_output",
  "invalid_evidence_output",
]);

function isQueryErrorBody(value: unknown): value is QueryErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  );
}

function categorizeErrorResponse(data: unknown): PolicyErrorCategory {
  if (!isQueryErrorBody(data)) return "unexpected";
  const { code } = data.error;
  if (code === "provider_timeout") return "timeout";
  if (RETRIEVAL_CODES.has(code)) return "retrieval_unavailable";
  if (GENERATION_CODES.has(code)) return "generation_unavailable";
  return "unexpected";
}

function categorizeClientError(err: ApiClientError): PolicyErrorCategory {
  if (err.category === "network") return "network";
  if (err.category === "timeout") return "timeout";
  return "unexpected"; // invalid_response -- the backend sent something unparseable
}

export async function queryPolicy(
  question: string,
  signal?: AbortSignal,
): Promise<PolicyQueryOutcome> {
  try {
    const result = await apiPost<RAGAnswer | QueryErrorBody>("/query", { question }, { signal });
    if (result.ok) {
      const answer = result.data as RAGAnswer;
      return {
        kind: answer.insufficient_evidence ? "abstained" : "answered",
        answer,
        requestId: result.requestId,
      };
    }
    return {
      kind: "error",
      category: categorizeErrorResponse(result.data),
      requestId: result.requestId,
    };
  } catch (err) {
    if (err instanceof ApiClientError) {
      return { kind: "error", category: categorizeClientError(err), requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}
