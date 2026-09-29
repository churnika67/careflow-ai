import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { decideReview, getReviewDetail, getReviewQueue } from "./reviewsApi";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const SNAPSHOT = {
  request_id: "req-1",
  workflow: "policy_and_structured",
  status: "ok",
  policy: null,
  structured: null,
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
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("getReviewQueue", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests GET /reviews with status/limit/cursor as query params", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ reviews: [], next_cursor: null }));
    await getReviewQueue({ status: "pending", limit: 10, cursor: "abc" });
    const [url] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/reviews?");
    expect(String(url)).toContain("status=pending");
    expect(String(url)).toContain("limit=10");
    expect(String(url)).toContain("cursor=abc");
  });

  it("returns kind=ok with an empty reviews array for an empty queue (not an error)", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ reviews: [], next_cursor: null }));
    const outcome = await getReviewQueue({ status: "pending" });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.page.reviews).toEqual([]);
      expect(outcome.page.next_cursor).toBeNull();
    }
  });

  it("returns kind=ok with reviews and a next_cursor when more pages exist", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ reviews: [reviewCase()], next_cursor: "next-page-token" }),
    );
    const outcome = await getReviewQueue({});
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.page.reviews).toHaveLength(1);
      expect(outcome.page.next_cursor).toBe("next-page-token");
    }
  });

  it("maps a network failure to category=network", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await getReviewQueue({});
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
    const pending = getReviewQueue({});
    const assertion = expect(pending).resolves.toMatchObject({ kind: "error", category: "timeout" });
    await vi.advanceTimersByTimeAsync(6000);
    await assertion;
    vi.useRealTimers();
  });
});

describe("getReviewDetail", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns kind=ok with case and events for a known review", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ case: reviewCase(), events: [] }));
    const outcome = await getReviewDetail("review-1");
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.detail.case.review_id).toBe("review-1");
    }
  });

  it("returns kind=not_found for a 404", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "unknown_review" } }, { status: 404 }),
    );
    const outcome = await getReviewDetail("review-missing");
    expect(outcome.kind).toBe("not_found");
  });

  it("returns kind=error category=invalid for a malformed review ID (422)", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "malformed_review_id" } }, { status: 422 }),
    );
    const outcome = await getReviewDetail("not-a-uuid");
    expect(outcome.kind).toBe("error");
    if (outcome.kind === "error") expect(outcome.category).toBe("invalid");
  });

  it("extracts the request ID", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ case: reviewCase(), events: [] }, { requestId: "req-xyz" }),
    );
    const outcome = await getReviewDetail("review-1");
    expect(outcome.requestId).toBe("req-xyz");
  });
});

describe("decideReview", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts the exact decision payload including expected_version", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(reviewCase({ status: "approved", version: 2 })));
    await decideReview("review-1", {
      reviewer_id: "alice",
      decision: "approve",
      expected_version: 1,
    });
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/reviews/review-1/decision");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ reviewer_id: "alice", decision: "approve", expected_version: 1 });
  });

  it("returns kind=ok with the updated case on success", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(reviewCase({ status: "approved", version: 2 })));
    const outcome = await decideReview("review-1", {
      reviewer_id: "alice",
      decision: "approve",
      expected_version: 1,
    });
    expect(outcome.kind).toBe("ok");
    if (outcome.kind === "ok") {
      expect(outcome.case.status).toBe("approved");
      expect(outcome.case.version).toBe(2);
    }
  });

  it("returns kind=not_found for a 404", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "unknown_review" } }, { status: 404 }),
    );
    const outcome = await decideReview("review-missing", {
      reviewer_id: "alice",
      decision: "approve",
      expected_version: 1,
    });
    expect(outcome.kind).toBe("not_found");
  });

  it("returns kind=conflict with the current case for a 409 (stale version)", async () => {
    const current = reviewCase({ status: "approved", version: 2 });
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "version_conflict" }, review: current }, { status: 409 }),
    );
    const outcome = await decideReview("review-1", {
      reviewer_id: "bob",
      decision: "reject",
      expected_version: 1,
    });
    expect(outcome.kind).toBe("conflict");
    if (outcome.kind === "conflict") {
      expect(outcome.current.status).toBe("approved");
      expect(outcome.current.version).toBe(2);
    }
  });

  it("returns kind=conflict for a terminal case rejecting a further decision", async () => {
    const current = reviewCase({ status: "rejected", version: 2 });
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "version_conflict" }, review: current }, { status: 409 }),
    );
    const outcome = await decideReview("review-1", {
      reviewer_id: "carol",
      decision: "approve",
      expected_version: 2,
    });
    expect(outcome.kind).toBe("conflict");
    if (outcome.kind === "conflict") expect(outcome.current.status).toBe("rejected");
  });

  it("maps a network failure to category=network", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await decideReview("review-1", {
      reviewer_id: "alice",
      decision: "approve",
      expected_version: 1,
    });
    expect(outcome).toEqual({ kind: "error", category: "network", requestId: null });
  });

  it("extracts the request ID from a successful decision", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(reviewCase({ status: "approved", version: 2 }), { requestId: "req-decide" }),
    );
    const outcome = await decideReview("review-1", {
      reviewer_id: "alice",
      decision: "approve",
      expected_version: 1,
    });
    expect(outcome.requestId).toBe("req-decide");
  });
});
