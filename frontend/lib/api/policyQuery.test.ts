import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryPolicy } from "./policyQuery";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const SUPPORTED_ANSWER = {
  answer:
    "CMS evidence [d9eb65be-cab7-5ee4-9fdb-d94e370fd15b]:\nA. General Requirements for Coverage of Hospital Beds\n\nA physician's prescription...",
  citations: [
    {
      document_id: "227",
      document_version: "1",
      title: "Hospital Beds",
      section: "A. General Requirements for Coverage of Hospital Beds",
      chunk_id: "d9eb65be-cab7-5ee4-9fdb-d94e370fd15b",
      source: "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDId=227&NCDver=1",
    },
  ],
  insufficient_evidence: false,
  retrieved_chunk_ids: ["d9eb65be-cab7-5ee4-9fdb-d94e370fd15b"],
  model_provider: "deterministic",
  model_name: "first-evidence-v1",
  prompt_version: "cms-extractive-v1",
  abstention_reason: null,
};

const ABSTAINED_ANSWER = {
  answer: "Insufficient evidence.",
  citations: [],
  insufficient_evidence: true,
  retrieved_chunk_ids: ["a", "b"],
  model_provider: "deterministic",
  model_name: "first-evidence-v1",
  prompt_version: "cms-extractive-v1",
  abstention_reason: "no_eligible_evidence",
};

describe("queryPolicy", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns kind=answered for a supported response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SUPPORTED_ANSWER, { requestId: "req-1" }));
    const outcome = await queryPolicy("Does Medicare cover hospital beds?");
    expect(outcome.kind).toBe("answered");
    if (outcome.kind === "answered") {
      expect(outcome.answer.citations).toHaveLength(1);
      expect(outcome.requestId).toBe("req-1");
    }
  });

  it("returns kind=abstained for insufficient_evidence=true, never answered", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(ABSTAINED_ANSWER));
    const outcome = await queryPolicy("What dental implant documentation is required?");
    expect(outcome.kind).toBe("abstained");
    if (outcome.kind === "abstained") {
      expect(outcome.answer.citations).toHaveLength(0);
      expect(outcome.answer.abstention_reason).toBe("no_eligible_evidence");
    }
  });

  it("maps a retrieval_unavailable GenerationError to category=retrieval_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "retrieval_unavailable" } }, { status: 503, requestId: "req-2" }),
    );
    const outcome = await queryPolicy("x");
    expect(outcome).toEqual({ kind: "error", category: "retrieval_unavailable", requestId: "req-2" });
  });

  it("maps a provider_unavailable GenerationError to category=generation_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "provider_unavailable" } }, { status: 502 }),
    );
    const outcome = await queryPolicy("x");
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("generation_unavailable");
  });

  it("maps a provider_timeout GenerationError to category=timeout", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "provider_timeout" } }, { status: 504 }),
    );
    const outcome = await queryPolicy("x");
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("timeout");
  });

  it("maps an unrecognized error code to category=unexpected rather than guessing", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "some_future_code" } }, { status: 500 }),
    );
    const outcome = await queryPolicy("x");
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("unexpected");
  });

  it("maps a malformed/unexpected error body shape to category=unexpected without throwing", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ detail: [{ msg: "some fastapi validation shape" }] }, { status: 422 }),
    );
    const outcome = await queryPolicy("x");
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("unexpected");
  });

  it("maps a network failure to category=network", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await queryPolicy("x");
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
    const pending = queryPolicy("x");
    const assertion = expect(pending).resolves.toMatchObject({ kind: "error", category: "timeout" });
    await vi.advanceTimersByTimeAsync(6000);
    await assertion;
    vi.useRealTimers();
  });

  it("sends the question exactly as given, with no transformation", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SUPPORTED_ANSWER));
    const question = "  Does Medicare cover hospital beds?  ";
    await queryPolicy(question);
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ question });
  });

  it("extracts the request ID from a successful response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SUPPORTED_ANSWER, { requestId: "req-xyz" }));
    const outcome = await queryPolicy("x");
    expect(outcome.requestId).toBe("req-xyz");
  });
});
