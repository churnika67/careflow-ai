"""Reads a fixed, hardcoded set of canonical Phase 12 evaluation artifacts
and shapes them into an ``EvaluationSnapshotResponse``.

Every path this module touches is a literal, named constant below -- never
built from a request parameter, header, or any other caller-supplied
value. There is no "experiment_id" argument anywhere in this module's
public API. This is a deliberate security property, not an oversight: a
read-only dashboard endpoint has no legitimate reason to accept an
arbitrary filesystem path, so the simplest way to make path traversal
impossible is to never parse one from a request at all. If a future slice
needs to expose a specific non-canonical experiment, it must add a new
named constant here and a corresponding audit entry in the design doc --
not a generic "read this experiment_id" endpoint.

Canonical artifact selection is not a guess: it follows the "Artifact
provenance" table in docs/evaluation/phase12_claim_matrix.md, which
Phase 12 Slice 6-8 already established as the authoritative source per
conclusion area (see that file for the full reasoning)."""

import json
from pathlib import Path
from typing import Any

from app.analytics.models import (
    ArtifactMetricBlock,
    CitationMetric,
    ClaimMatrixSummary,
    CostTokenStatus,
    DatasetSummary,
    EvaluationSnapshotResponse,
    GapEntry,
    GapRegistrySummary,
    ProductionConfig,
    Provenance,
    ThresholdInfo,
)

# Relative to the current working directory, matching the exact
# convention evaluation/run_experiment.py already established
# (`ARTIFACT_ROOT = Path("artifacts/evaluation")`) -- deliberately NOT
# derived from __file__. `pip install --no-deps .` (the Dockerfile's own
# install step) copies this package into site-packages, so __file__ would
# resolve somewhere under /usr/local/lib/..., not the repository; only an
# *editable* install (this repo's local dev setup, see README.md's
# "Native backend development") keeps __file__ pointing at the real repo
# tree. The container's WORKDIR is /app (see backend/Dockerfile, which
# COPYs artifacts/evaluation and docs/evaluation to that same relative
# location) and local commands are documented to run from the repository
# root, so a CWD-relative path resolves correctly in both places.
_REPO_ROOT = Path(".").resolve()
_ARTIFACT_ROOT = Path("artifacts/evaluation")
_DOCS_ROOT = Path("docs/evaluation")

# Canonical experiment IDs -- see docs/evaluation/phase12_claim_matrix.md's
# "Artifact provenance" table. Slice 6 explicitly supersedes Slice 2 for
# the reranker causal question; Slice 2 remains canonical for the plain
# per-mode retrieval baseline.
_DEV_BASELINE_ID = "eb59bc90_774ea9a697a1"
_HELDOUT_BASELINE_ID = "eb59bc90_a223469082ce"
_RERANKER_COMPARISON_ID = "eb59bc90_reranker_comparison"
_THRESHOLD_DEV_ID = "eb59bc90_threshold_sweep_development"
_THRESHOLD_HELDOUT_ID = "eb59bc90_threshold_sweep_held_out"
# The final Phase 12 report (docs/evaluation/phase12_final_report.md, "8.
# Latency evaluation") names this specific timestamped run as authoritative
# even though two later re-runs of the same live suite also exist on disk.
_LATENCY_ID = "eb59bc90_latency_1790202561"

_CLAIM_MATRIX_DOC = _DOCS_ROOT / "phase12_claim_matrix.md"
_GAP_REGISTRY_DOC = _DOCS_ROOT / "phase12_gap_registry.json"

_KNOWN_UNSUPPORTED_CASE_ID = "cms-v1-032"


class EvaluationArtifactMissingError(Exception):
    """A canonical artifact file this module depends on is not present.

    Distinguished from a generic FileNotFoundError so the API layer can
    return a clean 503 rather than an unhandled 500."""


class EvaluationArtifactMalformedError(Exception):
    """A canonical artifact file exists but is not valid JSON, or is
    missing a field this module requires from it."""


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise EvaluationArtifactMissingError(f"missing canonical evaluation artifact: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise EvaluationArtifactMalformedError(f"malformed JSON in {path}: {exc}") from exc


def _require(mapping: dict, *keys: str, source: Path) -> Any:
    node = mapping
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            raise EvaluationArtifactMalformedError(
                f"expected field {'.'.join(keys)!r} not found in {source}"
            )
        node = node[key]
    return node


def _artifact_dir(experiment_id: str) -> Path:
    return _ARTIFACT_ROOT / experiment_id


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(_REPO_ROOT))


def _load_retrieval_baseline(experiment_id: str) -> tuple[DatasetSummary, ArtifactMetricBlock]:
    summary_path = _artifact_dir(experiment_id) / "summary.json"
    summary = _read_json(summary_path)
    dataset = DatasetSummary(
        dataset_version=_require(summary, "dataset_version", source=summary_path),
        case_count=_require(summary, "case_count", source=summary_path),
        positive_cases=_require(summary, "positive_cases", source=summary_path),
        negative_cases=_require(summary, "negative_cases", source=summary_path),
        description=(
            "project-authored held-out engineering evaluation set"
            if experiment_id == _HELDOUT_BASELINE_ID
            else "development/regression evaluation set (not independent -- "
            "repeatedly inspected while building the retrieval pipeline)"
        ),
        limitation=(
            "Small sample (12 cases, 10 positive); one flipped case changes "
            "positive-only Hit@1 by 10 percentage points."
            if experiment_id == _HELDOUT_BASELINE_ID
            else "8 of 32 cases reuse earlier development questions; not an "
            "independent measurement of generalization."
        ),
    )
    metric_block = ArtifactMetricBlock(
        experiment_id=experiment_id,
        artifact_path=_relative(summary_path),
        metrics=_require(summary, "metrics", source=summary_path),
    )
    return dataset, metric_block


def _load_reranker_comparison() -> ArtifactMetricBlock:
    summary_path = _artifact_dir(_RERANKER_COMPARISON_ID) / "summary.json"
    summary = _read_json(summary_path)
    return ArtifactMetricBlock(
        experiment_id=_RERANKER_COMPARISON_ID,
        artifact_path=_relative(summary_path),
        metrics=summary,
    )


def _load_citation_metric(reranker_summary: dict) -> CitationMetric:
    def _citation_pair(dataset_key: str) -> dict[str, Any]:
        dataset_block = _require(
            reranker_summary, dataset_key, source=_artifact_dir(_RERANKER_COMPARISON_ID)
        )
        return {
            "hybrid": dataset_block.get("hybrid_citation_expected_evidence"),
            "hybrid_reranked": dataset_block.get("hybrid_reranked_citation_expected_evidence"),
        }

    return CitationMetric(
        definition=(
            "CITATION_REFERENCES_EXPECTED_EVIDENCE: among positive cases that "
            "were actually answered (not abstained), does at least one "
            "validated citation's chunk_id fall within the case's expected "
            "evidence? A deterministic expected-evidence match only -- no "
            "entailment, completeness, or semantic-correctness claim is made."
        ),
        development=_citation_pair("development"),
        held_out=_citation_pair("held_out"),
    )


def _load_threshold_info() -> ThresholdInfo:
    dev_dir = _artifact_dir(_THRESHOLD_DEV_ID)
    heldout_dir = _artifact_dir(_THRESHOLD_HELDOUT_ID)
    curve_path = dev_dir / "threshold_curve.json"
    curve = _read_json(curve_path)
    grid = _require(curve, "threshold_grid", source=curve_path)

    dev_transitions = _read_json(dev_dir / "case_transitions.json")
    heldout_transitions = _read_json(heldout_dir / "case_transitions.json")

    per_query_path = dev_dir / "per_query.jsonl"
    if not per_query_path.is_file():
        raise EvaluationArtifactMissingError(
            f"missing canonical evaluation artifact: {per_query_path}"
        )
    known_case_gate_score = None
    for line in per_query_path.read_text().splitlines():
        row = json.loads(line)
        if (
            row.get("case_id") == _KNOWN_UNSUPPORTED_CASE_ID
            and row.get("retrieval_mode") == "hybrid_reranked"
            and row.get("evidence_threshold") == max(grid)
        ):
            known_case_gate_score = row.get("gate_score")
            break
    if known_case_gate_score is None:
        raise EvaluationArtifactMalformedError(
            f"expected case {_KNOWN_UNSUPPORTED_CASE_ID!r} not found in {per_query_path}"
        )

    return ThresholdInfo(
        grid=grid,
        production_threshold=max(grid),
        case_transitions_observed=len(dev_transitions) + len(heldout_transitions),
        known_issue={
            "gap_id": "EVAL-UNSUPPORTED-HIGH-SIMILARITY",
            "case_id": _KNOWN_UNSUPPORTED_CASE_ID,
            "category": "out_of_corpus",
            "gate_score_at_production_threshold": known_case_gate_score,
            "note": (
                "This case still answers (without citing expected evidence, "
                "since none exists) at every tested threshold including "
                "production's own -- its gate score exceeds the threshold "
                "despite being genuinely unsupported. Retrieval-score "
                "thresholding alone does not guarantee abstention here. Not "
                "fixed; no special-case rule was added."
            ),
        },
    )


def _load_latency() -> ArtifactMetricBlock:
    latency_path = _artifact_dir(_LATENCY_ID) / "latency.json"
    latency = _read_json(latency_path)
    return ArtifactMetricBlock(
        experiment_id=_LATENCY_ID, artifact_path=_relative(latency_path), metrics=latency
    )


def _load_claim_matrix() -> ClaimMatrixSummary:
    from evaluation.claim_governance import parse_markdown_table, validate_claim_matrix

    if not _CLAIM_MATRIX_DOC.is_file():
        raise EvaluationArtifactMissingError(
            f"missing canonical evaluation doc: {_CLAIM_MATRIX_DOC}"
        )
    text = _CLAIM_MATRIX_DOC.read_text()
    rows = parse_markdown_table(text, heading_hint="Claim matrix")
    violations = validate_claim_matrix(rows)
    if violations or not rows:
        raise EvaluationArtifactMalformedError(
            f"{_CLAIM_MATRIX_DOC} failed claim-matrix validation: {violations}"
        )
    counts = {"SUPPORTED": 0, "PARTIALLY_SUPPORTED": 0, "NOT_EVALUATED": 0, "OUT_OF_SCOPE": 0}
    for row in rows:
        counts[row["Status"]] += 1
    return ClaimMatrixSummary(
        supported=counts["SUPPORTED"],
        partially_supported=counts["PARTIALLY_SUPPORTED"],
        not_evaluated=counts["NOT_EVALUATED"],
        out_of_scope=counts["OUT_OF_SCOPE"],
        total=len(rows),
        source=_relative(_CLAIM_MATRIX_DOC),
    )


def _load_gaps() -> GapRegistrySummary:
    from evaluation.claim_governance import validate_gap_registry

    registry = _read_json(_GAP_REGISTRY_DOC)
    violations = validate_gap_registry(registry)
    if violations:
        raise EvaluationArtifactMalformedError(
            f"{_GAP_REGISTRY_DOC} failed gap-registry validation: {violations}"
        )
    gaps = registry["gaps"]
    counts = {"OPEN": 0, "DOCUMENTED_LIMITATION": 0, "OUT_OF_SCOPE_PHASE12": 0}
    for gap in gaps:
        counts[gap["status"]] += 1
    return GapRegistrySummary(
        open=counts["OPEN"],
        out_of_scope_phase12=counts["OUT_OF_SCOPE_PHASE12"],
        documented_limitation=counts["DOCUMENTED_LIMITATION"],
        total=len(gaps),
        source=_relative(_GAP_REGISTRY_DOC),
        entries=[
            GapEntry(
                gap_id=gap["gap_id"],
                title=gap["title"],
                category=gap["category"],
                status=gap["status"],
                evidence=gap["evidence"],
                impact_on_claims=gap["impact_on_claims"],
            )
            for gap in gaps
        ],
    )


def _load_provenance() -> Provenance:
    config_path = _artifact_dir(_RERANKER_COMPARISON_ID) / "config.json"
    config = _read_json(config_path)
    baseline_config_path = _artifact_dir(_DEV_BASELINE_ID) / "config.json"
    baseline_config = _read_json(baseline_config_path)
    return Provenance(
        corpus_fingerprint=_require(config, "corpus_fingerprint", source=config_path),
        evaluated_production_config=ProductionConfig(
            chunk_size=_require(baseline_config, "chunk_size", source=baseline_config_path),
            chunk_overlap=_require(baseline_config, "chunk_overlap", source=baseline_config_path),
            evidence_threshold=_require(
                baseline_config, "evidence_threshold", source=baseline_config_path
            ),
            retrieval_candidate_k=_require(
                baseline_config, "candidate_k", source=baseline_config_path
            ),
            rrf_k=_require(baseline_config, "rrf_k", source=baseline_config_path),
            embedding_model=_require(
                baseline_config, "embedding_model", source=baseline_config_path
            ),
            embedding_revision=_require(
                baseline_config, "embedding_revision", source=baseline_config_path
            ),
            reranker_model=_require(baseline_config, "reranker_model", source=baseline_config_path),
            reranker_revision=_require(
                baseline_config, "reranker_revision", source=baseline_config_path
            ),
        ),
        generation_provider=_require(
            baseline_config, "generation_provider", source=baseline_config_path
        ),
        runtime_config_drift_warning=(
            "EVAL-RUNTIME-CONFIG-DRIFT (OPEN): the live multi-agent runtime "
            "resolves to retrieval_mode=dense, rerank_enabled=false in this "
            "environment (see app.core.config.get_settings()), while every "
            "retrieval-quality result in this snapshot was measured against "
            "hybrid retrieval with reranking enabled. These two result sets "
            "must never be cited interchangeably."
        ),
    )


_KNOWN_LIMITATIONS = [
    "Small held-out sample (12 cases, 10 positive, 2 negative): one flipped "
    "positive case changes positive-only Hit@1 by 10 percentage points.",
    "Small policy corpus: 8 NCD document versions, 32 sections, 39 chunks -- "
    "results may not generalize to larger or different policy corpora.",
    "Synthetic structured data only (DE-SynPUF and Synthea subsets), not hospital-scale.",
    "Local-machine latency only -- no load test, no SLA or throughput claim.",
    "No answer, factual, or clinical correctness has been evaluated anywhere in this project.",
    "No statistical-significance test was performed or is claimed anywhere in Phase 12.",
]


def load_evaluation_snapshot() -> EvaluationSnapshotResponse:
    """Raises EvaluationArtifactMissingError or EvaluationArtifactMalformedError
    if any canonical artifact this snapshot depends on is absent or invalid --
    callers (see api/analytics.py) turn that into a 503, never a fabricated
    fallback value."""
    dev_dataset, dev_baseline = _load_retrieval_baseline(_DEV_BASELINE_ID)
    heldout_dataset, heldout_baseline = _load_retrieval_baseline(_HELDOUT_BASELINE_ID)
    reranker_block = _load_reranker_comparison()
    citation_metric = _load_citation_metric(reranker_block.metrics)

    return EvaluationSnapshotResponse(
        source="phase12_artifact_snapshot",
        phase="Phase 12",
        generated_note=(
            "This is a curated snapshot of existing, already-persisted Phase "
            "12 evaluation artifacts. Nothing here re-runs an experiment or "
            "re-scores a metric -- every number is read verbatim from a "
            "named canonical artifact file (see each block's experiment_id "
            "and artifact_path)."
        ),
        datasets={"development": dev_dataset, "held_out": heldout_dataset},
        retrieval_baseline={"development": dev_baseline, "held_out": heldout_baseline},
        reranker_comparison=reranker_block,
        threshold=_load_threshold_info(),
        citation_metric=citation_metric,
        latency=_load_latency(),
        cost_tokens=CostTokenStatus(
            status="not_evaluated",
            note=(
                "No evaluation run in this project has ever exercised an "
                "LLM provider -- every artifact's generation_provider is "
                "'deterministic'. No token or dollar-cost metric is computed "
                "or persisted anywhere in the evaluation package."
            ),
        ),
        claim_matrix=_load_claim_matrix(),
        gaps=_load_gaps(),
        known_limitations=list(_KNOWN_LIMITATIONS),
        provenance=_load_provenance(),
    )
