/**
 * Types mirroring backend/app/services/health.py's Pydantic response
 * models exactly (Phase 13, unchanged by this slice) -- see
 * docs/phase14_frontend_design.md's "Backend API audit" for how these were
 * derived from the current FastAPI routes, not invented.
 */

export interface DependencyHealth {
  status: "ok" | "unavailable";
}

/** GET /live -- backend/app/services/health.py::LivenessResponse */
export interface LivenessResponse {
  status: "alive";
  service: string;
}

/** GET /ready -- backend/app/services/health.py::ReadinessResponse */
export interface ReadinessResponse {
  status: "ready" | "unready";
  service: string;
  version: string;
  dependencies: {
    postgresql: DependencyHealth;
    qdrant: DependencyHealth;
    redis: DependencyHealth;
  };
}

/**
 * POST /query -- backend/app/generation/models.py (Phase 14 Slice 2).
 * Derived directly from the Pydantic models, not inferred from prior docs:
 *   QueryRequest(StrictModel): question: str (1-4000 chars; blank/
 *     whitespace-only rejected server-side; server also trims it).
 *   Citation(StrictModel): document_id, document_version, chunk_id: str;
 *     title, section, source: str | None.
 *   RAGAnswer(StrictModel): answer, model_provider, model_name,
 *     prompt_version: str; citations: Citation[]; insufficient_evidence:
 *     bool; retrieved_chunk_ids: str[]; abstention_reason: str | None.
 *
 * Note: Citation has NO separate excerpt/quote field. The evidence text
 * the backend actually quoted is embedded directly inside `answer` itself
 * (RAGService.answer() joins "CMS evidence [chunk_id]:\n<quote>" blocks) --
 * see docs/phase14_frontend_design.md's "/query contract" section for why
 * the UI renders `answer` verbatim rather than inventing a per-citation
 * excerpt field that does not exist in the schema.
 */

export const QUESTION_MAX_LENGTH = 4000;

export interface QueryRequest {
  question: string;
}

export interface Citation {
  document_id: string;
  document_version: string;
  title: string | null;
  section: string | null;
  chunk_id: string;
  source: string | null;
}

export interface RAGAnswer {
  answer: string;
  citations: Citation[];
  insufficient_evidence: boolean;
  retrieved_chunk_ids: string[];
  model_provider: string;
  model_name: string;
  prompt_version: string;
  abstention_reason: string | null;
}

/** The JSON body backend/app/api/query.py returns for a GenerationError
 * (502/503/504) -- distinct from FastAPI's own request-validation error
 * shape, which the frontend should never trigger since it validates
 * length/blankness client-side before ever calling the API. */
export interface QueryErrorBody {
  error: {
    code: string;
  };
}
