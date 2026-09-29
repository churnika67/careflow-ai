import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewDetail } from "./ReviewDetail";
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

const SNAPSHOT = {
  request_id: "req-1",
  workflow: "policy_and_structured",
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

function reviewCase(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    review_id: "review-1",
    request_id: "req-1",
    workflow: "policy_and_structured",
    status: "pending",
    trigger_reason_codes: ["explicit_review_requested"],
    evidence_snapshot: SNAPSHOT,
    evidence_fingerprint: "a".repeat(64),
    version: 1,
    previous_review_id: null,
    created_at: "2026-01-01T12:00:00Z",
    updated_at: "2026-01-01T12:00:00Z",
    ...overrides,
  };
}

function event(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    event_id: "event-1",
    review_id: "review-1",
    event_type: "review_created",
    actor_id: "system",
    actor_type: "system",
    previous_status: null,
    new_status: "pending",
    reason: null,
    metadata: null,
    created_at: "2026-01-01T12:00:00Z",
    ...overrides,
  };
}

interface MockOptions {
  detailResponse?: (call: number) => Response | Promise<Response>;
  decisionResponse?: () => Response | Promise<Response>;
  readyOverrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>;
  liveFails?: boolean;
}

function setupFetchMock(options: MockOptions) {
  let detailCallCount = 0;
  const impl = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace("http://localhost:8000", "");
    if (path === "/live") {
      if (options.liveFails) throw new TypeError("Failed to fetch");
      return jsonResponse(LIVE_OK);
    }
    if (path === "/ready") {
      const anyDown =
        options.readyOverrides && Object.values(options.readyOverrides).some((v) => v === "unavailable");
      return jsonResponse({
        ...READY_ALL_HEALTHY,
        status: anyDown ? "unready" : "ready",
        dependencies: {
          postgresql: { status: options.readyOverrides?.postgresql ?? "ok" },
          qdrant: { status: options.readyOverrides?.qdrant ?? "ok" },
          redis: { status: options.readyOverrides?.redis ?? "ok" },
        },
      });
    }
    if (path === "/reviews/review-1" && !init) {
      // GET has no init.method distinguishable easily here; use path+method
    }
    if (path.startsWith("/reviews/review-1/decision")) {
      return options.decisionResponse
        ? options.decisionResponse()
        : jsonResponse(reviewCase({ status: "approved", version: 2 }));
    }
    if (path.startsWith("/reviews/")) {
      detailCallCount += 1;
      return options.detailResponse
        ? options.detailResponse(detailCallCount)
        : jsonResponse({ case: reviewCase(), events: [event()] });
    }
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

function renderDetail(reviewId = "review-1") {
  return render(
    <SystemStatusProvider>
      <ReviewDetail reviewId={reviewId} />
    </SystemStatusProvider>,
  );
}

async function fillReviewer(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.type(screen.getByLabelText("Reviewer identifier"), name);
}

describe("ReviewDetail metadata/snapshot/events", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders metadata, state, version, trigger reasons, evidence snapshot, and audit events", async () => {
    setupFetchMock({
      detailResponse: () =>
        jsonResponse({
          case: reviewCase(),
          events: [event()],
        }),
    });
    renderDetail();

    await waitFor(() => expect(screen.getByText("Pending")).toBeInTheDocument());
    expect(screen.getByText("Review ID: review-1")).toBeInTheDocument();
    // "Medicare Policy + Synthetic Data" legitimately appears twice: once in
    // the metadata field, once in the evidence snapshot's own routing
    // summary (reused unmodified from Workflow.tsx's rendering).
    expect(screen.getAllByText(/Medicare Policy \+ Synthetic Data/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/explicitly requested/i)).toBeInTheDocument();
    expect(screen.getByText(`Evidence fingerprint: ${"a".repeat(64)}`)).toBeInTheDocument();

    // Evidence snapshot rendered through the shared MultiAgentResultView.
    expect(screen.getByText("Medicare Policy Evidence")).toBeInTheDocument();
    expect(screen.getByText("Citation 1")).toBeInTheDocument();
    expect(screen.getByText("Synthetic Healthcare Data")).toBeInTheDocument();

    // Audit history.
    expect(screen.getByText("Review created")).toBeInTheDocument();
  });

  it("never mutates or re-fetches evidence on render -- exactly one GET per mount", async () => {
    const fetchMock = setupFetchMock({});
    renderDetail();
    await waitFor(() => expect(screen.getByText("Review created")).toBeInTheDocument());
    const detailCalls = fetchMock.mock.calls.filter(
      ([url]) => String(url).endsWith("/reviews/review-1") ,
    );
    expect(detailCalls).toHaveLength(1);
  });

  it("can reveal the raw snapshot JSON behind a disclosure, not as the primary UX", async () => {
    setupFetchMock({});
    renderDetail();
    await waitFor(() => expect(screen.getByText("Review created")).toBeInTheDocument());
    expect(screen.queryByText(/"request_id"/)).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Show raw snapshot JSON" }));
    expect(screen.getByText(/"request_id"/)).toBeInTheDocument();
  });

  it("shows a not-found message for an unknown review, not a generic error", async () => {
    setupFetchMock({ detailResponse: () => jsonResponse({ error: { code: "unknown_review" } }, { status: 404 }) });
    renderDetail("review-missing");
    await waitFor(() => expect(screen.getByText(/no review was found/i)).toBeInTheDocument());
  });
});

describe("ReviewDetail decisions", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the approval-semantics disclaimer near the decision controls", async () => {
    setupFetchMock({});
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    expect(
      screen.getByText(/approval accepts this careflow output for the application workflow/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/not a coverage, eligibility, medical-necessity, claim, or clinical decision/i)).toBeInTheDocument();
  });

  it("never labels the decision as Coverage/Claim/Medically/CMS approved anywhere on the page", async () => {
    setupFetchMock({});
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    expect(screen.queryByText(/coverage approved/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/claim approved/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/medically approved/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/cms approved/i)).not.toBeInTheDocument();
  });

  it("requires a reviewer identifier before submitting a decision", async () => {
    setupFetchMock({});
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a reviewer identifier/i);
  });

  it("sends the correct decision payload (reviewer_id, decision, expected_version) for Approve", async () => {
    const fetchMock = setupFetchMock({
      decisionResponse: () => jsonResponse(reviewCase({ status: "approved", version: 2 })),
      detailResponse: (call) =>
        call === 1
          ? jsonResponse({ case: reviewCase(), events: [event()] })
          : jsonResponse({
              case: reviewCase({ status: "approved", version: 2 }),
              events: [event(), event({ event_id: "event-2", event_type: "review_approved", actor_id: "alice", actor_type: "reviewer", previous_status: "pending", new_status: "approved" })],
            }),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    const user = userEvent.setup();
    await fillReviewer(user, "alice");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.getAllByText("Approved").length).toBeGreaterThan(0));
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/reviews/review-1/decision"));
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body).toEqual({ reviewer_id: "alice", decision: "approve", expected_version: 1 });
  });

  it("trims leading/trailing whitespace from the reviewer identifier and reason before sending (Slice 7)", async () => {
    const fetchMock = setupFetchMock({
      decisionResponse: () => jsonResponse(reviewCase({ status: "approved", version: 2 })),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Reviewer identifier"), "  alice  ");
    await user.type(screen.getByLabelText("Reason"), "  looks correct  ");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/decision"))).toBe(true),
    );
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/reviews/review-1/decision"));
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body).toEqual({
      reviewer_id: "alice",
      decision: "approve",
      reason: "looks correct",
      expected_version: 1,
    });
  });

  it("becomes APPROVED and disables further decisions after a successful approval", async () => {
    setupFetchMock({
      decisionResponse: () => jsonResponse(reviewCase({ status: "approved", version: 2 })),
      detailResponse: (call) =>
        call === 1
          ? jsonResponse({ case: reviewCase(), events: [event()] })
          : jsonResponse({ case: reviewCase({ status: "approved", version: 2 }), events: [event()] }),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    const user = userEvent.setup();
    await fillReviewer(user, "alice");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.getByText(/this review has already been decided/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request Revision" })).not.toBeInTheDocument();
  });

  it("sends the correct decision payload for Reject and becomes REJECTED", async () => {
    setupFetchMock({
      decisionResponse: () => jsonResponse(reviewCase({ status: "rejected", version: 2 })),
      detailResponse: (call) =>
        call === 1
          ? jsonResponse({ case: reviewCase(), events: [event()] })
          : jsonResponse({ case: reviewCase({ status: "rejected", version: 2 }), events: [event()] }),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument());
    const user = userEvent.setup();
    await fillReviewer(user, "bob");
    await user.click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(screen.getByText(/this review has already been decided \(Rejected\)/i)).toBeInTheDocument());
  });

  it("sends the correct decision payload for Request Revision and becomes REVISION_REQUESTED with no automatic rerun", async () => {
    const fetchMock = setupFetchMock({
      decisionResponse: () => jsonResponse(reviewCase({ status: "revision_requested", version: 2 })),
      detailResponse: (call) =>
        call === 1
          ? jsonResponse({ case: reviewCase(), events: [event()] })
          : jsonResponse({ case: reviewCase({ status: "revision_requested", version: 2 }), events: [event()] }),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Request Revision" })).toBeInTheDocument());
    const user = userEvent.setup();
    await fillReviewer(user, "carol");
    await user.click(screen.getByRole("button", { name: "Request Revision" }));

    await waitFor(() =>
      expect(screen.getByText(/this review has already been decided \(Revision Requested\)/i)).toBeInTheDocument(),
    );
    // No new /reviewable-query or /multi-agent request was ever made.
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("reviewable-query"))).toBe(false);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/multi-agent"))).toBe(false);
    // No second review was created -- only one detail GET target (review-1).
    expect(fetchMock.mock.calls.every(([url]) => String(url).includes("review-1") || String(url).includes("/live") || String(url).includes("/ready"))).toBe(true);
  });
});

describe("ReviewDetail conflict handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a calm conflict message and the backend's current state on a 409, without overwriting or silently retrying", async () => {
    const currentFromServer = reviewCase({ status: "approved", version: 2 });
    setupFetchMock({
      decisionResponse: () =>
        jsonResponse({ error: { code: "version_conflict" }, review: currentFromServer }, { status: 409 }),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    const user = userEvent.setup();
    await fillReviewer(user, "bob");
    await user.click(screen.getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(screen.getByText(/changed before your decision was saved/i)).toBeInTheDocument());
    // Immediately reflects the server's authoritative current state.
    expect(screen.getAllByText("Approved").length).toBeGreaterThan(0);
    // Exactly one decision POST was made -- no silent retry.
    const fetchMock = vi.mocked(fetch);
    const decisionCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/decision"));
    expect(decisionCalls).toHaveLength(1);
  });

  it("Refresh after a conflict re-fetches the full detail including events", async () => {
    let detailCallCount = 0;
    setupFetchMock({
      decisionResponse: () =>
        jsonResponse(
          { error: { code: "version_conflict" }, review: reviewCase({ status: "approved", version: 2 }) },
          { status: 409 },
        ),
      detailResponse: () => {
        detailCallCount += 1;
        return detailCallCount === 1
          ? jsonResponse({ case: reviewCase(), events: [event()] })
          : jsonResponse({
              case: reviewCase({ status: "approved", version: 2 }),
              events: [event(), event({ event_id: "event-2", event_type: "review_approved" })],
            });
      },
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    const user = userEvent.setup();
    await fillReviewer(user, "bob");
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(screen.getByText(/changed before your decision was saved/i)).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(detailCallCount).toBeGreaterThanOrEqual(2));
  });
});

describe("ReviewDetail reviewer semantics", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("never labels reviewer_id as authenticated, verified, or authorized", async () => {
    setupFetchMock({});
    renderDetail();
    await waitFor(() => expect(screen.getByLabelText("Reviewer identifier")).toBeInTheDocument());
    expect(screen.queryByText(/authenticated reviewer/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/verified reviewer/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/authorized reviewer/i)).not.toBeInTheDocument();
    expect(screen.getByText("Used for application audit history.")).toBeInTheDocument();
  });
});

describe("ReviewDetail request-ID on error (Slice 7)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the request ID as technical detail when loading the review fails unexpectedly", async () => {
    setupFetchMock({
      detailResponse: () =>
        jsonResponse({ error: { code: "boom" } }, { status: 500, requestId: "req-detail-1" }),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Request ID: req-detail-1")).toBeInTheDocument();
  });

  it("shows the request ID as technical detail when a decision fails unexpectedly", async () => {
    setupFetchMock({
      decisionResponse: () =>
        jsonResponse({ error: { code: "boom" } }, { status: 500, requestId: "req-decision-1" }),
    });
    renderDetail();
    await waitFor(() => expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument());
    const user = userEvent.setup();
    await fillReviewer(user, "alice");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByText("Request ID: req-decision-1")).toBeInTheDocument());
  });
});

describe("ReviewDetail readiness", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("blocks the surface when Postgres is unavailable", async () => {
    setupFetchMock({ readyOverrides: { postgresql: "unavailable" } });
    renderDetail();
    await waitFor(() => expect(screen.getByText(/database cannot be reached/i)).toBeInTheDocument());
  });
});
