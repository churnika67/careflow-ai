import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PatientData } from "./PatientData";
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

const PATIENT_SUMMARY_OK = {
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
  abstention_reason: null,
  error: null,
};

const EMPTY_ENCOUNTERS_OK = {
  request_id: "req-2",
  route: "fhir",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_patient_encounters",
  source_dataset: "synthea_fhir",
  record_count: 0,
  data: [],
  abstention_reason: null,
  error: null,
};

const UNKNOWN_PATIENT_ABSTAINED = {
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
      return options.queryResponse ? options.queryResponse() : jsonResponse(PATIENT_SUMMARY_OK);
    }
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

function renderPatientData() {
  return render(
    <SystemStatusProvider>
      <PatientData />
    </SystemStatusProvider>,
  );
}

async function waitForReady() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Load Patient" })).toBeEnabled());
}

describe("PatientData", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the synthetic-data notice", async () => {
    setupFetchMock({});
    renderPatientData();
    await waitForReady();
    expect(
      screen.getByText(/generated synthetic healthcare data and do not represent real patients/i),
    ).toBeInTheDocument();
  });

  it("blocks an empty patient ID", async () => {
    setupFetchMock({});
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Load Patient" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a synthetic patient id/i);
  });

  it("submits a valid ID and sends an explicit route=fhir, tool=get_patient_summary request", async () => {
    setupFetchMock({});
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(
      screen.getByLabelText("Synthetic Patient ID"),
      "31a2e8ec-69fc-8a71-3ab6-36cbdd508713",
    );
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    await waitFor(() => expect(screen.getByText("31a2e8ec-69fc-8a71-3ab6-36cbdd508713")).toBeInTheDocument());
    const orchestrateCall = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => String(url).endsWith("/orchestrate"));
    expect(orchestrateCall).toBeDefined();
    const [, init] = orchestrateCall!;
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.route).toBe("fhir");
    expect(body.tool).toBe("get_patient_summary");
    expect(body.tool_arguments).toEqual({ patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" });
  });

  it("trims leading/trailing whitespace from the patient ID before sending (Slice 7)", async () => {
    setupFetchMock({});
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "  31a2e8ec-69fc-8a71-3ab6-36cbdd508713  ");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    await waitFor(() => expect(screen.getByText("31a2e8ec-69fc-8a71-3ab6-36cbdd508713")).toBeInTheDocument());
    const orchestrateCall = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/orchestrate"));
    const body = JSON.parse((orchestrateCall![1] as RequestInit).body as string);
    expect(body.tool_arguments).toEqual({ patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" });
  });

  it("shows a loading state while the request is in flight", async () => {
    let resolveQuery!: (value: Response) => void;
    setupFetchMock({ queryResponse: () => new Promise((resolve) => (resolveQuery = resolve)) });
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    expect(screen.getByText(/Loading synthetic patient data/i)).toBeInTheDocument();
    resolveQuery(jsonResponse(PATIENT_SUMMARY_OK));
    await waitFor(() => expect(screen.getByText("31a2e8ec-69fc-8a71-3ab6-36cbdd508713")).toBeInTheDocument());
  });

  it("renders a successful patient summary result", async () => {
    setupFetchMock({ queryResponse: () => jsonResponse(PATIENT_SUMMARY_OK) });
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    await waitFor(() => expect(screen.getByText("Adelaida985")).toBeInTheDocument());
    expect(screen.getByText("DuBuque211")).toBeInTheDocument();
    expect(screen.getByText("1970-01-01")).toBeInTheDocument();
  });

  it("shows an honest empty-results message for a zero-record list, not an error", async () => {
    // The page always loads Summary first on submit, then Encounters only
    // once that tab is clicked -- the mock must distinguish the two
    // requests by tool, not return one canned response for both.
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        const path = url.replace("http://localhost:8000", "");
        if (path === "/live") return jsonResponse(LIVE_OK);
        if (path === "/ready") return jsonResponse(READY_ALL_HEALTHY);
        if (path === "/orchestrate") {
          const body = JSON.parse((init?.body as string) ?? "{}");
          return jsonResponse(
            body.tool === "get_patient_encounters" ? EMPTY_ENCOUNTERS_OK : PATIENT_SUMMARY_OK,
          );
        }
        throw new Error(`Unexpected fetch to ${path}`);
      }),
    );
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));
    await waitFor(() => expect(screen.getByText("Encounters")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Encounters" }));

    await waitFor(() =>
      expect(screen.getByText(/no records found for this synthetic identifier/i)).toBeInTheDocument(),
    );
  });

  it("shows a dedicated abstention message for an unknown patient ID, not a server error", async () => {
    setupFetchMock({ queryResponse: () => jsonResponse(UNKNOWN_PATIENT_ABSTAINED) });
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "nonexistent-id");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    await waitFor(() =>
      expect(screen.getByText(/no synthetic patient was found for this id/i)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/error|unavailable/i)).not.toBeInTheDocument();
  });

  it("shows a calm error message and allows retry on failure", async () => {
    let shouldFail = true;
    setupFetchMock({
      queryResponse: () => {
        if (shouldFail) {
          shouldFail = false;
          throw new TypeError("Failed to fetch");
        }
        return jsonResponse(PATIENT_SUMMARY_OK);
      },
    });
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    await waitFor(() => expect(screen.getByText(/could not reach the backend/i)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("31a2e8ec-69fc-8a71-3ab6-36cbdd508713")).toBeInTheDocument());
  });

  it("prevents a duplicate submission while one is already in flight", async () => {
    let resolveQuery!: (value: Response) => void;
    const fetchMock = setupFetchMock({
      queryResponse: () => new Promise((resolve) => (resolveQuery = resolve)),
    });
    renderPatientData();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));
    await user.click(screen.getByRole("button", { name: "Loading…" }));

    const orchestrateCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/orchestrate"));
    expect(orchestrateCalls).toHaveLength(1);
    resolveQuery(jsonResponse(PATIENT_SUMMARY_OK));
    await waitFor(() => expect(screen.getByText("31a2e8ec-69fc-8a71-3ab6-36cbdd508713")).toBeInTheDocument());
  });

  it("disables submission when the backend is unavailable", async () => {
    setupFetchMock({ liveFails: true });
    renderPatientData();
    await waitFor(() => expect(screen.getByRole("button", { name: "Load Patient" })).toBeDisabled());
  });
});
