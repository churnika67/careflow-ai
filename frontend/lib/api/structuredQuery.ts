/**
 * Structured data access for Patient Data (FHIR) and Claims (SynPUF):
 * POST /orchestrate with an explicit route + tool + tool_arguments. This
 * slice never relies on the free-text classifier -- the UI already knows
 * which dataset and tool the user selected (see
 * docs/phase14_frontend_design.md's "Route/tool strategy"), and always
 * sends that explicitly.
 *
 * `question` is required by OrchestrationRequest's schema (min_length=1)
 * but is not used for routing once route/tool are explicit -- a fixed
 * placeholder is sent, matching the exact convention backend's own
 * tests/test_orchestration_api.py already uses for structured-only calls.
 */

import { apiPost } from "./client";
import { ApiClientError } from "./errors";
import type {
  AbstentionReason,
  FhirToolName,
  OrchestrationErrorBody,
  OrchestrationRequest,
  OrchestrationResponse,
  Route,
  SourceDataset,
  SynpufToolName,
} from "./orchestrationTypes";

const STRUCTURED_QUESTION_PLACEHOLDER = "structured data request";

export type StructuredErrorCategory =
  | "network"
  | "timeout"
  | "backend_unavailable"
  | "unexpected";

export type StructuredQueryOutcome =
  | {
      kind: "ok";
      data: unknown;
      recordCount: number | null;
      tool: string | null;
      sourceDataset: SourceDataset | null;
      requestId: string | null;
    }
  | { kind: "abstained"; reason: AbstentionReason; requestId: string | null }
  | { kind: "error"; category: StructuredErrorCategory; requestId: string | null };

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

async function queryStructuredTool(
  route: Route,
  tool: FhirToolName | SynpufToolName,
  toolArguments: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<StructuredQueryOutcome> {
  const request: OrchestrationRequest = {
    question: STRUCTURED_QUESTION_PLACEHOLDER,
    route,
    tool,
    tool_arguments: toolArguments,
  };
  try {
    const result = await apiPost<OrchestrationResponse | OrchestrationErrorBody>(
      "/orchestrate",
      request,
      { signal },
    );
    if (!result.ok) {
      return { kind: "error", category: "backend_unavailable", requestId: result.requestId };
    }
    if (isOrchestrationErrorBody(result.data)) {
      // A GenerationError body reaching this branch would be unexpected for
      // a structured-only request (that error family belongs to the policy
      // path) -- treated conservatively as backend_unavailable rather than
      // guessed at.
      return { kind: "error", category: "backend_unavailable", requestId: result.requestId };
    }
    const response = result.data;
    if (response.status === "abstained") {
      return {
        kind: "abstained",
        reason: response.abstention_reason ?? "unsupported_request",
        requestId: result.requestId,
      };
    }
    if (response.status === "ok") {
      return {
        kind: "ok",
        data: response.data,
        recordCount: response.record_count,
        tool: response.tool,
        sourceDataset: response.source_dataset,
        requestId: result.requestId,
      };
    }
    return { kind: "error", category: "unexpected", requestId: result.requestId };
  } catch (err) {
    if (err instanceof ApiClientError) {
      const category: StructuredErrorCategory =
        err.category === "network" ? "network" : err.category === "timeout" ? "timeout" : "unexpected";
      return { kind: "error", category, requestId: err.requestId ?? null };
    }
    return { kind: "error", category: "unexpected", requestId: null };
  }
}

export function queryFhirTool(
  tool: FhirToolName,
  toolArguments: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<StructuredQueryOutcome> {
  return queryStructuredTool("fhir", tool, toolArguments, signal);
}

export function querySynpufTool(
  tool: SynpufToolName,
  toolArguments: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<StructuredQueryOutcome> {
  return queryStructuredTool("synpuf", tool, toolArguments, signal);
}
