import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SystemOverview } from "./SystemOverview";
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

function renderOverview() {
  return render(
    <SystemStatusProvider>
      <SystemOverview />
    </SystemStatusProvider>,
  );
}

describe("SystemOverview", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows an honest checking state before the backend responds", async () => {
    let resolveLive!: (value: Response) => void;
    vi.mocked(fetch).mockReturnValue(new Promise((resolve) => (resolveLive = resolve)));

    renderOverview();

    expect(screen.getByText(/Checking system status/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Ready$/i)).not.toBeInTheDocument();

    resolveLive(jsonResponse(LIVE_OK));
  });

  it("renders the ready state with all dependencies once /live and /ready succeed", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(READY_ALL_HEALTHY));

    renderOverview();

    await waitFor(() => expect(screen.getByText("Postgres")).toBeInTheDocument());
    expect(screen.getByText("Qdrant")).toBeInTheDocument();
    expect(screen.getByText("Cache (Redis)")).toBeInTheDocument();
    expect(screen.getAllByText("Available")).toHaveLength(3);
  });

  it("renders the unavailable state with a calm message when the backend cannot be reached", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    renderOverview();

    await waitFor(() =>
      expect(screen.getByText(/CareFlow backend is currently unavailable/i)).toBeInTheDocument(),
    );
    // No raw exception text leaked to the user.
    expect(screen.queryByText(/TypeError/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();
  });

  it("shows the data disclaimer", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(READY_ALL_HEALTHY));
    renderOverview();
    expect(
      screen.getByText(/public CMS policy information and synthetic/i),
    ).toBeInTheDocument();
  });

  it("makes clear that Redis is optional and never affects overall readiness (Slice 7)", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(READY_ALL_HEALTHY));
    renderOverview();
    await waitFor(() => expect(screen.getByText("Cache (Redis)")).toBeInTheDocument());
    expect(screen.getByText("Cache (Redis)").closest("li")).toHaveTextContent("(optional)");
    expect(
      screen.getByText(/redis backs an optional performance cache only and never affects overall system status/i),
    ).toBeInTheDocument();
    // Postgres/Qdrant are never described as optional.
    expect(screen.getByText("Postgres").closest("li")).not.toHaveTextContent("(optional)");
    expect(screen.getByText("Qdrant").closest("li")).not.toHaveTextContent("(optional)");
  });

  it("does not render request ID prominently when everything is healthy", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse(LIVE_OK))
      .mockResolvedValueOnce(jsonResponse(READY_ALL_HEALTHY, { requestId: "req-xyz" }));
    renderOverview();
    await waitFor(() => expect(screen.getByText("Postgres")).toBeInTheDocument());
    expect(screen.queryByText("req-xyz")).not.toBeInTheDocument();
  });
});
