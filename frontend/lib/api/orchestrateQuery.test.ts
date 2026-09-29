import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { orchestrateQuestion } from "./orchestrateQuery";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const POLICY_OK = {
  request_id: "req-1",
  route: "policy",
  status: "ok",
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
  tool: null,
  source_dataset: null,
  record_count: null,
  data: null,
  abstention_reason: null,
  error: null,
};

const FHIR_OK = {
  request_id: "req-2",
  route: "fhir",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_patient_summary",
  source_dataset: "synthea_fhir",
  record_count: 1,
  data: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" },
  abstention_reason: null,
  error: null,
};

const SYNPUF_OK = {
  request_id: "req-3",
  route: "synpuf",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_beneficiary_summary",
  source_dataset: "cms_desynpuf",
  record_count: 1,
  data: { beneficiary_id: "00013D2EFD8E45D1" },
  abstention_reason: null,
  error: null,
};

const ABSTAINED = {
  request_id: "req-4",
  route: "abstain",
  status: "abstained",
  answer: null,
  citations: null,
  tool: null,
  source_dataset: null,
  record_count: null,
  data: null,
  abstention_reason: "unsupported_request",
  error: null,
};

describe("orchestrateQuestion", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends only `question`, never route/tool", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(POLICY_OK));
    await orchestrateQuestion("What does Medicare say about hospital beds?");
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ question: "What does Medicare say about hospital beds?" });
  });

  it("returns kind=ok with route=policy for a policy response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(POLICY_OK, { requestId: "req-1" }));
    const outcome = await orchestrateQuestion("x");
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.route).toBe("policy");
      expect(outcome.response.status).toBe("ok");
      expect(outcome.requestId).toBe("req-1");
    }
  });

  it("returns kind=ok with route=fhir for a FHIR response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(FHIR_OK));
    const outcome = await orchestrateQuestion("x");
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.route).toBe("fhir");
      expect(outcome.response.tool).toBe("get_patient_summary");
    }
  });

  it("returns kind=ok with route=synpuf for a SynPUF response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SYNPUF_OK));
    const outcome = await orchestrateQuestion("x");
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.route).toBe("synpuf");
      expect(outcome.response.tool).toBe("get_beneficiary_summary");
    }
  });

  it("returns kind=ok with status=abstained for an abstention (not a client-level error)", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(ABSTAINED));
    const outcome = await orchestrateQuestion("x");
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.response.status).toBe("abstained");
      expect(outcome.response.abstention_reason).toBe("unsupported_request");
    }
  });

  it("maps a network failure to category=network", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await orchestrateQuestion("x");
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
    const pending = orchestrateQuestion("x");
    const assertion = expect(pending).resolves.toMatchObject({ kind: "error", category: "timeout" });
    await vi.advanceTimersByTimeAsync(6000);
    await assertion;
    vi.useRealTimers();
  });

  it("maps retrieval_unavailable to category=retrieval_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "retrieval_unavailable" } }, { status: 503 }),
    );
    const outcome = await orchestrateQuestion("x");
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("retrieval_unavailable");
  });

  it("maps orchestration_unavailable to category=orchestration_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "orchestration_unavailable" } }, { status: 503 }),
    );
    const outcome = await orchestrateQuestion("x");
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("orchestration_unavailable");
  });

  it("extracts the request ID from a successful response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(POLICY_OK, { requestId: "req-xyz" }));
    const outcome = await orchestrateQuestion("x");
    expect(outcome.requestId).toBe("req-xyz");
  });
});
