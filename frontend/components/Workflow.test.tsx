import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Workflow } from "./Workflow";
import { SystemStatusProvider } from "./SystemStatusProvider";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const LIVE_OK = { status: "alive", service: "careflow-ai" };

function readyPayload(overrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>) {
  const anyDown = overrides && Object.values(overrides).some((v) => v === "unavailable");
  return {
    status: anyDown ? "unready" : "ready",
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
  status: "ok",
  abstention_reason: null,
  answer:
    "CMS evidence [d9eb65be-cab7-5ee4-9fdb-d94e370fd15b]:\nA. General Requirements for Coverage of Hospital Beds",
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
};

const FHIR_SUMMARY_DATA = {
  patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713",
  family_name: "DuBuque211",
  given_name: "Adelaida985",
  birth_date: "1917-05-15",
  gender: "female",
  race_code: "2106-3",
  race_display: "White",
  ethnicity_code: "2186-5",
  ethnicity_display: "Not Hispanic or Latino",
  run_id: "run-1",
  source_bundle_sha256: "abc",
};

const SYNPUF_SUMMARY_DATA = {
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
  reimb_inpatient: "0.00",
  benres_inpatient: "0.00",
  pppymt_inpatient: "0.00",
  reimb_outpatient: "50.00",
  benres_outpatient: "10.00",
  pppymt_outpatient: "0.00",
  reimb_carrier: "0.00",
  benres_carrier: "0.00",
  pppymt_carrier: "0.00",
};

// Every mock reviewable-query response includes the 4 review_* fields
// ReviewableQueryResponse adds on top of MultiAgentResponse -- defaulting
// to "no review required" unless a test explicitly overrides them, per
// backend/app/review/models.py::ReviewableQueryResponse.
function combinedFhirOk(reviewOverrides: Partial<ReturnType<typeof reviewFields>> = {}) {
  return {
    request_id: "req-fhir",
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
          data: FHIR_SUMMARY_DATA,
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
    ...reviewFields(),
    ...reviewOverrides,
  };
}

function reviewFields() {
  return {
    review_required: false,
    review_reason_codes: [] as string[],
    review_id: null as string | null,
    review_status: null as string | null,
  };
}

function combinedSynpufOk() {
  return {
    request_id: "req-synpuf",
    workflow: "policy_and_structured",
    status: "ok",
    policy: POLICY_RESULT,
    structured: {
      route: "synpuf",
      results: [
        {
          tool: "get_beneficiary_summary",
          success: true,
          source_dataset: "cms_desynpuf",
          data: SYNPUF_SUMMARY_DATA,
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
    ...reviewFields(),
  };
}

function unknownPatientPartialFailure() {
  return {
    request_id: "req-partial",
    workflow: "policy_and_structured",
    status: "ok",
    policy: POLICY_RESULT,
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
    ...reviewFields(),
  };
}

function sourceMismatchValidatorFailure() {
  return {
    request_id: "req-validator",
    workflow: "policy_and_structured",
    status: "error",
    policy: POLICY_RESULT,
    structured: {
      route: "fhir",
      results: [
        {
          tool: "get_patient_summary",
          success: true,
          source_dataset: "cms_desynpuf",
          data: FHIR_SUMMARY_DATA,
          record_count: 1,
          error: null,
          abstention_reason: null,
        },
      ],
    },
    validation: {
      passed: false,
      issues: [{ code: "source_mismatch", detail: "expected synthea_fhir, got cms_desynpuf for tool get_patient_summary" }],
    },
    final_summary: null,
    abstention_reason: null,
    error: "validation_failed",
    // A validation issue always triggers a real review case -- see
    // backend/app/review/policy.py::determine_review_requirement.
    review_required: true,
    review_reason_codes: ["source_mismatch"],
    review_id: "review-validator-1",
    review_status: "pending",
  };
}

function setupFetchMock(options: {
  reviewableQueryResponse?: () => Response | Promise<Response>;
  readyOverrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>;
  liveFails?: boolean;
}) {
  const impl = vi.fn(async (url: string, init?: RequestInit) => {
    void init;
    const path = url.replace("http://localhost:8000", "");
    if (path === "/live") {
      if (options.liveFails) throw new TypeError("Failed to fetch");
      return jsonResponse(LIVE_OK);
    }
    if (path === "/ready") return jsonResponse(readyPayload(options.readyOverrides));
    if (path === "/reviewable-query") {
      return options.reviewableQueryResponse ? options.reviewableQueryResponse() : jsonResponse(combinedFhirOk());
    }
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

function renderWorkflow() {
  return render(
    <SystemStatusProvider>
      <Workflow />
    </SystemStatusProvider>,
  );
}

async function waitForReady() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Run Evidence Workflow" })).toBeEnabled());
}

async function fillAndSubmit(user: ReturnType<typeof userEvent.setup>, identifier: string) {
  await user.type(screen.getByLabelText("Policy question"), "What does Medicare say about hospital beds?");
  await user.type(screen.getByLabelText(/Synthetic (Patient|Beneficiary) ID/), identifier);
  await user.click(screen.getByRole("button", { name: "Run Evidence Workflow" }));
}

describe("Workflow form", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("blocks submission with an empty policy question", async () => {
    setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText(/Synthetic Patient ID/), "x");
    await user.click(screen.getByRole("button", { name: "Run Evidence Workflow" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a medicare policy question/i);
  });

  it("blocks submission with an empty identifier", async () => {
    setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Policy question"), "What does Medicare say about hospital beds?");
    await user.click(screen.getByRole("button", { name: "Run Evidence Workflow" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a synthetic identifier/i);
  });

  it("labels the identifier field for FHIR by default", async () => {
    setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    expect(screen.getByLabelText("Synthetic Patient ID")).toBeInTheDocument();
  });

  it("switches the identifier label to Beneficiary ID and clears any typed value when switching to SynPUF", async () => {
    setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Synthetic Patient ID"), "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
    await user.click(screen.getByRole("radio", { name: "Synthetic Claims" }));

    expect(screen.queryByLabelText("Synthetic Patient ID")).not.toBeInTheDocument();
    const beneficiaryInput = screen.getByLabelText("Synthetic Beneficiary ID") as HTMLInputElement;
    expect(beneficiaryInput.value).toBe("");
  });

  it("switches the tool dropdown options by dataset", async () => {
    setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    expect(screen.getByRole("option", { name: "Patient Conditions" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Beneficiary Claims" })).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Synthetic Claims" }));

    expect(screen.getByRole("option", { name: "Beneficiary Claims" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Patient Conditions" })).not.toBeInTheDocument();
  });

  it("prevents a duplicate submission while one is already in flight", async () => {
    let resolveFetch!: (value: Response) => void;
    const fetchMock = setupFetchMock({
      reviewableQueryResponse: () => new Promise((resolve) => (resolveFetch = resolve)),
    });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
    await user.click(screen.getByRole("button", { name: "Running evidence workflow…" }));

    const calls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/reviewable-query"));
    expect(calls).toHaveLength(1);
    resolveFetch(jsonResponse(combinedFhirOk()));
    await waitFor(() => expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument());
  });
});

describe("Workflow request construction (no cross-dataset identity)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends only a FHIR structured_route/tool when FHIR is selected -- never a SynPUF identifier alongside it", async () => {
    const fetchMock = setupFetchMock({ reviewableQueryResponse: () => jsonResponse(combinedFhirOk()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
    await waitFor(() => expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument());

    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/reviewable-query"));
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body.structured_route).toBe("fhir");
    expect(body.tools).toEqual([
      { tool: "get_patient_summary", arguments: { patient_id: "31a2e8ec-69fc-8a71-3ab6-36cbdd508713" } },
    ]);
    expect(body.explicit_review_requested).toBe(false);
    expect(JSON.stringify(body)).not.toMatch(/beneficiary_id/);
  });

  it("sends only a SynPUF structured_route/tool when SynPUF is selected -- never a FHIR identifier alongside it", async () => {
    const fetchMock = setupFetchMock({ reviewableQueryResponse: () => jsonResponse(combinedSynpufOk()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: "Synthetic Claims" }));
    await fillAndSubmit(user, "00013D2EFD8E45D1");
    await waitFor(() => expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument());

    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/reviewable-query"));
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body.structured_route).toBe("synpuf");
    expect(body.tools).toEqual([
      { tool: "get_beneficiary_summary", arguments: { beneficiary_id: "00013D2EFD8E45D1" } },
    ]);
    expect(JSON.stringify(body)).not.toMatch(/patient_id/);
  });

  it("sends explicit_review_requested=true when the checkbox is checked", async () => {
    const fetchMock = setupFetchMock({
      reviewableQueryResponse: () =>
        jsonResponse(
          combinedFhirOk({
            review_required: true,
            review_reason_codes: ["explicit_review_requested"],
            review_id: "review-explicit-1",
            review_status: "pending",
          }),
        ),
    });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Request human review" }));
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
    await waitFor(() => expect(screen.getByText("Review required")).toBeInTheDocument());

    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/reviewable-query"));
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body.explicit_review_requested).toBe(true);
  });

  it("trims leading/trailing whitespace from the policy question and identifier before sending (Slice 7)", async () => {
    const fetchMock = setupFetchMock({ reviewableQueryResponse: () => jsonResponse(combinedFhirOk()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Policy question"), "  What does Medicare say about hospital beds?  ");
    await user.type(screen.getByLabelText(/Synthetic Patient ID/), "  31a2e8ec-69fc-8a71-3ab6-36cbdd508713  ");
    await user.click(screen.getByRole("button", { name: "Run Evidence Workflow" }));
    await waitFor(() => expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument());

    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/reviewable-query"));
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body.policy_question).toBe("What does Medicare say about hospital beds?");
    expect(body.tools[0].arguments.patient_id).toBe("31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
  });
});

describe("Workflow review creation", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the Review required panel with review ID, state, trigger reason, and a View review link when a review is created", async () => {
    setupFetchMock({
      reviewableQueryResponse: () =>
        jsonResponse(
          combinedFhirOk({
            review_required: true,
            review_reason_codes: ["explicit_review_requested"],
            review_id: "review-abc-123",
            review_status: "pending",
          }),
        ),
    });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "Request human review" }));
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");

    await waitFor(() => expect(screen.getByText("Review required")).toBeInTheDocument());
    expect(screen.getByText("review-abc-123")).toBeInTheDocument();
    expect(screen.getByText(/State: Pending/)).toBeInTheDocument();
    expect(screen.getByText(/explicitly requested/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View review" })).toHaveAttribute(
      "href",
      "/reviews/review-abc-123",
    );
  });

  it("shows the honest no-review note when review is not required", async () => {
    setupFetchMock({ reviewableQueryResponse: () => jsonResponse(combinedFhirOk()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");

    await waitFor(() => expect(screen.getByText("No human review was required for this request.")).toBeInTheDocument());
    expect(screen.queryByText("Review required")).not.toBeInTheDocument();
  });

  it("shows the Review required panel automatically when validation finds an issue, even without the checkbox", async () => {
    setupFetchMock({ reviewableQueryResponse: () => jsonResponse(sourceMismatchValidatorFailure()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    // Checkbox intentionally left unchecked.
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");

    await waitFor(() => expect(screen.getByText("Review required")).toBeInTheDocument());
    expect(screen.getByText("review-validator-1")).toBeInTheDocument();
  });
});

describe("Workflow combined result rendering", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders policy and structured sections separately, with the safety disclaimer and no coverage conclusion", async () => {
    setupFetchMock({ reviewableQueryResponse: () => jsonResponse(combinedFhirOk()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");

    await waitFor(() => expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument());
    expect(screen.getByText("Synthetic Healthcare Data")).toBeInTheDocument();
    expect(screen.getByText("Validation")).toBeInTheDocument();
    expect(screen.getByText("Citation 1")).toBeInTheDocument();
    expect(screen.getByText("Hospital Beds")).toBeInTheDocument();
    expect(screen.getByText("Adelaida985")).toBeInTheDocument();
    expect(screen.getByText(/Synthea FHIR/)).toBeInTheDocument();

    expect(screen.getByText("Important")).toBeInTheDocument();
    expect(
      screen.getByText(/does not establish individual coverage, eligibility, medical\s*\n?\s*necessity, or claim approval/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/medicare covers this patient/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/this patient's condition qualifies/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/this beneficiary is covered/i)).not.toBeInTheDocument();
  });

  it("never presents structured records as citations", async () => {
    setupFetchMock({ reviewableQueryResponse: () => jsonResponse(combinedFhirOk()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
    await waitFor(() => expect(screen.getByText("Adelaida985")).toBeInTheDocument());

    // Only one "Citation 1" should exist (from the policy section), never a
    // second one representing the structured record.
    expect(screen.getAllByText("Citation 1")).toHaveLength(1);
  });

  it("renders a validation-warning state, not a fully-successful result, when the validator fails", async () => {
    setupFetchMock({ reviewableQueryResponse: () => jsonResponse(sourceMismatchValidatorFailure()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");

    await waitFor(() => expect(screen.getByText(/evidence validation did not pass/i)).toBeInTheDocument());
    const alert = screen.getByText(/evidence validation did not pass/i).closest('[role="alert"]');
    expect(alert).not.toBeNull();
    // The same trigger-reason text also legitimately appears in the "Review
    // required" panel above (this failure also triggers a review) -- scope
    // this assertion to the Validation section's own alert region.
    expect(alert).toHaveTextContent(/did not come from the expected dataset/i);
    expect(alert).toHaveTextContent(/source_mismatch/);
  });

  it("represents a partial specialist failure honestly -- policy succeeds, structured abstains, neither hidden", async () => {
    setupFetchMock({ reviewableQueryResponse: () => jsonResponse(unknownPatientPartialFailure()) });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "nonexistent-id");

    await waitFor(() => expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument());
    // Policy evidence still shown in full.
    expect(screen.getByText("Citation 1")).toBeInTheDocument();
    // Structured failure shown honestly, not silently dropped, not disguised as success.
    expect(screen.getByText(/no synthetic patient was found for this id/i)).toBeInTheDocument();
    expect(screen.getByText("Evidence validation passed with no issues.")).toBeInTheDocument();
  });
});

describe("Workflow readiness", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("blocks submission when the backend process is unreachable", async () => {
    setupFetchMock({ liveFails: true });
    renderWorkflow();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Evidence Workflow" })).toBeDisabled());
  });

  it("blocks submission when Qdrant is unavailable", async () => {
    setupFetchMock({ readyOverrides: { qdrant: "unavailable" } });
    renderWorkflow();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Evidence Workflow" })).toBeDisabled());
  });

  it("blocks submission when Postgres is unavailable", async () => {
    setupFetchMock({ readyOverrides: { postgresql: "unavailable" } });
    renderWorkflow();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Evidence Workflow" })).toBeDisabled());
  });

  it("allows submission when only Redis is unavailable", async () => {
    setupFetchMock({ readyOverrides: { redis: "unavailable" } });
    renderWorkflow();
    await waitForReady();
    expect(screen.getByRole("button", { name: "Run Evidence Workflow" })).toBeEnabled();
  });

  it("allows submission when every dependency is healthy", async () => {
    setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    expect(screen.getByRole("button", { name: "Run Evidence Workflow" })).toBeEnabled();
  });
});

describe("Workflow error handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a calm network-error message and allows retry", async () => {
    let shouldFail = true;
    setupFetchMock({
      reviewableQueryResponse: () => {
        if (shouldFail) {
          shouldFail = false;
          throw new TypeError("Failed to fetch");
        }
        return jsonResponse(combinedFhirOk());
      },
    });
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await fillAndSubmit(user, "31a2e8ec-69fc-8a71-3ab6-36cbdd508713");

    await waitFor(() => expect(screen.getByText(/could not reach the backend/i)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument());
  });
});

describe("Workflow example workflows", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the Policy + FHIR example without auto-submitting", async () => {
    const fetchMock = setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Policy + Synthetic FHIR" }));

    expect(screen.getByLabelText("Policy question")).toHaveValue("What does Medicare say about hospital beds?");
    expect(screen.getByLabelText("Synthetic Patient ID")).toHaveValue("31a2e8ec-69fc-8a71-3ab6-36cbdd508713");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reviewable-query"))).toBe(false);
  });

  it("loads the Policy + SynPUF example without auto-submitting", async () => {
    const fetchMock = setupFetchMock({});
    renderWorkflow();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Policy + Synthetic Claims" }));

    expect(screen.getByLabelText("Policy question")).toHaveValue("What does Medicare say about hospital beds?");
    expect(screen.getByLabelText("Synthetic Beneficiary ID")).toHaveValue("00013D2EFD8E45D1");
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/reviewable-query"))).toBe(false);
  });
});
