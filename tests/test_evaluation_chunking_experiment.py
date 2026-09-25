import json
import os

import pytest

from evaluation.chunking_experiment import (
    CHUNKING_GRID,
    EvidenceMappingFailure,
    ProductionAliasGuardError,
    experiment_alias_for,
    map_evidence_chunk,
    remap_dataset,
)
from ingestion.chunking.sections import ChunkingConfig
from ingestion.models import Chunk

pytestmark_live = pytest.mark.skipif(
    os.environ.get("CAREFLOW_INGESTION_INTEGRATION") != "1",
    reason="Set CAREFLOW_INGESTION_INTEGRATION=1 with Compose running and the frozen CMS "
    "source snapshot present to exercise real chunking/indexing",
)


# --- grid / naming ----------------------------------------------------


def test_grid_has_exactly_the_six_approved_configurations():
    assert CHUNKING_GRID == [(400, 0), (400, 120), (700, 0), (700, 120), (1200, 0), (1200, 120)]


def test_every_grid_point_is_a_valid_chunking_config():
    # Reuses ChunkingConfig's own validation -- not reimplemented here.
    for target, overlap in CHUNKING_GRID:
        ChunkingConfig(target_tokens=target, overlap_tokens=overlap)


def test_experiment_alias_naming_is_deterministic_and_distinct():
    aliases = {experiment_alias_for(t, o) for t, o in CHUNKING_GRID}
    assert len(aliases) == len(CHUNKING_GRID)
    assert experiment_alias_for(700, 120) == experiment_alias_for(700, 120)


def test_experiment_alias_matches_ncdindex_naming_rules():
    import re

    pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,60}$")
    for target, overlap in CHUNKING_GRID:
        assert pattern.fullmatch(experiment_alias_for(target, overlap))


def test_no_experiment_alias_equals_the_production_alias():
    from ingestion.indexing.qdrant import ALIAS as PRODUCTION_ALIAS

    for target, overlap in CHUNKING_GRID:
        assert experiment_alias_for(target, overlap) != PRODUCTION_ALIAS


# --- production alias guard (no live Qdrant needed for the literal-equality case) --


def test_guard_rejects_the_literal_production_alias():
    from evaluation.chunking_experiment import assert_not_production_alias

    with pytest.raises(ProductionAliasGuardError):
        assert_not_production_alias("careflow_cms_ncd", client=None)


# --- deterministic evidence remapping (pure, synthetic section/chunks) ---


def _chunk(chunk_id, section_id, char_start, char_end, text="x"):
    return Chunk(
        chunk_id,
        text,
        {
            "section_id": section_id,
            "section_char_start": char_start,
            "section_char_end": char_end,
        },
    )


def test_map_evidence_chunk_exact_single_match():
    production_corpus_by_id = {
        "orig-1": {
            "section_id": "sec-1",
            "section_char_start": 0,
            "section_char_end": 20,
            "NCD_id": "1",
            "NCD_vrsn_num": "1",
            "section": "A. General",
        }
    }
    section_text_by_id = {"sec-1": "the quick brown fox jumps"}
    experiment_chunks = [
        _chunk("new-1", "sec-1", 0, 15),
        _chunk("new-2", "sec-1", 15, 25),
    ]
    mapping = map_evidence_chunk(
        case_id="c1",
        original_chunk_id="orig-1",
        quote="quick brown",
        production_corpus_by_id=production_corpus_by_id,
        section_text_by_id=section_text_by_id,
        experiment_chunks=experiment_chunks,
    )
    assert mapping.mapped_chunk_ids == ["new-1"]
    assert mapping.method == "section_and_quote_span"
    assert mapping.ncd_id == "1"


def test_map_evidence_chunk_spans_two_overlapping_chunks():
    production_corpus_by_id = {
        "orig-1": {
            "section_id": "sec-1",
            "section_char_start": 0,
            "section_char_end": 25,
            "NCD_id": "1",
            "NCD_vrsn_num": "1",
            "section": "A. General",
        }
    }
    section_text_by_id = {"sec-1": "the quick brown fox jumps over"}
    # Two overlapping experiment chunks both fully contain "brown fox".
    experiment_chunks = [
        _chunk("new-1", "sec-1", 0, 20),
        _chunk("new-2", "sec-1", 10, 30),
    ]
    mapping = map_evidence_chunk(
        case_id="c1",
        original_chunk_id="orig-1",
        quote="brown fox",
        production_corpus_by_id=production_corpus_by_id,
        section_text_by_id=section_text_by_id,
        experiment_chunks=experiment_chunks,
    )
    assert mapping.mapped_chunk_ids == ["new-1", "new-2"]


def test_map_evidence_chunk_unknown_original_id_fails():
    with pytest.raises(EvidenceMappingFailure):
        map_evidence_chunk(
            case_id="c1",
            original_chunk_id="does-not-exist",
            quote="anything",
            production_corpus_by_id={},
            section_text_by_id={},
            experiment_chunks=[],
        )


def test_map_evidence_chunk_quote_not_in_section_fails():
    production_corpus_by_id = {
        "orig-1": {
            "section_id": "sec-1",
            "section_char_start": 0,
            "section_char_end": 10,
            "NCD_id": "1",
            "NCD_vrsn_num": "1",
            "section": "A. General",
        }
    }
    with pytest.raises(EvidenceMappingFailure):
        map_evidence_chunk(
            case_id="c1",
            original_chunk_id="orig-1",
            quote="not present anywhere",
            production_corpus_by_id=production_corpus_by_id,
            section_text_by_id={"sec-1": "totally unrelated text"},
            experiment_chunks=[_chunk("new-1", "sec-1", 0, 20)],
        )


def test_map_evidence_chunk_no_experiment_chunk_covers_the_span_fails():
    production_corpus_by_id = {
        "orig-1": {
            "section_id": "sec-1",
            "section_char_start": 0,
            "section_char_end": 25,
            "NCD_id": "1",
            "NCD_vrsn_num": "1",
            "section": "A. General",
        }
    }
    section_text_by_id = {"sec-1": "the quick brown fox jumps"}
    # No experiment chunk's range fully contains the quote span.
    experiment_chunks = [_chunk("new-1", "sec-1", 0, 6)]
    with pytest.raises(EvidenceMappingFailure):
        map_evidence_chunk(
            case_id="c1",
            original_chunk_id="orig-1",
            quote="quick brown",
            production_corpus_by_id=production_corpus_by_id,
            section_text_by_id=section_text_by_id,
            experiment_chunks=experiment_chunks,
        )


def test_map_evidence_chunk_repeated_quote_disambiguated_by_original_span():
    production_corpus_by_id = {
        "orig-1": {
            "section_id": "sec-1",
            "section_char_start": 20,
            "section_char_end": 30,
            "NCD_id": "1",
            "NCD_vrsn_num": "1",
            "section": "A. General",
        }
    }
    # "the fox" appears twice; the original chunk's span [20,30) overlaps
    # only the second occurrence.
    section_text_by_id = {"sec-1": "the fox ran. later, the fox slept again."}
    second_occurrence_start = section_text_by_id["sec-1"].rfind("the fox")
    experiment_chunks = [
        _chunk("new-early", "sec-1", 0, 12),
        _chunk(
            "new-late",
            "sec-1",
            second_occurrence_start,
            second_occurrence_start + len("the fox") + 5,
        ),
    ]
    mapping = map_evidence_chunk(
        case_id="c1",
        original_chunk_id="orig-1",
        quote="the fox",
        production_corpus_by_id=production_corpus_by_id,
        section_text_by_id=section_text_by_id,
        experiment_chunks=experiment_chunks,
    )
    assert mapping.mapped_chunk_ids == ["new-late"]


# --- negative-case handling in remap_dataset (pure, using the real frozen dev dataset) ---


def test_remap_dataset_preserves_negative_cases_unchanged():
    from pathlib import Path

    from evaluation.dataset import load_dataset

    dataset = load_dataset(Path("docs/evaluation/golden_retrieval_v1.json"))
    negatives = [c for c in dataset.cases if not c.answerable]
    assert negatives  # sanity: the dev set does have negatives

    # No production corpus / experiment chunks needed for negatives -- they
    # never reach map_evidence_chunk at all.
    remapped, mappings = remap_dataset(
        _dataset_with_only(dataset, negatives),
        documents=[],
        production_corpus_by_id={},
        experiment_chunks=[],
    )
    assert mappings == []
    assert len(remapped.cases) == len(negatives)
    for case in remapped.cases:
        assert case.answerable is False
        assert case.expected_chunk_ids == []


def _dataset_with_only(dataset, cases):
    from types import SimpleNamespace

    return SimpleNamespace(dataset_version=dataset.dataset_version, cases=cases)


# --- live: production source, guard, isolated index lifecycle -------------


@pytestmark_live
def test_frozen_source_reproduces_the_recorded_snapshot_fingerprint():
    from evaluation.chunking_experiment import load_frozen_source

    documents, _ = load_frozen_source()
    assert len(documents) == 8
    assert sum(len(d.sections) for d in documents) == 32
    assert (
        documents[0].metadata["snapshot_sha256"]
        == "735619558de8759427d5fe71989d06b48e5625376594fe94efa7a60f7e152ca3"
    )


@pytestmark_live
def test_isolated_700_120_reproduces_production_chunk_ids_and_text_exactly():
    # The strongest form of the required baseline-equivalence check: not
    # just a chunk count match, but exact chunk_id and exact text equality
    # against the live production corpus.
    from app.core.config import get_settings
    from app.retrieval.search import load_corpus
    from qdrant_client import QdrantClient

    from evaluation.chunking_experiment import build_experiment_chunks, load_frozen_source
    from ingestion.embeddings.providers import SentenceTransformerEmbedding
    from ingestion.indexing.qdrant import NCDIndex

    settings = get_settings()
    embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
    documents, _ = load_frozen_source()
    chunks = build_experiment_chunks(documents, embedding, 700, 120)

    client = QdrantClient(settings.qdrant_url, timeout=10)
    index = NCDIndex(client, settings.rag_qdrant_alias)
    production_corpus = load_corpus(index, index.resolve())

    local_by_id = {c.chunk_id: c for c in chunks}
    production_ids = {c["chunk_id"] for c in production_corpus}
    assert {c.chunk_id for c in chunks} == production_ids
    for row in production_corpus:
        assert local_by_id[row["chunk_id"]].text == row["text"]


@pytestmark_live
def test_guard_rejects_an_alias_resolving_to_the_production_collection(monkeypatch):
    # A second alias name that happens to resolve to the SAME physical
    # collection as production must also be refused, not just the literal
    # production alias string -- simulated by making every NCDIndex(...)
    # resolve to the production collection, regardless of which alias name
    # it was constructed with.
    from app.core.config import get_settings
    from qdrant_client import QdrantClient

    import evaluation.chunking_experiment as mod

    settings = get_settings()
    client = QdrantClient(settings.qdrant_url, timeout=10)
    real_index = mod.NCDIndex(client, settings.rag_qdrant_alias)
    production_collection = real_index.resolve()

    monkeypatch.setattr(
        mod,
        "NCDIndex",
        lambda client, alias: type(
            "AlwaysProduction", (), {"resolve": lambda self: production_collection}
        )(),
    )
    with pytest.raises(ProductionAliasGuardError):
        mod.assert_not_production_alias("careflow_exp_chunk_700_120", client)


@pytestmark_live
def test_publish_evaluate_teardown_lifecycle_leaves_production_untouched():
    from app.core.config import get_settings
    from qdrant_client import QdrantClient

    from evaluation.chunking_experiment import (
        build_experiment_chunks,
        experiment_alias_for,
        load_frozen_source,
        publish_experiment_index,
        teardown_experiment_index,
        verify_cleanup,
    )
    from ingestion.embeddings.providers import SentenceTransformerEmbedding
    from ingestion.indexing.qdrant import NCDIndex

    settings = get_settings()
    client = QdrantClient(settings.qdrant_url, timeout=10)
    production_before = client.get_collection(settings.rag_qdrant_alias).points_count

    embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
    documents, _ = load_frozen_source()
    chunks = build_experiment_chunks(documents, embedding, 1200, 0)
    alias = experiment_alias_for(1200, 0)

    result = None
    try:
        result = publish_experiment_index(client, alias, chunks, embedding)
        assert result["points"] == len(chunks)
        index = NCDIndex(client, alias)
        assert index.resolve() is not None
        assert client.get_collection(index.resolve()).points_count == len(chunks)
    finally:
        teardown_experiment_index(client, alias)
        cleanup = verify_cleanup(client, alias)
        assert cleanup["experiment_alias_gone"] is True
        assert cleanup["production_alias_present"] is True
        assert cleanup["production_point_count"] == production_before

    assert result is not None  # the publish itself succeeded before teardown
    assert client.get_collection(settings.rag_qdrant_alias).points_count == production_before


@pytestmark_live
def test_teardown_refuses_to_touch_the_production_alias():
    from app.core.config import get_settings
    from qdrant_client import QdrantClient

    from evaluation.chunking_experiment import teardown_experiment_index

    settings = get_settings()
    client = QdrantClient(settings.qdrant_url, timeout=10)
    with pytest.raises(ProductionAliasGuardError):
        teardown_experiment_index(client, settings.rag_qdrant_alias)


# --- aggregate comparison artifact schema (pure, structural contract) ------


def test_aggregate_comparison_schema_matches_run_chunking_grid_shape(tmp_path):
    from evaluation.artifacts import write_experiment_artifacts

    # A minimal synthetic aggregate, same shape run_chunking_grid() builds --
    # a structural contract test, independent of any specific real run.
    aggregate = {
        "grid": CHUNKING_GRID,
        "production_points_before": 39,
        "production_points_after": 39,
        "runs": [
            {
                "target_tokens": 700,
                "overlap_tokens": 120,
                "dataset": "development",
                "experiment_id": "abc12345_deadbeef0000",
                "artifact_dir": "artifacts/evaluation/abc12345_deadbeef0000",
                "chunk_count": 39,
                "setup_ms": 1234.5,
                "metrics": {"hybrid_reranked": {"overall": {"count": 25, "Hit@1": 0.96}}},
                "abstention": {"hybrid_reranked": {"negative_cases": 7}},
                "failure_category_counts": {"below_evidence_threshold": 4},
            }
        ],
    }
    artifact_dir = write_experiment_artifacts(tmp_path, "test_grid", {"comparison.json": aggregate})
    loaded = json.loads((artifact_dir / "comparison.json").read_text())
    assert loaded["production_points_before"] == 39
    assert loaded["production_points_after"] == 39
    assert len(loaded["grid"]) == 6
    run = loaded["runs"][0]
    for field in (
        "target_tokens",
        "overlap_tokens",
        "dataset",
        "experiment_id",
        "artifact_dir",
        "chunk_count",
        "setup_ms",
        "metrics",
        "abstention",
        "failure_category_counts",
    ):
        assert field in run
