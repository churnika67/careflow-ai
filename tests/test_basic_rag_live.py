import json
import os
from pathlib import Path

import httpx
import pytest
from app.core.config import Settings
from app.generation.providers import DeterministicProvider
from app.generation.runtime import retrieve
from app.generation.service import RAGService

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_RAG_INTEGRATION") != "1",
    reason="Requires pinned CMS index, cached embeddings and running Phase 4 API",
)


@pytest.mark.parametrize("index", [4, 5, 6, 7])
def test_real_retrieval_to_generation(index):
    case = json.loads(Path("docs/phase3_search_cases.json").read_text())[index]
    settings = Settings(rag_provider="deterministic")
    hits = retrieve(case["query"], settings)
    answer = RAGService(lambda _: hits, DeterministicProvider(), settings).answer(case["query"])
    assert not answer.insufficient_evidence
    assert case["expected_evidence_phrase"] in answer.answer
    assert answer.citations[0].document_id == case["expected_document_id"]
    assert answer.citations[0].document_version == case["expected_version"]
    assert answer.citations[0].section == case["expected_section"]
    assert all(c.chunk_id in {hit["chunk_id"] for hit in hits} for c in answer.citations)
    if index == 6:
        assert hits[0]["text"].endswith("N/A")
        assert answer.citations[0].chunk_id == hits[1]["chunk_id"]


@pytest.mark.parametrize(
    "question",
    [
        "What dental implant documentation is required?",
        "What chemotherapy regimen treats pancreatic cancer?",
        "How do I configure a Kubernetes ingress controller?",
    ],
)
def test_live_out_of_corpus(question):
    settings = Settings(rag_provider="deterministic")
    answer = RAGService(lambda q: retrieve(q, settings), DeterministicProvider(), settings).answer(
        question
    )
    assert answer.answer == "Insufficient evidence."
    assert answer.citations == []


def test_running_query_api():
    base = os.environ.get("CAREFLOW_API_URL", "http://localhost:8000")
    response = httpx.post(
        base + "/query",
        json={"question": "What must a physician prescription document to justify a hospital bed?"},
        timeout=60,
    )
    assert response.status_code == 200, response.text
    answer = response.json()
    assert not answer["insufficient_evidence"]
    assert answer["citations"][0]["document_id"] == "227"
    assert answer["citations"][0]["chunk_id"] in answer["retrieved_chunk_ids"]
