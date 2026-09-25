import os
from pathlib import Path

import pytest

from evaluation.dataset import load_dataset

HELDOUT_PATH = Path("docs/evaluation/golden_retrieval_heldout_v1.json")
DEV_PATH = Path("docs/evaluation/golden_retrieval_v1.json")


@pytest.fixture(scope="module")
def heldout():
    return load_dataset(HELDOUT_PATH)


@pytest.fixture(scope="module")
def dev():
    return load_dataset(DEV_PATH)


def test_heldout_dataset_loads_and_validates():
    dataset = load_dataset(HELDOUT_PATH)
    assert dataset.dataset_version == "cms-retrieval-heldout-v1"


def test_heldout_case_count_is_twelve(heldout):
    assert len(heldout.cases) == 12


def test_heldout_positive_negative_split(heldout):
    positive = sum(c.answerable for c in heldout.cases)
    negative = sum(not c.answerable for c in heldout.cases)
    assert positive == 10
    assert negative == 2
    assert positive + negative == len(heldout.cases)


def test_heldout_category_coverage(heldout):
    from collections import Counter

    counts = Counter(c.category for c in heldout.cases)
    assert counts == {
        "exact_lexical": 2,
        "semantic": 3,
        "mixed": 3,
        "hard_negative": 2,
        "out_of_corpus": 1,
        "adversarial_specificity": 1,
    }


def test_heldout_case_ids_use_the_held_out_namespace(heldout):
    assert all(c.case_id.startswith("cms-v1-h") for c in heldout.cases)


def test_heldout_shares_the_same_corpus_and_snapshot_fingerprint_as_dev(heldout, dev):
    # Proves both datasets are grounded against the identical, unmutated
    # 39-chunk corpus -- not just asserted, independently recomputed and
    # compared.
    assert heldout.corpus_sha256 == dev.corpus_sha256
    assert heldout.snapshot_sha256 == dev.snapshot_sha256


def test_heldout_evidence_chunks_never_overlap_with_dev_evidence_chunks(heldout, dev):
    dev_used = {cid for c in dev.cases for cid in c.expected_chunk_ids}
    heldout_used = {cid for c in heldout.cases for cid in c.expected_chunk_ids}
    assert dev_used & heldout_used == set()
    assert len(heldout_used) == 10  # one distinct chunk per positive case


def test_heldout_includes_long_section_coverage(heldout):
    # At least one held-out case must draw evidence from a section long
    # enough (>700 tokens) to be affected by the chunking experiment grid
    # (400/700/1200) -- otherwise the chunking comparison would have no
    # held-out signal at all. Verified against the dataset's own recorded
    # notes rather than re-deriving section length here.
    long_section_cases = [c for c in heldout.cases if "long-section" in c.notes]
    assert len(long_section_cases) >= 2
    assert {c.case_id for c in long_section_cases} == {"cms-v1-h003", "cms-v1-h004"}


def test_heldout_disclosures_present(heldout):
    assert "No ranking-based label tuning" in heldout.label_method
    # explicit non-claim of independent/clinical validation must be present,
    # matching the approved authorship disclosure requirement.
    assert "not an independently annotated" in heldout.label_method.lower()


def test_heldout_created_at_is_recorded(heldout):
    assert heldout.created_at is not None


def test_dev_dataset_still_loads_after_schema_widening():
    # Regression: extending Category/dataset_version/case_id for the
    # held-out set must not change how the frozen v1 file validates.
    dataset = load_dataset(DEV_PATH)
    assert dataset.dataset_version == "cms-retrieval-v1"
    assert len(dataset.cases) == 32
    assert dataset.created_at is None  # v1 predates this field; stays optional


@pytest.mark.skipif(
    os.environ.get("CAREFLOW_INGESTION_INTEGRATION") != "1",
    reason="Requires canonical live CMS index",
)
def test_heldout_labels_match_canonical_index():
    from contextlib import closing

    from app.core.config import Settings
    from app.retrieval.search import load_corpus
    from qdrant_client import QdrantClient

    from evaluation.dataset import validate_corpus
    from ingestion.indexing.qdrant import NCDIndex

    settings = Settings()
    with closing(QdrantClient(settings.qdrant_url, timeout=5)) as client:
        index = NCDIndex(client, settings.rag_qdrant_alias)
        validate_corpus(load_dataset(HELDOUT_PATH), load_corpus(index, index.resolve()))


@pytest.mark.skipif(
    os.environ.get("CAREFLOW_INGESTION_INTEGRATION") != "1",
    reason="Requires canonical live CMS index",
)
def test_production_qdrant_alias_still_has_39_points():
    from contextlib import closing

    from app.core.config import Settings
    from qdrant_client import QdrantClient

    settings = Settings()
    with closing(QdrantClient(settings.qdrant_url, timeout=5)) as client:
        info = client.get_collection(settings.rag_qdrant_alias)
        assert info.points_count == 39
