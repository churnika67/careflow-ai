import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Analytics } from "./Analytics";
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

const SNAPSHOT_OK = {
  source: "phase12_artifact_snapshot",
  phase: "Phase 12",
  generated_note: "A curated snapshot.",
  datasets: {
    development: {
      dataset_version: "cms-retrieval-v1",
      case_count: 32,
      positive_cases: 25,
      negative_cases: 7,
      description: "development/regression evaluation set",
      limitation: "8 of 32 cases reuse earlier development questions.",
    },
    held_out: {
      dataset_version: "cms-retrieval-heldout-v1",
      case_count: 12,
      positive_cases: 10,
      negative_cases: 2,
      description: "project-authored held-out engineering evaluation set",
      limitation: "Small sample (12 cases, 10 positive).",
    },
  },
  retrieval_baseline: {
    development: {
      experiment_id: "eb59bc90_774ea9a697a1",
      artifact_path: "x",
      metrics: {
        dense: { overall: { count: 25, "Hit@1": 0.88, "Hit@1_hits": 22, "Hit@1_total": 25, "Hit@3": 0.96, "Hit@3_hits": 24, "Hit@3_total": 25, "Hit@5": 1.0, "Hit@5_hits": 25, "Hit@5_total": 25, "MRR@5": 0.928 } },
        bm25: { overall: { count: 25, "Hit@1": 0.96, "Hit@1_hits": 24, "Hit@1_total": 25, "Hit@3": 1.0, "Hit@3_hits": 25, "Hit@3_total": 25, "Hit@5": 1.0, "Hit@5_hits": 25, "Hit@5_total": 25, "MRR@5": 0.98 } },
        hybrid: { overall: { count: 25, "Hit@1": 0.96, "Hit@1_hits": 24, "Hit@1_total": 25, "Hit@3": 1.0, "Hit@3_hits": 25, "Hit@3_total": 25, "Hit@5": 1.0, "Hit@5_hits": 25, "Hit@5_total": 25, "MRR@5": 0.98 } },
        hybrid_reranked: { overall: { count: 25, "Hit@1": 0.96, "Hit@1_hits": 24, "Hit@1_total": 25, "Hit@3": 1.0, "Hit@3_hits": 25, "Hit@3_total": 25, "Hit@5": 1.0, "Hit@5_hits": 25, "Hit@5_total": 25, "MRR@5": 0.98 } },
      },
    },
    held_out: {
      experiment_id: "eb59bc90_a223469082ce",
      artifact_path: "x",
      metrics: {
        dense: { overall: { count: 10, "Hit@1": 0.7, "Hit@1_hits": 7, "Hit@1_total": 10, "Hit@3": null, "Hit@5": null, "MRR@5": null } },
        bm25: { overall: { count: 10, "Hit@1": 0.7, "Hit@1_hits": 7, "Hit@1_total": 10, "Hit@3": null, "Hit@5": null, "MRR@5": null } },
        hybrid: { overall: { count: 10, "Hit@1": 0.7, "Hit@1_hits": 7, "Hit@1_total": 10, "Hit@3": 0.9, "Hit@3_hits": 9, "Hit@3_total": 10, "Hit@5": 0.9, "Hit@5_hits": 9, "Hit@5_total": 10, "MRR@5": 0.7833 } },
        hybrid_reranked: { overall: { count: 10, "Hit@1": 0.7, "Hit@1_hits": 7, "Hit@1_total": 10, "Hit@3": 1.0, "Hit@3_hits": 10, "Hit@3_total": 10, "Hit@5": 1.0, "Hit@5_hits": 10, "Hit@5_total": 10, "MRR@5": 0.8333 } },
      },
    },
  },
  reranker_comparison: {
    experiment_id: "eb59bc90_reranker_comparison",
    artifact_path: "x",
    metrics: {
      development: {
        hybrid_metrics: {},
        hybrid_reranked_metrics: {},
        rank_change_counts: { improved: 1, unchanged: 23, degraded: 1 },
      },
      held_out: {
        hybrid_metrics: {},
        hybrid_reranked_metrics: {},
        rank_change_counts: { improved: 2, unchanged: 8, degraded: 0 },
      },
    },
  },
  threshold: {
    grid: [0.4, 0.45, 0.5, 0.55, 0.6],
    production_threshold: 0.6,
    case_transitions_observed: 27,
    known_issue: {
      case_id: "cms-v1-032",
      gate_score_at_production_threshold: 0.613495,
      note: "Still answers at every tested threshold.",
    },
  },
  citation_metric: {
    definition: "CITATION_REFERENCES_EXPECTED_EVIDENCE definition text.",
    development: {
      hybrid: { citation_expected_evidence_rate: 0.9545454545454546 },
      hybrid_reranked: { citation_expected_evidence_rate: 0.9545454545454546 },
    },
    held_out: {
      hybrid: { citation_expected_evidence_rate: 0.7 },
      hybrid_reranked: { citation_expected_evidence_rate: null },
    },
  },
  latency: {
    experiment_id: "eb59bc90_latency_1790202561",
    artifact_path: "x",
    metrics: {
      retrieval_and_reranker: {
        development: {
          stages: {
            dense: { calls: 96, median_ms: 16.02, p95_ms: 22.11 },
            rerank_only: { calls: 96, median_ms: 426.34, p95_ms: 643.4 },
          },
        },
        held_out: { stages: { dense: { calls: 36, median_ms: 16.9, p95_ms: 28.4 } } },
      },
      boundaries: {
        multi_agent: { policy_only: { calls: 10, median_ms: 25.63, p95_ms: 26.42 } },
        structured_tools: { get_beneficiary_summary: { calls: 30, median_ms: 0.25, p95_ms: 0.38 } },
        review_policy: { review_not_required: { calls: 30, median_ms: 0.0007, p95_ms: 0.0009 } },
        review_persistence: { review_case_creation: { calls: 10, median_ms: 0.89, p95_ms: 1.86 } },
      },
    },
  },
  cost_tokens: { status: "not_evaluated", note: "No LLM provider was ever exercised." },
  claim_matrix: {
    supported: 6,
    partially_supported: 10,
    not_evaluated: 11,
    out_of_scope: 3,
    total: 30,
    source: "docs/evaluation/phase12_claim_matrix.md",
  },
  gaps: {
    open: 5,
    out_of_scope_phase12: 4,
    documented_limitation: 4,
    total: 13,
    source: "docs/evaluation/phase12_gap_registry.json",
    entries: [
      {
        gap_id: "EVAL-RUNTIME-CONFIG-DRIFT",
        title: "Evaluated retrieval configuration differs from the live multi-agent runtime configuration",
        category: "configuration",
        status: "OPEN",
        evidence: "Live runtime resolves to dense/no-rerank.",
        impact_on_claims: "Retrieval-quality results describe the hybrid+rerank pipeline only.",
      },
      {
        gap_id: "EVAL-ROUTING-ACCURACY-NOT-EVALUATED",
        title: "No representative routing-accuracy benchmark exists",
        category: "measurement-gap",
        status: "OPEN",
        evidence: "No labeled routing dataset was constructed.",
        impact_on_claims: "Only 'deterministic router behavior is tested' is supported.",
      },
      {
        gap_id: "EVAL-SMALL-HELDOUT-SAMPLE",
        title: "The held-out evaluation set is small",
        category: "sample-size",
        status: "DOCUMENTED_LIMITATION",
        evidence: "12 cases, 10 positive.",
        impact_on_claims: "One flipped case changes Hit@1 by 10 points.",
      },
      {
        gap_id: "EVAL-ANSWER-CORRECTNESS-NOT-EVALUATED",
        title: "General answer/factual/clinical correctness has not been evaluated",
        category: "measurement-gap",
        status: "OUT_OF_SCOPE_PHASE12",
        evidence: "DeterministicProvider quotes the first eligible chunk.",
        impact_on_claims: "No result may be cited as evidence of answer correctness.",
      },
    ],
  },
  known_limitations: ["Small held-out sample.", "Small policy corpus."],
  provenance: {
    corpus_fingerprint: "1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2",
    evaluated_production_config: {
      chunk_size: 700,
      chunk_overlap: 120,
      evidence_threshold: 0.6,
      retrieval_candidate_k: 10,
      rrf_k: 60,
      embedding_model: "sentence-transformers/all-MiniLM-L6-v2",
      embedding_revision: "x",
      reranker_model: "cross-encoder/ms-marco-MiniLM-L6-v2",
      reranker_revision: "x",
    },
    generation_provider: "deterministic",
    runtime_config_drift_warning: "EVAL-RUNTIME-CONFIG-DRIFT: the live runtime differs.",
  },
};

const STRUCTURED_OK = {
  fhir: {
    source: "live_structured_query",
    dataset: "synthea_fhir",
    patient_count: 5,
    top_n: 5,
    encounter_counts_by_class: { AMB: 169, EMER: 6, IMP: 2 },
    top_conditions: [
      { code: "160903007", code_system: "http://snomed.info/sct", code_display: "Stress (finding)", occurrences: 24 },
    ],
    top_procedures: [],
    top_medications: [],
  },
  synpuf: {
    source: "live_structured_query",
    dataset: "cms_desynpuf",
    beneficiary_count: 15,
    top_n: 5,
    claim_counts_by_type: { outpatient: 191, inpatient: 28 },
    payment_totals_by_type: {
      outpatient: { claim_type: "outpatient", total_payment: "46010.00", claim_count: 191 },
      inpatient: { claim_type: "inpatient", total_payment: "300000.00", claim_count: 28 },
    },
    top_diagnoses: [{ icd9_code: "4019", occurrences: 37 }],
    top_procedures: [],
    top_hcpcs: [],
  },
};

function setupFetchMock(options: {
  snapshotResponse?: () => Response | Promise<Response>;
  structuredResponse?: () => Response | Promise<Response>;
}) {
  const impl = vi.fn(async (url: string) => {
    const path = url.replace("http://localhost:8000", "");
    if (path === "/live") return jsonResponse(LIVE_OK);
    if (path === "/ready") return jsonResponse(READY_ALL_HEALTHY);
    if (path === "/analytics/evaluation/snapshot") {
      return options.snapshotResponse ? options.snapshotResponse() : jsonResponse(SNAPSHOT_OK);
    }
    if (path === "/analytics/structured/overview") {
      return options.structuredResponse ? options.structuredResponse() : jsonResponse(STRUCTURED_OK);
    }
    throw new Error(`Unexpected fetch to ${path}`);
  });
  vi.stubGlobal("fetch", impl);
  return impl;
}

function renderAnalytics() {
  return render(
    <SystemStatusProvider>
      <Analytics />
    </SystemStatusProvider>,
  );
}

describe("Analytics", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders both panel headings", async () => {
    setupFetchMock({});
    renderAnalytics();
    expect(screen.getByRole("heading", { name: "Evaluation Snapshot" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Structured Analytics" })).toBeInTheDocument();
  });

  it("shows a loading state before the backend responds", async () => {
    setupFetchMock({ snapshotResponse: () => new Promise(() => {}) });
    renderAnalytics();
    await waitFor(() => expect(screen.getByText(/Loading evaluation snapshot/i)).toBeInTheDocument());
  });

  it("renders real claim matrix and gap counts once the snapshot loads", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Claim Matrix" })).toBeInTheDocument());
    const claimMatrixCard = screen.getByRole("heading", { name: "Claim Matrix" }).closest("div");
    expect(claimMatrixCard).not.toBeNull();
    expect(claimMatrixCard).toHaveTextContent("Supported6");
    expect(claimMatrixCard).toHaveTextContent("Partially supported10");
    expect(claimMatrixCard).toHaveTextContent("Not evaluated11");
    expect(claimMatrixCard).toHaveTextContent("Out of scope3");

    const gapsCard = screen.getByRole("heading", { name: "Open Evaluation Gaps" }).closest("div");
    expect(gapsCard).not.toBeNull();
    expect(gapsCard).toHaveTextContent(/5 open/i);
  });

  it("shows a calm error and retry when the evaluation snapshot is unavailable", async () => {
    setupFetchMock({ snapshotResponse: () => jsonResponse({ error: { code: "evaluation_snapshot_unavailable" } }, { status: 503 }) });
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByText(/temporarily unavailable/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("shows a calm error when structured analytics is unavailable", async () => {
    setupFetchMock({
      structuredResponse: () => jsonResponse({ error: { code: "structured_overview_unavailable" } }, { status: 503 }),
    });
    renderAnalytics();
    await waitFor(() => expect(screen.getAllByText(/temporarily unavailable/i).length).toBeGreaterThan(0));
  });

  it("does not hide the Evaluation Snapshot panel when Structured Analytics fails", async () => {
    setupFetchMock({
      structuredResponse: () => jsonResponse({ error: { code: "structured_overview_unavailable" } }, { status: 503 }),
    });
    renderAnalytics();
    // The failing panel shows its own error...
    await waitFor(() => expect(screen.getAllByText(/temporarily unavailable/i).length).toBeGreaterThan(0));
    // ...while the healthy Evaluation Snapshot panel still renders its real content.
    expect(screen.getByRole("heading", { name: "Evaluation Overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Claim Matrix" })).toBeInTheDocument();
  });

  it("does not hide the Structured Analytics panel when the Evaluation Snapshot fails", async () => {
    setupFetchMock({
      snapshotResponse: () => jsonResponse({ error: { code: "evaluation_snapshot_unavailable" } }, { status: 503 }),
    });
    renderAnalytics();
    // The failing panel shows its own error...
    await waitFor(() => expect(screen.getAllByText(/temporarily unavailable/i).length).toBeGreaterThan(0));
    // ...while the healthy Structured Analytics panel still renders its real content.
    expect(screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" })).toBeInTheDocument();
  });

  it("renders a not-evaluated citation rate as text, never as 0%", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Citation Expected-Evidence Match" })).toBeInTheDocument(),
    );
    expect(screen.getAllByText("95.5%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Not evaluated").length).toBeGreaterThan(0);
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("renders live FHIR and SynPUF aggregates as two separate, never-joined dataset sections", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" })).toBeInTheDocument(),
    );
    expect(screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" })).toBeInTheDocument();
  });

  it("renders frequency tables with accessible table semantics", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByText("Top 5 condition codes")).toBeInTheDocument());
    const table = screen.getByText("Top 5 condition codes").closest("table");
    expect(table).not.toBeNull();
    expect(screen.getAllByRole("columnheader").length).toBeGreaterThan(0);
  });

  // --- Slice 2: retrieval visualization -----------------------------------

  it("renders retrieval Hit@k/MRR@5 labels, exact numerator/denominator, and keeps development/held-out separate", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Retrieval Quality" })).toBeInTheDocument());
    const section = screen.getByRole("heading", { name: "Retrieval Quality" }).closest("div")!;
    // Development hybrid_reranked Hit@1 = 0.96 (24/25)
    expect(section).toHaveTextContent("0.96 (24/25)");
    // Held-out hybrid Hit@1 = 0.70 (7/10)
    expect(section).toHaveTextContent("0.70 (7/10)");
    expect(section).toHaveTextContent("Development");
    expect(section).toHaveTextContent("Held-out");
    // No single combined/averaged retrieval score anywhere in this section.
    expect(section).not.toHaveTextContent(/overall score|combined score|average score/i);
  });

  it("never labels retrieval metrics as answer correctness", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Retrieval Quality" })).toBeInTheDocument());
    const section = screen.getByRole("heading", { name: "Retrieval Quality" }).closest("div")!;
    expect(section).toHaveTextContent(/never answer\s*\n?\s*correctness/i);
  });

  // --- Slice 2: reranker visualization -------------------------------------

  it("shows reranker improved/unchanged/degraded counts with latency alongside, no winner language", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Reranker Analysis" })).toBeInTheDocument());
    const analysisSection = screen.getByRole("heading", { name: "Reranker Analysis" }).closest("div")!;
    expect(analysisSection).toHaveTextContent("1");
    expect(analysisSection).toHaveTextContent("23");
    expect(analysisSection).toHaveTextContent(/no winner is declared/i);

    const tradeoffSection = screen
      .getByRole("heading", { name: "Reranker Quality / Latency Tradeoff" })
      .closest("div")!;
    expect(tradeoffSection).toHaveTextContent("426.34");
    expect(tradeoffSection).toHaveTextContent(/not a recommendation for or against/i);

    expect(document.body).not.toHaveTextContent(/reranking is better|reranking should be enabled/i);
  });

  // --- Slice 2: threshold visualization -------------------------------------

  it("renders all threshold grid points, the production threshold, and the known high-similarity case with no mutation control", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Threshold Behavior" })).toBeInTheDocument());
    const section = screen.getByRole("heading", { name: "Threshold Behavior" }).closest("div")!;
    expect(section).toHaveTextContent("0.4 / 0.45 / 0.5 / 0.55 / 0.6");
    expect(section).toHaveTextContent("cms-v1-032");
    expect(section).toHaveTextContent("0.613495");
    expect(section).toHaveTextContent(/not a clinical failure/i);
    // No interactive threshold control anywhere on the page.
    expect(screen.queryByRole("slider")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /apply threshold/i })).not.toBeInTheDocument();
  });

  // --- Slice 2: latency visualization -----------------------------------

  it("renders latency in milliseconds, separated by category, with the local/service-level limitation stated", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Latency" })).toBeInTheDocument());
    const section = screen.getByRole("heading", { name: "Latency" }).closest("div")!;
    expect(section).toHaveTextContent(/local development-machine, service-level/i);
    expect(section).toHaveTextContent("Retrieval & reranker stages -- development");
    expect(section).toHaveTextContent("Structured tools (5 of 18 registered tools)");
    expect(section).toHaveTextContent("Multi-agent workflows");
    expect(section).toHaveTextContent("16.0 ms");
  });

  // --- Slice 2: citation semantics -----------------------------------

  it("never labels the citation metric as accuracy, correctness, or an entailment score", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Citation Expected-Evidence Match" })).toBeInTheDocument(),
    );
    const section = screen.getByRole("heading", { name: "Citation Expected-Evidence Match" }).closest("div")!;
    expect(section).not.toHaveTextContent(/citation accuracy/i);
    expect(section).not.toHaveTextContent(/citation correctness/i);
    expect(section).not.toHaveTextContent(/entailment score/i);
    expect(section).toHaveTextContent(/does not establish citation entailment/i);
  });

  // --- Slice 2: claim matrix -----------------------------------

  it("renders all four claim matrix categories with no overall percentage score", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Claim Matrix" })).toBeInTheDocument());
    const section = screen.getByRole("heading", { name: "Claim Matrix" }).closest("div")!;
    expect(section).toHaveTextContent("Supported");
    expect(section).toHaveTextContent("Partially supported");
    expect(section).toHaveTextContent("Not evaluated");
    expect(section).toHaveTextContent("Out of scope");
    expect(section).not.toHaveTextContent(/%/);
  });

  // --- Slice 2: evaluation gaps -----------------------------------

  it("groups gap entries by status and surfaces runtime configuration drift prominently", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Open Evaluation Gaps" })).toBeInTheDocument());
    const section = screen.getByRole("heading", { name: "Open Evaluation Gaps" }).closest("div")!;
    expect(section).toHaveTextContent("Open (2)");
    expect(section).toHaveTextContent("Documented limitation (1)");
    expect(section).toHaveTextContent("Out of scope (Phase 12) (1)");
    expect(section).toHaveTextContent("Runtime configuration drift");
    expect(section).toHaveTextContent(/live runtime resolves to dense\/no-rerank/i);
    expect(section).toHaveTextContent("routing-accuracy");
  });

  // --- Slice 2: provenance -----------------------------------

  it("renders provenance experiment metadata with no secret or local-machine field, and the snapshot label", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByText(/Phase 12 Evaluation Snapshot/)).toBeInTheDocument());
    const summary = screen.getByText("Show experiment metadata and evaluated configuration");
    summary.click();
    expect(screen.getByText("eb59bc90_774ea9a697a1")).toBeInTheDocument();
    expect(screen.getByText(/1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/\/Users\//);
    expect(document.body).not.toHaveTextContent(/api[_-]?key/i);
  });

  // --- Slice 2 (Phase 16): Evaluation Provenance interaction -----------------

  it("starts the Evaluation Provenance details collapsed, and expanding it via a real click reveals the real fields", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Evaluation Provenance" })).toBeInTheDocument());

    const details = screen
      .getByText("Show experiment metadata and evaluated configuration")
      .closest("details") as HTMLDetailsElement;
    expect(details).not.toBeNull();

    // Collapsed initial state: the <details> element itself is not open,
    // and its field content is not visible (native <details> semantics --
    // the content is present in the DOM but hidden until expanded).
    expect(details.open).toBe(false);
    expect(screen.queryByText("eb59bc90_774ea9a697a1")).not.toBeVisible();

    // A real user interaction (not a raw DOM .click()) expands it.
    const user = userEvent.setup();
    await user.click(screen.getByText("Show experiment metadata and evaluated configuration"));

    expect(details.open).toBe(true);
    // Real provenance fields become visible -- not fabricated placeholder text.
    expect(screen.getByText("eb59bc90_774ea9a697a1")).toBeVisible();
    expect(screen.getByText("eb59bc90_a223469082ce")).toBeVisible();
    expect(screen.getByText("eb59bc90_reranker_comparison")).toBeVisible();
    expect(screen.getByText(/1e55c381f68f3e0fe021b217a49ad05d246e87943a7f33cc5780e3e1bf31bcc2/)).toBeVisible();
  });

  // --- Slice 3: FHIR population analytics -----------------------------------

  it("renders FHIR dataset overview, encounter distribution, and code/display/system-preserving frequency tables", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" })).toBeInTheDocument(),
    );
    const section = screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" }).closest("div")!;
    expect(section).toHaveTextContent("Synthea-generated synthetic FHIR data");
    expect(section).toHaveTextContent("Patients in sample");
    expect(section).toHaveTextContent("5");
    expect(section).toHaveTextContent("Encounter Distribution");
    expect(section).toHaveTextContent("AMB");
    expect(section).toHaveTextContent("169");
    expect(section).toHaveTextContent("Top 5 condition codes");
    expect(section).toHaveTextContent("160903007");
    expect(section).toHaveTextContent("http://snomed.info/sct");
    expect(section).toHaveTextContent("Stress (finding)");
    // The only mentions of "risk"/"prevalence" are the disclaimer that
    // frequency is NOT such a claim -- never an actual risk/prevalence figure.
    expect(section).toHaveTextContent(/not a clinical risk or prevalence claim/i);
  });

  it("shows a meaningful empty state for a FHIR aggregate with zero rows, not an error", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" })).toBeInTheDocument(),
    );
    const section = screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" }).closest("div")!;
    expect(section).toHaveTextContent("No procedure-frequency rows available.");
    expect(section).toHaveTextContent("No medication-frequency rows available.");
  });

  // --- Slice 3: SynPUF claims analytics -----------------------------------

  it("renders SynPUF dataset overview, claim distribution, payment totals, and code-only frequency tables", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" })).toBeInTheDocument(),
    );
    const section = screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" }).closest("div")!;
    expect(section).toHaveTextContent("CMS DE-SynPUF synthetic/sample claims data");
    expect(section).toHaveTextContent("Beneficiaries in sample");
    expect(section).toHaveTextContent("15");
    expect(section).toHaveTextContent("Claim Distribution");
    expect(section).toHaveTextContent("outpatient");
    expect(section).toHaveTextContent("191");
    expect(section).toHaveTextContent("$46,010.00");
    expect(section).toHaveTextContent("$300,000.00");
    expect(section).toHaveTextContent("Top 5 diagnosis codes");
    expect(section).toHaveTextContent("4019");
    // No description field is invented for SynPUF codes.
    expect(section).not.toHaveTextContent(/hypertension/i);
  });

  it("shows a meaningful empty state for a SynPUF aggregate with zero rows, not an error", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" })).toBeInTheDocument(),
    );
    const section = screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" }).closest("div")!;
    expect(section).toHaveTextContent("No procedure-frequency rows available.");
    expect(section).toHaveTextContent("No HCPCS-frequency rows available.");
  });

  // --- Slice 3: dataset boundary -----------------------------------

  it("never renders a patient_id, beneficiary_id, or a cross-dataset linkage claim", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" })).toBeInTheDocument(),
    );
    expect(document.body).not.toHaveTextContent(/patient_id/i);
    expect(document.body).not.toHaveTextContent(/beneficiary_id/i);
    expect(document.body).not.toHaveTextContent(/linked to|matched with|cross-referenced with/i);
    expect(document.body).toHaveTextContent(/never joined or cross-referenced/i);
  });

  it("keeps the two dataset sections visually and structurally separate even when both render at once", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" })).toBeInTheDocument(),
    );
    const fhirSection = screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" }).closest("div")!;
    const synpufSection = screen
      .getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" })
      .closest("div")!;
    expect(fhirSection).not.toBe(synpufSection);
    expect(fhirSection.contains(synpufSection)).toBe(false);
    expect(synpufSection.contains(fhirSection)).toBe(false);
  });

  // --- Slice 3: payment formatting -----------------------------------

  it("formats payment totals as exact USD and never renders a missing payment as $0", async () => {
    setupFetchMock({
      structuredResponse: () =>
        jsonResponse({
          fhir: {
            source: "live_structured_query",
            dataset: "synthea_fhir",
            patient_count: 5,
            top_n: 5,
            encounter_counts_by_class: {},
            top_conditions: [],
            top_procedures: [],
            top_medications: [],
          },
          synpuf: {
            source: "live_structured_query",
            dataset: "cms_desynpuf",
            beneficiary_count: 15,
            top_n: 5,
            claim_counts_by_type: { outpatient: 191 },
            payment_totals_by_type: {
              outpatient: { claim_type: "outpatient", total_payment: null, claim_count: 191 },
            },
            top_diagnoses: [],
            top_procedures: [],
            top_hcpcs: [],
          },
        }),
    });
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" })).toBeInTheDocument(),
    );
    const section = screen.getByRole("heading", { name: "Synthetic SynPUF Claims Analytics" }).closest("div")!;
    expect(section).toHaveTextContent("Not evaluated");
    expect(section).not.toHaveTextContent("$0.00");
  });

  // --- Slice 3: top-N semantics -----------------------------------

  it("labels frequency tables as Top 5, never implying a complete distribution", async () => {
    setupFetchMock({});
    renderAnalytics();
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Synthetic FHIR Population Analytics" })).toBeInTheDocument(),
    );
    expect(screen.getByText("Top 5 condition codes")).toBeInTheDocument();
    expect(screen.getByText("Top 5 diagnosis codes")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/condition distribution\b/i);
  });
});
