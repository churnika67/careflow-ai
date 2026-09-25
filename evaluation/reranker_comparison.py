"""Phase 12 Slice 6: reranker quality-vs-latency trade-off.

Isolates exactly one experimental difference: the SAME pre-rerank hybrid
candidate pool (search.search(query, "hybrid", 10, for_rag=True)), compared
before reranking (RRF order) and after reranking (rerank() on that identical
pool). Chunking (700/120), embedding, BM25, RRF, candidate_k, evidence
threshold (0.60), and final_top_k are all held fixed at production values --
nothing here re-runs the chunking grid or threshold sweep.

Why this module exists instead of reusing Slice 2's stored artifacts
verbatim (audited first, per instructions): Slice 2's own "hybrid" per-query
rows come from search.search(query, "hybrid", 5, for_rag=True) -- a
SEPARATE, SHALLOWER (depth 5) call than the depth-10 for_rag candidate pool
actually handed to rerank() for "hybrid_reranked". Comparing those two stored
rows therefore confounds two effects -- candidate-pool depth (5 vs 10) and
reordering -- rather than isolating reranking alone, and the stored artifact
carries no pre-rerank candidate_ids, gate scores, or reranker scores at all.
A minimal, targeted live pass (ONE deterministic call per case, no repeats --
reproducibility was already established extensively in Phase 6/7/Slices
2-4 and is not re-proven here) is therefore required to produce a genuinely
paired, same-candidate-pool comparison. Slice 2's own hybrid_reranked
generation-provider/citation logic is reused via the identical RAGService/
eligibility() pattern evaluate() already uses -- not reimplemented.

Retrieval-stage and rerank-only LATENCY are read directly from the existing
Slice 2 baseline artifacts (development: eb59bc90_774ea9a697a1, held_out:
eb59bc90_a223469082ce) -- not re-measured here."""

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.generation.providers import DeterministicProvider
from app.generation.service import RAGService
from app.reranking.cross_encoder import MODEL_NAME, MODEL_REVISION, MiniLMCrossEncoder
from app.reranking.service import rerank
from app.retrieval.search import Retriever, load_corpus
from qdrant_client import QdrantClient

from evaluation.analysis import eligibility
from evaluation.artifacts import write_experiment_artifacts
from evaluation.config import current_git_commit, git_source_state
from evaluation.dataset import load_dataset
from evaluation.environment import capture_environment
from evaluation.metrics import FailureCategory, first_rank, rank_change, retrieval_metrics
from evaluation.run_experiment import (
    ARTIFACT_ROOT,
    FROZEN_HELDOUT_SHA256,
    PRODUCTION_CHUNK_OVERLAP,
    PRODUCTION_CHUNK_SIZE,
    PRODUCTION_SETTINGS,
    HeldoutDatasetTamperedError,
    ProductionCorpusChangedError,
)
from evaluation.threshold_experiment import citation_expected_evidence, explicit_abstention_labels
from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import digest

DATASET_PATHS = {
    "development": Path("docs/evaluation/golden_retrieval_v1.json"),
    "held_out": Path("docs/evaluation/golden_retrieval_heldout_v1.json"),
}
EVIDENCE_THRESHOLD = 0.60
CANDIDATE_DEPTH = 10
FINAL_TOP_K = 5
LONG_SECTION_CASE_IDS = {"cms-v1-h003", "cms-v1-h004"}
RETRIEVAL_BASELINE_ARTIFACTS = {
    "development": "eb59bc90_774ea9a697a1",
    "held_out": "eb59bc90_a223469082ce",
}


@dataclass(frozen=True)
class PairedCase:
    case_id: str
    dataset: str
    category: str
    answerable: bool
    hybrid_rank: int | None
    hybrid_abstained: bool
    hybrid_gate_score: float | None
    hybrid_top_chunk_ids: list[str]
    hybrid_reranked_rank: int | None
    hybrid_reranked_abstained: bool
    hybrid_reranked_gate_score: float | None
    hybrid_reranked_top_chunk_ids: list[str]
    hybrid_reranked_scores: list[float | None]
    rank_change_class: str
    entered_top1: bool
    left_top1: bool
    entered_top3: bool
    left_top3: bool
    entered_top5: bool
    left_top5: bool
    candidate_set_equal: bool
    hybrid_cites_expected: bool | None
    hybrid_reranked_cites_expected: bool | None
    failure_categories: list[str]


def _entered_left(before: int | None, after: int | None, k: int) -> tuple[bool, bool]:
    was_in = before is not None and before <= k
    now_in = after is not None and after <= k
    return (not was_in and now_in), (was_in and not now_in)


def _failure_categories(
    *,
    answerable: bool,
    hybrid_rank,
    hybrid_reranked_rank,
    hybrid_abstained,
    hybrid_reranked_abstained,
) -> list[str]:
    """Reuses exactly the existing approved FailureCategory taxonomy -- no
    new causal category invented for Slice 6."""
    categories: set[str] = set()
    if answerable:
        if hybrid_rank is None:
            categories.add(FailureCategory.NO_RELEVANT_IN_TOP_K.value)
        if hybrid_reranked_rank is None:
            categories.add(FailureCategory.NO_RELEVANT_IN_TOP_K.value)
        if hybrid_abstained and not hybrid_reranked_abstained and hybrid_rank is not None:
            categories.add(FailureCategory.BELOW_EVIDENCE_THRESHOLD.value)
        if hybrid_reranked_abstained and not hybrid_abstained and hybrid_reranked_rank is not None:
            categories.add(FailureCategory.BELOW_EVIDENCE_THRESHOLD.value)
        if hybrid_abstained or hybrid_reranked_abstained:
            categories.add(FailureCategory.INCORRECT_ABSTENTION.value)
    else:
        if not hybrid_abstained or not hybrid_reranked_abstained:
            categories.add(FailureCategory.INCORRECT_ABSTENTION.value)
    return sorted(categories)


def _evaluate_case(*, case, search, reranker, settings) -> PairedCase:
    candidates = search.search(case.query, "hybrid", CANDIDATE_DEPTH, for_rag=True)
    reranked = rerank(case.query, candidates, reranker, FINAL_TOP_K)

    expected = case.expected_chunk_ids
    hybrid_rank = first_rank(candidates, expected) if case.answerable else None
    hybrid_reranked_rank = first_rank(reranked, expected) if case.answerable else None

    hybrid_eligibility = eligibility(
        candidates, expected, EVIDENCE_THRESHOLD, settings.rag_context_chars
    )
    reranked_eligibility = eligibility(
        reranked, expected, EVIDENCE_THRESHOLD, settings.rag_context_chars
    )
    hybrid_gate_score = (
        hybrid_eligibility["hits"][0]["cosine"] if hybrid_eligibility["hits"] else None
    )
    reranked_gate_score = (
        reranked_eligibility["hits"][0]["cosine"] if reranked_eligibility["hits"] else None
    )

    def _make_retrieve(hits, target):
        def retrieve(_question, rows=hits, out=target):
            out.extend(
                eligibility(rows, expected, EVIDENCE_THRESHOLD, settings.rag_context_chars)[
                    "context_chunk_ids"
                ]
            )
            return rows

        return retrieve

    hybrid_context_ids: list[str] = []
    hybrid_answer = RAGService(
        _make_retrieve(candidates, hybrid_context_ids), DeterministicProvider(), settings
    ).answer(case.query)
    reranked_context_ids: list[str] = []
    reranked_answer = RAGService(
        _make_retrieve(reranked, reranked_context_ids), DeterministicProvider(), settings
    ).answer(case.query)

    hybrid_cites_expected = (
        any(c.chunk_id in expected for c in hybrid_answer.citations) if case.answerable else None
    )
    reranked_cites_expected = (
        any(c.chunk_id in expected for c in reranked_answer.citations) if case.answerable else None
    )

    change = rank_change(hybrid_rank, hybrid_reranked_rank) if case.answerable else None
    e1, l1 = _entered_left(hybrid_rank, hybrid_reranked_rank, 1)
    e3, l3 = _entered_left(hybrid_rank, hybrid_reranked_rank, 3)
    e5, l5 = _entered_left(hybrid_rank, hybrid_reranked_rank, 5)

    candidate_ids = {h["chunk_id"] for h in candidates}
    reranked_ids = {h["chunk_id"] for h in reranked}

    return PairedCase(
        case_id=case.case_id,
        dataset="",  # filled by caller
        category=case.category,
        answerable=case.answerable,
        hybrid_rank=hybrid_rank,
        hybrid_abstained=hybrid_answer.insufficient_evidence,
        hybrid_gate_score=hybrid_gate_score,
        hybrid_top_chunk_ids=[h["chunk_id"] for h in candidates[:FINAL_TOP_K]],
        hybrid_reranked_rank=hybrid_reranked_rank,
        hybrid_reranked_abstained=reranked_answer.insufficient_evidence,
        hybrid_reranked_gate_score=reranked_gate_score,
        hybrid_reranked_top_chunk_ids=[h["chunk_id"] for h in reranked],
        hybrid_reranked_scores=[h.get("rerank_score") for h in reranked],
        rank_change_class=change["classification"] if change else "not_applicable",
        entered_top1=e1,
        left_top1=l1,
        entered_top3=e3,
        left_top3=l3,
        entered_top5=e5,
        left_top5=l5,
        candidate_set_equal=reranked_ids <= candidate_ids,
        hybrid_cites_expected=hybrid_cites_expected,
        hybrid_reranked_cites_expected=reranked_cites_expected,
        failure_categories=_failure_categories(
            answerable=case.answerable,
            hybrid_rank=hybrid_rank,
            hybrid_reranked_rank=hybrid_reranked_rank,
            hybrid_abstained=hybrid_answer.insufficient_evidence,
            hybrid_reranked_abstained=reranked_answer.insufficient_evidence,
        ),
    )


def _abstention_confusion(cases: list[PairedCase], *, reranked: bool) -> dict:
    positives = [c for c in cases if c.answerable]
    negatives = [c for c in cases if not c.answerable]
    abstained = (
        (lambda c: c.hybrid_reranked_abstained) if reranked else (lambda c: c.hybrid_abstained)
    )
    tp = sum(abstained(c) for c in negatives)
    fp = sum(abstained(c) for c in positives)
    return {
        "negative_cases": len(negatives),
        "positive_cases": len(positives),
        "correct_abstentions": tp,
        "incorrect_answer_attempts": len(negatives) - tp,
        "positive_abstentions": fp,
    }


def _citation_rows(cases: list[PairedCase], *, reranked: bool) -> list[dict]:
    abstained_key = "hybrid_reranked_abstained" if reranked else "hybrid_abstained"
    cites_key = "hybrid_reranked_cites_expected" if reranked else "hybrid_cites_expected"
    return [
        {
            "answerable": c.answerable,
            "modes": {
                "x": {
                    "abstained": getattr(c, abstained_key),
                    "cites_expected": bool(getattr(c, cites_key)),
                }
            },
        }
        for c in cases
    ]


def _summarize_dataset(dataset_name: str, cases: list[PairedCase]) -> dict:
    positives = [c for c in cases if c.answerable]
    hybrid_metrics = retrieval_metrics([c.hybrid_rank for c in positives])
    reranked_metrics = retrieval_metrics([c.hybrid_reranked_rank for c in positives])

    def _delta(key):
        a, b = hybrid_metrics.get(key), reranked_metrics.get(key)
        return (b - a) if a is not None and b is not None else None

    rank_counts = {"improved": 0, "unchanged": 0, "degraded": 0}
    for c in positives:
        rank_counts[c.rank_change_class] = rank_counts.get(c.rank_change_class, 0) + 1

    hybrid_abstention = _abstention_confusion(cases, reranked=False)
    reranked_abstention = _abstention_confusion(cases, reranked=True)

    abstention_transitions = []
    for c in cases:
        if c.hybrid_abstained != c.hybrid_reranked_abstained:
            abstention_transitions.append(
                {
                    "case_id": c.case_id,
                    "answerable": c.answerable,
                    "hybrid_abstained": c.hybrid_abstained,
                    "hybrid_reranked_abstained": c.hybrid_reranked_abstained,
                    "effect": (
                        "creates_false_abstention"
                        if c.answerable and c.hybrid_reranked_abstained
                        else "removes_false_abstention"
                        if c.answerable and c.hybrid_abstained
                        else "creates_unsupported_answer"
                        if not c.answerable and c.hybrid_abstained
                        else "removes_unsupported_answer"
                    ),
                }
            )

    hybrid_citation = citation_expected_evidence(_citation_rows(cases, reranked=False), "x")
    reranked_citation = citation_expected_evidence(_citation_rows(cases, reranked=True), "x")

    long_section = [
        {
            "case_id": c.case_id,
            "hybrid_rank": c.hybrid_rank,
            "hybrid_reranked_rank": c.hybrid_reranked_rank,
            "rank_change_class": c.rank_change_class,
        }
        for c in cases
        if c.case_id in LONG_SECTION_CASE_IDS
    ]

    return {
        "dataset": dataset_name,
        "case_count": len(cases),
        "positive_cases": len(positives),
        "negative_cases": len(cases) - len(positives),
        "hybrid_metrics": hybrid_metrics,
        "hybrid_reranked_metrics": reranked_metrics,
        "metric_deltas": {k: _delta(k) for k in ("Hit@1", "Hit@3", "Hit@5", "MRR@5")},
        "rank_change_counts": rank_counts,
        "hybrid_abstention": {**hybrid_abstention, **explicit_abstention_labels(hybrid_abstention)},
        "hybrid_reranked_abstention": {
            **reranked_abstention,
            **explicit_abstention_labels(reranked_abstention),
        },
        "abstention_transitions": abstention_transitions,
        "hybrid_citation_expected_evidence": hybrid_citation,
        "hybrid_reranked_citation_expected_evidence": reranked_citation,
        "long_section_cases": long_section,
        "candidate_set_equal_for_all_cases": all(c.candidate_set_equal for c in cases),
    }


def load_retrieval_and_rerank_latency() -> dict:
    result = {}
    for dataset, experiment_id in RETRIEVAL_BASELINE_ARTIFACTS.items():
        stages = json.loads((ARTIFACT_ROOT / experiment_id / "latency.json").read_text())["stages"]
        hybrid_median = stages["hybrid_candidates_with_gate"]["median_ms"]
        rerank_median = stages["rerank_only"]["median_ms"]
        result[dataset] = {
            "source_experiment_id": experiment_id,
            "hybrid_candidates_with_gate": stages["hybrid_candidates_with_gate"],
            "rerank_only": stages["rerank_only"],
            "descriptive_summed_stage_medians_ms": hybrid_median + rerank_median,
            "rerank_to_hybrid_median_ratio": (
                rerank_median / hybrid_median if hybrid_median else None
            ),
        }
    return result


def run_reranker_comparison(*, artifact_root: Path = ARTIFACT_ROOT) -> dict:
    """`artifact_root` defaults to the real repository artifact directory
    (production behavior, unchanged) but may be overridden -- e.g. with a
    pytest tmp_path -- so a live test can exercise the real retrieval/rerank
    path against the real production Qdrant/corpus while writing its own
    artifacts into an isolated directory. This never changes experiment_id
    or weakens write_experiment_artifacts()'s no-overwrite guarantee; it
    only changes WHERE that guarantee is enforced. The reused Slice 2
    latency artifacts are always read from the real repository root
    (load_retrieval_and_rerank_latency() -- historical data, not written
    here), regardless of this override."""
    settings = PRODUCTION_SETTINGS
    embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
    reranker = MiniLMCrossEncoder(settings.rerank_model_cache, True)

    with closing(QdrantClient(settings.qdrant_url, timeout=10)) as client:
        info = client.get_collection(settings.rag_qdrant_alias)
        if info.points_count != 39:
            raise ProductionCorpusChangedError(
                f"Production alias has {info.points_count} points before evaluation, expected 39."
            )
        index = NCDIndex(client, settings.rag_qdrant_alias)
        collection = index.resolve()
        corpus = load_corpus(index, collection)
        search = Retriever(
            index,
            embedding,
            settings.retrieval_candidate_k,
            settings.retrieval_rrf_constant,
            settings.bm25_k1,
            settings.bm25_b,
        )

        datasets = {}
        for name, path in DATASET_PATHS.items():
            dataset = load_dataset(path)
            if name == "held_out" and digest(dataset.model_dump()) != FROZEN_HELDOUT_SHA256:
                raise HeldoutDatasetTamperedError(
                    "Held-out dataset hash does not match the frozen value."
                )
            datasets[name] = dataset

        all_paired: dict[str, list[PairedCase]] = {}
        for name, dataset in datasets.items():
            rows = []
            for case in dataset.cases:
                paired = _evaluate_case(
                    case=case, search=search, reranker=reranker, settings=settings
                )
                rows.append(PairedCase(**{**paired.__dict__, "dataset": name}))
                print(f"Evaluated {case.case_id}", flush=True)
            all_paired[name] = rows

        info_after = client.get_collection(settings.rag_qdrant_alias)
        if info_after.points_count != 39:
            raise ProductionCorpusChangedError(
                f"Production alias has {info_after.points_count} points after evaluation, "
                "expected 39."
            )
        corpus_fingerprint_after = digest(load_corpus(index, index.resolve()))

    summaries = {name: _summarize_dataset(name, rows) for name, rows in all_paired.items()}
    latency = load_retrieval_and_rerank_latency()

    git_commit = current_git_commit()
    source_state = git_source_state()
    config = {
        "experiment_type": "reranker_comparison",
        "description": (
            "Phase 12 Slice 6: paired hybrid vs hybrid_reranked comparison over the "
            "identical depth-10 pre-rerank candidate pool. Reranker is the only "
            "experimental difference."
        ),
        "chunk_size": PRODUCTION_CHUNK_SIZE,
        "chunk_overlap": PRODUCTION_CHUNK_OVERLAP,
        "candidate_k": settings.retrieval_candidate_k,
        "rrf_k": settings.retrieval_rrf_constant,
        "evidence_threshold": EVIDENCE_THRESHOLD,
        "final_top_k": FINAL_TOP_K,
        "candidate_depth_for_rerank": CANDIDATE_DEPTH,
        "reranker_model": MODEL_NAME,
        "reranker_revision": MODEL_REVISION,
        "reranker_device": "cpu",
        "generation_provider": "deterministic",
        "git_commit": git_commit,
        "timestamp": datetime.now(UTC).isoformat(),
        "corpus_fingerprint": digest(corpus),
        **source_state,
    }

    paired_rows = [
        {
            "case_id": c.case_id,
            "dataset": c.dataset,
            "category": c.category,
            "answerable": c.answerable,
            "hybrid": {
                "rank": c.hybrid_rank,
                "abstained": c.hybrid_abstained,
                "gate_score": c.hybrid_gate_score,
                "top_chunk_ids": c.hybrid_top_chunk_ids,
                "cites_expected": c.hybrid_cites_expected,
            },
            "hybrid_reranked": {
                "rank": c.hybrid_reranked_rank,
                "abstained": c.hybrid_reranked_abstained,
                "gate_score": c.hybrid_reranked_gate_score,
                "top_chunk_ids": c.hybrid_reranked_top_chunk_ids,
                "reranker_scores": c.hybrid_reranked_scores,
                "cites_expected": c.hybrid_reranked_cites_expected,
            },
            "rank_change_class": c.rank_change_class,
            "entered_top1": c.entered_top1,
            "left_top1": c.left_top1,
            "entered_top3": c.entered_top3,
            "left_top3": c.left_top3,
            "entered_top5": c.entered_top5,
            "left_top5": c.left_top5,
            "candidate_set_equal": c.candidate_set_equal,
            "failure_categories": c.failure_categories,
        }
        for rows in all_paired.values()
        for c in rows
    ]

    experiment_id = f"{git_commit[:8]}_reranker_comparison"
    artifact_dir = write_experiment_artifacts(
        artifact_root,
        experiment_id,
        {
            "config.json": config,
            "paired_cases.jsonl": paired_rows,
            "summary.json": {
                "development": summaries["development"],
                "held_out": summaries["held_out"],
            },
            "latency.json": latency,
            "environment.json": capture_environment(git_commit),
        },
    )
    result = {
        "experiment_id": experiment_id,
        "artifact_dir": str(artifact_dir),
        "corpus_fingerprint_unchanged": digest(corpus) == corpus_fingerprint_after,
    }
    print(json.dumps(result, indent=2))
    return {**result, "summaries": summaries, "latency": latency}
