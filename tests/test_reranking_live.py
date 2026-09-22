import json
import os
from pathlib import Path

import numpy as np
import pytest
import torch
from app.core.config import Settings
from app.generation.providers import DeterministicProvider
from app.generation.runtime import retrieve
from app.generation.service import RAGService
from app.reranking.cross_encoder import MiniLMCrossEncoder, RerankQueryError

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_RERANK_INTEGRATION") != "1",
    reason="Requires downloaded cross-encoder and existing CMS index",
)


@pytest.fixture(scope="module")
def provider():
    return MiniLMCrossEncoder()


def test_real_short_pair_matches_native_prediction(provider):
    query = "hospital bed prescription"
    passage = "The prescription must describe the medical condition and severity of symptoms."
    raw = provider.encoder.predict(
        [(query, passage)], activation_fn=torch.nn.Identity(), show_progress_bar=False
    )
    score = provider.score(query, [passage])[0]
    assert score.window_count == 1
    assert np.allclose(score.score, raw[0], atol=1e-5)
    assert provider.score(query, [passage])[0] == score


def test_tail_is_scored_and_long_query_rejected(provider):
    query = "hospital bed prescription"
    irrelevant = "Stars and galaxies are observed through a telescope. " * 100
    relevant = (
        "A hospital bed prescription must describe the medical condition and severity of symptoms."
    )
    before = provider.score(query, [irrelevant])[0]
    after = provider.score(query, [irrelevant + relevant])[0]
    assert after.window_count > 1 and after.token_start > 0
    assert after.score > before.score
    with pytest.raises(RerankQueryError):
        provider.score("oxygen " * 129, [relevant])


@pytest.mark.parametrize("case_index", [4, 6, 7])
def test_live_rag_provenance(case_index):
    case = json.loads(Path("docs/phase3_search_cases.json").read_text())[case_index]
    settings = Settings(retrieval_mode="hybrid", rerank_enabled=True)
    hits = retrieve(case["query"], settings)
    assert all("rerank_score" in h for h in hits)
    answer = RAGService(lambda _: hits, DeterministicProvider(), settings).answer(case["query"])
    assert not answer.insufficient_evidence
    assert answer.citations[0].document_id == case["expected_document_id"]
    assert answer.citations[0].document_version == case["expected_version"]
    assert answer.citations[0].chunk_id in [h["chunk_id"] for h in hits]
    assert case["expected_evidence_phrase"] in answer.answer


@pytest.mark.parametrize(
    "question",
    [
        "What dental implant documentation is required?",
        "What chemotherapy regimen treats pancreatic cancer?",
        "How do I configure a Kubernetes ingress controller?",
    ],
)
def test_live_reranked_negatives(question):
    settings = Settings(retrieval_mode="hybrid", rerank_enabled=True)
    answer = RAGService(lambda q: retrieve(q, settings), DeterministicProvider(), settings).answer(
        question
    )
    assert answer.answer == "Insufficient evidence." and not answer.citations
