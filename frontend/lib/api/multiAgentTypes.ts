/**
 * POST /multi-agent -- Phase 10's bounded multi-agent workflow (Phase 14
 * Slice 5). Derived directly from backend/app/agents/models.py and
 * backend/app/agents/graph.py::build_response -- re-audited from current
 * source, not assumed from Slice 4's /orchestrate contract, since this is a
 * genuinely different endpoint with a different response shape.
 *
 * Route/Status/AbstentionReason are reused from ./orchestrationTypes
 * (themselves Phase 9 types) rather than redefined here -- the backend does
 * exactly the same thing (`from app.orchestration.models import
 * AbstentionReason, Route, Status`), so duplicating them here would risk
 * silent drift from a single shared vocabulary.
 */

import type { Citation } from "./types";
import type { AbstentionReason, OrchestrationStatus, Route } from "./orchestrationTypes";

// backend/app/agents/models.py::WorkflowDecision
export type WorkflowDecision = "policy_only" | "structured_only" | "policy_and_structured" | "abstain";

// backend/app/agents/models.py::ValidationIssueCode -- the full enum. Some
// values (e.g. cross_dataset_identity_violation) are not currently
// reachable through this page's own request construction (see
// docs/phase14_frontend_design.md's Slice 5 "Dataset boundary" section for
// why), but are still mapped defensively since they are part of the real
// contract.
export type ValidationIssueCode =
  | "missing_policy_result"
  | "missing_policy_citations"
  | "missing_structured_result"
  | "source_mismatch"
  | "specialist_failure"
  | "cross_dataset_identity_violation"
  | "workflow_result_mismatch";

export interface ValidationIssue {
  code: ValidationIssueCode;
  detail: string;
}

export interface ValidationResult {
  passed: boolean;
  issues: ValidationIssue[];
}

// backend/app/agents/models.py::MAX_STRUCTURED_TOOL_CALLS -- the backend
// rejects a `tools` array longer than this with a 422, rather than
// truncating it. This page only ever sends one.
export const MAX_STRUCTURED_TOOL_CALLS = 5;

export interface StructuredToolRequest {
  tool: string;
  arguments: Record<string, unknown>;
}

export interface MultiAgentRequest {
  question: string;
  workflow?: WorkflowDecision;
  policy_question?: string;
  structured_route?: Route;
  tools?: StructuredToolRequest[];
}

/** The `policy` field of MultiAgentResponse -- exactly Phase 9's RAGAnswer
 * shape plus a top-level `status`, per
 * backend/app/agents/graph.py::policy_node's
 * `{"status": ..., "abstention_reason": ..., **policy_result}` merge, where
 * policy_result is `RAGAnswer.model_dump()`. Within a 200 response this
 * `status` can only be "ok" or "abstained" -- a genuine retrieval/provider
 * failure (GenerationError) never reaches this shape; it surfaces as an
 * HTTP-level error instead (see MultiAgentErrorCategory below). */
export interface MultiAgentPolicyResult {
  status: OrchestrationStatus;
  abstention_reason: AbstentionReason | null;
  answer: string;
  citations: Citation[];
  insufficient_evidence: boolean;
  retrieved_chunk_ids: string[];
  model_provider: string;
  model_name: string;
  prompt_version: string;
}

/** One attempted structured tool call's outcome --
 * backend/app/agents/structured_specialist.py's per-item shape. A failed
 * or abstained attempt is never dropped from the array -- it is preserved
 * with success=false and either abstention_reason or error set. */
export interface StructuredSpecialistResult {
  tool: string | null;
  success: boolean;
  source_dataset: string | null;
  data: unknown;
  record_count: number | null;
  error: string | null;
  abstention_reason: AbstentionReason | null;
}

export interface MultiAgentStructured {
  route: Route | null;
  results: StructuredSpecialistResult[];
}

export interface MultiAgentResponse {
  request_id: string;
  workflow: WorkflowDecision;
  status: OrchestrationStatus;
  policy: MultiAgentPolicyResult | null;
  structured: MultiAgentStructured | null;
  validation: ValidationResult | null;
  final_summary: string | null;
  abstention_reason: AbstentionReason | null;
  error: string | null;
}

/** backend/app/api/multi_agent.py's own error bodies: a GenerationError
 * (retrieval/provider failure on the policy path, propagated with its own
 * status code) or the generic infrastructure-failure fallback
 * (`multi_agent_unavailable`, always 503 -- e.g. Postgres unreachable for
 * the structured path). Both share the same `{error: {code}}` shape. */
export interface MultiAgentErrorBody {
  error: {
    code: string;
  };
}
