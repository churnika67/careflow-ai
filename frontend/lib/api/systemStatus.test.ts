import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchSystemStatus } from "./systemStatus";

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

const READY_REDIS_DOWN_STILL_READY = {
  status: "ready",
  service: "careflow-ai",
  version: "0.1.0",
  dependencies: {
    postgresql: { status: "ok" },
    qdrant: { status: "ok" },
    redis: { status: "unavailable" },
  },
};

const UNREADY_POSTGRES_DOWN = {
  status: "unready",
  service: "careflow-ai",
  version: "0.1.0",
  dependencies: {
    postgresql: { status: "unavailable" },
    qdrant: { status: "ok" },
    redis: { status: "ok" },
  },
};

describe("fetchSystemStatus", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("maps a healthy /ready to state=ready", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(READY_ALL_HEALTHY, { requestId: "req-1" }));
    const status = await fetchSystemStatus();
    expect(status.state).toBe("ready");
    expect(status.readiness).toEqual(READY_ALL_HEALTHY);
    expect(status.requestId).toBe("req-1");
    expect(status.error).toBeNull();
  });

  it("maps status=unready from /ready to state=degraded", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(UNREADY_POSTGRES_DOWN, { status: 503 }));
    const status = await fetchSystemStatus();
    expect(status.state).toBe("degraded");
    expect(status.readiness?.dependencies.postgresql.status).toBe("unavailable");
  });

  it("maps a network failure on /live to state=unavailable", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));
    const status = await fetchSystemStatus();
    expect(status.state).toBe("unavailable");
    expect(status.liveness).toBeNull();
    expect(status.readiness).toBeNull();
    expect(status.error).toBeTruthy();
  });

  it("maps a /live success followed by a /ready transport failure to state=degraded, not unavailable", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const status = await fetchSystemStatus();
    expect(status.state).toBe("degraded");
    expect(status.liveness).toEqual(LIVE_OK); // we do know the process is alive
  });

  it("extracts the request ID from the /ready response", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(READY_ALL_HEALTHY, { requestId: "req-abc-123" }));
    const status = await fetchSystemStatus();
    expect(status.requestId).toBe("req-abc-123");
  });

  it("Redis being unavailable does not by itself mark overall state as unavailable or degraded", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(READY_REDIS_DOWN_STILL_READY));
    const status = await fetchSystemStatus();
    expect(status.state).toBe("ready");
    expect(status.readiness?.dependencies.redis.status).toBe("unavailable");
  });
});
