"""Response contracts for the Phase 15 Slice 1 analytics API.

Fields that hold a metric block copied verbatim from a Phase 12 artifact
are typed ``dict[str, Any]`` deliberately, not re-typed field-by-field.
This is a passthrough, not a redesign: re-typing every nested metric name
here would risk silently transcribing a value wrong, or turning a genuine
``null`` (not evaluated / zero-denominator) into a numeric ``0`` somewhere
along the way. The artifact JSON is the source of truth; this module only
adds a thin, honest envelope (provenance, dataset description, known
limitations) around it.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetSummary(AnalyticsModel):
    dataset_version: str
    case_count: int
    positive_cases: int
    negative_cases: int
    description: str
    limitation: str


class ArtifactMetricBlock(AnalyticsModel):
    """One canonical experiment artifact's metrics, verbatim."""

    experiment_id: str
    artifact_path: str
    metrics: dict[str, Any]


class CitationMetric(AnalyticsModel):
    definition: str
    development: dict[str, Any]
    held_out: dict[str, Any]


class ThresholdInfo(AnalyticsModel):
    grid: list[float]
    production_threshold: float
    case_transitions_observed: int
    known_issue: dict[str, Any]


class CostTokenStatus(AnalyticsModel):
    status: Literal["not_evaluated"]
    note: str


class ClaimMatrixSummary(AnalyticsModel):
    supported: int
    partially_supported: int
    not_evaluated: int
    out_of_scope: int
    total: int
    source: str


class GapEntry(AnalyticsModel):
    """One row of docs/evaluation/phase12_gap_registry.json, verbatim.
    Added in Phase 15 Slice 2 because the Evaluation Gaps section needs
    to show individual gaps (their title/category/evidence), not just
    per-status counts -- Slice 1's GapRegistrySummary only had counts."""

    gap_id: str
    title: str
    category: str
    status: Literal["OPEN", "DOCUMENTED_LIMITATION", "OUT_OF_SCOPE_PHASE12"]
    evidence: str
    impact_on_claims: str


class GapRegistrySummary(AnalyticsModel):
    open: int
    out_of_scope_phase12: int
    documented_limitation: int
    total: int
    source: str
    entries: list[GapEntry]


class ProductionConfig(AnalyticsModel):
    chunk_size: int
    chunk_overlap: int
    evidence_threshold: float
    retrieval_candidate_k: int
    rrf_k: int
    embedding_model: str
    embedding_revision: str
    reranker_model: str
    reranker_revision: str


class Provenance(AnalyticsModel):
    corpus_fingerprint: str
    evaluated_production_config: ProductionConfig
    generation_provider: str
    runtime_config_drift_warning: str


class EvaluationSnapshotResponse(AnalyticsModel):
    source: Literal["phase12_artifact_snapshot"]
    phase: str
    generated_note: str
    datasets: dict[str, DatasetSummary]
    retrieval_baseline: dict[str, ArtifactMetricBlock]
    reranker_comparison: ArtifactMetricBlock
    threshold: ThresholdInfo
    citation_metric: CitationMetric
    latency: ArtifactMetricBlock
    cost_tokens: CostTokenStatus
    claim_matrix: ClaimMatrixSummary
    gaps: GapRegistrySummary
    known_limitations: list[str]
    provenance: Provenance


class FhirAggregateOverview(AnalyticsModel):
    source: Literal["live_structured_query"]
    dataset: Literal["synthea_fhir"]
    patient_count: int
    top_n: int
    encounter_counts_by_class: dict[str, int]
    top_conditions: list[dict[str, Any]]
    top_procedures: list[dict[str, Any]]
    top_medications: list[dict[str, Any]]


class SynpufAggregateOverview(AnalyticsModel):
    source: Literal["live_structured_query"]
    dataset: Literal["cms_desynpuf"]
    beneficiary_count: int
    top_n: int
    claim_counts_by_type: dict[str, int]
    payment_totals_by_type: dict[str, dict[str, Any]]
    top_diagnoses: list[dict[str, Any]]
    top_procedures: list[dict[str, Any]]
    top_hcpcs: list[dict[str, Any]]


class StructuredAnalyticsOverview(AnalyticsModel):
    """Two independently-queried, never-joined evidence domains. There is
    no shared identifier between ``fhir`` and ``synpuf`` anywhere in this
    response -- each is a separate GROUP BY over its own dataset's tables."""

    fhir: FhirAggregateOverview
    synpuf: SynpufAggregateOverview
