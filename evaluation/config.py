"""Typed, versioned Phase 12 experiment configuration and deterministic
experiment identity. Reuses evaluation.dataset.StrictModel (extra="forbid",
strict=True) — the same convention every other evaluation/orchestration
contract in this codebase already uses — rather than a second config style.

Field selection follows what the actual retrieval pipeline exposes, not a
generic wishlist: there is one shared candidate_k governing both dense and
BM25 candidate depth in app.retrieval.search.Retriever (not two independent
knobs), so this config has one field, not two differently-named ones that
would silently always be equal. random_seed is omitted entirely: nothing in
the current pipeline (BM25 scoring, dense cosine similarity, RRF fusion) is
stochastic, so a seed field would carry no real meaning."""

import subprocess
from enum import StrEnum
from typing import Literal

from pydantic import Field

from evaluation.dataset import StrictModel
from ingestion.models import digest


class ExperimentType(StrEnum):
    RETRIEVAL_BASELINE = "retrieval_baseline"
    CHUNKING = "chunking"
    THRESHOLD = "threshold"
    RERANKER_COMPARISON = "reranker_comparison"
    LATENCY = "latency"


class ExperimentConfig(StrictModel):
    experiment_type: ExperimentType
    dataset_version: Literal["cms-retrieval-v1", "cms-retrieval-heldout-v1"]
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    embedding_model: str = Field(min_length=1)
    embedding_revision: str = Field(min_length=1)

    chunk_size: int = Field(ge=32, le=4000)
    chunk_overlap: int = Field(ge=0)

    candidate_k: int = Field(ge=1, le=20)
    rrf_k: int = Field(gt=0)

    rerank_enabled: bool
    reranker_model: str | None = None
    reranker_revision: str | None = None
    rerank_candidates: int | None = Field(default=None, ge=1)

    final_top_k: int = Field(ge=1)
    evidence_threshold: float = Field(ge=-1, le=1)

    generation_provider: Literal["deterministic", "openai"]
    generation_model: str = Field(min_length=1)

    # Identity metadata: excluded from the canonical hash (see config_hash)
    # so the same parameters always produce the same experiment identity
    # regardless of when, on which commit, or with which uncommitted changes
    # they were run.
    git_commit: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)

    # git_commit alone does not prove source identity while Phase 12 work is
    # uncommitted (the working tree may legitimately be dirty with earlier,
    # not-yet-committed phase work too) — these record exactly which
    # tracked files differ from git_commit, or that none do.
    working_tree_clean: bool
    modified_files: list[str] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)


def current_git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def git_source_state() -> dict:
    """Bounded, deterministic disclosure of what differs from git_commit —
    file paths only (sorted), never file contents or absolute paths (git
    already reports repo-relative paths)."""
    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout
    modified, untracked = [], []
    for line in status.splitlines():
        code, path = line[:2], line[3:]
        (untracked if code == "??" else modified).append(path)
    return {
        "working_tree_clean": not modified and not untracked,
        "modified_files": sorted(modified),
        "untracked_files": sorted(untracked),
    }


def config_hash(config: ExperimentConfig) -> str:
    """Deterministic hash over the experiment's actual parameters only.
    git_commit/timestamp/working_tree_clean/modified_files/untracked_files
    are excluded: they identify *when and on what exact code state* an
    experiment ran, not *what it measured* — two runs of the same
    parameters must hash identically so they can be compared as the same
    experiment regardless of execution provenance."""
    payload = config.model_dump(
        mode="json",
        exclude={
            "git_commit",
            "timestamp",
            "working_tree_clean",
            "modified_files",
            "untracked_files",
        },
    )
    return digest(payload)[:12]


def experiment_id(config: ExperimentConfig) -> str:
    return f"{config.git_commit[:8]}_{config_hash(config)}"
