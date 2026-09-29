/**
 * Explicit proof that Patient Data (FHIR) and Claims (SynPUF) never
 * cross-contaminate -- see docs/phase14_frontend_design.md's "Dataset
 * separation rule". Each page's own component/integration tests already
 * assert the route/tool sent for their own happy path; this file exists
 * specifically to make the *absence* of cross-dataset behavior explicit
 * and independently verifiable.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Claims } from "./Claims";
import { PatientData } from "./PatientData";
import { SystemStatusProvider } from "./SystemStatusProvider";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
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

const GENERIC_OK = {
  request_id: "req-1",
  route: "fhir",
  status: "ok",
  answer: null,
  citations: null,
  tool: "get_patient_summary",
  source_dataset: "synthea_fhir",
  record_count: 1,
  data: { patient_id: "x" },
  abstention_reason: null,
  error: null,
};

function stubBaseFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const path = url.replace("http://localhost:8000", "");
      if (path === "/live") return jsonResponse(LIVE_OK);
      if (path === "/ready") return jsonResponse(READY_ALL_HEALTHY);
      if (path === "/orchestrate") return jsonResponse(GENERIC_OK);
      throw new Error(`Unexpected fetch to ${path}`);
    }),
  );
}

function orchestrateCalls() {
  return vi.mocked(fetch).mock.calls.filter(([url]) => String(url).endsWith("/orchestrate"));
}

describe("dataset separation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("Patient Data sends route=fhir only, never route=synpuf", async () => {
    stubBaseFetch();
    render(
      <SystemStatusProvider>
        <PatientData />
      </SystemStatusProvider>,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Load Patient" })).toBeEnabled());
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    await waitFor(() => expect(orchestrateCalls().length).toBeGreaterThan(0));
    for (const [, init] of orchestrateCalls()) {
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.route).toBe("fhir");
      expect(body.route).not.toBe("synpuf");
      expect(body.tool_arguments).not.toHaveProperty("beneficiary_id");
    }
  });

  it("Claims sends route=synpuf only, never route=fhir", async () => {
    stubBaseFetch();
    render(
      <SystemStatusProvider>
        <Claims />
      </SystemStatusProvider>,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Load Beneficiary" })).toBeEnabled());
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Beneficiary ID"), "00013D2EFD8E45D1");
    await user.click(screen.getByRole("button", { name: "Load Beneficiary" }));

    await waitFor(() => expect(orchestrateCalls().length).toBeGreaterThan(0));
    for (const [, init] of orchestrateCalls()) {
      const body = JSON.parse((init as RequestInit).body as string);
      expect(body.route).toBe("synpuf");
      expect(body.route).not.toBe("fhir");
      expect(body.tool_arguments).not.toHaveProperty("patient_id");
    }
  });

  it("never emits a single request naming both a patient_id and a beneficiary_id", async () => {
    stubBaseFetch();
    render(
      <SystemStatusProvider>
        <PatientData />
      </SystemStatusProvider>,
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Load Patient" })).toBeEnabled());
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "x");
    await user.click(screen.getByRole("button", { name: "Load Patient" }));

    await waitFor(() => expect(orchestrateCalls().length).toBeGreaterThan(0));
    const [, init] = orchestrateCalls()[0];
    const body = JSON.parse((init as RequestInit).body as string);
    const hasBoth = "patient_id" in body.tool_arguments && "beneficiary_id" in body.tool_arguments;
    expect(hasBoth).toBe(false);
  });
});
