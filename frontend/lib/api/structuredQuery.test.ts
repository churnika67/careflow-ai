import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryFhirTool, querySynpufTool } from "./structuredQuery";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const FHIR_PATIENT_SUMMARY_OK = {
  request_id: "req-1",
  route: "fhir",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_patient_summary",
  source_dataset: "synthea_fhir",
  record_count: 1,
  data: {
    patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713",
    family_name: "DuBuque211",
    given_name: "Adelaida985",
    birth_date: "1970-01-01",
    gender: "female",
    race_code: "2106-3",
    race_display: "White",
    ethnicity_code: "2186-5",
    ethnicity_display: "Not Hispanic or Latino",
    run_id: "run-1",
    source_bundle_sha256: "abc",
  },
};

const SYNPUF_BENEFICIARY_OK = {
  request_id: "req-2",
  route: "synpuf",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_beneficiary_summary",
  source_dataset: "cms_desynpuf",
  record_count: 1,
  data: { beneficiary_id: "00013D2EFD8E45D1", birth_date: "1923-05-01", sex_code: "1" },
};

const ABSTAINED_UNKNOWN_PATIENT = {
  request_id: "req-3",
  route: "fhir",
  status: "abstained",
  answer: null,
  citations: null,
  tool: "get_patient_summary",
  source_dataset: null,
  record_count: null,
  data: null,
  abstention_reason: "unknown_patient",
  error: null,
};

describe("queryFhirTool", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes the request with route=fhir and the given tool/arguments", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(FHIR_PATIENT_SUMMARY_OK));
    await queryFhirTool("get_patient_summary", { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/orchestrate");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({
      question: expect.any(String),
      route: "fhir",
      tool: "get_patient_summary",
      tool_arguments: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" },
    });
  });

  it("returns kind=ok with data/recordCount/tool/sourceDataset for a successful result", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(FHIR_PATIENT_SUMMARY_OK, { requestId: "req-1" }));
    const outcome = await queryFhirTool("get_patient_summary", { patient_id: "x" });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.recordCount).toBe(1);
      expect(outcome.tool).toBe("get_patient_summary");
      expect(outcome.sourceDataset).toBe("synthea_fhir");
      expect(outcome.requestId).toBe("req-1");
      expect((outcome.data as { patient_id: string }).patient_id).toBe(
        "31a2e8ec-69fc-8a71-3ab6-36cbdd508713",
      );
    }
  });

  it("returns kind=abstained with the real abstention reason for an unknown patient", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(ABSTAINED_UNKNOWN_PATIENT));
    const outcome = await queryFhirTool("get_patient_summary", { patient_id: "nonexistent" });
    expect(outcome).toEqual({ kind: "abstained", reason: "unknown_patient", requestId: null });
  });

  it("maps a network failure to category=network", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await queryFhirTool("get_patient_summary", { patient_id: "x" });
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
    const pending = queryFhirTool("get_patient_summary", { patient_id: "x" });
    const assertion = expect(pending).resolves.toMatchObject({ kind: "error", category: "timeout" });
    await vi.advanceTimersByTimeAsync(6000);
    await assertion;
    vi.useRealTimers();
  });

  it("maps an orchestration_unavailable GenerationError-shaped body to backend_unavailable", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "orchestration_unavailable" } }, { status: 503 }),
    );
    const outcome = await queryFhirTool("get_patient_summary", { patient_id: "x" });
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("backend_unavailable");
  });

  it("maps an unexpected/malformed response shape to category=unexpected without throwing", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ something: "else" }, { status: 200 }));
    const outcome = await queryFhirTool("get_patient_summary", { patient_id: "x" });
    expect(outcome.kind).toBe("error");
  });

  it("extracts the request ID from a successful response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(FHIR_PATIENT_SUMMARY_OK, { requestId: "req-xyz" }));
    const outcome = await queryFhirTool("get_patient_summary", { patient_id: "x" });
    expect(outcome.requestId).toBe("req-xyz");
  });
});

describe("querySynpufTool", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("serializes the request with route=synpuf and the given tool/arguments", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SYNPUF_BENEFICIARY_OK));
    await querySynpufTool("get_beneficiary_summary", { beneficiary_id: "00013D2EFD8E45D1" });
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.route).toBe("synpuf");
    expect(body.tool).toBe("get_beneficiary_summary");
    expect(body.tool_arguments).toEqual({ beneficiary_id: "00013D2EFD8E45D1" });
  });

  it("returns kind=ok for a successful beneficiary lookup", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SYNPUF_BENEFICIARY_OK));
    const outcome = await querySynpufTool("get_beneficiary_summary", { beneficiary_id: "x" });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") expect(outcome.sourceDataset).toBe("cms_desynpuf");
  });

  it("never sends a fhir identifier field for a synpuf call", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(SYNPUF_BENEFICIARY_OK));
    await querySynpufTool("get_beneficiary_summary", { beneficiary_id: "x" });
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.tool_arguments).not.toHaveProperty("patient_id");
  });
});
