import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPost } from "./client";
import { ApiClientError } from "./errors";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

describe("apiGet", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("returns typed data, status, ok, and requestId for a successful response", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ status: "alive", service: "careflow-ai" }, { requestId: "req-123" }),
    );
    const result = await apiGet<{ status: string; service: string }>("/live");
    expect(result.data).toEqual({ status: "alive", service: "careflow-ai" });
    expect(result.status).toBe(200);
    expect(result.ok).toBe(true);
    expect(result.requestId).toBe("req-123");
  });

  it("uses the configured base URL", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}));
    await apiGet("/live");
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/live",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("returns a non-2xx JSON response normally, not as a thrown error", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ status: "unready" }, { status: 503, requestId: "req-503" }),
    );
    const result = await apiGet<{ status: string }>("/ready");
    expect(result.ok).toBe(false);
    expect(result.status).toBe(503);
    expect(result.data).toEqual({ status: "unready" });
    expect(result.requestId).toBe("req-503");
  });

  it("normalizes a network failure into ApiClientError(category: network)", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiGet("/live")).rejects.toMatchObject({
      name: "ApiClientError",
      category: "network",
    });
  });

  it("normalizes an unparseable body into ApiClientError(category: invalid_response)", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("not json", { status: 200, headers: { "Content-Type": "text/plain" } }),
    );
    await expect(apiGet("/live")).rejects.toMatchObject({
      name: "ApiClientError",
      category: "invalid_response",
      status: 200,
    });
  });

  it("aborts and normalizes into ApiClientError(category: timeout) past the configured timeout", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(
      (_url, init) =>
        new Promise((_resolve, reject) => {
          const signal = (init as RequestInit).signal;
          signal?.addEventListener("abort", () => {
            const err = new DOMException("Aborted", "AbortError");
            reject(err);
          });
        }),
    );
    const pending = apiGet("/live", { timeoutMs: 10 });
    const assertion = expect(pending).rejects.toMatchObject({
      name: "ApiClientError",
      category: "timeout",
    });
    await vi.advanceTimersByTimeAsync(20);
    await assertion;
  });

  it("never throws a plain Error that bypasses ApiClientError for network failures", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    try {
      await apiGet("/live");
      expect.unreachable("apiGet should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
    }
  });
});

describe("apiPost", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a JSON body with the correct method and content type", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ answer: "x" }));
    await apiPost("/query", { question: "Does Medicare cover hospital beds?" });
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:8000/query",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ question: "Does Medicare cover hospital beds?" }),
        headers: expect.objectContaining({ "Content-Type": "application/json" }),
      }),
    );
  });

  it("returns a non-2xx JSON body (e.g. a GenerationError) normally, not thrown", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ error: { code: "retrieval_unavailable" } }, { status: 503 }),
    );
    const result = await apiPost<{ error: { code: string } }>("/query", { question: "x" });
    expect(result.ok).toBe(false);
    expect(result.status).toBe(503);
    expect(result.data.error.code).toBe("retrieval_unavailable");
  });

  it("normalizes a network failure the same way as apiGet", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiPost("/query", { question: "x" })).rejects.toMatchObject({
      name: "ApiClientError",
      category: "network",
    });
  });

  it("extracts the request ID from a POST response", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ answer: "x" }, { requestId: "req-post-1" }));
    const result = await apiPost("/query", { question: "x" });
    expect(result.requestId).toBe("req-post-1");
  });
});
