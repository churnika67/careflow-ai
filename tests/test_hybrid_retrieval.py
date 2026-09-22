import json
import math
import sys
from copy import deepcopy
from uuid import UUID

import numpy as np
import pytest
from app.core.config import Settings
from app.generation.context import build_context
from app.generation.providers import DeterministicProvider
from app.generation.service import RAGService
from app.retrieval.fusion import dense_results, reciprocal_rank_fusion
from app.retrieval.lexical import BM25Index, tokenize
from app.retrieval.search import Retriever, load_corpus
from pydantic import ValidationError
from qdrant_client import QdrantClient

from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import Chunk


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("CPAP OSA AHI RDI", ["cpap", "osa", "ahi", "rdi"]),
        ("C-peptide 12-week non-covered", ["c", "peptide", "12", "week", "non", "covered"]),
        ("physician's patient’s patients'", ["physician", "patient", "patients"]),
        ("≤ 225 mg/dL 280.16 5%", ["225", "mg", "dl", "280.16", "5"]),
        ("U.S. CPT E1234", ["u.s", "cpt", "e1234"]),
        ("NOT necessary\t\n  ＣＰＡＰ", ["not", "necessary", "cpap"]),
        ("What is not covered?", ["what", "is", "not", "covered"]),
        ("", []),
    ],
)
def test_tokenizer(text, expected):
    assert tokenize(text) == expected


def row(number, text="oxygen prescription", **extra):
    return {
        "chunk_id": str(UUID(int=number)),
        "NCD_id": str(number),
        "NCD_vrsn_num": "1",
        "title": "",
        "section": "",
        "text": text,
        "source_field": "indctn_lmtn",
        "document_version_id": f"test:{number}:v1",
        "coverage_code": "2",
        "source_url": "https://example.test/source",
        "snapshot_sha256": "test-snapshot",
        "source_record_sha256": "test-record",
        **extra,
    }


def test_bm25_formula_mapping_and_no_keywords():
    rows = [row(2, "sleep", search_keywords="oxygen"), row(1, "oxygen oxygen")]
    index = BM25Index(rows)
    assert index.chunk_ids == (str(UUID(int=1)), str(UUID(int=2)))
    hits = index.search("oxygen")
    assert len(hits) == 1
    assert hits[0]["score"] == pytest.approx(math.log(2) * 2 * 2.2 / (2 + 1.5))
    assert hits[0]["chunk_id"] == str(UUID(int=1))
    assert hits[0]["retrieval_sources"] == ["bm25"]
    assert hits[0]["source_record_sha256"] == "test-record"
    assert hits == BM25Index(list(reversed(rows))).search("oxygen oxygen")
    hits[0]["text"] = "modified result"
    rows[1]["text"] = "modified input"
    assert index.search("oxygen")[0]["text"] == "oxygen oxygen"


@pytest.mark.parametrize("query", ["", " \n\t", "!!!", "unseenword987"])
def test_empty_and_unknown_queries(query):
    assert BM25Index([row(1)]).search(query) == []
    assert BM25Index([]).search(query) == []


def test_filters_use_global_corpus_statistics():
    index = BM25Index([row(1), row(2, "oxygen"), row(3, "sleep")])
    all_hits = index.search("oxygen")
    filtered = index.search("oxygen", filters={"NCD_id": "1", "NCD_vrsn_num": "1"})
    assert filtered[0]["score"] == next(h["score"] for h in all_hits if h["NCD_id"] == "1")
    assert index.search("oxygen", filters={"NCD_id": "absent"}) == []
    for filters in ({"fake": "x"}, {"NCD_id": 1}, {"NCD_id": ""}):
        with pytest.raises(ValueError, match="filter"):
            index.search("oxygen", filters=filters)


def test_invalid_index_and_search_inputs():
    with pytest.raises(ValueError, match="Duplicate"):
        BM25Index([row(1), row(1)])
    with pytest.raises(ValueError, match="Empty"):
        BM25Index([row(1, " ")])
    for kwargs in ({"k1": 0}, {"b": 2}, {"b": float("nan")}):
        with pytest.raises(ValueError):
            BM25Index([], **kwargs)
    for kwargs in ({"top_k": 0}, {"top_k": 21}):
        with pytest.raises(ValueError):
            BM25Index([]).search("oxygen", **kwargs)
    with pytest.raises(ValueError):
        BM25Index([]).search("x" * 4001)


def test_rrf_formula_deduplication_provenance_and_ties():
    a, b = row(1) | {"score": 0.9}, row(2) | {"score": 0.8}
    lexical = [b | {"score": 1000}, a | {"score": 1}]
    hits = reciprocal_rank_fusion(dense_results([a, b]), lexical)
    assert len(hits) == 2
    assert hits[0]["chunk_id"] == a["chunk_id"]  # Exact score tie breaks by stable ID.
    assert hits[0]["score"] == pytest.approx(1 / 61 + 1 / 62)
    assert hits[0]["dense_score"] == 0.9 and hits[0]["bm25_score"] == 1
    assert hits[0]["dense_rank"] == 1 and hits[0]["bm25_rank"] == 2
    assert hits[0]["retrieval_sources"] == ["dense", "bm25"]
    assert hits[0]["source_record_sha256"] == "test-record"
    assert reciprocal_rank_fusion([a, a], [a])[0]["score"] == pytest.approx(2 / 61)
    assert reciprocal_rank_fusion([], [a], constant=10)[0]["score"] == pytest.approx(1 / 11)
    assert reciprocal_rank_fusion([], []) == []
    assert hits == reciprocal_rank_fusion(dense_results([a, b]), lexical)


def test_rrf_rejects_conflicting_sources_and_nonfinite_scores():
    a = row(1) | {"score": 0.8}
    with pytest.raises(ValueError, match="Conflicting"):
        reciprocal_rank_fusion([a], [a | {"text": "different evidence"}])
    with pytest.raises(ValueError, match="Non-finite"):
        reciprocal_rank_fusion([a | {"score": float("inf")}], [])
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([], [], constant=0)


class TestEmbedding:
    def describe(self):
        return {"dimension": 2, "provider": "test-vectors"}

    def embed(self, texts):
        return np.array([[1.0, 0.0] for _ in texts])


@pytest.fixture
def published():
    client = QdrantClient(":memory:")
    index = NCDIndex(client)
    rows = [row(1, "oxygen prescription"), row(2, "oxygen equipment"), row(3, "sleep therapy")]
    chunks = [
        Chunk(
            r["chunk_id"], r["text"], {k: v for k, v in r.items() if k not in {"chunk_id", "text"}}
        )
        for r in rows
    ]
    index.publish(
        chunks, np.array([[1.0, 0.0], [0.0, 1.0], [0.8, 0.6]]), TestEmbedding().describe()
    )
    yield index
    client.close()


def test_published_corpus_matches_exact_point_ids(published):
    corpus = load_corpus(published, published.resolve())
    assert len(corpus) == 3
    assert BM25Index(corpus).chunk_ids == tuple(str(UUID(int=i)) for i in (1, 2, 3))
    assert all(row["collection"] == published.resolve() for row in corpus)


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_modes_and_rag_gate(published, mode):
    retriever = Retriever(published, TestEmbedding())
    raw = retriever.search("oxygen prescription", mode, top_k=2)
    assert raw and all(h["retrieval_method"] == mode for h in raw)
    assert len({h["chunk_id"] for h in raw}) == len(raw)
    hits = retriever.search("oxygen prescription", mode, top_k=2, for_rag=True)
    settings = Settings(_env_file=None)
    answer = RAGService(lambda _: hits, DeterministicProvider(), settings).answer(
        "oxygen prescription"
    )
    assert not answer.insufficient_evidence
    assert answer.citations[0].chunk_id == str(UUID(int=1))
    assert answer.citations[0].document_id == "1"
    assert answer.citations[0].source == "https://example.test/source"
    if mode != "dense":
        assert not build_context(raw, 0.6, 24000).chunks  # Never gate on BM25 or RRF values.
        assert hits[0]["evidence_gate_score"] is not None
    assert retriever.search("   ", mode) == []


def test_bm25_search_does_not_need_an_embedding_model(published):
    assert Retriever(published).search("oxygen", "bm25")
    with pytest.raises(ValueError, match="requires embeddings"):
        Retriever(published).search("oxygen", "bm25", for_rag=True)


def test_pin_collection_once(published, monkeypatch):
    collection = published.resolve()
    calls = []

    def resolve_once():
        calls.append(1)
        assert len(calls) == 1
        return collection

    monkeypatch.setattr(published, "resolve", resolve_once)
    assert Retriever(published, TestEmbedding()).search("oxygen", "hybrid", for_rag=True)


def test_no_published_corpus():
    with pytest.raises(ValueError, match="No published"):
        Retriever(NCDIndex(QdrantClient(":memory:"))).search("oxygen", "bm25")


def test_configuration_and_invalid_modes(published):
    assert Settings(_env_file=None).retrieval_mode == "dense"
    assert Settings(_env_file=None).retrieval_rrf_constant == 60
    for mode in ("dense", "bm25", "hybrid"):
        assert Settings(_env_file=None, retrieval_mode=mode).retrieval_mode == mode
    with pytest.raises(ValidationError):
        Settings(_env_file=None, retrieval_mode="reranker")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, retrieval_rrf_constant=0)
    with pytest.raises(ValueError, match="mode"):
        Retriever(published).search("oxygen", "invalid")


@pytest.mark.parametrize("mode", ["dense", "bm25", "hybrid"])
def test_search_cli_modes(published, monkeypatch, capsys, mode):
    from ingestion import cli

    calls = []

    class CLIEmbedding(TestEmbedding):
        def __init__(self, *args):
            calls.append(1)

    monkeypatch.setattr(cli, "QdrantClient", lambda **_: published.client)
    monkeypatch.setattr(cli, "SentenceTransformerEmbedding", CLIEmbedding)
    monkeypatch.setattr(sys, "argv", ["cli", "search", "--mode", mode, "oxygen"])
    cli.main()
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["retrieval_method"] == mode
    assert bool(calls) == (mode != "bm25")


def test_cli_rejects_invalid_mode(monkeypatch):
    from ingestion import cli

    monkeypatch.setattr(sys, "argv", ["cli", "search", "--mode", "invalid", "oxygen"])
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


@pytest.mark.parametrize("method", ["bm25", "hybrid"])
def test_large_raw_scores_do_not_bypass_abstention(method):
    hit = row(1) | {"retrieval_method": method, "score": 999, "evidence_gate_score": 0.3}
    answer = RAGService(lambda _: [hit], DeterministicProvider(), Settings(_env_file=None)).answer(
        "unknown policy"
    )
    assert answer.answer == "Insufficient evidence."
    assert answer.citations == []
    hit["evidence_gate_score"] = None
    assert not build_context([hit], -1, 24000).chunks


def test_corrupt_payload_is_rejected(published):
    collection = published.resolve()
    payload = deepcopy(load_corpus(published, collection)[0])
    payload["chunk_id"] = "wrong-id"
    published.client.set_payload(collection, payload, points=[str(UUID(int=1))])
    with pytest.raises(ValueError, match="point and chunk ID"):
        load_corpus(published, collection)


@pytest.mark.parametrize("mode", ["bm25", "hybrid"])
def test_rag_cli_mode_wiring(monkeypatch, capsys, mode):
    from ingestion import cli

    calls = []

    def retrieve_question(question, settings):
        calls.append(settings.retrieval_mode)
        return [row(1) | {"retrieval_method": mode, "score": 10, "evidence_gate_score": 0.9}]

    monkeypatch.setattr("app.generation.runtime.retrieve", retrieve_question)
    monkeypatch.setattr(sys, "argv", ["cli", "rag", "--mode", mode, "oxygen prescription"])
    cli.main()
    assert calls == [mode]
    assert json.loads(capsys.readouterr().out)["citations"][0]["document_id"] == "1"


@pytest.mark.parametrize("mode", ["bm25", "hybrid"])
def test_query_api_with_retrieval_mode(published, monkeypatch, mode):
    from app.main import app
    from fastapi.testclient import TestClient

    retriever = Retriever(published, TestEmbedding())
    settings = Settings(_env_file=None, retrieval_mode=mode)
    service = RAGService(
        lambda q: retriever.search(q, mode, for_rag=True), DeterministicProvider(), settings
    )
    monkeypatch.setattr("app.api.query.get_rag_service", lambda: service)
    with TestClient(app) as client:
        response = client.post("/query", json={"question": "oxygen prescription"})
    assert response.status_code == 200
    assert response.json()["citations"][0]["document_id"] == "1"
