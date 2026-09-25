"""Phase 12 generic experiment runner.

    python -m evaluation.run_experiment --config <request.json>

Slice 2 supports exactly one experiment_type: "retrieval_baseline" — it
measures the current, unmodified production retrieval configuration against
a chosen dataset (development or held-out), reusing evaluate()/summarize()
from evaluation.run_retrieval_eval/evaluation.analysis directly rather than
re-implementing retrieval evaluation. chunking/threshold/reranker_comparison/
latency experiment types are valid ExperimentType values (later slices
implement them) but are explicitly rejected here, not silently run as a
baseline.

Read-only against the production Qdrant alias: no collection is created, no
alias is modified, no point is written or deleted. Does not touch
PostgreSQL at all."""

import argparse
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from app.core.config import Settings
from app.generation.providers import DeterministicProvider
from app.reranking.cross_encoder import MiniLMCrossEncoder
from app.retrieval.search import Retriever, load_corpus
from pydantic import field_validator, model_validator
from qdrant_client import QdrantClient

from evaluation.analysis import MODES, summarize
from evaluation.artifacts import write_experiment_artifacts
from evaluation.config import (
    ExperimentConfig,
    ExperimentType,
    current_git_commit,
    experiment_id,
    git_source_state,
)
from evaluation.dataset import StrictModel, load_dataset, validate_corpus
from evaluation.environment import capture_environment
from evaluation.run_retrieval_eval import evaluate
from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import digest

ARTIFACT_ROOT = Path("artifacts/evaluation")

DATASET_PATHS: dict[str, Path] = {
    "development": Path("docs/evaluation/golden_retrieval_v1.json"),
    "held_out": Path("docs/evaluation/golden_retrieval_heldout_v1.json"),
}
EXPECTED_DATASET_VERSION: dict[str, str] = {
    "development": "cms-retrieval-v1",
    "held_out": "cms-retrieval-heldout-v1",
}
# Frozen at Slice 1 approval. Any mismatch means the held-out file was
# edited after freeze -- the run must stop, not proceed or self-repair.
FROZEN_HELDOUT_SHA256 = "a144fc2e1611b41dca66dff0dc5a3415f3b1a11476de2d19555a2a3bacfe0158"

# Verified from backend/app/core/config.py::Settings defaults, not assumed.
# Slice 2 measures this configuration; it never modifies it.
PRODUCTION_SETTINGS = Settings(
    retrieval_candidate_k=10,
    retrieval_rrf_constant=60,
    bm25_k1=1.2,
    bm25_b=0.75,
    rerank_candidate_k=10,
    rag_top_k=5,
    rag_min_score=0.6,
    rag_context_chars=24000,
)
PRODUCTION_CHUNK_SIZE = 700
PRODUCTION_CHUNK_OVERLAP = 120


class UnsupportedExperimentTypeError(Exception):
    """Raised when a RunRequest names an experiment_type this slice of the
    runner does not implement. Never silently falls back to
    retrieval_baseline."""


class HeldoutDatasetTamperedError(Exception):
    """Raised when the held-out dataset's validated hash no longer matches
    the hash frozen at Slice 1 approval — the file was edited after
    freeze. The runner refuses to proceed or self-repair."""


class ProductionCorpusChangedError(Exception):
    """Raised when the production Qdrant alias's point count is not 39
    before running, or changes during the run."""


class RunRequest(StrictModel):
    """The user-supplied --config file: a request, not a resolved
    ExperimentConfig. dataset_sha256, embedding/reranker identity, and
    other fields a caller cannot know in advance are resolved by the
    runner itself and recorded in the artifact's config.json."""

    experiment_type: ExperimentType
    # Required for retrieval_baseline (selects which dataset to measure).
    # Ignored for chunking, which always runs the predetermined grid
    # against both datasets — not user-selectable, per the approved Slice 3
    # methodology.
    dataset: Literal["development", "held_out"] | None = None
    repeats: int = 3

    @field_validator("experiment_type", mode="before")
    @classmethod
    def _experiment_type_from_string(cls, value: object) -> object:
        # StrictModel's strict=True blocks plain-string-to-enum coercion, but
        # a JSON request file can only ever supply a plain string — same
        # pattern already established in app.orchestration.models,
        # app.agents.models, and app.review.models.
        if isinstance(value, str):
            try:
                return ExperimentType(value)
            except ValueError:
                return value
        return value

    @model_validator(mode="after")
    def _dataset_required_for_retrieval_baseline(self) -> "RunRequest":
        if self.experiment_type == ExperimentType.RETRIEVAL_BASELINE and self.dataset is None:
            raise ValueError("dataset is required when experiment_type='retrieval_baseline'")
        return self


def _resolve_dataset(name: Literal["development", "held_out"]):
    path = DATASET_PATHS[name]
    dataset = load_dataset(path)
    if dataset.dataset_version != EXPECTED_DATASET_VERSION[name]:
        raise ValueError(
            f"{path}: dataset_version {dataset.dataset_version!r} does not match the "
            f"expected {EXPECTED_DATASET_VERSION[name]!r} for dataset selection {name!r}"
        )
    if name == "held_out":
        actual = digest(dataset.model_dump())
        if actual != FROZEN_HELDOUT_SHA256:
            raise HeldoutDatasetTamperedError(
                f"Held-out dataset hash {actual} does not match the frozen "
                f"{FROZEN_HELDOUT_SHA256} — the file was modified after freeze."
            )
    return dataset


def run_retrieval_baseline(request: RunRequest) -> Path:
    dataset = _resolve_dataset(request.dataset)
    settings = PRODUCTION_SETTINGS

    with closing(QdrantClient(settings.qdrant_url, timeout=10)) as client:
        info = client.get_collection(settings.rag_qdrant_alias)
        if info.points_count != 39:
            raise ProductionCorpusChangedError(
                f"Production alias {settings.rag_qdrant_alias!r} has "
                f"{info.points_count} points before evaluation, expected 39."
            )
        index = NCDIndex(client, settings.rag_qdrant_alias)
        collection = index.resolve()
        corpus = load_corpus(index, collection)
        validate_corpus(dataset, corpus)

        embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
        reranker = MiniLMCrossEncoder(settings.rerank_model_cache, True)
        search = Retriever(
            index,
            embedding,
            settings.retrieval_candidate_k,
            settings.retrieval_rrf_constant,
            settings.bm25_k1,
            settings.bm25_b,
        )
        # evaluate()'s third positional argument is the reranker (cross-
        # encoder) it passes to rerank() — the generation provider is fixed
        # internally to DeterministicProvider() per case, not a parameter.
        cases, timings = evaluate(dataset, search, reranker, settings, request.repeats)

        info_after = client.get_collection(settings.rag_qdrant_alias)
        if info_after.points_count != 39:
            raise ProductionCorpusChangedError(
                f"Production alias {settings.rag_qdrant_alias!r} has "
                f"{info_after.points_count} points after evaluation, expected 39."
            )

    summary = summarize(cases, timings)

    git_commit = current_git_commit()
    source_state = git_source_state()
    config = ExperimentConfig(
        experiment_type=ExperimentType.RETRIEVAL_BASELINE,
        dataset_version=dataset.dataset_version,
        dataset_sha256=digest(dataset.model_dump()),
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
        evidence_threshold=settings.rag_min_score,
        generation_provider=settings.rag_provider,
        generation_model=DeterministicProvider.model,
        git_commit=git_commit,
        timestamp=datetime.now(UTC).isoformat(),
        **source_state,
    )
    exp_id = experiment_id(config)
    files = build_artifact_files(dataset.dataset_version, config, cases, summary, git_commit)
    artifact_dir = write_experiment_artifacts(ARTIFACT_ROOT, exp_id, files)
    print(json.dumps({"experiment_id": exp_id, "artifact_dir": str(artifact_dir)}, indent=2))
    return artifact_dir


def build_artifact_files(
    dataset_version: str,
    config: ExperimentConfig,
    cases: list[dict],
    summary: dict,
    git_commit: str,
) -> dict[str, object]:
    """Shared by every experiment_type that ultimately runs evaluate()/
    summarize() over a list of per-case, per-mode results (the same 'cases'
    shape evaluate() itself returns) — reused by both retrieval_baseline and
    the Slice 3 chunking grid, not duplicated."""
    per_query_rows = []
    for case in cases:
        for mode in MODES:
            result = case["modes"][mode]
            per_query_rows.append(
                {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "answerable": case["answerable"],
                    "retrieval_mode": mode,
                    "expected_chunk_ids": case["expected_chunk_ids"],
                    "rank": result["rank"],
                    "retrieved_chunk_ids": [h["chunk_id"] for h in result["hits"]],
                    "abstained": result["abstained"],
                    "abstention_reason": result["abstention_reason"],
                    "cites_expected": result["cites_expected"],
                    "latency_ms": result["latency_ms"],
                }
            )
    return {
        "config.json": config.model_dump(mode="json"),
        "per_query.jsonl": per_query_rows,
        "summary.json": {
            "dataset_version": dataset_version,
            "dataset_sha256": config.dataset_sha256,
            "case_count": len(cases),
            "positive_cases": sum(c["answerable"] for c in cases),
            "negative_cases": sum(not c["answerable"] for c in cases),
            "metrics": summary["metrics"],
            "abstention": summary["abstention"],
            "reranking": summary["reranking"],
            "failure_category_counts": failure_category_counts(summary["failures"]),
        },
        "latency.json": {"stages": summary["latency"]},
        "environment.json": capture_environment(git_commit),
    }


def failure_category_counts(failures: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for failure in failures:
        for category in failure.get("categories", []):
            counts[category] = counts.get(category, 0) + 1
    return counts


def dispatch(request: RunRequest) -> Path | dict:
    """retrieval_baseline (Slice 2) and chunking (Slice 3) are implemented.
    threshold/reranker_comparison/latency remain valid ExperimentType
    values with no branch here yet — explicitly rejected, never silently
    run as a baseline."""
    if request.experiment_type == ExperimentType.RETRIEVAL_BASELINE:
        return run_retrieval_baseline(request)
    if request.experiment_type == ExperimentType.CHUNKING:
        from evaluation.chunking_experiment import run_chunking_grid

        return run_chunking_grid(request.repeats)
    if request.experiment_type == ExperimentType.THRESHOLD:
        from evaluation.threshold_experiment import run_threshold_sweep

        return run_threshold_sweep(request.repeats)
    if request.experiment_type == ExperimentType.LATENCY:
        import asyncio

        from evaluation.latency_experiment import run_latency_evaluation

        return asyncio.run(run_latency_evaluation())
    if request.experiment_type == ExperimentType.RERANKER_COMPARISON:
        from evaluation.reranker_comparison import run_reranker_comparison

        return run_reranker_comparison()
    raise UnsupportedExperimentTypeError(
        f"experiment_type={request.experiment_type!r} is not implemented by this slice "
        "of evaluation.run_experiment; only 'retrieval_baseline', 'chunking', 'threshold', "
        "'latency', and 'reranker_comparison' are supported."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    request = RunRequest.model_validate(json.loads(args.config.read_text()))
    dispatch(request)


if __name__ == "__main__":
    main()
