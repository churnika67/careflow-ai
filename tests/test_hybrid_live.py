import json
import os
from contextlib import closing
from pathlib import Path

import pytest
from app.core.config import Settings
from app.generation.providers import DeterministicProvider
from app.generation.runtime import retrieve
from app.generation.service import RAGService
from app.retrieval.lexical import BM25Index
from app.retrieval.search import Retriever, load_corpus
from qdrant_client import QdrantClient

from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_HYBRID_INTEGRATION") != "1",
    reason="Requires the reviewed CMS index and cached MiniLM model",
)


@pytest.fixture(scope="module")
def live():
    settings = Settings()
    with closing(QdrantClient(settings.qdrant_url, timeout=30)) as client:
        index = NCDIndex(client, settings.rag_qdrant_alias)
        yield index, Retriever(index, SentenceTransformerEmbedding(local_only=True))


def test_same_reviewed_corpus_and_reproducible_mapping(live):
    index, _ = live
    corpus = load_corpus(index, index.resolve())
    assert len(corpus) == 39
    assert len({r["document_version_id"] for r in corpus}) == 8
    assert len({r["section_id"] for r in corpus}) == 32
    recorded = json.loads(Path("docs/phase5_retrieval_comparison.json").read_text())
    assert list(BM25Index(corpus).chunk_ids) == recorded["corpus"]["chunk_ids"]
    assert BM25Index(corpus).chunk_ids == BM25Index(list(reversed(corpus))).chunk_ids


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_eight_queries_and_provenance(live, mode):
    index, retriever = live
    corpus = {row["chunk_id"]: row for row in load_corpus(index, index.resolve())}
    cases = json.loads(Path("docs/phase3_search_cases.json").read_text())
    for case in cases:
        hits = retriever.search(case["query"], mode)
        assert any(
            hit["NCD_id"] == case["expected_document_id"]
            and hit["NCD_vrsn_num"] == case["expected_version"]
            and hit["source_field"] == "indctn_lmtn"
            and hit["section"] == case["expected_section"]
            and case["expected_evidence_phrase"] in hit["text"]
            for hit in hits
        )
        for hit in hits:
            expected = corpus[hit["chunk_id"]]
            for key, value in expected.items():
                assert hit[key] == value
        gated = retriever.search(case["query"], mode, for_rag=True)
        assert [h["chunk_id"] for h in gated] == [h["chunk_id"] for h in hits]
        answer = RAGService(lambda _, rows=gated: rows, DeterministicProvider(), Settings()).answer(
            case["query"]
        )
        assert answer.citations and not answer.insufficient_evidence
        assert all(c.chunk_id in corpus for c in answer.citations)


@pytest.mark.parametrize("mode", ["bm25", "hybrid"])
def test_seat_elevation_top_one_rag(mode):
    settings = Settings(retrieval_mode=mode, rag_top_k=1)
    question = (
        "What specialty evaluation is required for power wheelchair seat elevation equipment?"
    )
    answer = RAGService(lambda q: retrieve(q, settings), DeterministicProvider(), settings).answer(
        question
    )
    assert not answer.insufficient_evidence
    assert answer.citations[0].chunk_id == "d760711e-bf95-5e64-9d58-31510aba392e"
    assert "specialty evaluation" in answer.answer


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_negative_queries_keep_abstention(live, mode):
    _, retriever = live
    cases = json.loads(Path("docs/phase4_rag_results.json").read_text())["cases"][8:]
    for case in cases:
        question = case["question"]
        hits = retriever.search(question, mode, for_rag=True)
        answer = RAGService(lambda _, rows=hits: rows, DeterministicProvider(), Settings()).answer(
            question
        )
        assert answer.answer == "Insufficient evidence."
        assert answer.citations == []
