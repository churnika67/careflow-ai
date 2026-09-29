/**
 * CareFlow Assistant: POST /orchestrate with `question` only -- the
 * backend's deterministic classifier (backend/app/orchestration/
 * classify.py) picks the route. This is deliberately the opposite of
 * lib/api/structuredQuery.ts, which always sends an explicit route/tool:
 * this page's entire purpose is to demonstrate the router itself (Phase
 * 14 Slice 4), so it must never short-circuit that by supplying route/tool.
 *
 * `OrchestrationResponse.status` already discriminates ok/abstained/error
 * for a normal 200 response -- unlike lib/api/policyQuery.ts, there is no
 * need for a separate "abstained" outcome kind here, since abstention is
 * just one more value of the same `status` field the caller already reads.
 */

import { apiPost } from "./client";
import { ApiClientError } from "./errors";
import type { OrchestrationErrorBody, OrchestrationRequest, OrchestrationResponse } from "./orchestrationTypes";

export type OrchestrateErrorCategory =
  | "network"
  | "timeout"
  | "orchestration_unavailable"
  | "retrieval_unavailable"
  | "unexpected";

export type OrchestrateOutcome =
  | { kind: "ok"; response: OrchestrationResponse; requestId: string | null }
  | { kind: "error"; category: OrchestrateErrorCategory; requestId: string | null };

// backend/app/generation/runtime.py::retrieve()'s GenerationError codes --
// identical set to lib/api/policyQuery.ts's RETRIEVAL_CODES, since
// route=policy goes through the exact same retrieve() call.
const RETRIEVAL_CODES = new Set([
  "retrieval_unavailable",
  "reranking_unavailable",
  "rerank_query_too_long",
]);

// backend/app/api/orchestrate.py's own generic-exception fallback, plus
// backend/app/generation/providers.py's provider-layer GenerationError
// codes (reachable via route=policy, the same as /query).
const ORCHESTRATION_UNAVAILABLE_CODES = new Set([
  "orchestration_unavailable",
  "provider_not_configured",
  "provider_unavailable",
  "provider_incomplete",
  "malformed_provider_response",
  "malformed_model_output",
  "invalid_evidence_output",
]);

function isOrchestrationErrorBody(value: unknown): value is OrchestrationErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  );
}

function categorizeErrorResponse(data: unknown): OrchestrateErrorCategory {
  if (!isOrchestrationErrorBody(data)) return "unexpected";
  const { code } = data.error;
  if (code === "provider_timeout") return "timeout";
  if (RETRIEVAL_CODES.has(code)) return "retrieval_unavailable";
  if (ORCHESTRATION_UNAVAILABLE_CODES.has(code)) return "orchestration_unavailable";
  return "unexpected";
}

function categorizeClientError(err: ApiClientError): OrchestrateErrorCategory {
  if (err.category === "network") return "network";
  if (err.category === "timeout") return "timeout";
  return "unexpected"; // invalid_response -- the backend sent something unparseable
}

export async function orchestrateQuestion(
  question: string,
  signal?: AbortSignal,
): Promise<OrchestrateOutcome> {
  const request: OrchestrationRequest = { question };
  try {
    const result = await apiPost<OrchestrationResponse | OrchestrationErrorBody>(
      "/orchestrate",
      request,
      { signal },
    );
    if (!result.ok) {
      return { kind: "error", category: categorizeErrorResponse(result.data), requestId: result.requestId };
    }
    if (isOrchestrationErrorBody(result.data)) {
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
