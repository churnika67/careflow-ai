"""Phase 12 Slice 3: isolated chunking experiments.

Reuses the production ingestion pipeline unchanged — chunk_documents(),
load_documents(), NCDIndex.publish(), Retriever, evaluate(), summarize() —
parameterized by an alternate ChunkingConfig against an isolated Qdrant
alias. Nothing here re-implements chunking, embedding, indexing, or
retrieval; this module only adds the experiment-lifecycle plumbing (index
create/teardown, production-alias guard, deterministic evidence remapping)
those functions don't need to know about.

The single most important property of this module: chunk_id already
incorporates the chunking config (target_tokens/overlap_tokens/version) as
part of its identity hash (see ingestion/chunking/sections.py) — verified by
direct inspection, not assumed. Different configurations can never collide
on chunk_id, and a config's own chunk_ids are already fully deterministic
and reproducible. What is NOT stable across configs is which chunk_id holds
a given piece of evidence — that is what evidence remapping (below) exists
to compute, deterministically, from source provenance."""

import json
from dataclasses import dataclass
from typing import Literal

from ingestion.chunking.sections import ChunkingConfig, chunk_documents
from ingestion.cms_coverage.source import load_documents
from ingestion.embeddings.providers import EmbeddingProvider
from ingestion.indexing.qdrant import ALIAS as PRODUCTION_ALIAS
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import Chunk, Document, digest

# The exact frozen local CMS source snapshot every golden dataset was built
# against — verified (not assumed) to reproduce snapshot_sha256
# 735619558de8759427d5fe71989d06b48e5625376594fe94efa7a60f7e152ca3, the same
# value recorded in both golden_retrieval_v1.json and
# golden_retrieval_heldout_v1.json, before this module was written. No
# network access; a checksum-gated local archive.
SOURCE_ARCHIVE = "data/raw/cms_coverage/ncd.zip"
SOURCE_SUBSET = "docs/cms_inspection/dev_subset.json"
SOURCE_PROFILE = "docs/cms_inspection/ncd_profile.json"

# Approved, predetermined 6-point grid. Not modified after seeing any result.
CHUNKING_GRID: list[tuple[int, int]] = [
    (400, 0),
    (400, 120),
    (700, 0),
    (700, 120),
    (1200, 0),
    (1200, 120),
]


class ProductionAliasGuardError(Exception):
    """Raised when experiment code would touch the production alias or its
    currently-resolved physical collection. Never bypassed."""


def experiment_alias_for(target_tokens: int, overlap_tokens: int) -> str:
    # NCDIndex requires ^[a-zA-Z][a-zA-Z0-9_]{0,60}$ -- no hyphens.
    return f"careflow_exp_chunk_{target_tokens}_{overlap_tokens}"


def assert_not_production_alias(alias: str, client) -> None:
    """Hard guard, not developer discipline: refuses to proceed if the
    requested experiment alias is literally the production alias, or would
    resolve to the collection the production alias currently points at."""
    if alias == PRODUCTION_ALIAS:
        raise ProductionAliasGuardError(
            f"Refusing to use {alias!r} as an experiment alias — it is the production alias."
        )
    production_collection = NCDIndex(client, PRODUCTION_ALIAS).resolve()
    experiment_collection = NCDIndex(client, alias).resolve()
    if production_collection is not None and experiment_collection == production_collection:
        raise ProductionAliasGuardError(
            f"Refusing to proceed — experiment alias {alias!r} resolves to the production "
            f"physical collection {production_collection!r}."
        )


def load_frozen_source() -> tuple[list[Document], dict]:
    from pathlib import Path

    return load_documents(Path(SOURCE_ARCHIVE), Path(SOURCE_SUBSET), Path(SOURCE_PROFILE))


def build_experiment_chunks(
    documents: list[Document], embedding: EmbeddingProvider, target_tokens: int, overlap_tokens: int
) -> list[Chunk]:
    config = ChunkingConfig(target_tokens=target_tokens, overlap_tokens=overlap_tokens)
    return chunk_documents(documents, embedding.tokenizer, config)


def chunk_corpus_statistics(chunks: list[Chunk]) -> dict:
    token_counts = sorted(c.metadata["token_count"] for c in chunks)
    n = len(token_counts)
    median = (
        token_counts[n // 2] if n % 2 else (token_counts[n // 2 - 1] + token_counts[n // 2]) / 2
    )
    by_ncd: dict[str, int] = {}
    for c in chunks:
        by_ncd[c.metadata["NCD_id"]] = by_ncd.get(c.metadata["NCD_id"], 0) + 1
    return {
        "section_count": len({c.metadata["section_id"] for c in chunks}),
        "chunk_count": len(chunks),
        "min_tokens": token_counts[0],
        "median_tokens": median,
        "mean_tokens": sum(token_counts) / n,
        "max_tokens": token_counts[-1],
        "chunks_per_ncd": by_ncd,
    }


# --- evidence remapping ----------------------------------------------------


@dataclass(frozen=True)
class EvidenceMapping:
    case_id: str
    original_chunk_id: str
    ncd_id: str
    ncd_version: str
    section: str
    mapped_chunk_ids: list[str]
    method: Literal["section_and_quote_span"]


class EvidenceMappingFailure(Exception):
    """Raised when expected evidence cannot be deterministically mapped for
    a case under a chunking configuration. Never guessed, never resolved by
    retrieval rank/embedding/reranker score, never silently skipped."""

    def __init__(self, case_id: str, chunk_id: str, reason: str) -> None:
        self.case_id = case_id
        self.chunk_id = chunk_id
        self.reason = reason
        super().__init__(f"{case_id} / evidence chunk {chunk_id}: {reason}")


def _section_text_by_id(documents: list[Document]) -> dict[str, str]:
    """The exact same section_id hash chunk_documents() computes internally
    (document_version_id + field + ordinal + text) — independent of
    chunking config, so it is stable across every configuration for the
    same section. Reused here as the deterministic anchor between a
    production chunk and its experiment-config chunk(s)."""
    result = {}
    for document in documents:
        for section in document.sections:
            section_id = digest(
                {
                    "document": document.metadata["document_version_id"],
                    "field": section.field,
                    "ordinal": section.ordinal,
                    "text": section.text,
                }
            )
            result[section_id] = section.text
    return result


def map_evidence_chunk(
    *,
    case_id: str,
    original_chunk_id: str,
    quote: str,
    production_corpus_by_id: dict[str, dict],
    section_text_by_id: dict[str, str],
    experiment_chunks: list[Chunk],
) -> EvidenceMapping:
    production_chunk = production_corpus_by_id.get(original_chunk_id)
    if production_chunk is None:
        raise EvidenceMappingFailure(
            case_id, original_chunk_id, "original chunk_id not found in the production corpus"
        )
    section_id = production_chunk["section_id"]
    section_text = section_text_by_id.get(section_id)
    if section_text is None:
        raise EvidenceMappingFailure(
            case_id, original_chunk_id, f"section_id {section_id} not found in frozen source"
        )

    # Disambiguate a repeated quote using the original chunk's own char span
    # as the anchor -- the occurrence that overlaps it is the one already
    # validated for this case.
    orig_start = production_chunk["section_char_start"]
    orig_end = production_chunk["section_char_end"]
    candidates = []
    search_from = 0
    while (found := section_text.find(quote, search_from)) != -1:
        candidates.append((found, found + len(quote)))
        search_from = found + 1
    overlapping = [(s, e) for s, e in candidates if s < orig_end and e > orig_start] or candidates
    if not overlapping:
        raise EvidenceMappingFailure(
            case_id, original_chunk_id, "quote not found in the frozen section text"
        )
    quote_start, quote_end = overlapping[0]

    mapped = sorted(
        {
            c.chunk_id
            for c in experiment_chunks
            if c.metadata["section_id"] == section_id
            and c.metadata["section_char_start"] <= quote_start
            and quote_end <= c.metadata["section_char_end"]
        }
    )
    if not mapped:
        raise EvidenceMappingFailure(
            case_id,
            original_chunk_id,
            f"no experiment chunk under section {section_id} fully contains the quote span "
            f"[{quote_start}, {quote_end})",
        )
    return EvidenceMapping(
        case_id=case_id,
        original_chunk_id=original_chunk_id,
        ncd_id=production_chunk["NCD_id"],
        ncd_version=production_chunk["NCD_vrsn_num"],
        section=production_chunk["section"],
        mapped_chunk_ids=mapped,
        method="section_and_quote_span",
    )


@dataclass(frozen=True)
class RemappedCase:
    case_id: str
    query: str
    category: str
    answerable: bool
    expected_chunk_ids: list[str]


@dataclass(frozen=True)
class RemappedDataset:
    dataset_version: str
    cases: list[RemappedCase]


def remap_dataset(
    dataset,
    documents: list[Document],
    production_corpus_by_id: dict[str, dict],
    experiment_chunks: list[Chunk],
) -> tuple[RemappedDataset, list[EvidenceMapping]]:
    """Negative cases are preserved exactly (expected_chunk_ids stays [],
    answerable stays False) — no remapping needed or attempted for them.
    Positive cases are remapped case-by-case, evidence-entry-by-evidence-
    entry, unioning mapped chunk ids across all of a case's evidence
    entries (handles the one multi-evidence case in the dev set)."""
    section_text_by_id = _section_text_by_id(documents)
    remapped_cases = []
    mappings = []
    for case in dataset.cases:
        if not case.answerable:
            remapped_cases.append(RemappedCase(case.case_id, case.query, case.category, False, []))
            continue
        mapped_ids: set[str] = set()
        for evidence in case.evidence:
            mapping = map_evidence_chunk(
                case_id=case.case_id,
                original_chunk_id=evidence.chunk_id,
                quote=evidence.quote,
                production_corpus_by_id=production_corpus_by_id,
                section_text_by_id=section_text_by_id,
                experiment_chunks=experiment_chunks,
            )
            mappings.append(mapping)
            mapped_ids.update(mapping.mapped_chunk_ids)
        remapped_cases.append(
            RemappedCase(case.case_id, case.query, case.category, True, sorted(mapped_ids))
        )
    return RemappedDataset(dataset.dataset_version, remapped_cases), mappings


# --- isolated index lifecycle ----------------------------------------------


def publish_experiment_index(
    client, alias: str, chunks: list[Chunk], embedding: EmbeddingProvider
) -> dict:
    assert_not_production_alias(alias, client)
    inputs = [f"{c.metadata['title']}\n{c.metadata['section']}\n{c.text}" for c in chunks]
    vectors = embedding.embed(inputs)
    return NCDIndex(client, alias).publish(chunks, vectors, embedding.describe())


def teardown_experiment_index(client, alias: str) -> None:
    """Always safe to call even if publish partially failed: removes the
    alias (if present) and its physical collection (if present). Refuses,
    like publish, to ever touch the production alias."""
    if alias == PRODUCTION_ALIAS:
        raise ProductionAliasGuardError(f"Refusing to tear down the production alias {alias!r}.")
    from qdrant_client import models

    index = NCDIndex(client, alias)
    collection = index.resolve()
    if collection == NCDIndex(client, PRODUCTION_ALIAS).resolve() and collection is not None:
        raise ProductionAliasGuardError(
            f"Refusing to delete collection {collection!r} — it is the production collection."
        )
    if collection is not None:
        client.update_collection_aliases(
            [models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))]
        )
        client.delete_collection(collection)


def verify_cleanup(client, alias: str) -> dict:
    """Checked after every configuration, before the next one starts."""
    production_index = NCDIndex(client, PRODUCTION_ALIAS)
    return {
        "experiment_alias_gone": NCDIndex(client, alias).resolve() is None,
        "production_alias_present": production_index.resolve() is not None,
        "production_point_count": client.get_collection(PRODUCTION_ALIAS).points_count,
    }


class CleanupVerificationError(Exception):
    """Raised when post-teardown verification finds the experiment alias
    still present, or the production alias/point count disturbed. Stops the
    grid before the next configuration runs."""


class MappingFailuresPresentError(Exception):
    """Raised when Phase A (evidence remapping for the whole grid) finds
    any failure anywhere. Nothing is published to Qdrant in this case — the
    grid never begins Phase B."""

    def __init__(self, failures: list[dict]) -> None:
        self.failures = failures
        super().__init__(f"{len(failures)} evidence-mapping failure(s) — grid not run")


# --- grid orchestration ------------------------------------------------


def run_chunking_grid(repeats: int = 3) -> dict:
    """Phase A: build chunks and remap evidence for the whole 6-config x
    2-dataset grid using only local files and the read-only production
    corpus snapshot -- no Qdrant collection is created yet. If any mapping
    fails anywhere in the grid, stop here and report before touching
    Qdrant at all.

    Phase B (only reached if Phase A found zero failures): for each
    configuration, publish an isolated index, evaluate both datasets
    against it, write standard artifacts plus chunk_stats.json/
    evidence_mapping.json, tear the index down, and verify cleanup before
    moving to the next configuration.

    Phase C: write one aggregate comparison artifact across all 12 runs."""
    from datetime import UTC, datetime
    from pathlib import Path
    from time import perf_counter

    from app.generation.providers import DeterministicProvider
    from app.reranking.cross_encoder import MiniLMCrossEncoder
    from app.retrieval.search import Retriever, load_corpus
    from qdrant_client import QdrantClient

    from evaluation.analysis import summarize
    from evaluation.artifacts import write_experiment_artifacts
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
        PRODUCTION_SETTINGS,
        HeldoutDatasetTamperedError,
        build_artifact_files,
        failure_category_counts,
    )
    from evaluation.run_retrieval_eval import evaluate
    from ingestion.embeddings.providers import SentenceTransformerEmbedding

    settings = PRODUCTION_SETTINGS
    dev = load_dataset(Path("docs/evaluation/golden_retrieval_v1.json"))
    heldout = load_dataset(Path("docs/evaluation/golden_retrieval_heldout_v1.json"))
    if digest(heldout.model_dump()) != FROZEN_HELDOUT_SHA256:
        raise HeldoutDatasetTamperedError("Held-out dataset hash does not match the frozen value.")
    datasets = {"development": dev, "held_out": heldout}

    embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
    reranker = MiniLMCrossEncoder(settings.rerank_model_cache, True)
    documents, _ = load_frozen_source()

    client = QdrantClient(settings.qdrant_url, timeout=10)
    production_index = NCDIndex(client, settings.rag_qdrant_alias)
    production_before = client.get_collection(settings.rag_qdrant_alias).points_count
    production_corpus = load_corpus(production_index, production_index.resolve())
    production_corpus_by_id = {c["chunk_id"]: c for c in production_corpus}

    # --- Phase A: build + remap everything before touching Qdrant ---
    per_config: dict[tuple[int, int], dict] = {}
    all_failures: list[dict] = []
    for target, overlap in CHUNKING_GRID:
        chunks = build_experiment_chunks(documents, embedding, target, overlap)
        stats = chunk_corpus_statistics(chunks)
        remapped: dict[str, tuple] = {}
        for name, ds in datasets.items():
            try:
                remapped_dataset, mappings = remap_dataset(
                    ds, documents, production_corpus_by_id, chunks
                )
            except EvidenceMappingFailure as exc:
                all_failures.append(
                    {
                        "target_tokens": target,
                        "overlap_tokens": overlap,
                        "dataset": name,
                        "case_id": exc.case_id,
                        "chunk_id": exc.chunk_id,
                        "reason": exc.reason,
                    }
                )
                continue
            remapped[name] = (remapped_dataset, mappings)
        per_config[(target, overlap)] = {"chunks": chunks, "stats": stats, "remapped": remapped}

    if all_failures:
        raise MappingFailuresPresentError(all_failures)

    # --- Phase B: publish, evaluate, teardown, verify -- one config at a time ---
    git_commit = current_git_commit()
    source_state = git_source_state()
    run_records: list[dict] = []
    for target, overlap in CHUNKING_GRID:
        entry = per_config[(target, overlap)]
        chunks, stats = entry["chunks"], entry["stats"]
        alias = experiment_alias_for(target, overlap)
        assert_not_production_alias(alias, client)

        setup_started = perf_counter()
        publish_experiment_index(client, alias, chunks, embedding)
        setup_ms = (perf_counter() - setup_started) * 1000
        try:
            index = NCDIndex(client, alias)
            search = Retriever(
                index,
                embedding,
                settings.retrieval_candidate_k,
                settings.retrieval_rrf_constant,
                settings.bm25_k1,
                settings.bm25_b,
            )
            for name, (remapped_dataset, mappings) in entry["remapped"].items():
                cases, timings = evaluate(remapped_dataset, search, reranker, settings, repeats)
                summary = summarize(cases, timings)
                config = ExperimentConfig(
                    experiment_type=ExperimentType.CHUNKING,
                    dataset_version=remapped_dataset.dataset_version,
                    dataset_sha256=digest(datasets[name].model_dump()),
                    embedding_model=embedding.describe()["model"],
                    embedding_revision=embedding.describe()["revision"],
                    chunk_size=target,
                    chunk_overlap=overlap,
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
                files = build_artifact_files(
                    remapped_dataset.dataset_version, config, cases, summary, git_commit
                )
                files["chunk_stats.json"] = stats
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
                    for m in mappings
                ]
                files["environment.json"]["setup_ms"] = setup_ms
                artifact_dir = write_experiment_artifacts(ARTIFACT_ROOT, exp_id, files)
                run_records.append(
                    {
                        "target_tokens": target,
                        "overlap_tokens": overlap,
                        "dataset": name,
                        "experiment_id": exp_id,
                        "artifact_dir": str(artifact_dir),
                        "chunk_count": stats["chunk_count"],
                        "setup_ms": setup_ms,
                        "metrics": summary["metrics"],
                        "abstention": summary["abstention"],
                        "failure_category_counts": failure_category_counts(summary["failures"]),
                    }
                )
        finally:
            teardown_experiment_index(client, alias)
            cleanup = verify_cleanup(client, alias)
            if (
                not cleanup["experiment_alias_gone"]
                or not cleanup["production_alias_present"]
                or cleanup["production_point_count"] != production_before
            ):
                raise CleanupVerificationError(
                    f"Cleanup verification failed for {alias!r}: {cleanup}"
                )

    aggregate = {
        "grid": [(t, o) for t, o in CHUNKING_GRID],
        "production_points_before": production_before,
        "production_points_after": client.get_collection(settings.rag_qdrant_alias).points_count,
        "runs": run_records,
    }
    aggregate_id = f"{git_commit[:8]}_chunking_grid"
    aggregate_dir = write_experiment_artifacts(
        ARTIFACT_ROOT, aggregate_id, {"comparison.json": aggregate}
    )
    client.close()
    result = {
        "aggregate_id": aggregate_id,
        "aggregate_dir": str(aggregate_dir),
        "run_count": len(run_records),
    }
    print(json.dumps(result, indent=2))
    return {**result, "runs": run_records}
