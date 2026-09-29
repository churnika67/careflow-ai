import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AskCareFlow } from "./AskCareFlow";
import { SystemStatusProvider } from "./SystemStatusProvider";

function jsonResponse(body: unknown, init?: { status?: number; requestId?: string }) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (init?.requestId) headers.set("X-Request-ID", init.requestId);
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

const LIVE_OK = { status: "alive", service: "careflow-ai" };

function readyPayload(overrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>) {
  return {
    status: overrides?.qdrant === "unavailable" ? "unready" : "ready",
    service: "careflow-ai",
    version: "0.1.0",
    dependencies: {
      postgresql: { status: overrides?.postgresql ?? "ok" },
      qdrant: { status: overrides?.qdrant ?? "ok" },
      redis: { status: overrides?.redis ?? "ok" },
    },
  };
}

const SUPPORTED_ANSWER = {
  answer:
    "CMS evidence [d9eb65be-cab7-5ee4-9fdb-d94e370fd15b]:\nA. General Requirements for Coverage of Hospital Beds\n\nA physician's prescription and additional documentation must establish medical necessity.",
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
  abstention_reason: null,
};

const ABSTAINED_ANSWER = {
  answer: "Insufficient evidence.",
  citations: [],
  insufficient_evidence: true,
  retrieved_chunk_ids: [],
  model_provider: "deterministic",
  model_name: "first-evidence-v1",
  prompt_version: "cms-extractive-v1",
  abstention_reason: "no_eligible_evidence",
};

function setupFetchMock(options: {
  queryResponse?: () => Response | Promise<Response>;
  readyOverrides?: Partial<Record<"postgresql" | "qdrant" | "redis", string>>;
  liveFails?: boolean;
}) {
  const queryImpl = vi.fn(async (url: string) => {
    const path = url.replace("http://localhost:8000", "");
    if (path === "/live") {
      if (options.liveFails) throw new TypeError("Failed to fetch");
      return jsonResponse(LIVE_OK);
    }
    if (path === "/ready") return jsonResponse(readyPayload(options.readyOverrides));
    if (path === "/query") return options.queryResponse ? options.queryResponse() : jsonResponse(SUPPORTED_ANSWER);
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", queryImpl);
  return queryImpl;
}

function renderAskCareFlow() {
  return render(
    <SystemStatusProvider>
      <AskCareFlow />
    </SystemStatusProvider>,
  );
}

async function waitForReady() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeEnabled());
}

describe("AskCareFlow form", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("blocks an empty question", async () => {
    setupFetchMock({});
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a question/i);
  });

  it("blocks a whitespace-only question", async () => {
    setupFetchMock({});
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "   ");
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));
    expect(screen.getByRole("alert")).toHaveTextContent(/enter a question/i);
  });

  it("submits a valid question and sends it exactly as typed", async () => {
    setupFetchMock({});
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "Does Medicare cover hospital beds?");
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));

    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
    const queryCall = vi.mocked(fetch).mock.calls.find(([url]) => String(url).endsWith("/query"));
    expect(queryCall).toBeDefined();
    const [, init] = queryCall!;
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      question: "Does Medicare cover hospital beds?",
    });
  });

  it("disables the button and shows searching text while submitting", async () => {
    let resolveQuery!: (value: Response) => void;
    setupFetchMock({
      queryResponse: () => new Promise((resolve) => (resolveQuery = resolve)),
    });
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "Does Medicare cover hospital beds?");
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));

    expect(screen.getByRole("button", { name: "Searching Medicare policy…" })).toBeDisabled();
    expect(screen.getByText("Searching Medicare policy…", { selector: "p" })).toBeInTheDocument();

    resolveQuery(jsonResponse(SUPPORTED_ANSWER));
    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
  });

  it("prevents a duplicate submission while one is already in flight", async () => {
    let resolveQuery!: (value: Response) => void;
    const fetchMock = setupFetchMock({
      queryResponse: () => new Promise((resolve) => (resolveQuery = resolve)),
    });
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "Does Medicare cover hospital beds?");
    const button = screen.getByRole("button", { name: "Ask CareFlow" });
    await user.click(button);
    // The button is now disabled, but fire a raw click event to simulate any
    // programmatic double-submit attempt and confirm the guard still holds.
    await user.click(screen.getByRole("button", { name: "Searching Medicare policy…" }));

    const queryCalls = fetchMock.mock.calls.filter(([url]) => url.endsWith("/query"));
    expect(queryCalls).toHaveLength(1);
    resolveQuery(jsonResponse(SUPPORTED_ANSWER));
    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
  });

  it("populates the input from an example without auto-submitting", async () => {
    const fetchMock = setupFetchMock({});
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Does Medicare cover hospital beds?" }));

    expect(screen.getByLabelText("Your question")).toHaveValue("Does Medicare cover hospital beds?");
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith("/query"))).toBe(false);
  });
});

describe("AskCareFlow supported answer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the answer, evidence, and citation metadata without fake confidence or prominent request ID", async () => {
    setupFetchMock({ queryResponse: () => jsonResponse(SUPPORTED_ANSWER, { requestId: "req-ok" }) });
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "Does Medicare cover hospital beds?");
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));

    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText(/A physician's prescription/)).toBeInTheDocument();
    expect(screen.getByText("Citation 1")).toBeInTheDocument();
    expect(screen.getByText("Hospital Beds")).toBeInTheDocument();
    expect(screen.getByText(/NCD 227/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view source document/i })).toHaveAttribute(
      "href",
      SUPPORTED_ANSWER.citations[0].source,
    );
    expect(screen.queryByText("req-ok")).not.toBeInTheDocument();
    expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });
});

describe("AskCareFlow abstention", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the dedicated insufficient-evidence message, never a fake answer or negative-coverage language", async () => {
    setupFetchMock({ queryResponse: () => jsonResponse(ABSTAINED_ANSWER) });
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "What dental implant documentation is required?");
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));

    await waitFor(() =>
      expect(screen.getByText(/couldn.t find enough evidence/i)).toBeInTheDocument(),
    );
    expect(screen.getByText(/more specific Medicare policy question/i)).toBeInTheDocument();
    expect(screen.queryByText("Answer")).not.toBeInTheDocument();
    expect(screen.queryByText("Evidence")).not.toBeInTheDocument();
    expect(screen.queryByText(/not covered/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/does not cover/i)).not.toBeInTheDocument();
  });
});

describe("AskCareFlow error handling", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a calm network-error message and allows retry", async () => {
    let shouldFail = true;
    setupFetchMock({
      queryResponse: () => {
        if (shouldFail) {
          shouldFail = false;
          throw new TypeError("Failed to fetch");
        }
        return jsonResponse(SUPPORTED_ANSWER);
      },
    });
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "Does Medicare cover hospital beds?");
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));

    await waitFor(() => expect(screen.getByText(/could not reach the backend/i)).toBeInTheDocument());
    expect(screen.queryByText(/TypeError/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Failed to fetch/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Answer")).toBeInTheDocument());
  });

  it("shows a calm message for a retrieval_unavailable backend error", async () => {
    setupFetchMock({
      queryResponse: () => jsonResponse({ error: { code: "retrieval_unavailable" } }, { status: 503 }),
    });
    renderAskCareFlow();
    await waitForReady();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Your question"), "Does Medicare cover hospital beds?");
    await user.click(screen.getByRole("button", { name: "Ask CareFlow" }));

    await waitFor(() => expect(screen.getByText(/search index is temporarily unavailable/i)).toBeInTheDocument());
  });
});

describe("AskCareFlow system readiness integration", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("disables submission when the backend is unavailable", async () => {
    setupFetchMock({ liveFails: true });
    renderAskCareFlow();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeDisabled(),
    );
    expect(screen.getByText(/currently unavailable/i)).toBeInTheDocument();
  });

  it("disables submission when readiness reports Qdrant unavailable", async () => {
    setupFetchMock({ readyOverrides: { qdrant: "unavailable" } });
    renderAskCareFlow();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeDisabled(),
    );
    expect(screen.getByText(/search index cannot be reached/i)).toBeInTheDocument();
  });

  it("keeps submission enabled when only Redis is unavailable", async () => {
    setupFetchMock({ readyOverrides: { redis: "unavailable" } });
    renderAskCareFlow();
    await waitForReady();
    expect(screen.getByRole("button", { name: "Ask CareFlow" })).toBeEnabled();
  });
});
