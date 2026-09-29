import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Assistant } from "./Assistant";
import { SystemStatusProvider } from "./SystemStatusProvider";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const LIVE_OK = { status: "alive", service: "careflow-ai" };

function readyPayload(overrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>) {
  return {
    status: "ready",
    service: "careflow-ai",
    version: "0.1.0",
    dependencies: {
      postgresql: { status: overrides?.postgresql ?? "ok" },
      qdrant: { status: overrides?.qdrant ?? "ok" },
      redis: { status: overrides?.redis ?? "ok" },
    },
  };
}

const POLICY_RESULT = {
  request_id: "req-policy",
  route: "policy",
  status: "ok",
  answer:
    "CMS evidence [d9eb65be-cab7-5ee4-9fdb-d94e370fd15b]:\nA. General Requirements for Coverage of Hospital Beds\n\nA physician's prescription is required.",
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
  tool: null,
  source_dataset: null,
  record_count: null,
  data: null,
  abstention_reason: null,
  error: null,
};

const FHIR_RESULT = {
  request_id: "req-fhir",
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
  abstention_reason: null,
  error: null,
};

const SYNPUF_RESULT = {
  request_id: "req-synpuf",
  route: "synpuf",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_beneficiary_summary",
  source_dataset: "cms_desynpuf",
  record_count: 1,
  data: {
    beneficiary_id: "00013D2EFD8E45D1",
    birth_date: "1923-05-01",
    death_date: null,
    sex_code: "2",
    race_code: "1",
    esrd_indicator: "0",
    state_code: "26",
    county_code: "570",
  },
  abstention_reason: null,
  error: null,
};

function abstainedResult(reason: string) {
  return {
    request_id: "req-abstain",
    route: "abstain",
    status: "abstained",
    answer: null,
    citations: null,
    tool: null,
    source_dataset: null,
    record_count: null,
    data: null,
    abstention_reason: reason,
    error: null,
  };
}

function setupFetchMock(options: {
  orchestrateResponse?: () => Response | Promise<Response>;
  readyOverrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>;
  liveFails?: boolean;
  readyState?: "checking" | "unready";
}) {
  const impl = vi.fn(async (url: string) => {
    const path = url.replace("http://localhost:8000", "");
    if (path === "/live") {
      if (options.liveFails) throw new TypeError("Failed to fetch");
      return jsonResponse(LIVE_OK);
    }
    if (path === "/ready") {
      const payload = readyPayload(options.readyOverrides);
      if (options.readyState === "unready") payload.status = "unready";
      return jsonResponse(payload);
    }
    if (path === "/orchestrate") {
      return options.orchestrateResponse ? options.orchestrateResponse() : jsonResponse(POLICY_RESULT);
    }
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

function renderAssistant() {
  return render(
    <SystemStatusProvider>
      <Assistant />
    </SystemStatusProvider>,
  );
}

async function waitForReady() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeEnabled());
}

async function submitQuestion(text: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Your request"), text);
  await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));
  return user;
}

describe("Assistant request shape", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends only the question field, never an explicit route/tool/tool_arguments", async () => {
    setupFetchMock({});
    renderAssistant();
    await waitForReady();
    await submitQuestion("What does Medicare say about hospital beds?");

    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/orchestrate"));
    expect(call).toBeDefined();
    const [, init] = call!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ question: "What does Medicare say about hospital beds?" });
  });
});

describe("Assistant policy routing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the CareFlow Routing panel and reuses the Slice 2 policy answer/citation rendering", async () => {
    setupFetchMock({ orchestrateResponse: () => jsonResponse(POLICY_RESULT) });
    renderAssistant();
    await waitForReady();
    await submitQuestion("What does Medicare say about hospital beds?");

    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
    expect(screen.getByText("CareFlow Routing")).toBeInTheDocument();
    expect(screen.getByText("Source: Medicare Policy")).toBeInTheDocument();
    // Reused from Slice 2's PolicyAnswer component -- same "Evidence"/citation
    // rendering, not a second implementation.
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText("Citation 1")).toBeInTheDocument();
    expect(screen.getByText("Hospital Beds")).toBeInTheDocument();
  });
});

describe("Assistant FHIR routing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the CareFlow Routing panel and reuses the Slice 3 structured rendering for a patient summary", async () => {
    setupFetchMock({ orchestrateResponse: () => jsonResponse(FHIR_RESULT) });
    renderAssistant();
    await waitForReady();
    await submitQuestion("Show me FHIR patient 31a2e8ec-69fc-8a71-3ab6-36cbdd508713");

    await waitFor(() => expect(screen.getByText("Adelaida985")).toBeInTheDocument());
    expect(screen.getByText("Source: Synthea FHIR · Synthetic")).toBeInTheDocument();
    expect(screen.getByText(/Patient Summary/)).toBeInTheDocument();
    expect(screen.getByText("(get_patient_summary)")).toBeInTheDocument();
    expect(screen.getByText("DuBuque211")).toBeInTheDocument();
    expect(screen.getByText("1970-01-01")).toBeInTheDocument();
    expect(screen.getByText("1 record")).toBeInTheDocument();
    expect(
      screen.getByText(/generated synthetic healthcare data and do not represent real patients/i),
    ).toBeInTheDocument();
  });
});

describe("Assistant SynPUF routing", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the CareFlow Routing panel and reuses the Slice 3 structured rendering for a beneficiary summary", async () => {
    setupFetchMock({ orchestrateResponse: () => jsonResponse(SYNPUF_RESULT) });
    renderAssistant();
    await waitForReady();
    await submitQuestion("Look up SynPUF beneficiary 00013D2EFD8E45D1");

    await waitFor(() => expect(screen.getByText("00013D2EFD8E45D1")).toBeInTheDocument());
    expect(screen.getByText("Source: CMS DE-SynPUF · Synthetic")).toBeInTheDocument();
    expect(screen.getByText(/Beneficiary Summary/)).toBeInTheDocument();
    expect(screen.getByText("(get_beneficiary_summary)")).toBeInTheDocument();
    expect(
      screen.getByText(/synthetic, de-identified demonstration claims data/i),
    ).toBeInTheDocument();
  });
});

describe("Assistant abstention", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a generic structured-abstention message for a missing required identifier", async () => {
    setupFetchMock({ orchestrateResponse: () => jsonResponse(abstainedResult("missing_required_identifier")) });
    renderAssistant();
    await waitForReady();
    await submitQuestion("Show me patient conditions");

    await waitFor(() =>
      expect(screen.getByText(/a synthetic identifier is required for this request/i)).toBeInTheDocument(),
    );
  });

  it("shows a generic structured-abstention message for an unsupported request", async () => {
    setupFetchMock({ orchestrateResponse: () => jsonResponse(abstainedResult("unsupported_request")) });
    renderAssistant();
    await waitForReady();
    await submitQuestion("What is the weather today?");

    await waitFor(() =>
      expect(screen.getByText(/careflow could not process this structured data request/i)).toBeInTheDocument(),
    );
  });

  it("shows the dedicated cross-dataset safety message and never attempts a join", async () => {
    setupFetchMock({
      orchestrateResponse: () =>
        jsonResponse(abstainedResult("cross_dataset_linkage_request")),
    });
    renderAssistant();
    await waitForReady();
    await submitQuestion(
      "Link FHIR patient 31a2e8ec-69fc-8a71-3ab6-36cbdd508713 to SynPUF beneficiary 00013D2EFD8E45D1",
    );

    await waitFor(() =>
      expect(
        screen.getByText(
          "CareFlow does not link identities across the synthetic FHIR and SynPUF datasets.",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText(/no synthetic patient was found/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/no synthetic beneficiary was found/i)).not.toBeInTheDocument();
  });

  it("shows the dedicated policy-abstention panel for a policy_abstained reason", async () => {
    setupFetchMock({ orchestrateResponse: () => jsonResponse(abstainedResult("policy_abstained")) });
    renderAssistant();
    await waitForReady();
    await submitQuestion("What does Medicare say about an extremely obscure procedure?");

    await waitFor(() =>
      expect(screen.getByText(/couldn.t find enough evidence in the indexed medicare policy documents/i)).toBeInTheDocument(),
    );
  });
});

describe("Assistant readiness matrix", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("blocks submission while the backend process is unreachable", async () => {
    setupFetchMock({ liveFails: true });
    renderAssistant();
    await waitFor(() => expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeDisabled());
    expect(screen.getByText(/currently unavailable/i)).toBeInTheDocument();
  });

  it("allows submission when only Redis is unavailable", async () => {
    setupFetchMock({ readyOverrides: { redis: "unavailable" } });
    renderAssistant();
    await waitForReady();
    expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeEnabled();
  });

  it("allows submission when only Postgres is unavailable", async () => {
    setupFetchMock({ readyOverrides: { postgresql: "unavailable" }, readyState: "unready" });
    renderAssistant();
    await waitForReady();
    expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeEnabled();
  });

  it("allows submission when only Qdrant is unavailable", async () => {
    setupFetchMock({ readyOverrides: { qdrant: "unavailable" }, readyState: "unready" });
    renderAssistant();
    await waitForReady();
    expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeEnabled();
  });
});

describe("Assistant examples and validation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("populates the textarea from an example without auto-submitting", async () => {
    const fetchMock = setupFetchMock({});
    renderAssistant();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "What does Medicare say about hospital beds?" }));

    expect(screen.getByLabelText("Your request")).toHaveValue("What does Medicare say about hospital beds?");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/orchestrate"))).toBe(false);
  });

  it("blocks an empty request", async () => {
    setupFetchMock({});
    renderAssistant();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a request/i);
  });
});

describe("Assistant error handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a calm network-error message and allows retry", async () => {
    let shouldFail = true;
    setupFetchMock({
      orchestrateResponse: () => {
        if (shouldFail) {
          shouldFail = false;
          throw new TypeError("Failed to fetch");
        }
        return jsonResponse(POLICY_RESULT);
      },
    });
    renderAssistant();
    await waitForReady();
    await submitQuestion("What does Medicare say about hospital beds?");

    await waitFor(() => expect(screen.getByText(/could not reach the backend/i)).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
  });
});
