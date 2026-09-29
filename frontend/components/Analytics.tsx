"use client";

import { useEffect, useRef, useState } from "react";
import { useSystemStatusContext } from "./SystemStatusProvider";
import {
  evaluationSnapshotBlockedReason,
  isEvaluationSnapshotAllowed,
} from "@/lib/evaluationSnapshotReadiness";
import {
  isStructuredAnalyticsAllowed,
  structuredAnalyticsBlockedReason,
} from "@/lib/structuredAnalyticsReadiness";
import {
  getEvaluationSnapshot,
  getStructuredAnalyticsOverview,
  type AnalyticsErrorCategory,
} from "@/lib/api/analyticsQuery";
import type {
  EvaluationSnapshotResponse,
  StructuredAnalyticsOverview,
  FhirAggregateOverview,
  FhirCodeFrequencyRow,
  SynpufAggregateOverview,
  SynpufDiagnosisFrequencyRow,
  SynpufProcedureFrequencyRow,
  SynpufHcpcsFrequencyRow,
} from "@/lib/api/analyticsTypes";
import { MetricValue, formatRate } from "./analytics/MetricValue";
import { AccessibleBarChart, type BarChartRow } from "./analytics/AccessibleBarChart";
import { ComparisonTable, type ComparisonRow } from "./analytics/ComparisonTable";
import { LatencyTable, type LatencyStage } from "./analytics/LatencyTable";
import { GapList } from "./analytics/GapList";
import { ProvenanceDetails } from "./analytics/ProvenanceDetails";
import structuredResultStyles from "./structured/StructuredResultStates.module.css";
import styles from "./Analytics.module.css";

const ERROR_MESSAGES: Record<AnalyticsErrorCategory, string> = {
  network: "CareFlow could not reach the backend. Check your connection and try again.",
  timeout: "The request took too long to complete. Please try again.",
  unavailable: "This evidence is temporarily unavailable. Please try again shortly.",
  unexpected: "Something went wrong while loading this data. Please try again.",
};

type SnapshotState =
  | { status: "loading" }
  | { status: "ok"; snapshot: EvaluationSnapshotResponse }
  | { status: "error"; category: AnalyticsErrorCategory; requestId: string | null };

type StructuredState =
  | { status: "loading" }
  | { status: "ok"; overview: StructuredAnalyticsOverview }
  | { status: "error"; category: AnalyticsErrorCategory; requestId: string | null };

function ErrorPanel({
  category,
  requestId,
  onRetry,
}: {
  category: AnalyticsErrorCategory;
  requestId: string | null;
  onRetry: () => void;
}) {
  return (
    <div className={structuredResultStyles.error} role="alert">
      <p>{ERROR_MESSAGES[category]}</p>
      <button type="button" className={structuredResultStyles.retryButton} onClick={onRetry}>
        Retry
      </button>
      {requestId && <p className={structuredResultStyles.technicalDetail}>Request ID: {requestId}</p>}
    </div>
  );
}

function EvaluationSnapshotPanel() {
  const { status: systemStatus } = useSystemStatusContext();
  const [state, setState] = useState<SnapshotState>({ status: "loading" });
  const abortRef = useRef<AbortController | null>(null);

  const allowed = isEvaluationSnapshotAllowed(systemStatus);
  const blockedReason = evaluationSnapshotBlockedReason(systemStatus);

  function load(): void {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    getEvaluationSnapshot(controller.signal).then((outcome) => {
      if (controller.signal.aborted) return;
      if (outcome.kind === "error") {
        setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
        return;
      }
      setState({ status: "ok", snapshot: outcome.snapshot });
    });
  }

  useEffect(() => {
    if (!allowed) return;
    load();
    return () => abortRef.current?.abort();
  }, [allowed]);

  function handleRetry() {
    setState({ status: "loading" });
    load();
  }

  return (
    <section className={styles.panel} aria-labelledby="evaluation-snapshot-heading">
      <h2 id="evaluation-snapshot-heading">Evaluation Snapshot</h2>
      <p className={styles.panelSubheading}>
        A curated snapshot of Phase 12&apos;s existing, already-persisted evaluation artifacts.
        Nothing here re-runs an experiment or re-scores a metric.
      </p>

      {!allowed && blockedReason && <p className={styles.blockedReason}>{blockedReason}</p>}

      {allowed && (
        <div aria-live="polite">
          {state.status === "loading" && <p className={styles.loading}>Loading evaluation snapshot…</p>}
          {state.status === "error" && (
            <ErrorPanel category={state.category} requestId={state.requestId} onRetry={handleRetry} />
          )}
          {state.status === "ok" && <EvaluationSnapshotContent snapshot={state.snapshot} />}
        </div>
      )}
    </section>
  );
}

// --- Shared type shapes for known-but-passthrough nested JSON. These
// mirror the exact fields backend/app/analytics/snapshot.py reads from
// the real Phase 12 artifacts (see docs/phase15_analytics_design.md) --
// not a guess, and not re-validated here (the backend's own tests do
// that); this is only enough typing to render them without `any`.

interface RetrievalOverall {
  count: number;
  "Hit@1": number | null;
  "Hit@1_hits"?: number;
  "Hit@1_total"?: number;
  "Hit@3": number | null;
  "Hit@3_hits"?: number;
  "Hit@3_total"?: number;
  "Hit@5": number | null;
  "Hit@5_hits"?: number;
  "Hit@5_total"?: number;
  "MRR@5": number | null;
}

interface RetrievalModeMetrics {
  dense?: { overall: RetrievalOverall };
  bm25?: { overall: RetrievalOverall };
  hybrid?: { overall: RetrievalOverall };
  hybrid_reranked?: { overall: RetrievalOverall };
}

interface RerankerDatasetComparison {
  hybrid_metrics: Record<string, number | null>;
  hybrid_reranked_metrics: Record<string, number | null>;
  rank_change_counts: { improved: number; unchanged: number; degraded: number };
}

interface RerankerComparisonMetrics {
  development: RerankerDatasetComparison;
  held_out: RerankerDatasetComparison;
}

interface LatencyStageRaw {
  calls?: number | null;
  median_ms?: number | null;
  p95_ms?: number | null;
}

interface LatencyMetrics {
  retrieval_and_reranker: {
    development: { stages: Record<string, LatencyStageRaw> };
    held_out: { stages: Record<string, LatencyStageRaw> };
  };
  boundaries: {
    multi_agent: Record<string, LatencyStageRaw>;
    structured_tools: Record<string, LatencyStageRaw>;
    review_policy: Record<string, LatencyStageRaw>;
    review_persistence: Record<string, LatencyStageRaw>;
  };
}

const MODE_ORDER = ["dense", "bm25", "hybrid", "hybrid_reranked"] as const;
const MODE_LABELS: Record<(typeof MODE_ORDER)[number], string> = {
  dense: "Dense",
  bm25: "BM25",
  hybrid: "Hybrid",
  hybrid_reranked: "Hybrid + reranker",
};

const RETRIEVAL_STAGE_LABELS: Record<string, string> = {
  dense: "Dense retrieval",
  bm25: "BM25 retrieval",
  hybrid: "Hybrid retrieval",
  hybrid_candidates_with_gate: "Hybrid candidates + evidence gate",
  rerank_only: "Reranker only",
};

function formatHitCell(overall: RetrievalOverall | undefined, key: "Hit@1" | "Hit@3" | "Hit@5"): string | null {
  if (!overall) return null;
  const value = overall[key];
  if (value === null || value === undefined) return null;
  const hits = overall[`${key}_hits` as keyof RetrievalOverall];
  const total = overall[`${key}_total` as keyof RetrievalOverall];
  return hits !== undefined && total !== undefined ? `${value.toFixed(2)} (${hits}/${total})` : value.toFixed(2);
}

function formatMrrCell(overall: RetrievalOverall | undefined): string | null {
  if (!overall) return null;
  const value = overall["MRR@5"];
  return value === null || value === undefined ? null : value.toFixed(3);
}

function retrievalTableRows(metrics: RetrievalModeMetrics): ComparisonRow[] {
  return MODE_ORDER.map((mode) => {
    const overall = metrics[mode]?.overall;
    return {
      key: mode,
      label: MODE_LABELS[mode],
      cells: [
        formatHitCell(overall, "Hit@1"),
        formatHitCell(overall, "Hit@3"),
        formatHitCell(overall, "Hit@5"),
        formatMrrCell(overall),
      ],
    };
  });
}

function retrievalBarRows(metrics: RetrievalModeMetrics): BarChartRow[] {
  return MODE_ORDER.map((mode) => {
    const overall = metrics[mode]?.overall;
    const value = overall?.["Hit@1"] ?? null;
    return {
      key: mode,
      label: MODE_LABELS[mode],
      value,
      displayText: formatHitCell(overall, "Hit@1") ?? "Not evaluated",
    };
  });
}

function latencyStages(source: Record<string, LatencyStageRaw>, labels?: Record<string, string>): LatencyStage[] {
  return Object.entries(source).map(([name, stage]) => ({
    name: labels?.[name] ?? name,
    medianMs: stage.median_ms,
    p95Ms: stage.p95_ms,
    calls: stage.calls,
  }));
}

function EvaluationOverviewSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  return (
    <div className={styles.card}>
      <h3>Evaluation Overview</h3>
      <dl className={styles.claimList}>
        <div>
          <dt>Development/regression cases</dt>
          <dd>{snapshot.datasets.development.case_count}</dd>
        </div>
        <div>
          <dt>Development positives / negatives</dt>
          <dd>
            {snapshot.datasets.development.positive_cases} / {snapshot.datasets.development.negative_cases}
          </dd>
        </div>
        <div>
          <dt>Held-out cases</dt>
          <dd>{snapshot.datasets.held_out.case_count}</dd>
        </div>
        <div>
          <dt>Held-out positives / negatives</dt>
          <dd>
            {snapshot.datasets.held_out.positive_cases} / {snapshot.datasets.held_out.negative_cases}
          </dd>
        </div>
        <div>
          <dt>Production threshold</dt>
          <dd>{snapshot.threshold.production_threshold}</dd>
        </div>
        <div>
          <dt>Generation provider</dt>
          <dd>{snapshot.provenance.generation_provider}</dd>
        </div>
      </dl>
      <p className={styles.cardNote}>
        These figures describe two separate evaluation sets, never a combined or averaged one. No
        overall accuracy, safety, or readiness score is computed anywhere in this project.
      </p>
    </div>
  );
}

function DatasetLimitationsSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  return (
    <div className={styles.cardGrid}>
      <div className={styles.card}>
        <h4>Development / regression set</h4>
        <p className={styles.cardNote}>{snapshot.datasets.development.description}</p>
        <p className={styles.cardNote}>{snapshot.datasets.development.limitation}</p>
      </div>
      <div className={styles.card}>
        <h4>Held-out set</h4>
        <p className={styles.cardNote}>{snapshot.datasets.held_out.description}</p>
        <p className={styles.cardNote}>{snapshot.datasets.held_out.limitation}</p>
      </div>
    </div>
  );
}

function RetrievalQualitySection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  const devMetrics = snapshot.retrieval_baseline.development.metrics as RetrievalModeMetrics;
  const heldOutMetrics = snapshot.retrieval_baseline.held_out.metrics as RetrievalModeMetrics;
  const devRows = retrievalTableRows(devMetrics);
  const heldOutRows = retrievalTableRows(heldOutMetrics);

  return (
    <div className={styles.card}>
      <h3>Retrieval Quality</h3>
      <p className={styles.cardNote}>
        Hit@1: expected evidence ranked first. Hit@3: expected evidence appears in the top 3. Hit@5:
        expected evidence appears in the top 5. MRR@5: reciprocal-rank measure of how early expected
        evidence appears within the top 5. These describe retrieval behavior only -- never answer
        correctness.
      </p>

      <h4>Hit@1 by mode -- development</h4>
      <AccessibleBarChart rows={retrievalBarRows(devMetrics)} />
      <h4>Hit@1 by mode -- held-out</h4>
      <AccessibleBarChart rows={retrievalBarRows(heldOutMetrics)} />

      <ComparisonTable
        caption={`Development (${snapshot.retrieval_baseline.development.experiment_id})`}
        columnHeadings={["Hit@1", "Hit@3", "Hit@5", "MRR@5"]}
        rows={devRows}
      />
      <ComparisonTable
        caption={`Held-out (${snapshot.retrieval_baseline.held_out.experiment_id})`}
        columnHeadings={["Hit@1", "Hit@3", "Hit@5", "MRR@5"]}
        rows={heldOutRows}
      />
      <p className={styles.cardNote}>
        Development and held-out results are kept separate deliberately -- the two samples do not
        carry equal evidentiary strength, and this project never averages them into one figure.
      </p>
    </div>
  );
}

function RerankerAnalysisSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  const metrics = snapshot.reranker_comparison.metrics as unknown as RerankerComparisonMetrics;
  const rows: ComparisonRow[] = [
    {
      key: "development",
      label: "Development",
      cells: [
        metrics.development.rank_change_counts.improved,
        metrics.development.rank_change_counts.unchanged,
        metrics.development.rank_change_counts.degraded,
      ],
    },
    {
      key: "held_out",
      label: "Held-out",
      cells: [
        metrics.held_out.rank_change_counts.improved,
        metrics.held_out.rank_change_counts.unchanged,
        metrics.held_out.rank_change_counts.degraded,
      ],
    },
  ];

  return (
    <div className={styles.card}>
      <h3>Reranker Analysis</h3>
      <p className={styles.cardNote}>
        Same-pool paired comparison (Phase 12 Slice 6, {snapshot.reranker_comparison.experiment_id}) --
        the reranker is the only experimental difference; the pre-rerank candidate pool is identical
        for both arms. This is the authoritative source for the reranker&apos;s causal effect.
      </p>
      <ComparisonTable
        caption="Per-query rank change counts"
        columnHeadings={["Improved", "Unchanged", "Degraded"]}
        rows={rows}
      />
      <p className={styles.cardNote}>
        No winner is declared here, and production reranker configuration is unchanged. A count in
        &quot;improved&quot; or &quot;degraded&quot; describes a measured rank change on this specific
        evaluation set, not a general recommendation.
      </p>
    </div>
  );
}

function RerankerLatencyTradeoffSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  const latencyMetrics = snapshot.latency.metrics as unknown as LatencyMetrics;
  const devStages = latencyMetrics.retrieval_and_reranker.development.stages;
  const rerankMs = devStages.rerank_only?.median_ms;
  const hybridGateMs = devStages.hybrid_candidates_with_gate?.median_ms;
  const ratio = rerankMs != null && hybridGateMs ? rerankMs / hybridGateMs : null;
  const rerankerMetrics = snapshot.reranker_comparison.metrics as unknown as RerankerComparisonMetrics;

  return (
    <div className={styles.card}>
      <h3>Reranker Quality / Latency Tradeoff</h3>
      <p className={styles.cardNote}>
        Development: aggregate Hit@1/3/5/MRR@5 are unchanged by reranking (
        {rerankerMetrics.development.rank_change_counts.improved} improved /{" "}
        {rerankerMetrics.development.rank_change_counts.degraded} degraded, an offsetting pair). Held-out:
        Hit@1 unchanged, some deeper-ranking metrics improved (see the comparison table above).
      </p>
      <ComparisonTable
        caption="Reranker latency cost (development)"
        columnHeadings={["Median ms"]}
        rows={[
          { key: "hybrid_gate", label: "Hybrid candidates + gate", cells: [hybridGateMs ?? null] },
          { key: "rerank_only", label: "Reranker only", cells: [rerankMs ?? null] },
        ]}
      />
      <p className={styles.cardNote}>
        {ratio !== null
          ? `Reranker-only latency is approximately ${ratio.toFixed(1)}x the hybrid candidate-retrieval median on this measurement.`
          : "Reranker latency ratio not evaluated."}{" "}
        This is a measured cost, not a recommendation for or against enabling reranking.
      </p>
    </div>
  );
}

function ThresholdSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  const knownIssue = snapshot.threshold.known_issue as {
    case_id?: string;
    gate_score_at_production_threshold?: number;
    note?: string;
  };
  return (
    <div className={styles.card}>
      <h3>Threshold Behavior</h3>
      <p className={styles.cardNote}>
        Frozen sweep grid: {snapshot.threshold.grid.join(" / ")}. Production threshold:{" "}
        {snapshot.threshold.production_threshold}. This is a read-only report of measured behavior --
        there is no control here that changes the production threshold.
      </p>
      <p>
        {snapshot.threshold.case_transitions_observed} case-level transitions were observed across the
        adjacent threshold pairs in the frozen grid. A transition means one case&apos;s answered/abstained
        status changed between two adjacent threshold values; this describes abstention-gate behavior,
        not a model-accuracy score.
      </p>
      <div className={styles.card} data-status="OPEN">
        <h4>Known issue: {knownIssue.case_id}</h4>
        <p>
          Gate score at production threshold:{" "}
          <MetricValue value={knownIssue.gate_score_at_production_threshold} />
        </p>
        <p className={styles.cardNote}>{knownIssue.note}</p>
        <p className={styles.cardNote}>
          Threshold gating alone does not eliminate every unsupported/high-similarity answer attempt.
          This is a retrieval/abstention-pipeline behavior, not a clinical failure.
        </p>
      </div>
    </div>
  );
}

function LatencySection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  const latencyMetrics = snapshot.latency.metrics as unknown as LatencyMetrics;
  return (
    <div className={styles.card}>
      <h3>Latency</h3>
      <p className={styles.cardNote}>
        Local development-machine, service-level measurements only ({snapshot.latency.experiment_id}).
        No production SLA, throughput, or requests-per-second claim is made anywhere in this project.
      </p>

      <LatencyTable
        caption="Retrieval &amp; reranker stages -- development"
        stages={latencyStages(latencyMetrics.retrieval_and_reranker.development.stages, RETRIEVAL_STAGE_LABELS)}
      />
      <LatencyTable
        caption="Retrieval &amp; reranker stages -- held-out"
        stages={latencyStages(latencyMetrics.retrieval_and_reranker.held_out.stages, RETRIEVAL_STAGE_LABELS)}
      />
      <LatencyTable caption="Structured tools (5 of 18 registered tools)" stages={latencyStages(latencyMetrics.boundaries.structured_tools)} />
      <LatencyTable caption="Multi-agent workflows" stages={latencyStages(latencyMetrics.boundaries.multi_agent)} />
      <LatencyTable caption="Review policy decision" stages={latencyStages(latencyMetrics.boundaries.review_policy)} />
      <LatencyTable caption="Review persistence" stages={latencyStages(latencyMetrics.boundaries.review_persistence)} />
    </div>
  );
}

function CitationSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  const dev = snapshot.citation_metric.development as {
    hybrid?: { citation_expected_evidence_rate?: number | null };
    hybrid_reranked?: { citation_expected_evidence_rate?: number | null };
  };
  const heldOut = snapshot.citation_metric.held_out as {
    hybrid?: { citation_expected_evidence_rate?: number | null };
    hybrid_reranked?: { citation_expected_evidence_rate?: number | null };
  };
  const rows: ComparisonRow[] = [
    {
      key: "development",
      label: "Development",
      cells: [
        dev.hybrid?.citation_expected_evidence_rate != null
          ? formatRate(dev.hybrid.citation_expected_evidence_rate)
          : null,
        dev.hybrid_reranked?.citation_expected_evidence_rate != null
          ? formatRate(dev.hybrid_reranked.citation_expected_evidence_rate)
          : null,
      ],
    },
    {
      key: "held_out",
      label: "Held-out",
      cells: [
        heldOut.hybrid?.citation_expected_evidence_rate != null
          ? formatRate(heldOut.hybrid.citation_expected_evidence_rate)
          : null,
        heldOut.hybrid_reranked?.citation_expected_evidence_rate != null
          ? formatRate(heldOut.hybrid_reranked.citation_expected_evidence_rate)
          : null,
      ],
    },
  ];
  return (
    <div className={styles.card}>
      <h3>Citation Expected-Evidence Match</h3>
      <p className={styles.cardNote}>{snapshot.citation_metric.definition}</p>
      <p className={styles.cardNote}>
        This metric does not establish citation entailment, citation completeness, answer correctness,
        or clinical correctness.
      </p>
      <ComparisonTable caption="Citation-references-expected-evidence rate" columnHeadings={["Hybrid", "Hybrid + reranker"]} rows={rows} />
    </div>
  );
}

function ClaimMatrixSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  return (
    <div className={styles.card}>
      <h3>Claim Matrix</h3>
      <dl className={styles.claimList}>
        <div>
          <dt>Supported</dt>
          <dd>{snapshot.claim_matrix.supported}</dd>
        </div>
        <div>
          <dt>Partially supported</dt>
          <dd>{snapshot.claim_matrix.partially_supported}</dd>
        </div>
        <div>
          <dt>Not evaluated</dt>
          <dd>{snapshot.claim_matrix.not_evaluated}</dd>
        </div>
        <div>
          <dt>Out of scope</dt>
          <dd>{snapshot.claim_matrix.out_of_scope}</dd>
        </div>
      </dl>
      <p className={styles.cardNote}>
        {snapshot.claim_matrix.total} claim areas total (source: {snapshot.claim_matrix.source}). This
        is a count of evidence-boundary categories, not a percentage project score --
        &quot;partially supported&quot; and &quot;not evaluated&quot; are not failures, they describe
        what evidence does and does not exist. This snapshot exposes only aggregate counts; individual
        claim rows are not exposed here.
      </p>
    </div>
  );
}

function EvaluationGapsSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  return (
    <div className={styles.card}>
      <h3>Open Evaluation Gaps</h3>
      <p className={styles.cardNote}>
        {snapshot.gaps.total} entries total (source: {snapshot.gaps.source}): {snapshot.gaps.open} open,{" "}
        {snapshot.gaps.documented_limitation} documented limitation,{" "}
        {snapshot.gaps.out_of_scope_phase12} out of scope for Phase 12.
      </p>
      <div className={styles.card} data-status="OPEN">
        <h4>Runtime configuration drift</h4>
        <p className={styles.cardNote}>{snapshot.provenance.runtime_config_drift_warning}</p>
      </div>
      <GapList entries={snapshot.gaps.entries} highlightGapId="EVAL-RUNTIME-CONFIG-DRIFT" />
    </div>
  );
}

function CostTokenSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  return (
    <div className={styles.card}>
      <h3>Cost / Token Usage</h3>
      <p>
        <MetricValue value={null} notEvaluatedLabel="Not evaluated" />
      </p>
      <p className={styles.cardNote}>{snapshot.cost_tokens.note}</p>
    </div>
  );
}

function ProvenanceSection({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  const config = snapshot.provenance.evaluated_production_config;
  return (
    <div className={styles.card}>
      <h3>Evaluation Provenance</h3>
      <ProvenanceDetails
        summary="Show experiment metadata and evaluated configuration"
        fields={[
          { label: "Development baseline experiment", value: snapshot.retrieval_baseline.development.experiment_id },
          { label: "Held-out baseline experiment", value: snapshot.retrieval_baseline.held_out.experiment_id },
          { label: "Reranker comparison experiment", value: snapshot.reranker_comparison.experiment_id },
          { label: "Latency experiment", value: snapshot.latency.experiment_id },
          { label: "Corpus fingerprint", value: snapshot.provenance.corpus_fingerprint },
          { label: "Chunk size / overlap", value: `${config.chunk_size} / ${config.chunk_overlap}` },
          { label: "Evidence threshold", value: String(config.evidence_threshold) },
          { label: "Retrieval candidate k / RRF k", value: `${config.retrieval_candidate_k} / ${config.rrf_k}` },
          { label: "Embedding model", value: `${config.embedding_model} @ ${config.embedding_revision}` },
          { label: "Reranker model", value: `${config.reranker_model} @ ${config.reranker_revision}` },
          { label: "Generation provider", value: snapshot.provenance.generation_provider },
        ]}
      />
    </div>
  );
}

function EvaluationSnapshotContent({ snapshot }: { snapshot: EvaluationSnapshotResponse }) {
  return (
    <div className={styles.snapshotContent}>
      <p className={styles.snapshotLabel}>
        <span className={styles.snapshotLabelTag}>Phase 12 Evaluation Snapshot</span> —{" "}
        {snapshot.generated_note}
      </p>

      <EvaluationOverviewSection snapshot={snapshot} />
      <DatasetLimitationsSection snapshot={snapshot} />
      <RetrievalQualitySection snapshot={snapshot} />
      <RerankerAnalysisSection snapshot={snapshot} />
      <RerankerLatencyTradeoffSection snapshot={snapshot} />
      <ThresholdSection snapshot={snapshot} />
      <LatencySection snapshot={snapshot} />
      <CitationSection snapshot={snapshot} />
      <ClaimMatrixSection snapshot={snapshot} />
      <EvaluationGapsSection snapshot={snapshot} />
      <CostTokenSection snapshot={snapshot} />
      <ProvenanceSection snapshot={snapshot} />

      <div className={styles.card}>
        <h3>Known limitations</h3>
        <ul className={styles.limitationsList}>
          {snapshot.known_limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function StructuredAnalyticsPanel() {
  const { status: systemStatus } = useSystemStatusContext();
  const [state, setState] = useState<StructuredState>({ status: "loading" });
  const abortRef = useRef<AbortController | null>(null);

  const allowed = isStructuredAnalyticsAllowed(systemStatus);
  const blockedReason = structuredAnalyticsBlockedReason(systemStatus);

  function load(): void {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    getStructuredAnalyticsOverview(controller.signal).then((outcome) => {
      if (controller.signal.aborted) return;
      if (outcome.kind === "error") {
        setState({ status: "error", category: outcome.category, requestId: outcome.requestId });
        return;
      }
      setState({ status: "ok", overview: outcome.overview });
    });
  }

  useEffect(() => {
    if (!allowed) return;
    load();
    return () => abortRef.current?.abort();
  }, [allowed]);

  function handleRetry() {
    setState({ status: "loading" });
    load();
  }

  return (
    <section className={styles.panel} aria-labelledby="structured-analytics-heading">
      <h2 id="structured-analytics-heading">Structured Analytics</h2>
      <p className={styles.panelSubheading}>
        Live population-level aggregates over the synthetic FHIR and SynPUF datasets. These two
        datasets are never joined or cross-referenced -- there is no shared identifier between them.
      </p>

      {!allowed && blockedReason && <p className={styles.blockedReason}>{blockedReason}</p>}

      {allowed && (
        <div aria-live="polite">
          {state.status === "loading" && <p className={styles.loading}>Loading structured analytics…</p>}
          {state.status === "error" && (
            <ErrorPanel category={state.category} requestId={state.requestId} onRetry={handleRetry} />
          )}
          {state.status === "ok" && <StructuredAnalyticsContent overview={state.overview} />}
        </div>
      )}
    </section>
  );
}

function formatUsd(value: string | number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return null;
  return numeric.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function countBarRows(counts: Record<string, number>): { rows: BarChartRow[]; max: number } {
  const entries = Object.entries(counts);
  const max = Math.max(1, ...entries.map(([, count]) => count));
  return {
    max,
    rows: entries.map(([key, count]) => ({ key, label: key, value: count, displayText: String(count) })),
  };
}

function occurrenceBarRows<T extends { occurrences: number }>(
  rows: T[],
  labelOf: (row: T) => string,
): { rows: BarChartRow[]; max: number } {
  const max = Math.max(1, ...rows.map((row) => row.occurrences));
  return {
    max,
    rows: rows.map((row, index) => ({
      key: String(index),
      label: labelOf(row),
      value: row.occurrences,
      displayText: String(row.occurrences),
    })),
  };
}

function EmptyAggregateNotice({ message }: { message: string }) {
  return (
    <p className={structuredResultStyles.empty} role="status">
      {message}
    </p>
  );
}

function FhirCodeTable({
  caption,
  rows,
  emptyMessage,
}: {
  caption: string;
  rows: FhirCodeFrequencyRow[];
  emptyMessage: string;
}) {
  if (rows.length === 0) return <EmptyAggregateNotice message={emptyMessage} />;
  return (
    <div className={styles.tableScroll}>
      <table className={styles.table}>
        <caption className={styles.tableCaption}>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Code</th>
            <th scope="col">Code system</th>
            <th scope="col">Display</th>
            <th scope="col">Occurrences</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              <td>{row.code}</td>
              <td>{row.code_system}</td>
              <td>{row.code_display}</td>
              <td>{row.occurrences}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SynpufCodeTable({
  caption,
  codeHeading,
  rows,
  emptyMessage,
}: {
  caption: string;
  codeHeading: string;
  rows: { occurrences: number }[];
  emptyMessage: string;
}) {
  if (rows.length === 0) return <EmptyAggregateNotice message={emptyMessage} />;
  return (
    <div className={styles.tableScroll}>
      <table className={styles.table}>
        <caption className={styles.tableCaption}>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">{codeHeading}</th>
            <th scope="col">Occurrences</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const code = Object.entries(row).find(([key]) => key !== "occurrences")?.[1];
            return (
              <tr key={index}>
                <td>{String(code)}</td>
                <td>{row.occurrences}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FhirAnalyticsSection({ fhir }: { fhir: FhirAggregateOverview }) {
  const totalEncounters = Object.values(fhir.encounter_counts_by_class).reduce((a, b) => a + b, 0);
  const encounterBars = countBarRows(fhir.encounter_counts_by_class);
  const conditionBars = occurrenceBarRows(fhir.top_conditions, (row: FhirCodeFrequencyRow) => row.code_display);
  const procedureBars = occurrenceBarRows(fhir.top_procedures, (row: FhirCodeFrequencyRow) => row.code_display);
  const medicationBars = occurrenceBarRows(fhir.top_medications, (row: FhirCodeFrequencyRow) => row.code_display);

  return (
    <div className={styles.card}>
      <h3>Synthetic FHIR Population Analytics</h3>
      <p className={styles.cardNote}>
        Synthea-generated synthetic FHIR data. This is the loaded project sample, not a real hospital
        population.
      </p>

      <h4>Dataset Overview</h4>
      <dl className={styles.claimList}>
        <div>
          <dt>Patients in sample</dt>
          <dd>{fhir.patient_count}</dd>
        </div>
        <div>
          <dt>Encounters in sample</dt>
          <dd>{totalEncounters}</dd>
        </div>
      </dl>

      <h4>Encounter Distribution (by encounter class code)</h4>
      {encounterBars.rows.length === 0 ? (
        <EmptyAggregateNotice message="No encounter aggregate data available." />
      ) : (
        <>
          <AccessibleBarChart rows={encounterBars.rows} maxValue={encounterBars.max} />
          <div className={styles.tableScroll}>
            <table className={styles.table}>
              <caption className={styles.tableCaption}>Encounters by class code</caption>
              <thead>
                <tr>
                  <th scope="col">Class code</th>
                  <th scope="col">Encounters</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(fhir.encounter_counts_by_class).map(([code, count]) => (
                  <tr key={code}>
                    <td>{code}</td>
                    <td>{count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <h4>Condition Frequency</h4>
      <p className={styles.cardNote}>
        Top {fhir.top_n} most frequent condition codes in the loaded synthetic FHIR sample. Not a
        clinical risk or prevalence claim.
      </p>
      {conditionBars.rows.length > 0 && <AccessibleBarChart rows={conditionBars.rows} maxValue={conditionBars.max} />}
      <FhirCodeTable
        caption={`Top ${fhir.top_n} condition codes`}
        rows={fhir.top_conditions}
        emptyMessage="No condition-frequency rows available."
      />

      <h4>Procedure Frequency</h4>
      <p className={styles.cardNote}>
        Top {fhir.top_n} most frequent procedure codes in the loaded synthetic FHIR sample. Not a claim
        about procedure necessity, success, or outcome.
      </p>
      {procedureBars.rows.length > 0 && <AccessibleBarChart rows={procedureBars.rows} maxValue={procedureBars.max} />}
      <FhirCodeTable
        caption={`Top ${fhir.top_n} procedure codes`}
        rows={fhir.top_procedures}
        emptyMessage="No procedure-frequency rows available."
      />

      <h4>Medication Frequency</h4>
      <p className={styles.cardNote}>
        Top {fhir.top_n} most frequent medication codes in the loaded synthetic FHIR sample. Not
        prescribing guidance or a treatment recommendation.
      </p>
      {medicationBars.rows.length > 0 && <AccessibleBarChart rows={medicationBars.rows} maxValue={medicationBars.max} />}
      <FhirCodeTable
        caption={`Top ${fhir.top_n} medication codes`}
        rows={fhir.top_medications}
        emptyMessage="No medication-frequency rows available."
      />
    </div>
  );
}

function SynpufAnalyticsSection({ synpuf }: { synpuf: SynpufAggregateOverview }) {
  const totalClaims = Object.values(synpuf.claim_counts_by_type).reduce((a, b) => a + b, 0);
  const claimBars = countBarRows(synpuf.claim_counts_by_type);
  const diagnosisBars = occurrenceBarRows(synpuf.top_diagnoses, (row: SynpufDiagnosisFrequencyRow) => row.icd9_code);
  const procedureBars = occurrenceBarRows(synpuf.top_procedures, (row: SynpufProcedureFrequencyRow) => row.icd9_procedure_code);
  const hcpcsBars = occurrenceBarRows(synpuf.top_hcpcs, (row: SynpufHcpcsFrequencyRow) => row.hcpcs_code);
  const paymentRows = Object.values(synpuf.payment_totals_by_type);

  return (
    <div className={styles.card}>
      <h3>Synthetic SynPUF Claims Analytics</h3>
      <p className={styles.cardNote}>
        CMS DE-SynPUF synthetic/sample claims data. This is the loaded project sample, not Medicare
        spending or a national sample.
      </p>

      <h4>Dataset Overview</h4>
      <dl className={styles.claimList}>
        <div>
          <dt>Beneficiaries in sample</dt>
          <dd>{synpuf.beneficiary_count}</dd>
        </div>
        <div>
          <dt>Claims in sample</dt>
          <dd>{totalClaims}</dd>
        </div>
      </dl>

      <h4>Claim Distribution (by claim type)</h4>
      {claimBars.rows.length === 0 ? (
        <EmptyAggregateNotice message="No claim aggregate data available." />
      ) : (
        <>
          <AccessibleBarChart rows={claimBars.rows} maxValue={claimBars.max} />
          <ComparisonTable
            caption="Claims by type"
            columnHeadings={["Claims"]}
            rows={Object.entries(synpuf.claim_counts_by_type).map(([type, count]) => ({
              key: type,
              label: type,
              cells: [count],
            }))}
          />
        </>
      )}

      <h4>Payment Totals</h4>
      <p className={styles.cardNote}>
        Aggregate claim_payment_amount sums by claim type -- a descriptive total from this sample, not
        a healthcare-cost or spending claim.
      </p>
      {paymentRows.length === 0 ? (
        <EmptyAggregateNotice message="No payment aggregate data available." />
      ) : (
        <ComparisonTable
          caption="Total payment by claim type"
          columnHeadings={["Total payment", "Claim count"]}
          rows={paymentRows.map((row) => ({
            key: row.claim_type,
            label: row.claim_type,
            cells: [formatUsd(row.total_payment), row.claim_count],
          }))}
        />
      )}

      <h4>Diagnosis Frequency</h4>
      <p className={styles.cardNote}>
        Top {synpuf.top_n} most frequent ICD-9 diagnosis codes in the loaded synthetic sample. The
        backend provides no description field for these codes, so none is shown here.
      </p>
      {diagnosisBars.rows.length > 0 && <AccessibleBarChart rows={diagnosisBars.rows} maxValue={diagnosisBars.max} />}
      <SynpufCodeTable
        caption={`Top ${synpuf.top_n} diagnosis codes`}
        codeHeading="ICD-9 code"
        rows={synpuf.top_diagnoses}
        emptyMessage="No diagnosis-frequency rows available."
      />

      <h4>Procedure Frequency</h4>
      <p className={styles.cardNote}>
        Top {synpuf.top_n} most frequent ICD-9 procedure codes in the loaded synthetic sample.
      </p>
      {procedureBars.rows.length > 0 && <AccessibleBarChart rows={procedureBars.rows} maxValue={procedureBars.max} />}
      <SynpufCodeTable
        caption={`Top ${synpuf.top_n} procedure codes`}
        codeHeading="ICD-9 procedure code"
        rows={synpuf.top_procedures}
        emptyMessage="No procedure-frequency rows available."
      />

      <h4>HCPCS Frequency</h4>
      <p className={styles.cardNote}>
        Top {synpuf.top_n} most frequent HCPCS codes in the loaded synthetic sample -- a code
        frequency, not a cost, medical-necessity, or coverage claim.
      </p>
      {hcpcsBars.rows.length > 0 && <AccessibleBarChart rows={hcpcsBars.rows} maxValue={hcpcsBars.max} />}
      <SynpufCodeTable
        caption={`Top ${synpuf.top_n} HCPCS codes`}
        codeHeading="HCPCS code"
        rows={synpuf.top_hcpcs}
        emptyMessage="No HCPCS-frequency rows available."
      />
    </div>
  );
}

function StructuredAnalyticsContent({ overview }: { overview: StructuredAnalyticsOverview }) {
  return (
    <div className={styles.snapshotContent}>
      <FhirAnalyticsSection fhir={overview.fhir} />
      <SynpufAnalyticsSection synpuf={overview.synpuf} />
      <div className={styles.card}>
        <h4>Structured Analytics Limitations</h4>
        <ul className={styles.limitationsList}>
          <li>Small project sample -- {overview.fhir.patient_count} FHIR patients, {overview.synpuf.beneficiary_count} SynPUF beneficiaries.</li>
          <li>Both datasets are synthetic/sample data, not real patient records.</li>
          <li>Frequency tables show only the top {overview.fhir.top_n} rows, not the complete distribution.</li>
          <li>FHIR and SynPUF are never linked -- there is no cross-dataset patient identity.</li>
          <li>Aggregate counts are descriptive only, never a clinical, coverage, or eligibility conclusion.</li>
        </ul>
      </div>
    </div>
  );
}

export function Analytics() {
  return (
    <div className={styles.page}>
      <section>
        <h1 className={styles.heading}>Analytics &amp; Evaluation</h1>
        <p className={styles.subheading}>
          Phase 12 evaluation evidence and population-level synthetic-data aggregates for the
          synthetic FHIR and SynPUF datasets.
        </p>
      </section>

      <EvaluationSnapshotPanel />
      <StructuredAnalyticsPanel />
    </div>
  );
}
