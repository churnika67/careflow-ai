"""Phase 12 Slice 4: evidence-threshold sensitivity + deterministic citation
evaluation, against the unmodified production 700/120 retrieval
configuration only. No chunk-size x threshold Cartesian product.

Evidence-gate semantics (audited by direct code read before this module was
written, not assumed):

- backend/app/generation/context.py::build_context() gates each hit on
  hit.get("evidence_gate_score") when hit["retrieval_method"] in
  {"bm25", "hybrid"}, else on hit["score"].
- backend/app/retrieval/search.py::Retriever.search(): whenever for_rag=True
  (the only way the evidence gate is ever invoked), an auxiliary dense-only
  lookup at depth 20 is ALWAYS performed regardless of the requested mode,
  and its cosine similarity is attached to every hit as
  evidence_gate_score -- own comment: "Preserve Phase 4's cosine gate
  without interpreting lexical/fusion scores as cosine." For dense mode,
  hit["score"] already *is* that same cosine value directly.
- backend/app/reranking/service.py::rerank() only ADDS fields via a
  non-destructive `hit | {...}` merge (rerank_score, rerank_rank,
  candidate_rank, ...) on top of the hybrid for_rag=True hits it receives --
  it never removes or overwrites the inherited evidence_gate_score or
  retrieval_method fields.

Conclusion: the evidence gate always compares a genuine dense cosine
similarity value -- never a BM25 score, an RRF-fused score, or an
uninterpreted cross-encoder logit -- and it is architecturally identical in
kind across all four modes (dense, bm25, hybrid, hybrid_reranked). The
threshold sweep below therefore runs, unmodified, against all four modes;
no mode is excluded, and none of the scores are fabricated or reinterpreted.
This module never calls the gate score "confidence" or "calibrated" --
evaluation.analysis.eligibility() already exposes it as a plain "cosine"
field, reused verbatim here.

Evidence labels reuse Slice 3's validated provenance-based remapping
(evaluation.chunking_experiment.remap_dataset) against a local rebuild of
the *production* 700/120 chunking configuration -- proven in Slice 3 to be
byte-identical (chunk_id set and chunk text) to the live production corpus
-- rather than Slice 2's single-authored expected_chunk_id semantics, so
that overlap-duplicated evidence is recognized consistently. Retrieval
itself runs read-only against the live production Qdrant alias, exactly
like Slice 2's retrieval_baseline -- no isolated collection is created,
because no chunking configuration is being varied here."""

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

from app.reranking.cross_encoder import MiniLMCrossEncoder
from app.retrieval.search import Retriever, load_corpus
from qdrant_client import QdrantClient

from evaluation.analysis import MODES, summarize
from evaluation.artifacts import write_experiment_artifacts
from evaluation.chunking_experiment import (
    EvidenceMappingFailure,
    build_experiment_chunks,
    load_frozen_source,
    remap_dataset,
)
from evaluation.config import (
    ExperimentConfig,
    ExperimentType,
    current_git_commit,
    experiment_id,
    git_source_state,
)
from evaluation.dataset import load_dataset
from evaluation.run_experiment import (
    ARTIFACT_ROOT,
    FROZEN_HELDOUT_SHA256,
    PRODUCTION_CHUNK_OVERLAP,
    PRODUCTION_CHUNK_SIZE,
    PRODUCTION_SETTINGS,
    HeldoutDatasetTamperedError,
    ProductionCorpusChangedError,
    build_artifact_files,
    failure_category_counts,
)
from evaluation.run_retrieval_eval import evaluate
from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import digest

# Frozen at Slice 4 approval. Not modified after seeing any result.
THRESHOLD_GRID: list[float] = [0.40, 0.45, 0.50, 0.55, 0.60]

DATASET_PATHS: dict[str, Path] = {
    "development": Path("docs/evaluation/golden_retrieval_v1.json"),
    "held_out": Path("docs/evaluation/golden_retrieval_heldout_v1.json"),
}


class ThresholdMappingFailuresPresentError(Exception):
    """Raised when production-provenance evidence remapping fails for any
    case in either dataset. Nothing is evaluated in this case."""

    def __init__(self, failures: list[dict]) -> None:
        self.failures = failures
        super().__init__(f"{len(failures)} evidence-mapping failure(s) — sweep not run")


class RetrievalRankChangedAcrossThresholdsError(Exception):
    """Raised if the same (dataset, mode, case) retrieval rank differs
    across threshold runs. Threshold is never passed into search.search();
    if ranks differ anyway, something other than a threshold effect
    changed, and results must not be interpreted until that is understood."""


class ProductionChunkingConfigMismatchError(Exception):
    """Raised if a local 700/120 rebuild of the frozen source does not
    reproduce the exact chunk_id set of the live production corpus --
    Slice 4's provenance remapping is only valid against a proven-identical
    corpus (established by Slice 3), not assumed identical here."""


def explicit_abstention_labels(abstention_entry: dict) -> dict:
    """Renames the existing TP/FP/FN confusion counts already computed by
    evaluation.analysis.summarize() into the explicit terminology this
    slice requires (SUPPORTED/UNSUPPORTED x ANSWERED/ABSTAINED), plus all
    four derived rates with explicit denominators. Computed from the same
    counts as evaluation.metrics.derived_abstention_rates(), not a second
    independent computation -- this is a relabeling/extension, not a
    parallel metric."""
    positive_cases = abstention_entry["positive_cases"]
    negative_cases = abstention_entry["negative_cases"]
    supported_abstained = abstention_entry["positive_abstentions"]
    unsupported_answered = abstention_entry["incorrect_answer_attempts"]
    unsupported_abstained = abstention_entry["correct_abstentions"]
    supported_answered = positive_cases - supported_abstained
    return {
        "supported_answered": supported_answered,
        "supported_abstained": supported_abstained,
        "unsupported_answered": unsupported_answered,
        "unsupported_abstained": unsupported_abstained,
        "supported_answer_rate": (supported_answered / positive_cases if positive_cases else None),
        "false_abstention_rate": (supported_abstained / positive_cases if positive_cases else None),
        "correct_abstention_rate": (
            unsupported_abstained / negative_cases if negative_cases else None
        ),
        "false_answer_rate": (unsupported_answered / negative_cases if negative_cases else None),
    }


def citation_expected_evidence(cases: list[dict], mode: str) -> dict:
    """CITATION_REFERENCES_EXPECTED_EVIDENCE -- the sole approved primary
    citation metric: among positive cases that were actually answered (not
    abstained), does at least one validated citation's chunk_id fall in the
    case's (provenance-remapped) expected_chunk_ids? This is exactly the
    existing deterministic cites_expected field evaluate() already computes
    per case/mode -- restricted here to the answered-supported denominator
    the metric is defined over. No entailment, completeness, or semantic
    correctness claim is made or computed."""
    answered_supported = [c for c in cases if c["answerable"] and not c["modes"][mode]["abstained"]]
    hits = sum(c["modes"][mode]["cites_expected"] for c in answered_supported)
    total = len(answered_supported)
    return {
        "answered_supported_cases": total,
        "citation_expected_hits": hits,
        "citation_expected_evidence_rate": hits / total if total else None,
    }


def _score_summary(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    return {
        "n": n,
        "min": ordered[0],
        "median": float(median(ordered)),
        "max": ordered[-1],
    }


def gate_score_distribution(cases: list[dict], mode: str) -> dict:
    """Distribution of the top-ranked candidate's evidence-gate cosine
    score, split by whether the case is (provenance-remapped) supported or
    unsupported. Reuses eligibility()'s own "cosine" field verbatim (never
    relabeled "confidence" or "calibrated") -- evaluate() already computes
    this per case via evaluation.analysis.eligibility()."""
    supported, unsupported = [], []
    for c in cases:
        hits = c["modes"][mode]["eligibility"]["hits"]
        if not hits or hits[0]["cosine"] is None:
            continue
        (supported if c["answerable"] else unsupported).append(hits[0]["cosine"])
    return {"supported": _score_summary(supported), "unsupported": _score_summary(unsupported)}


@dataclass(frozen=True)
class CaseTransition:
    case_id: str
    mode: str
    from_threshold: float
    to_threshold: float
    from_status: str
    to_status: str


def detect_case_transitions(
    status_by_mode_case_threshold: dict[str, dict[str, dict[float, bool]]],
) -> list[CaseTransition]:
    """Checks every adjacent pair in THRESHOLD_GRID for each (mode, case)
    whose abstained/answered status differs between the two thresholds.
    Does not assume the general answer->abstain-as-threshold-rises
    direction; both directions are recorded exactly as observed."""
    transitions = []
    pairs = list(zip(THRESHOLD_GRID, THRESHOLD_GRID[1:], strict=False))
    for mode, by_case in status_by_mode_case_threshold.items():
        for case_id, by_threshold in by_case.items():
            for lo, hi in pairs:
                if lo not in by_threshold or hi not in by_threshold:
                    continue
                before, after = by_threshold[lo], by_threshold[hi]
                if before != after:
                    transitions.append(
                        CaseTransition(
                            case_id=case_id,
                            mode=mode,
                            from_threshold=lo,
                            to_threshold=hi,
                            from_status="abstained" if before else "answered",
                            to_status="abstained" if after else "answered",
                        )
                    )
    return transitions


def _build_production_provenance_datasets(embedding, documents, production_corpus_by_id):
    """Rebuilds the production 700/120 chunking configuration locally from
    the frozen source (Slice 3 proved this reproduces the live production
    corpus's chunk_id set and chunk text exactly) and remaps both datasets'
    expected evidence against it -- the same deterministic,
    section-anchored, quote-span-containment method validated in Slice 3,
    reused unmodified, not reimplemented."""
    local_chunks = build_experiment_chunks(
        documents, embedding, PRODUCTION_CHUNK_SIZE, PRODUCTION_CHUNK_OVERLAP
    )
    if {c.chunk_id for c in local_chunks} != set(production_corpus_by_id):
        raise ProductionChunkingConfigMismatchError(
            "Locally rebuilt 700/120 chunk_id set does not match the live production corpus."
        )

    remapped: dict[str, object] = {}
    mappings_by_dataset: dict[str, list] = {}
    failures: list[dict] = []
    original_datasets: dict[str, object] = {}
    for name, path in DATASET_PATHS.items():
        dataset = load_dataset(path)
        if name == "held_out" and digest(dataset.model_dump()) != FROZEN_HELDOUT_SHA256:
            raise HeldoutDatasetTamperedError(
                "Held-out dataset hash does not match the frozen value."
            )
        original_datasets[name] = dataset
        try:
            remapped_dataset, mappings = remap_dataset(
                dataset, documents, production_corpus_by_id, local_chunks
            )
        except EvidenceMappingFailure as exc:
            failures.append(
                {
                    "dataset": name,
                    "case_id": exc.case_id,
                    "chunk_id": exc.chunk_id,
                    "reason": exc.reason,
                }
            )
            continue
        remapped[name] = remapped_dataset
        mappings_by_dataset[name] = mappings

    if failures:
        raise ThresholdMappingFailuresPresentError(failures)
    return remapped, mappings_by_dataset, original_datasets


def run_threshold_sweep(repeats: int = 3, *, artifact_root: Path = ARTIFACT_ROOT) -> dict:
    """Phase A: rebuild the production 700/120 chunking configuration
    locally, verify it matches the live production corpus exactly, and
    remap both datasets' expected evidence against it (zero mapping
    failures required). Phase B: for each dataset, run evaluate() once per
    frozen threshold (5 runs), read-only against the unmodified live
    production Qdrant alias -- no collection is created, no chunking
    configuration is varied. Phase C: verify retrieval-rank invariance
    across all 5 threshold runs, detect case-level transitions, write one
    per-threshold artifact (reusing build_artifact_files exactly like
    Slice 2/3) plus one aggregate curve artifact per dataset.

    `artifact_root` defaults to the real repository artifact directory
    (production behavior, unchanged) but may be overridden -- e.g. with a
    pytest tmp_path -- so a live test can exercise the real retrieval path
    against the real production Qdrant/corpus while writing its own
    artifacts into an isolated directory. This never changes experiment_id
    (still a pure function of git commit + behavioral config) or weakens
    write_experiment_artifacts()'s no-overwrite guarantee -- it only
    changes WHERE that guarantee is enforced for a given call."""
    settings_base = PRODUCTION_SETTINGS
    embedding = SentenceTransformerEmbedding(settings_base.rag_model_cache, True)
    reranker = MiniLMCrossEncoder(settings_base.rerank_model_cache, True)
    documents, _ = load_frozen_source()

    with closing(QdrantClient(settings_base.qdrant_url, timeout=10)) as client:
        info = client.get_collection(settings_base.rag_qdrant_alias)
        if info.points_count != 39:
            raise ProductionCorpusChangedError(
                f"Production alias {settings_base.rag_qdrant_alias!r} has "
                f"{info.points_count} points before evaluation, expected 39."
            )
        index = NCDIndex(client, settings_base.rag_qdrant_alias)
        collection = index.resolve()
        production_corpus = load_corpus(index, collection)
        production_corpus_by_id = {c["chunk_id"]: c for c in production_corpus}

        remapped, mappings_by_dataset, original_datasets = _build_production_provenance_datasets(
            embedding, documents, production_corpus_by_id
        )

        search = Retriever(
            index,
            embedding,
            settings_base.retrieval_candidate_k,
            settings_base.retrieval_rrf_constant,
            settings_base.bm25_k1,
            settings_base.bm25_b,
        )

        git_commit = current_git_commit()
        source_state = git_source_state()

        dataset_results: dict[str, dict] = {}
        for name, remapped_dataset in remapped.items():
            rank_by_threshold: dict[float, dict[str, dict[str, int | None]]] = {}
            status_by_mode_case: dict[str, dict[str, dict[float, bool]]] = {
                mode: {} for mode in MODES
            }
            per_query_rows: list[dict] = []
            per_threshold_records: list[dict] = []

            for threshold in THRESHOLD_GRID:
                settings = settings_base.model_copy(update={"rag_min_score": threshold})
                cases, timings = evaluate(remapped_dataset, search, reranker, settings, repeats)
                summary = summarize(cases, timings)

                rank_by_threshold[threshold] = {
                    mode: {c["case_id"]: c["modes"][mode]["rank"] for c in cases} for mode in MODES
                }
                for mode in MODES:
                    for c in cases:
                        status_by_mode_case[mode].setdefault(c["case_id"], {})[threshold] = c[
                            "modes"
                        ][mode]["abstained"]
                        gate_hits = c["modes"][mode]["eligibility"]["hits"]
                        per_query_rows.append(
                            {
                                "case_id": c["case_id"],
                                "category": c["category"],
                                "answerable": c["answerable"],
                                "retrieval_mode": mode,
                                "evidence_threshold": threshold,
                                "expected_evidence_ids": c["expected_chunk_ids"],
                                "rank": c["modes"][mode]["rank"],
                                "gate_score": gate_hits[0]["cosine"] if gate_hits else None,
                                "answered_or_abstained": (
                                    "abstained" if c["modes"][mode]["abstained"] else "answered"
                                ),
                                "citation_expected_match": c["modes"][mode]["cites_expected"],
                            }
                        )

                config = ExperimentConfig(
                    experiment_type=ExperimentType.THRESHOLD,
                    dataset_version=remapped_dataset.dataset_version,
                    dataset_sha256=digest(original_datasets[name].model_dump()),
                    embedding_model=embedding.describe()["model"],
                    embedding_revision=embedding.describe()["revision"],
                    chunk_size=PRODUCTION_CHUNK_SIZE,
                    chunk_overlap=PRODUCTION_CHUNK_OVERLAP,
                    candidate_k=settings.retrieval_candidate_k,
                    rrf_k=settings.retrieval_rrf_constant,
                    rerank_enabled=True,
                    reranker_model=reranker.describe()["model"],
                    reranker_revision=reranker.describe()["revision"],
                    rerank_candidates=settings.rerank_candidate_k,
                    final_top_k=settings.rag_top_k,
                    evidence_threshold=threshold,
                    generation_provider=settings.rag_provider,
                    generation_model="deterministic",
                    git_commit=git_commit,
                    timestamp=datetime.now(UTC).isoformat(),
                    **source_state,
                )
                exp_id = experiment_id(config)
                files = build_artifact_files(
                    remapped_dataset.dataset_version, config, cases, summary, git_commit
                )
                files["evidence_mapping.json"] = [
                    {
                        "case_id": m.case_id,
                        "original_chunk_id": m.original_chunk_id,
                        "ncd_id": m.ncd_id,
                        "ncd_version": m.ncd_version,
                        "section": m.section,
                        "mapped_chunk_ids": m.mapped_chunk_ids,
                        "method": m.method,
                    }
                    for m in mappings_by_dataset[name]
                ]
                explicit_labels = {
                    mode: explicit_abstention_labels(summary["abstention"][mode]) for mode in MODES
                }
                citation = {mode: citation_expected_evidence(cases, mode) for mode in MODES}
                gate_dist = {mode: gate_score_distribution(cases, mode) for mode in MODES}
                files["summary.json"]["explicit_abstention_labels"] = explicit_labels
                files["summary.json"]["citation_expected_evidence"] = citation
                files["summary.json"]["gate_score_distribution"] = gate_dist
                artifact_dir = write_experiment_artifacts(artifact_root, exp_id, files)

                per_threshold_records.append(
                    {
                        "threshold": threshold,
                        "experiment_id": exp_id,
                        "artifact_dir": str(artifact_dir),
                        "retrieval_metrics": summary["metrics"],
                        "explicit_abstention_labels": explicit_labels,
                        "citation_expected_evidence": citation,
                        "gate_score_distribution": gate_dist,
                        "failure_category_counts": failure_category_counts(summary["failures"]),
                    }
                )

            info_after = client.get_collection(settings_base.rag_qdrant_alias)
            if info_after.points_count != 39:
                raise ProductionCorpusChangedError(
                    f"Production alias {settings_base.rag_qdrant_alias!r} has "
                    f"{info_after.points_count} points after evaluation, expected 39."
                )

            violations = []
            for mode in MODES:
                base = rank_by_threshold[THRESHOLD_GRID[0]][mode]
                for threshold in THRESHOLD_GRID[1:]:
                    other = rank_by_threshold[threshold][mode]
                    for case_id, rank in base.items():
                        if other.get(case_id) != rank:
                            violations.append(
                                {
                                    "mode": mode,
                                    "case_id": case_id,
                                    "threshold_a": THRESHOLD_GRID[0],
                                    "rank_a": rank,
                                    "threshold_b": threshold,
                                    "rank_b": other.get(case_id),
                                }
                            )
            if violations:
                raise RetrievalRankChangedAcrossThresholdsError(
                    f"{len(violations)} case(s) changed retrieval rank across thresholds "
                    f"for dataset {name!r}: {violations[:5]}"
                )

            transitions = detect_case_transitions(status_by_mode_case)

            historical = None
            if name == "development":
                historical_case_ids = {"cms-v1-003", "cms-v1-013", "cms-v1-017", "cms-v1-018"}
                historical = {}
                for row in per_query_rows:
                    if row["case_id"] in historical_case_ids and row["evidence_threshold"] == 0.60:
                        historical.setdefault(row["case_id"], {})[row["retrieval_mode"]] = row[
                            "gate_score"
                        ]

            curve_id = f"{git_commit[:8]}_threshold_sweep_{name}"
            curve_dir = write_experiment_artifacts(
                artifact_root,
                curve_id,
                {
                    "per_query.jsonl": per_query_rows,
                    "threshold_curve.json": {
                        "dataset": name,
                        "dataset_version": remapped_dataset.dataset_version,
                        "threshold_grid": THRESHOLD_GRID,
                        "per_threshold": per_threshold_records,
                    },
                    "case_transitions.json": [
                        {
                            "case_id": t.case_id,
                            "mode": t.mode,
                            "from_threshold": t.from_threshold,
                            "to_threshold": t.to_threshold,
                            "from_status": t.from_status,
                            "to_status": t.to_status,
                        }
                        for t in transitions
                    ],
                    "rank_invariance.json": {"invariant": True, "violations": []},
                    **(
                        {"historical_case_gate_scores.json": historical}
                        if historical is not None
                        else {}
                    ),
                },
            )
            dataset_results[name] = {
                "curve_id": curve_id,
                "curve_dir": str(curve_dir),
                "per_threshold_experiment_ids": [r["experiment_id"] for r in per_threshold_records],
                "transition_count": len(transitions),
            }

    result = {"datasets": dataset_results}
    print(json.dumps(result, indent=2))
    return result
