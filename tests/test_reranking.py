import sys

import pytest
from app.core.config import Settings
from app.generation.context import build_context
from app.generation.providers import DeterministicProvider
from app.generation.service import RAGService
from app.reranking.cross_encoder import PassageScore, token_windows
from app.reranking.service import rerank
from pydantic import ValidationError


class FakeScorer:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def describe(self):
        return {"model": "test-double"}

    def score(self, query, passages):
        self.calls.append((query, passages))
        return [PassageScore(value, 1, 0, 10) for value in self.values]


def candidates():
    return [
        {
            "chunk_id": key,
            "NCD_id": "test",
            "NCD_vrsn_num": "1",
            "title": "Test policy",
            "section": "Requirements",
            "text": "A prescription is required.",
            "retrieval_method": "hybrid",
            "score": 0.03,
            "fusion_score": 0.03,
            "evidence_gate_score": 0.7,
            "source_url": "https://example.test/policy",
        }
        for key in ("a", "b", "c")
    ]


def test_rerank_preserves_payload_and_changes_only_order():
    hits = candidates()
    provider = FakeScorer([-2, 3, 1])
    result = rerank("prescription", hits, provider, 2)
    assert [h["chunk_id"] for h in result] == ["b", "c"]
    assert result[0]["candidate_rank"] == 2 and result[0]["rerank_rank"] == 1
    for hit in result:
        original = next(h for h in hits if h["chunk_id"] == hit["chunk_id"])
        assert all(hit[k] == v for k, v in original.items())
    assert "rerank_score" not in hits[0]
    assert provider.calls == [
        ("prescription", ["Test policy\nRequirements\nA prescription is required."] * 3)
    ]


def test_ties_empty_duplicate_and_bad_output():
    hits = candidates()
    assert [h["chunk_id"] for h in rerank("x", list(reversed(hits)), FakeScorer([1, 1, 1]))] == [
        "a",
        "b",
        "c",
    ]
    provider = FakeScorer([])
    assert rerank("x", [], provider) == [] and not provider.calls
    with pytest.raises(ValueError, match="Duplicate"):
        rerank("x", [hits[0], hits[0]], provider)
    for scores in ([1], [1, 2, float("nan")]):
        with pytest.raises(ValueError, match="output"):
            rerank("x", hits, FakeScorer(scores))
    with pytest.raises(ValueError):
        rerank("x", hits, FakeScorer([1, 2, 3]), 0)


@pytest.mark.parametrize(
    ("length", "capacity", "overlap"), [(1, 10, 2), (10, 10, 2), (21, 10, 2), (1000, 381, 64)]
)
def test_windows_cover_all_tokens_without_truncated_tail(length, capacity, overlap):
    windows = list(token_windows(length, capacity, overlap))
    assert windows[0][0] == 0 and windows[-1][1] == length
    assert set(range(length)) == {i for start, end in windows for i in range(start, end)}
    assert all(end - start <= capacity for start, end in windows)
    for previous, current in zip(windows, windows[1:], strict=False):
        assert previous[1] - current[0] == overlap


def test_invalid_windows():
    for args in [(0, 10, 2), (10, 2, 2), (10, 10, -1)]:
        with pytest.raises(ValueError):
            list(token_windows(*args))


def test_rag_gate_does_not_use_cross_encoder_logits():
    hits = candidates()
    for hit in hits:
        hit["evidence_gate_score"] = 0.2
    ranked = rerank("prescription", hits, FakeScorer([999, 998, 997]))
    assert not build_context(ranked, 0.6, 24000).chunks
    answer = RAGService(lambda _: ranked, DeterministicProvider(), Settings(_env_file=None)).answer(
        "prescription"
    )
    assert answer.insufficient_evidence
    hits[1]["evidence_gate_score"] = 0.7
    ranked = rerank("prescription", hits, FakeScorer([999, 998, 997]))
    answer = RAGService(lambda _: ranked, DeterministicProvider(), Settings(_env_file=None)).answer(
        "prescription"
    )
    assert answer.citations[0].chunk_id == "b"


def test_config_and_cli_flag(monkeypatch):
    from ingestion import cli

    assert not Settings(_env_file=None).rerank_enabled
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rerank_candidate_k=21)
    calls = []

    def retrieve(query, settings):
        calls.append(
            (settings.rerank_enabled, settings.rerank_candidate_k, settings.retrieval_mode)
        )
        return []

    monkeypatch.setattr("app.generation.runtime.retrieve", retrieve)
    monkeypatch.setattr(
        sys,
        "argv",
        ["cli", "rag", "--mode", "hybrid", "--rerank", "--rerank-candidates", "12", "hospital bed"],
    )
    cli.main()
    assert calls == [(True, 12, "hybrid")]


def test_bad_scorer_failure_is_not_silently_ignored():
    class Broken(FakeScorer):
        def score(self, *args):
            raise RuntimeError("model failure")

    with pytest.raises(RuntimeError):
        rerank("prescription", candidates(), Broken([]))


@pytest.mark.parametrize("failure", ["load", "query"])
def test_runtime_structured_errors(monkeypatch, failure):
    from app.generation.providers import GenerationError
    from app.generation.runtime import retrieve
    from app.reranking.cross_encoder import RerankQueryError

    class Client:
        def __init__(self, **kwargs):
            pass

        def close(self):
            pass

    class Retrieval:
        def __init__(self, *args):
            pass

        def search(self, *args, **kwargs):
            return candidates()

    def fail(*args):
        if failure == "load":
            raise OSError("private cache path")
        raise RerankQueryError("too long")

    monkeypatch.setattr("qdrant_client.QdrantClient", Client)
    monkeypatch.setattr("app.retrieval.search.Retriever", Retrieval)
    monkeypatch.setattr("app.generation.runtime.load_embedding", lambda *args: None)
    monkeypatch.setattr("app.generation.runtime.load_reranker", fail)
    with pytest.raises(GenerationError) as error:
        retrieve("hospital bed", Settings(_env_file=None, rerank_enabled=True))
    assert error.value.code == (
        "reranking_unavailable" if failure == "load" else "rerank_query_too_long"
    )
    assert error.value.status_code == (503 if failure == "load" else 422)


def test_initialization_pins_revision_and_cpu(monkeypatch):
    from types import SimpleNamespace

    from app.reranking.cross_encoder import MODEL_NAME, MODEL_REVISION, MiniLMCrossEncoder

    calls = []

    class Encoder:
        def __init__(self, name, **kwargs):
            calls.append((name, kwargs))
            self.model = SimpleNamespace(eval=lambda: calls.append("eval"))
            self.tokenizer = object()

    monkeypatch.setattr("sentence_transformers.CrossEncoder", Encoder)
    provider = MiniLMCrossEncoder("/test/cache", True)
    name, kwargs = calls[0]
    assert name == MODEL_NAME and kwargs["revision"] == MODEL_REVISION
    assert kwargs["device"] == "cpu" and kwargs["local_files_only"] is True
    assert kwargs["trust_remote_code"] is False
    assert kwargs["model_kwargs"]["use_safetensors"] is True
    assert calls[1] == "eval" and provider.max_length == 512


def test_max_window_aggregation_scores_every_window():
    from types import SimpleNamespace

    import torch
    from app.reranking.cross_encoder import MiniLMCrossEncoder

    seen = []

    class Tokenizer:
        def encode(self, value, **kwargs):
            assert kwargs["truncation"] is False
            return [int(word) for word in value.split()]

        def num_special_tokens_to_add(self, pair):
            return 3

        def prepare_for_model(self, query, pair_ids, **kwargs):
            ids = [101] + query + [102] + pair_ids + [102]
            assert len(ids) <= 10
            seen.append(pair_ids)
            return {"input_ids": ids}

        def pad(self, pairs, **kwargs):
            return {"pairs": pairs}

    class Model:
        offset = 0

        def __call__(self, pairs):
            values = [1.0, 5.0, 3.0][self.offset : self.offset + len(pairs)]
            self.offset += len(pairs)
            return SimpleNamespace(logits=torch.tensor(values).reshape(-1, 1))

    provider = object.__new__(MiniLMCrossEncoder)
    provider.tokenizer = Tokenizer()
    provider.encoder = SimpleNamespace(model=Model())
    provider.max_length, provider.query_limit = 10, 3
    provider.overlap, provider.batch_size = 2, 2
    score = provider.score("9", [" ".join(str(i) for i in range(11))])[0]
    assert score == PassageScore(5.0, 3, 4, 10)
    assert seen == [list(range(0, 6)), list(range(4, 10)), list(range(8, 11))]


def test_placeholder_with_high_rerank_score_still_excluded():
    hits = candidates()[:2]
    hits[0]["text"] = hits[0]["section"] + "\n\nN/A"
    ranked = rerank("prescription", hits, FakeScorer([1000, 1]), 5)
    assert len(ranked) == 2
    context = build_context(ranked, 0.6, 24000)
    assert [h["chunk_id"] for h in context.chunks] == ["b"]


def test_invalid_citation_after_reranking():
    import json

    class Provider:
        name, model = "test", "test"

        def generate(self, query, context):
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "quotes": [{"chunk_id": "invented", "quote": "A prescription is required."}],
                }
            )

    ranked = rerank("prescription", candidates(), FakeScorer([1, 2, 3]))
    answer = RAGService(lambda _: ranked, Provider(), Settings(_env_file=None)).answer(
        "prescription"
    )
    assert answer.abstention_reason == "invalid_citation" and answer.citations == []


def test_reranking_log_contains_only_debug_identifiers(caplog):
    import json
    import logging

    with caplog.at_level(logging.INFO, logger="app.reranking.service"):
        rerank("private question", candidates(), FakeScorer([1, 2, 3]))
    record = json.loads(caplog.records[-1].message)
    assert record["candidate_count"] == 3
    assert record["final_chunk_ids"] == ["c", "b", "a"]
    assert record["latency_ms"] >= 0
    assert (
        "private question" not in caplog.text and "A prescription is required." not in caplog.text
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_candidate_depth_and_disabled_path(monkeypatch, enabled):
    from app.generation.runtime import retrieve

    depths, models = [], []

    class Client:
        def __init__(self, **kwargs):
            pass

        def close(self):
            pass

    class Retrieval:
        def __init__(self, *args):
            pass

        def search(self, query, mode, depth, **kwargs):
            depths.append(depth)
            return candidates()[:2]

    def load(*args):
        models.append(1)
        return FakeScorer([1, 2])

    monkeypatch.setattr("qdrant_client.QdrantClient", Client)
    monkeypatch.setattr("app.retrieval.search.Retriever", Retrieval)
    monkeypatch.setattr("app.generation.runtime.load_embedding", lambda *args: None)
    monkeypatch.setattr("app.generation.runtime.load_reranker", load)
    hits = retrieve(
        "hospital bed",
        Settings(_env_file=None, rerank_enabled=enabled, rag_top_k=1, rerank_candidate_k=10),
    )
    assert depths == [10 if enabled else 1]
    assert bool(models) == enabled
    if enabled:
        assert len(hits) == 1 and hits[0]["chunk_id"] == "b"
    else:
        assert hits == candidates()[:2]
