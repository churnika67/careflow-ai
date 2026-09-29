/**
 * Typed contracts for Phase 15 Slice 1's two read-only analytics
 * endpoints: GET /analytics/evaluation/snapshot and GET
 * /analytics/structured/overview. Mirrors
 * backend/app/analytics/models.py field-for-field.
 *
 * The nested metric blocks (`metrics`, `known_issue`, the citation pair
 * dictionaries) are typed as `Record<string, unknown>` deliberately, not
 * `any` and not re-typed field-by-field: these are verbatim passthroughs
 * of a Phase 12 artifact's own JSON shape (see the backend module's own
 * docstring), and re-typing every nested metric name on the frontend too
 * would risk the same silent-transcription-error/null-becomes-zero risk
 * the backend explicitly avoids. Consumers must read a value and check
 * for `null`/`undefined` before rendering it as a number -- never coerce
 * a missing metric to 0.
 */

export interface DatasetSummary {
  dataset_version: string;
  case_count: number;
  positive_cases: number;
  negative_cases: number;
  description: string;
  limitation: string;
}

export interface ArtifactMetricBlock {
  experiment_id: string;
  artifact_path: string;
  metrics: Record<string, unknown>;
}

export interface CitationMetric {
  definition: string;
  development: Record<string, unknown>;
  held_out: Record<string, unknown>;
}

export interface ThresholdInfo {
  grid: number[];
  production_threshold: number;
  case_transitions_observed: number;
  known_issue: Record<string, unknown>;
}

export interface CostTokenStatus {
  status: "not_evaluated";
  note: string;
}

export interface ClaimMatrixSummary {
  supported: number;
  partially_supported: number;
  not_evaluated: number;
  out_of_scope: number;
  total: number;
  source: string;
}

export type GapStatus = "OPEN" | "DOCUMENTED_LIMITATION" | "OUT_OF_SCOPE_PHASE12";

export interface GapEntry {
  gap_id: string;
  title: string;
  category: string;
  status: GapStatus;
  evidence: string;
  impact_on_claims: string;
}

export interface GapRegistrySummary {
  open: number;
  out_of_scope_phase12: number;
  documented_limitation: number;
  total: number;
  source: string;
  entries: GapEntry[];
}

export interface ProductionConfig {
  chunk_size: number;
  chunk_overlap: number;
  evidence_threshold: number;
  retrieval_candidate_k: number;
  rrf_k: number;
  embedding_model: string;
  embedding_revision: string;
  reranker_model: string;
  reranker_revision: string;
}

export interface Provenance {
  corpus_fingerprint: string;
  evaluated_production_config: ProductionConfig;
  generation_provider: string;
  runtime_config_drift_warning: string;
}

export interface EvaluationSnapshotResponse {
  source: "phase12_artifact_snapshot";
  phase: string;
  generated_note: string;
  datasets: { development: DatasetSummary; held_out: DatasetSummary };
  retrieval_baseline: { development: ArtifactMetricBlock; held_out: ArtifactMetricBlock };
  reranker_comparison: ArtifactMetricBlock;
  threshold: ThresholdInfo;
  citation_metric: CitationMetric;
  latency: ArtifactMetricBlock;
  cost_tokens: CostTokenStatus;
  claim_matrix: ClaimMatrixSummary;
  gaps: GapRegistrySummary;
  known_limitations: string[];
  provenance: Provenance;
}

export interface FhirCodeFrequencyRow {
  code: string;
  code_system: string;
  code_display: string;
  occurrences: number;
}

export interface FhirAggregateOverview {
  source: "live_structured_query";
  dataset: "synthea_fhir";
  patient_count: number;
  top_n: number;
  encounter_counts_by_class: Record<string, number>;
  top_conditions: FhirCodeFrequencyRow[];
  top_procedures: FhirCodeFrequencyRow[];
  top_medications: FhirCodeFrequencyRow[];
}

export interface SynpufPaymentTotal {
  claim_type: string;
  total_payment: string | number | null;
  claim_count: number;
}

export interface SynpufDiagnosisFrequencyRow {
  icd9_code: string;
  occurrences: number;
}

export interface SynpufProcedureFrequencyRow {
  icd9_procedure_code: string;
  occurrences: number;
}

export interface SynpufHcpcsFrequencyRow {
  hcpcs_code: string;
  occurrences: number;
}

export interface SynpufAggregateOverview {
  source: "live_structured_query";
  dataset: "cms_desynpuf";
  beneficiary_count: number;
  top_n: number;
  claim_counts_by_type: Record<string, number>;
  payment_totals_by_type: Record<string, SynpufPaymentTotal>;
  top_diagnoses: SynpufDiagnosisFrequencyRow[];
  top_procedures: SynpufProcedureFrequencyRow[];
  top_hcpcs: SynpufHcpcsFrequencyRow[];
}

export interface StructuredAnalyticsOverview {
  fhir: FhirAggregateOverview;
  synpuf: SynpufAggregateOverview;
}

export interface AnalyticsErrorBody {
  error: { code: string };
}
