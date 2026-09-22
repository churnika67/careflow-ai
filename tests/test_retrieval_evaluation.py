import os
from contextlib import closing
from copy import deepcopy
from pathlib import Path

import pytest
from app.core.config import Settings
from pydantic import ValidationError

from evaluation.analysis import MODES, eligibility, summarize
from evaluation.dataset import GoldenCase, GoldenDataset, load_dataset, validate_corpus
from evaluation.metrics import Latency, first_rank, latency_summary, rank_change, retrieval_metrics
from evaluation.run_retrieval_eval import repeated
from ingestion.models import digest


@pytest.fixture
def labelled():
    hit = {
        "chunk_id": "a",
        "NCD_id": "1",
        "NCD_vrsn_num": "2",
        "section": "Requirements",
        "text": "A prescription is required.",
        "source_record_sha256": "a" * 64,
        "snapshot_sha256": "b" * 64,
        "viewer_url": "https://www.cms.gov/example",
    }
    ref = {
        "chunk_id": "a",
        "ncd_id": "1",
        "ncd_version": "2",
        "section": "Requirements",
        "quote": hit["text"],
        "source_url": hit["viewer_url"],
        "source_record_sha256": "a" * 64,
        "text_sha256": digest(hit["text"]),
    }
    case = {
        "case_id": "cms-v1-001",
        "query": "What prescription is required?",
        "category": "mixed",
        "expected_chunk_ids": ["a"],
        "evidence": [ref],
        "answerable": True,
        "notes": "Synthetic test evidence only.",
    }
    dataset = {
        "schema_version": "1.0",
        "dataset_version": "cms-retrieval-v1",
        "corpus_sha256": digest([hit]),
        "snapshot_sha256": "b" * 64,
        "label_method": "Synthetic fixture for contract tests.",
        "cases": [case],
    }
    return dataset, hit


def test_committed_dataset_schema_and_split():
    dataset = load_dataset(Path("docs/evaluation/golden_retrieval_v1.json"))
    assert len(dataset.cases) == 32
    assert sum(c.answerable for c in dataset.cases) == 25
    assert len({c.category for c in dataset.cases}) == 7
    assert any(len(c.expected_chunk_ids) > 1 for c in dataset.cases)


def test_positive_provenance(labelled):
    dataset, hit = labelled
    validate_corpus(GoldenDataset.model_validate(dataset), [hit])


@pytest.mark.parametrize(
    "field,value",
    [
        ("NCD_id", "99"),
        ("NCD_vrsn_num", "99"),
        ("section", "Wrong"),
        ("text", "Other evidence"),
        ("viewer_url", "https://example.test"),
        ("source_record_sha256", "c" * 64),
    ],
)
def test_changed_evidence_rejected(labelled, field, value):
    dataset, hit = labelled
    hit[field] = value
    with pytest.raises(ValueError):
        validate_corpus(GoldenDataset.model_validate(dataset), [hit])


def test_missing_and_drifted_corpus_rejected(labelled):
    dataset, hit = labelled
    d = GoldenDataset.model_validate(dataset)
    with pytest.raises(ValueError, match="missing chunk"):
        validate_corpus(d, [])
    with pytest.raises(ValueError, match="fingerprint"):
        validate_corpus(d, [hit | {"new_metadata": "drift"}])


@pytest.mark.parametrize(
    "change",
    [
        {"query": " "},
        {"category": "invented"},
        {"expected_chunk_ids": []},
        {"evidence": []},
        {"answerable": False},
        {"answerable": "true"},
        {"unknown": 1},
    ],
)
def test_malformed_cases_rejected(labelled, change):
    case = labelled[0]["cases"][0] | change
    with pytest.raises(ValidationError):
        GoldenCase.model_validate(case)


def test_duplicate_ids_queries_and_negative_contract(labelled):
    data, _ = labelled
    data["cases"] *= 2
    with pytest.raises(ValidationError, match="Duplicate"):
        GoldenDataset.model_validate(data)
    data["cases"][1] = deepcopy(data["cases"][0]) | {"case_id": "cms-v1-002"}
    with pytest.raises(ValidationError, match="Duplicate"):
        GoldenDataset.model_validate(data)
    case = data["cases"][0] | {
        "category": "ambiguous",
        "answerable": False,
        "evidence": [],
        "expected_chunk_ids": [],
    }
    assert not GoldenCase.model_validate(case).answerable
    with pytest.raises(ValidationError):
        GoldenCase.model_validate(case | {"evidence": data["cases"][0]["evidence"]})


def test_multiple_acceptable_chunks_and_metrics():
    assert first_rank([{"chunk_id": x} for x in ["x", "b", "a"]], ["a", "b"]) == 2
    assert first_rank([{"chunk_id": "x"}], ["a"]) is None
    result = retrieval_metrics([1, 3, 5, None])
    assert result["Hit@1"] == 0.25 and result["Hit@3"] == 0.5 and result["Hit@5"] == 0.75
    assert result["MRR@5"] == pytest.approx((1 + 1 / 3 + 1 / 5) / 4)
    assert retrieval_metrics([])["MRR@5"] is None


@pytest.mark.parametrize(
    "before,after,label,delta",
    [
        (3, 1, "improved", 2),
        (1, 4, "degraded", -3),
        (2, 2, "unchanged", 0),
        (None, 1, "improved", None),
        (2, None, "degraded", None),
        (None, None, "unchanged", None),
    ],
)
def test_rank_change_censoring(before, after, label, delta):
    assert rank_change(before, after) == {"classification": label, "observed_rank_delta": delta}


def test_eligibility_separates_gate_placeholder_and_budget():
    hits = [
        {
            "chunk_id": str(i),
            "text": text,
            "section": "",
            "retrieval_method": "hybrid",
            "score": 999,
            "evidence_gate_score": score,
        }
        for i, (text, score) in enumerate(
            [
                ("Evidence.", 0.546),
                ("N/A", 0.9),
                ("Relevant evidence.", 0.7),
                ("Missing cosine.", None),
            ]
        )
    ]
    result = eligibility(hits, ["0", "2"], 0.6, 24000)
    assert result["hits"][0]["expected"] and not result["hits"][0]["cosine_eligible"]
    assert not result["hits"][1]["substantive"]
    assert result["context_chunk_ids"] == ["2"]
    assert eligibility(hits, ["2"], 0.6, 1)["context_chunk_ids"] == []


def test_latency_schema_nearest_rank_and_invalid_values():
    result = latency_summary(list(range(1, 21)))
    assert result["calls"] == 20 and result["median_ms"] == 10.5 and result["p95_ms"] == 19
    for values in ([], [-1], [float("nan")], [float("inf")]):
        with pytest.raises(ValueError):
            latency_summary(values)
    with pytest.raises(ValidationError):
        Latency.model_validate(result | {"p95_ms": 1.0})


def test_repeated_calls_reject_instability():
    rows = [{"chunk_id": "a", "score": 0.7}]
    assert repeated(lambda: deepcopy(rows), 3)[0] == rows
    iterator = iter([rows, []])
    with pytest.raises(ValueError, match="Non-reproducible"):
        repeated(lambda: next(iterator), 2)


def observation(answerable, category, rank, abstained):
    result = {
        "rank": rank,
        "abstained": abstained,
        "hits": [{"chunk_id": "x"}],
        "eligibility": {"hits": []},
        "cites_expected": answerable and not abstained,
    }
    return {
        "case_id": category,
        "query": "Test query",
        "category": category,
        "answerable": answerable,
        "modes": {m: deepcopy(result) for m in MODES},
        "reranking_change": rank_change(rank, rank) if answerable else None,
    }


def test_category_aggregation_negative_denominators_and_abstention():
    cases = [
        observation(True, "mixed", 1, False),
        observation(True, "semantic", None, True),
        observation(False, "out_of_corpus", None, True),
        observation(False, "ambiguous", None, False),
    ]
    result = summarize(cases, {"dense": [1.0, 2.0, 3.0]})
    m = result["metrics"]["dense"]
    assert m["overall"]["count"] == 2 and m["overall"]["Hit@1"] == 0.5
    assert m["categories"]["mixed"]["Hit@1"] == 1
    assert m["categories"]["out_of_corpus"]["Hit@1"] is None
    assert result["abstention"]["dense"]["precision"] == 0.5
    assert result["abstention"]["dense"]["recall"] == 0.5
    assert result["abstention"]["dense"]["incorrect_answer_attempts"] == 1
    assert result == summarize(cases, {"dense": [1.0, 2.0, 3.0]})


def test_failures_expose_degradation_and_component_disagreement():
    case = observation(True, "mixed", None, False)
    case["modes"]["bm25"]["rank"] = 1
    case["modes"]["hybrid"]["rank"] = 2
    case["reranking_change"] = rank_change(2, None)
    flags = summarize([case], {"dense": [1.0]})["failures"][0]["flags"]
    assert "bm25 succeeds where dense misses top5" in flags
    assert "hybrid worse than at least one component" in flags
    assert "reranker degraded first acceptable rank" in flags


@pytest.mark.skipif(
    os.environ.get("CAREFLOW_INGESTION_INTEGRATION") != "1",
    reason="Requires canonical live CMS index",
)
def test_golden_labels_match_canonical_index():
    from app.retrieval.search import load_corpus
    from qdrant_client import QdrantClient

    from ingestion.indexing.qdrant import NCDIndex

    settings = Settings()
    with closing(QdrantClient(settings.qdrant_url, timeout=5)) as client:
        index = NCDIndex(client, settings.rag_qdrant_alias)
        validate_corpus(
            load_dataset(Path("docs/evaluation/golden_retrieval_v1.json")),
            load_corpus(index, index.resolve()),
        )


def test_evaluation_uses_existing_context_and_ambiguity_rules(labelled):
    from app.reranking.cross_encoder import PassageScore

    from evaluation.run_retrieval_eval import evaluate

    data, hit = labelled
    negative = deepcopy(data["cases"][0]) | {
        "case_id": "cms-v1-002",
        "query": "Is it covered?",
        "category": "ambiguous",
        "answerable": False,
        "expected_chunk_ids": [],
        "evidence": [],
    }
    data["cases"].append(negative)

    class Search:
        def search(self, query, mode, top_k, for_rag=False):
            return [
                hit
                | {
                    "title": "Test policy",
                    "score": 0.7,
                    "retrieval_method": mode,
                    "evidence_gate_score": 0.7,
                }
            ]

    class Scorer:
        def describe(self):
            return {"model": "test double"}

        def score(self, query, passages):
            return [PassageScore(1.0, 1, 0, 5) for _ in passages]

    cases, timings = evaluate(GoldenDataset.model_validate(data), Search(), Scorer(), Settings(), 2)
    for mode in MODES:
        assert cases[0]["modes"][mode]["rank"] == 1
        assert cases[0]["modes"][mode]["generation_context_chunk_ids"] == ["a"]
        assert cases[0]["modes"][mode]["cites_expected"]
        assert cases[1]["modes"][mode]["abstention_reason"] == "ambiguous_question"
        assert cases[1]["modes"][mode]["generation_context_chunk_ids"] == []
        assert cases[1]["modes"][mode]["eligibility"]["context_chunk_ids"] == ["a"]
    assert all(len(samples) == 4 for samples in timings.values())
