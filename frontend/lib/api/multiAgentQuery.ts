/**
 * CareFlow Evidence Workflow: POST /multi-agent with an explicit, typed
 * request -- workflow="policy_and_structured", an explicit policy_question,
 * an explicit structured_route, and exactly one explicit tool request.
 * Unlike Slice 4's /assistant (which deliberately sends `question` only to
 * exercise the free-text classifier), this page's whole point is a
 * deterministic, user-controlled request -- so the classifier
 * (supervisor_node's classify_workflow() fallback) is never exercised here
 * (see backend/app/agents/graph.py::supervisor_node: an explicit
 * `requested_workflow` is honored directly, never re-classified).
 *
 * `question` is still required by MultiAgentRequest's schema (min_length=1)
 * even when policy_question is also supplied -- the graph only falls back
 * to `question` for the policy branch when policy_question is absent (see
 * backend/app/agents/graph.py::policy_node), so its content is inert for
 * every request this page constructs. Rather than a meaningless
 * placeholder (Slice 3's structuredQuery.ts convention for a route where
 * `question` is truly never read), this module sends the same text as
 * policy_question, since a combined request always has one -- more
 * transparent in logs/debugging than an opaque filler string, and still
 * never logged in full server-side (backend/app/api/multi_agent.py's
 * `_log` only ever includes workflow/status/counts/reason codes).
 */

import { apiPost } from "./client";
import { ApiClientError } from "./errors";
import type {
  MultiAgentErrorBody,
  MultiAgentRequest,
  MultiAgentResponse,
  StructuredToolRequest,
} from "./multiAgentTypes";
import type { Route } from "./orchestrationTypes";

export type MultiAgentErrorCategory =
  | "network"
  | "timeout"
  | "retrieval_unavailable"
  | "workflow_unavailable"
  | "unexpected";

export type MultiAgentOutcome =
  | { kind: "ok"; response: MultiAgentResponse; requestId: string | null }
  | { kind: "error"; category: MultiAgentErrorCategory; requestId: string | null };

// backend/app/generation/runtime.py::retrieve()'s GenerationError codes --
// identical set to lib/api/policyQuery.ts's and
// lib/api/orchestrateQuery.ts's RETRIEVAL_CODES, since the policy branch of
// a combined workflow goes through the exact same retrieve() call.
const RETRIEVAL_CODES = new Set(["retrieval_unavailable", "reranking_unavailable", "rerank_query_too_long"]);

// backend/app/api/multi_agent.py's own generic-exception fallback
// (`multi_agent_unavailable`, e.g. Postgres unreachable for the structured
// branch), plus backend/app/generation/providers.py's provider-layer
// GenerationError codes (reachable via the policy branch).
const WORKFLOW_UNAVAILABLE_CODES = new Set([
  "multi_agent_unavailable",
  "provider_not_configured",
  "provider_unavailable",
  "provider_incomplete",
  "malformed_provider_response",
  "malformed_model_output",
  "invalid_evidence_output",
]);

function isMultiAgentErrorBody(value: unknown): value is MultiAgentErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error?: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  );
}

function categorizeErrorResponse(data: unknown): MultiAgentErrorCategory {
  if (!isMultiAgentErrorBody(data)) return "unexpected";
  const { code } = data.error;
  if (code === "provider_timeout") return "timeout";
  if (RETRIEVAL_CODES.has(code)) return "retrieval_unavailable";
  if (WORKFLOW_UNAVAILABLE_CODES.has(code)) return "workflow_unavailable";
  return "unexpected";
}

function categorizeClientError(err: ApiClientError): MultiAgentErrorCategory {
  if (err.category === "network") return "network";
  if (err.category === "timeout") return "timeout";
  return "unexpected"; // invalid_response -- the backend sent something unparseable
}

export interface CombinedWorkflowInput {
  policyQuestion: string;
  structuredRoute: Route;
  tool: string;
  toolArguments: Record<string, unknown>;
}

/** Constructs and sends the one request shape this page ever builds:
 * workflow="policy_and_structured" with exactly one structured tool call --
 * never FHIR+SynPUF together (structuredRoute is a single Route value, so
 * this is structurally impossible to misuse into a cross-dataset request;
 * see docs/phase14_frontend_design.md's Slice 5 "Dataset boundary"). */
export async function runCombinedWorkflow(
  input: CombinedWorkflowInput,
  signal?: AbortSignal,
): Promise<MultiAgentOutcome> {
  const tools: StructuredToolRequest[] = [{ tool: input.tool, arguments: input.toolArguments }];
  const request: MultiAgentRequest = {
    question: input.policyQuestion,
    workflow: "policy_and_structured",
    policy_question: input.policyQuestion,
    structured_route: input.structuredRoute,
    tools,
  };
  return runMultiAgentWorkflow(request, signal);
}

export async function runMultiAgentWorkflow(
  request: MultiAgentRequest,
  signal?: AbortSignal,
): Promise<MultiAgentOutcome> {
  try {
    const result = await apiPost<MultiAgentResponse | MultiAgentErrorBody>("/multi-agent", request, { signal });
    if (!result.ok) {
      return { kind: "error", category: categorizeErrorResponse(result.data), requestId: result.requestId };
    }
    if (isMultiAgentErrorBody(result.data)) {
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
