import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReviewQueue } from "./ReviewQueue";
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

function reviewCase(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    review_id: "review-1",
    request_id: "req-1",
    workflow: "policy_and_structured",
    status: "pending",
    trigger_reason_codes: ["explicit_review_requested"],
    evidence_snapshot: {},
    evidence_fingerprint: "a".repeat(64),
    version: 1,
    previous_review_id: null,
    created_at: "2026-01-01T12:00:00Z",
    updated_at: "2026-01-01T12:00:00Z",
    ...overrides,
  };
}

function setupFetchMock(options: {
  queueResponse?: (url: string) => Response | Promise<Response>;
  readyOverrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>;
  liveFails?: boolean;
}) {
  const impl = vi.fn(async (url: string) => {
    const path = url.replace("http://localhost:8000", "");
    if (path === "/live") {
      if (options.liveFails) throw new TypeError("Failed to fetch");
      return jsonResponse(LIVE_OK);
    }
    if (path.startsWith("/ready")) {
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
    if (path.startsWith("/reviews")) {
      return options.queueResponse ? options.queueResponse(path) : jsonResponse({ reviews: [], next_cursor: null });
    }
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

function renderQueue() {
  return render(
    <SystemStatusProvider>
      <ReviewQueue />
    </SystemStatusProvider>,
  );
}

describe("ReviewQueue", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a successful empty state, not an error, when there are no pending reviews", async () => {
    setupFetchMock({ queueResponse: () => jsonResponse({ reviews: [], next_cursor: null }) });
    renderQueue();
    await waitFor(() => expect(screen.getByText("No pending reviews.")).toBeInTheDocument());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders pending review rows with bounded fields, never the full evidence snapshot", async () => {
    setupFetchMock({
      queueResponse: () =>
        jsonResponse({
          reviews: [reviewCase({ trigger_reason_codes: ["specialist_failure"] })],
          next_cursor: null,
        }),
    });
    renderQueue();
    // "Pending" also appears as a status-filter <option>, always present
    // from the first render -- wait for something unambiguous to the
    // loaded review row instead.
    await waitFor(() => expect(screen.getByText("Review ID: review-1")).toBeInTheDocument());
    expect(screen.getByText(/Medicare Policy \+ Synthetic Data/)).toBeInTheDocument();
    expect(screen.getByText(/did not complete successfully/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View review" })).toHaveAttribute("href", "/reviews/review-1");
    // No raw evidence_snapshot JSON dump anywhere in the queue row.
    expect(screen.queryByText(/"evidence_snapshot"/)).not.toBeInTheDocument();
  });

  it("requests GET /reviews with status=pending by default", async () => {
    const fetchMock = setupFetchMock({ queueResponse: () => jsonResponse({ reviews: [], next_cursor: null }) });
    renderQueue();
    await waitFor(() => expect(screen.getByText("No pending reviews.")).toBeInTheDocument());
    const call = fetchMock.mock.calls.find(([url]) => String(url).includes("/reviews?"));
    expect(String(call![0])).toContain("status=pending");
  });

  it("switches the status filter and refetches", async () => {
    const fetchMock = setupFetchMock({
      queueResponse: (path) =>
        path.includes("status=approved")
          ? jsonResponse({ reviews: [reviewCase({ status: "approved" })], next_cursor: null })
          : jsonResponse({ reviews: [], next_cursor: null }),
    });
    renderQueue();
    await waitFor(() => expect(screen.getByText("No pending reviews.")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.selectOptions(screen.getByLabelText("Status"), "approved");

    await waitFor(() => expect(screen.getAllByText("Approved").length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("status=approved"))).toBe(true);
  });

  it("shows Next enabled only when next_cursor is present, and Previous disabled on the first page", async () => {
    setupFetchMock({
      queueResponse: () => jsonResponse({ reviews: [reviewCase()], next_cursor: "cursor-2" }),
    });
    renderQueue();
    await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("Next fetches using the returned cursor", async () => {
    const fetchMock = setupFetchMock({
      queueResponse: (path) =>
        path.includes("cursor=cursor-2")
          ? jsonResponse({ reviews: [reviewCase({ review_id: "review-2" })], next_cursor: null })
          : jsonResponse({ reviews: [reviewCase()], next_cursor: "cursor-2" }),
    });
    renderQueue();
    await waitFor(() => expect(screen.getByRole("button", { name: "Next" })).toBeEnabled());

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText("Review ID: review-2")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("cursor=cursor-2"))).toBe(true);
  });

  it("shows a calm error state with retry on a backend failure", async () => {
    let shouldFail = true;
    setupFetchMock({
      queueResponse: () => {
        if (shouldFail) {
          shouldFail = false;
          throw new TypeError("Failed to fetch");
        }
        return jsonResponse({ reviews: [], next_cursor: null });
      },
    });
    renderQueue();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("No pending reviews.")).toBeInTheDocument());
  });

  it("shows the request ID as technical detail on an unexpected error (Slice 7)", async () => {
    setupFetchMock({
      queueResponse: () => jsonResponse({ error: { code: "boom" } }, { status: 500, requestId: "req-queue-1" }),
    });
    renderQueue();
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Request ID: req-queue-1")).toBeInTheDocument();
  });

  it("blocks the surface when Postgres is unavailable", async () => {
    setupFetchMock({ readyOverrides: { postgresql: "unavailable" } });
    renderQueue();
    await waitFor(() => expect(screen.getByText(/database cannot be reached/i)).toBeInTheDocument());
  });

  it("allows the surface when only Qdrant is unavailable", async () => {
    setupFetchMock({
      readyOverrides: { qdrant: "unavailable" },
      queueResponse: () => jsonResponse({ reviews: [], next_cursor: null }),
    });
    renderQueue();
    await waitFor(() => expect(screen.getByText("No pending reviews.")).toBeInTheDocument());
  });
});
