import json
import os
from pathlib import Path

import numpy as np
import pytest
from app.core.config import get_settings
from qdrant_client import QdrantClient

from ingestion.chunking.sections import ChunkingConfig
from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex
from ingestion.pipeline import build_corpus

pytestmark = pytest.mark.skipif(
    os.environ.get("CAREFLOW_INGESTION_INTEGRATION") != "1",
    reason="Requires downloaded model, CMS snapshot and published local Qdrant index",
)


@pytest.fixture(scope="module")
def provider():
    return SentenceTransformerEmbedding(local_only=True)


def test_real_embeddings_normalized_repeatable_and_not_truncated(provider):
    first = "oxygen " * 600
    second = first + "sleep apnea CPAP " * 600
    vectors = provider.embed([first, second])
    assert vectors.shape == (2, 384)
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
    assert np.allclose(vectors[0], provider.embed([first])[0], atol=1e-6)
    assert not np.allclose(vectors[0], vectors[1], atol=0.01)
    with pytest.raises(ValueError, match="empty"):
        provider.embed([""])


def test_short_embedding_matches_sentence_transformers_encode(provider):
    text = "What documentation supports home oxygen equipment?"
    native = provider.model.encode([text], normalize_embeddings=True)
    assert np.allclose(provider.embed([text]), native, atol=1e-6)


def test_published_semantic_search_and_provenance(provider):
    from ingestion.verification import verify

    _, chunks, _ = build_corpus(
        Path("data/raw/cms_coverage/ncd.zip"),
        Path("docs/cms_inspection/dev_subset.json"),
        Path("docs/cms_inspection/ncd_profile.json"),
        provider,
        ChunkingConfig(),
    )
    client = QdrantClient(url=get_settings().qdrant_url, timeout=30)
    try:
        report = verify(
            provider,
            NCDIndex(client),
            chunks,
            json.loads(Path("docs/phase3_search_cases.json").read_text()),
        )
        assert report["cases_passed"] == report["cases_total"]
        assert client.count(NCDIndex(client).alias, exact=True).count == len(chunks)
    finally:
        client.close()
