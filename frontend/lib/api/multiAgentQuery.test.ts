import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runCombinedWorkflow, runMultiAgentWorkflow } from "./multiAgentQuery";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const POLICY_ONLY_OK = {
  request_id: "req-1",
  workflow: "policy_only",
  status: "ok",
  policy: {
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
  },
  structured: null,
  validation: { passed: true, issues: [] },
  final_summary: null,
  abstention_reason: null,
  error: null,
};

const STRUCTURED_ONLY_OK = {
  request_id: "req-2",
  workflow: "structured_only",
  status: "ok",
  policy: null,
  structured: {
    route: "synpuf",
    results: [
      {
        tool: "get_beneficiary_summary",
        success: true,
        source_dataset: "cms_desynpuf",
        data: { beneficiary_id: "00013D2EFD8E45D1" },
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
};

const COMBINED_FHIR_OK = {
  request_id: "req-3",
  workflow: "policy_and_structured",
  status: "ok",
  policy: POLICY_ONLY_OK.policy,
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
};

const COMBINED_SYNPUF_OK = {
  ...COMBINED_FHIR_OK,
  request_id: "req-4",
  structured: STRUCTURED_ONLY_OK.structured,
};

const ABSTAIN_RESPONSE = {
  request_id: "req-5",
  workflow: "abstain",
  status: "abstained",
  policy: null,
  structured: null,
  validation: { passed: true, issues: [] },
  final_summary: null,
  abstention_reason: "unsupported_request",
  error: null,
};

const VALIDATOR_ISSUE_RESPONSE = {
  request_id: "req-6",
  workflow: "policy_and_structured",
  status: "error",
  policy: POLICY_ONLY_OK.policy,
  structured: {
    route: "fhir",
    results: [
      {
        tool: "get_patient_summary",
        success: false,
        source_dataset: "cms_desynpuf",
        data: null,
        record_count: null,
        error: null,
        abstention_reason: null,
      },
    ],
  },
  validation: {
    passed: false,
    issues: [{ code: "source_mismatch", detail: "expected synthea_fhir, got cms_desynpuf" }],
  },
  final_summary: null,
  abstention_reason: null,
  error: "validation_failed",
};

const PARTIAL_FAILURE_RESPONSE = {
  request_id: "req-7",
  workflow: "policy_and_structured",
  status: "ok",
  policy: POLICY_ONLY_OK.policy,
  structured: {
    route: "fhir",
    results: [
      {
        tool: "get_patient_summary",
        success: false,
        source_dataset: null,
        data: null,
        record_count: null,
        error: null,
        abstention_reason: "unknown_patient",
      },
    ],
  },
  validation: { passed: true, issues: [] },
  final_summary: null,
  abstention_reason: null,
  error: null,
};

describe("runMultiAgentWorkflow", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns kind=ok for a valid policy_only request", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(POLICY_ONLY_OK, { requestId: "req-1" }));
    const outcome = await runMultiAgentWorkflow({
      question: "x",
      workflow: "policy_only",
      policy_question: "Does Medicare cover hospital beds?",
    });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.workflow).toBe("policy_only");
      expect(outcome.response.structured).toBeNull();
      expect(outcome.requestId).toBe("req-1");
    }
  });

  it("returns kind=ok for a valid structured_only request", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(STRUCTURED_ONLY_OK));
    const outcome = await runMultiAgentWorkflow({
      question: "x",
      workflow: "structured_only",
      structured_route: "synpuf",
      tools: [{ tool: "get_beneficiary_summary", arguments: { beneficiary_id: "00013D2EFD8E45D1" } }],
    });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.workflow).toBe("structured_only");
      expect(outcome.response.policy).toBeNull();
    }
  });

  it("returns kind=ok for a valid policy_and_structured FHIR request", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(COMBINED_FHIR_OK));
    const outcome = await runCombinedWorkflow({
      policyQuestion: "What does Medicare say about hospital beds?",
      structuredRoute: "fhir",
      tool: "get_patient_summary",
      toolArguments: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" },
    });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.workflow).toBe("policy_and_structured");
      expect(outcome.response.policy).not.toBeNull();
      expect(outcome.response.structured?.route).toBe("fhir");
    }
  });

  it("returns kind=ok for a valid policy_and_structured SynPUF request", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(COMBINED_SYNPUF_OK));
    const outcome = await runCombinedWorkflow({
      policyQuestion: "What does Medicare say about hospital beds?",
      structuredRoute: "synpuf",
      tool: "get_beneficiary_summary",
      toolArguments: { beneficiary_id: "00013D2EFD8E45D1" },
    });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.structured?.route).toBe("synpuf");
    }
  });

  it("sends workflow=policy_and_structured with exactly one structured tool request and matching policy_question", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(COMBINED_FHIR_OK));
    await runCombinedWorkflow({
      policyQuestion: "What does Medicare say about hospital beds?",
      structuredRoute: "fhir",
      tool: "get_patient_summary",
      toolArguments: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" },
    });
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      question: "What does Medicare say about hospital beds?",
      workflow: "policy_and_structured",
      policy_question: "What does Medicare say about hospital beds?",
      structured_route: "fhir",
      tools: [{ tool: "get_patient_summary", arguments: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" } }],
    });
  });

  it("returns kind=ok with workflow=abstain for an abstention (not a client-level error)", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(ABSTAIN_RESPONSE));
    const outcome = await runMultiAgentWorkflow({ question: "what is the weather" });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.workflow).toBe("abstain");
      expect(outcome.response.abstention_reason).toBe("unsupported_request");
    }
  });

  it("returns kind=ok with status=error and validation issues for a validator failure (not a client-level error)", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(VALIDATOR_ISSUE_RESPONSE));
    const outcome = await runCombinedWorkflow({
      policyQuestion: "x",
      structuredRoute: "fhir",
      tool: "get_patient_summary",
      toolArguments: { patient_id: "x" },
    });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.status).toBe("error");
      expect(outcome.response.validation?.passed).toBe(false);
      expect(outcome.response.validation?.issues[0].code).toBe("source_mismatch");
    }
  });

  it("returns kind=ok preserving a partial specialist failure (policy ok, structured abstained)", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(PARTIAL_FAILURE_RESPONSE));
    const outcome = await runCombinedWorkflow({
      policyQuestion: "x",
      structuredRoute: "fhir",
      tool: "get_patient_summary",
      toolArguments: { patient_id: "nonexistent" },
    });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.status).toBe("ok");
      expect(outcome.response.policy?.answer).toBeTruthy();
      expect(outcome.response.structured?.results[0].success).toBe(false);
      expect(outcome.response.structured?.results[0].abstention_reason).toBe("unknown_patient");
    }
  });

  it("maps a network failure to category=network", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await runMultiAgentWorkflow({ question: "x" });
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
    const pending = runMultiAgentWorkflow({ question: "x" });
    const assertion = expect(pending).resolves.toMatchObject({ kind: "error", category: "timeout" });
    await vi.advanceTimersByTimeAsync(31_000);
    await assertion;
    vi.useRealTimers();
  });

  it("maps retrieval_unavailable to category=retrieval_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "retrieval_unavailable" } }, { status: 503 }),
    );
    const outcome = await runMultiAgentWorkflow({ question: "x" });
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("retrieval_unavailable");
  });

  it("maps multi_agent_unavailable to category=workflow_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "multi_agent_unavailable" } }, { status: 503 }),
    );
    const outcome = await runMultiAgentWorkflow({ question: "x" });
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("workflow_unavailable");
  });

  it("extracts the request ID from a successful response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(POLICY_ONLY_OK, { requestId: "req-xyz" }));
    const outcome = await runMultiAgentWorkflow({ question: "x" });
    expect(outcome.requestId).toBe("req-xyz");
  });
});
