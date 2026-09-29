import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Claims } from "./Claims";
import { SystemStatusProvider } from "./SystemStatusProvider";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const LIVE_OK = { status: "alive", service: "careflow-ai" };
const READY_ALL_HEALTHY = {
  status: "ready",
  service: "careflow-ai",
  version: "0.1.0",
  dependencies: {
    postgresql: { status: "ok" },
    qdrant: { status: "ok" },
    redis: { status: "ok" },
  },
};

const BENEFICIARY_OK = {
  request_id: "req-1",
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
    sex_code: "1",
    race_code: "1",
    esrd_indicator: "0",
    state_code: "26",
    county_code: "950",
    hi_coverage_months: 12,
    smi_coverage_months: 12,
    hmo_coverage_months: 12,
    plan_coverage_months: 12,
    chronic_alzheimers: 2,
    chronic_heart_failure: 2,
    chronic_kidney_disease: 2,
    chronic_cancer: 2,
    chronic_copd: 2,
    chronic_depression: 2,
    chronic_diabetes: 2,
    chronic_ischemic_heart: 2,
    chronic_osteoporosis: 2,
    chronic_ra_oa: 2,
    chronic_stroke_tia: 2,
    reimb_inpatient: 0,
    benres_inpatient: 0,
    pppymt_inpatient: 0,
    reimb_outpatient: 50,
    benres_outpatient: 10,
    pppymt_outpatient: 0,
    reimb_carrier: 0,
    benres_carrier: 0,
    pppymt_carrier: 0,
  },
  abstention_reason: null,
  error: null,
};

const EMPTY_CLAIMS_OK = {
  request_id: "req-2",
  route: "synpuf",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_claims_for_beneficiary",
  source_dataset: "cms_desynpuf",
  record_count: 0,
  data: [],
  abstention_reason: null,
  error: null,
};

const UNKNOWN_BENEFICIARY_ABSTAINED = {
  request_id: "req-3",
  route: "synpuf",
  status: "abstained",
  answer: null,
  citations: null,
  tool: "get_beneficiary_summary",
  source_dataset: null,
  record_count: null,
  data: null,
  abstention_reason: "unknown_beneficiary",
  error: null,
};

function setupFetchMock(options: {
  queryResponse?: () => Response | Promise<Response>;
  liveFails?: boolean;
}) {
  const impl = vi.fn(async (url: string) => {
    const path = url.replace("http://localhost:8000", "");
    if (path === "/live") {
      if (options.liveFails) throw new TypeError("Failed to fetch");
      return jsonResponse(LIVE_OK);
    }
    if (path === "/ready") return jsonResponse(READY_ALL_HEALTHY);
    if (path === "/orchestrate") {
      return options.queryResponse ? options.queryResponse() : jsonResponse(BENEFICIARY_OK);
    }
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

function renderClaims() {
  return render(
    <SystemStatusProvider>
      <Claims />
    </SystemStatusProvider>,
  );
}

async function waitForReady() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Load Beneficiary" })).toBeEnabled());
}

describe("Claims", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the synthetic-data notice", async () => {
    setupFetchMock({});
    renderClaims();
    await waitForReady();
    expect(
      screen.getByText(/synthetic, de-identified demonstration claims data/i),
    ).toBeInTheDocument();
  });

  it("blocks an empty beneficiary ID", async () => {
    setupFetchMock({});
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a synthetic beneficiary id/i);
  });

  it("submits a valid ID and sends an explicit route=synpuf, tool=get_beneficiary_summary request", async () => {
    setupFetchMock({});
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "00013D2EFD8E45D1");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));

    await waitFor(() => expect(screen.getByText("00013D2EFD8E45D1")).toBeInTheDocument());
    const orchestrateCall = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => String(url).endsWith("/orchestrate"));
    const [, init] = orchestrateCall!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.route).toBe("synpuf");
    expect(body.tool).toBe("get_beneficiary_summary");
    expect(body.tool_arguments).toEqual({ beneficiary_id: "00013D2EFD8E45D1" });
  });

  it("shows a loading state while the request is in flight", async () => {
    let resolveQuery!: (value: Response) => void;
    setupFetchMock({ queryResponse: () => new Promise((resolve) => (resolveQuery = resolve)) });
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));

    expect(screen.getByText(/Loading synthetic beneficiary data/i)).toBeInTheDocument();
    resolveQuery(jsonResponse(BENEFICIARY_OK));
    await waitFor(() => expect(screen.getByText("00013D2EFD8E45D1")).toBeInTheDocument());
  });

  it("renders a successful beneficiary overview with grouped sections", async () => {
    setupFetchMock({ queryResponse: () => jsonResponse(BENEFICIARY_OK) });
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));

    await waitFor(() => expect(screen.getByText("00013D2EFD8E45D1")).toBeInTheDocument());
    expect(screen.getByText("Coverage")).toBeInTheDocument();
    expect(screen.getByText("Chronic Condition Indicators")).toBeInTheDocument();
    expect(screen.getByText("Payment Amounts")).toBeInTheDocument();
    expect(screen.getByText("$50.00")).toBeInTheDocument(); // reimb_outpatient formatted as currency
  });

  it("shows an honest empty-results message for zero claims, not an error", async () => {
    // The page always loads Beneficiary Overview first on submit, then
    // Claims only once the "Claims" tab is clicked -- the mock must
    // distinguish the two requests by tool, not return one canned
    // response for both.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = url.replace("http://localhost:8000", "");
        if (path === "/live") return jsonResponse(LIVE_OK);
        if (path === "/ready") return jsonResponse(READY_ALL_HEALTHY);
        if (path === "/orchestrate") {
          const body = JSON.parse((init?.body as string) ?? "{}");
          return jsonResponse(body.tool === "get_claims_for_beneficiary" ? EMPTY_CLAIMS_OK : BENEFICIARY_OK);
        }
        throw new Error(`Unexpected fetch to ${path}`);
      }),
    );
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Claims" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Claims" }));

    await waitFor(() =>
      expect(screen.getByText(/no records found for this synthetic identifier/i)).toBeInTheDocument(),
    );
  });

  it("shows a dedicated abstention message for an unknown beneficiary ID", async () => {
    setupFetchMock({ queryResponse: () => jsonResponse(UNKNOWN_BENEFICIARY_ABSTAINED) });
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "nonexistent");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));

    await waitFor(() =>
      expect(screen.getByText(/no synthetic beneficiary was found for this id/i)).toBeInTheDocument(),
    );
  });

  it("shows a calm error message and allows retry on failure", async () => {
    let shouldFail = true;
    setupFetchMock({
      queryResponse: () => {
        if (shouldFail) {
          shouldFail = false;
          throw new TypeError("Failed to fetch");
        }
        return jsonResponse(BENEFICIARY_OK);
      },
    });
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));

    await waitFor(() => expect(screen.getByText(/could not reach the backend/i)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("00013D2EFD8E45D1")).toBeInTheDocument());
  });

  it("prevents a duplicate submission while one is already in flight", async () => {
    let resolveQuery!: (value: Response) => void;
    const fetchMock = setupFetchMock({
      queryResponse: () => new Promise((resolve) => (resolveQuery = resolve)),
    });
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));
    await user.click(screen.getByRole("button", { name: "Loading…" }));

    const orchestrateCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/orchestrate"));
    expect(orchestrateCalls).toHaveLength(1);
    resolveQuery(jsonResponse(BENEFICIARY_OK));
    await waitFor(() => expect(screen.getByText("00013D2EFD8E45D1")).toBeInTheDocument());
  });

  it("disables submission when the backend is unavailable", async () => {
    setupFetchMock({ liveFails: true });
    renderClaims();
    await waitFor(() => expect(screen.getByRole("button", { name: "Load Beneficiary" })).toBeDisabled());
  });

  it("drills into claim details showing diagnoses/procedures/line codes on demand", async () => {
    const ONE_CLAIM_OK = {
      request_id: "req-4",
      route: "synpuf",
      status: "ok",
      answer: null,
      citations: null,
      tool: "get_claims_for_beneficiary",
      source_dataset: "cms_desynpuf",
      record_count: 1,
      data: [
        {
          claim_row_id: "claim-row-1",
          claim_type: "outpatient",
          claim_id: "clm-1",
          segment: 1,
          beneficiary_id: "00013D2EFD8E45D1",
          from_date: "2010-01-01",
          thru_date: "2010-01-02",
          admission_date: null,
          discharge_date: null,
          provider_number: "PRV-1",
          claim_payment_amount: 100,
          primary_payer_paid_amount: 90,
          attending_physician_npi: null,
          operating_physician_npi: null,
          other_physician_npi: null,
          drg_code: null,
          admitting_diagnosis_code: "78900",
        },
      ],
      abstention_reason: null,
      error: null,
    };
    const CLAIM_DETAILS_OK = {
      request_id: "req-5",
      route: "synpuf",
      status: "ok",
      answer: null,
      citations: null,
      tool: "get_claim_details",
      source_dataset: "cms_desynpuf",
      record_count: 1,
      data: {
        ...ONE_CLAIM_OK.data[0],
        diagnoses: [{ sequence: 1, icd9_code: "25000" }],
        procedures: [{ sequence: 1, icd9_procedure_code: "8154" }],
        lines: [{ line_number: 1, hcpcs_code: "99213" }],
      },
      abstention_reason: null,
      error: null,
    };

    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = url.replace("http://localhost:8000", "");
        if (path === "/live") return jsonResponse(LIVE_OK);
        if (path === "/ready") return jsonResponse(READY_ALL_HEALTHY);
        if (path === "/orchestrate") {
          const body = JSON.parse((init?.body as string) ?? "{}");
          if (body.tool === "get_claim_details") return jsonResponse(CLAIM_DETAILS_OK);
          if (body.tool === "get_claims_for_beneficiary") return jsonResponse(ONE_CLAIM_OK);
          return jsonResponse(BENEFICIARY_OK);
        }
        throw new Error(`Unexpected fetch to ${path}`);
      }),
    );
    renderClaims();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "00013D2EFD8E45D1");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Claims" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Claims" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "View details" })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "View details" }));

    await waitFor(() => expect(screen.getByText("Diagnoses (ICD-9)")).toBeInTheDocument());
    expect(screen.getByText("25000")).toBeInTheDocument();
    expect(screen.getByText("8154")).toBeInTheDocument();
    expect(screen.getByText("99213")).toBeInTheDocument();
  });
});
