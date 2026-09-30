import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runReviewableCombinedWorkflow, runReviewableQuery } from "./reviewableQuery";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const POLICY_RESULT = {
  status: "ok",
  abstention_reason: null,
  answer: "CMS evidence [chunk-1]:\nSome policy text.",
  citations: [
    {
      document_id: "227",
      document_version: "1",
      title: "Hospital Beds",
      section: "A",
      chunk_id: "chunk-1",
      source: "https://cms.gov/x",
    },
  ],
  insufficient_evidence: false,
  retrieved_chunk_ids: ["chunk-1"],
  model_provider: "deterministic",
  model_name: "first-evidence-v1",
  prompt_version: "cms-extractive-v1",
};

function noReviewOk() {
  return {
    request_id: "req-1",
    workflow: "policy_and_structured",
    status: "ok",
    policy: POLICY_RESULT,
    structured: {
      route: "fhir",
      results: [
        {
          tool: "get_patient_summary",
          success: true,
          source_dataset: "synthea_fhir",
          data: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" },
          record_count: 1,
          error: null,
          abstention_reason: null,
        },
      ],
    },
    validation: { passed: true, issues: [] },
    final_summary: null,
    abstention_reason: null,
    error: null,
    review_required: false,
    review_reason_codes: [],
    review_id: null,
    review_status: null,
  };
}

function reviewCreatedOk() {
  return {
    ...noReviewOk(),
    review_required: true,
    review_reason_codes: ["explicit_review_requested"],
    review_id: "review-abc-123",
    review_status: "pending",
  };
}

describe("runReviewableQuery / runReviewableCombinedWorkflow", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts to /reviewable-query with the exact combined-workflow request shape plus explicit_review_requested", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(noReviewOk()));
    await runReviewableCombinedWorkflow({
      policyQuestion: "What does Medicare say about hospital beds?",
      structuredRoute: "fhir",
      tool: "get_patient_summary",
      toolArguments: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" },
      explicitReviewRequested: false,
    });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/reviewable-query");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      question: "What does Medicare say about hospital beds?",
      workflow: "policy_and_structured",
      policy_question: "What does Medicare say about hospital beds?",
      structured_route: "fhir",
      tools: [{ tool: "get_patient_summary", arguments: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" } }],
      explicit_review_requested: false,
    });
  });

  it("returns kind=ok with review_required=false when no review is created", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(noReviewOk()));
    const outcome = await runReviewableQuery({ question: "x" });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.review_required).toBe(false);
      expect(outcome.response.review_id).toBeNull();
    }
  });

  it("returns kind=ok with review_required=true and a review_id when a review is created", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(reviewCreatedOk()));
    const outcome = await runReviewableQuery({ question: "x", explicit_review_requested: true });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.review_required).toBe(true);
      expect(outcome.response.review_id).toBe("review-abc-123");
      expect(outcome.response.review_status).toBe("pending");
      expect(outcome.response.review_reason_codes).toEqual(["explicit_review_requested"]);
    }
  });

  it("maps a network failure to category=network", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await runReviewableQuery({ question: "x" });
    expect(outcome).toEqual({ kind: "error", category: "network", requestId: null });
  });

  it("maps a client-side timeout to category=timeout", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          (init as RequestInit).signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        }),
    );
    const pending = runReviewableQuery({ question: "x" });
    const assertion = expect(pending).resolves.toMatchObject({ kind: "error", category: "timeout" });
    await vi.advanceTimersByTimeAsync(31_000);
    await assertion;
    vi.useRealTimers();
  });

  it("maps retrieval_unavailable to category=retrieval_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "retrieval_unavailable" } }, { status: 503 }),
    );
    const outcome = await runReviewableQuery({ question: "x" });
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("retrieval_unavailable");
  });

  it("maps reviewable_query_unavailable to category=workflow_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "reviewable_query_unavailable" } }, { status: 503 }),
    );
    const outcome = await runReviewableQuery({ question: "x" });
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("workflow_unavailable");
  });

  it("extracts the request ID from a successful response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(noReviewOk(), { requestId: "req-xyz" }));
    const outcome = await runReviewableQuery({ question: "x" });
    expect(outcome.requestId).toBe("req-xyz");
  });
});
