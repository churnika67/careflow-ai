import copy
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest
from qdrant_client import QdrantClient
from transformers import BertTokenizerFast

from ingestion.chunking.sections import ChunkingConfig, chunk_documents
from ingestion.cms_coverage.cleaning import clean_sections
from ingestion.cms_coverage.source import load_documents, validate_tables
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import Document

ARCHIVE = Path("data/raw/cms_coverage/ncd.zip")
SUBSET = Path("docs/cms_inspection/dev_subset.json")
PROFILE = Path("docs/cms_inspection/ncd_profile.json")


@pytest.fixture
def source():
    if not ARCHIVE.exists():
        pytest.skip("Download the reviewed CMS snapshot to run source-data tests")
    return load_documents(ARCHIVE, SUBSET, PROFILE)


@pytest.fixture
def tables():
    if not ARCHIVE.exists():
        pytest.skip("Download the reviewed CMS snapshot to run source-data tests")
    with ZipFile(ARCHIVE) as outer:
        with ZipFile(io.BytesIO(outer.read("ncd_csv.zip"))) as inner:
            return {
                name: list(csv.DictReader(io.StringIO(inner.read(name).decode(), newline="")))
                for name in inner.namelist()
                if name.endswith(".csv")
            }


@pytest.fixture
def tokenizer(tmp_path):
    path = tmp_path / "vocab.txt"
    path.write_text(
        "\n".join(
            ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "oxygen", "sleep", "not", "covered", "."]
        )
    )
    return BertTokenizerFast(vocab_file=str(path))


def test_source_constructs_exact_versions_and_aggregates_benefits(source):
    docs, report = source
    assert len(docs) == 8
    expected = {(r["NCD_id"], r["NCD_vrsn_num"]) for r in json.loads(SUBSET.read_text())["records"]}
    assert {(d.metadata["NCD_id"], d.metadata["NCD_vrsn_num"]) for d in docs} == expected
    assert report["unselected_records"] == 349
    for doc in docs:
        assert doc.metadata["page"] is None
        assert doc.metadata["benefit_categories"]
        assert doc.metadata["publication"]["pblctn_num"] == "100-3"
        assert doc.metadata["source_record_sha256"]
        assert doc.metadata["snapshot_sha256"] == json.loads(PROFILE.read_text())["archive_sha256"]
    oxygen = next(d for d in docs if d.metadata["NCD_id"] == "169")
    assert oxygen.metadata["effective_date"] == "2021-09-27"
    assert oxygen.metadata["termination_date"] is None
    assert oxygen.metadata["flags"]["NCD_AMA"] is False


@pytest.mark.parametrize(
    "kind", ["column", "duplicate", "date", "boolean", "foreign_key", "empty_id", "timestamp"]
)
def test_malformed_tables_fail(tables, kind):
    if kind == "column":
        tables["ncd_trkg.csv"][0]["invented_field"] = "test"
    elif kind == "duplicate":
        tables["ncd_trkg.csv"].append(tables["ncd_trkg.csv"][0])
    elif kind == "date":
        tables["ncd_trkg.csv"][0]["NCD_efctv_dt"] = "not a date"
    elif kind == "boolean":
        tables["ncd_trkg.csv"][0]["under_rvw"] = "maybe"
    elif kind == "foreign_key":
        tables["ncd_trkg_bnft_xref.csv"][0]["bnft_ctgry_cd"] = "missing"
    elif kind == "timestamp":
        tables["ncd_trkg.csv"][0]["last_updt_tmstmp"] = ""
    else:
        tables["ncd_trkg.csv"][0]["NCD_id"] = ""
    with pytest.raises(ValueError):
        validate_tables(tables, json.loads(PROFILE.read_text())["tables"])


def test_unknown_coverage_is_explicit_and_not_mapped_to_denial(tables):
    observations = validate_tables(tables, json.loads(PROFILE.read_text())["tables"])
    assert {r["NCD_id"] for r in observations if "unknown_coverage_code" in r["flags"]} == {
        "73",
        "368",
    }


def test_wrong_archive_fails_before_parsing(tmp_path):
    p = tmp_path / "wrong.zip"
    p.write_bytes(b"not a dataset")
    with pytest.raises(ValueError, match="checksum"):
        load_documents(p, SUBSET, PROFILE)


def test_altered_subset_fails(source, tmp_path):
    subset = json.loads(SUBSET.read_text())
    subset["records"][0]["NCD_vrsn_num"] = "999"
    p = tmp_path / "subset.json"
    p.write_text(json.dumps(subset))
    with pytest.raises(ValueError, match="Selection"):
        load_documents(ARCHIVE, p, PROFILE)


def test_cleaning_preserves_negation_entities_lists_tables_and_safe_links():
    raw = (
        "<p><strong>B. Covered indications</p></strong><p>not covered if x &lt; 5 &a"
        'mp; y ≥ 3</p><ol type="a"><li>first</li><li>second</li></ol><table><tr><th>'
        "code</th><th>meaning</th></tr><tr><td>1</td><td>no</td></tr></table><a href"
        '="../view/ncd.aspx?NCDId=169">policy</a><script>bad()</script><!--hidden-->'
        "<p>C. Other</p><p>Exception</p>"
    )
    sections = clean_sections(raw, "indctn_lmtn")
    assert len(sections) == 2
    assert "not covered if x < 5 & y ≥ 3" in sections[0].text
    assert "a. first" in sections[0].text and "b. second" in sections[0].text
    assert "code | meaning |" in sections[0].text
    assert "bad()" not in sections[0].text and "hidden" not in sections[0].text
    assert sections[0].links == (
        "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDId=169",
    )
    assert sections[1].heading == "C. Other"


def test_empty_sections_remain_absent():
    assert clean_sections("<p>&nbsp; </p>", "othr_txt") == ()


def test_actual_sections_and_no_keywords_as_evidence(source):
    docs, _ = source
    cpap = next(d for d in docs if d.metadata["NCD_id"] == "226")
    assert any(s.heading == "B. Nationally Covered Indications" for s in cpap.sections)
    assert any("Nationally Non-covered" in s.heading for s in cpap.sections)
    assert all(
        s.field in {"itm_srvc_desc", "indctn_lmtn", "xref_txt", "othr_txt"}
        for d in docs
        for s in d.sections
    )


def test_chunking_offsets_overlap_determinism_and_version_identity(tokenizer):
    sections = clean_sections(
        "<p>B. Evidence</p><p>" + "oxygen not covered. " * 150 + "</p>", "indctn_lmtn"
    )
    doc = Document({"document_version_id": "test:v1", "page": None}, sections)
    config = ChunkingConfig(64, 12)
    chunks = chunk_documents([doc], tokenizer, config)
    assert len(chunks) > 1
    assert [c.chunk_id for c in chunks] == [
        c.chunk_id for c in chunk_documents([doc], tokenizer, config)
    ]
    intervals = []
    for c in chunks:
        start, stop = c.metadata["section_char_start"], c.metadata["section_char_end"]
        assert c.text == sections[0].text[start:stop]
        assert c.metadata["token_count"] <= 64
        intervals.append((c.metadata["section_token_start"], c.metadata["section_token_end"]))
    assert intervals[0][0] == 0
    assert intervals[-1][1] == chunks[-1].metadata["section_token_count"]
    assert all(a[1] > b[0] and b[1] > a[1] for a, b in zip(intervals, intervals[1:], strict=False))
    changed = Document(doc.metadata | {"document_version_id": "test:v2"}, sections)
    assert {c.chunk_id for c in chunks}.isdisjoint(
        c.chunk_id for c in chunk_documents([changed], tokenizer, config)
    )


@pytest.mark.parametrize("target,overlap", [(0, 0), (700, 700), (700, -1), (5001, 120)])
def test_invalid_chunk_configuration(target, overlap):
    with pytest.raises(ValueError):
        ChunkingConfig(target, overlap)


@pytest.fixture
def small_index(tokenizer):
    # Synthetic vectors exercise storage semantics only, never semantic quality.
    sections = clean_sections("<p>B. Covered</p><p>oxygen not covered.</p>", "indctn_lmtn")
    doc = Document(
        {"document_version_id": "test:v1", "NCD_id": "test", "NCD_vrsn_num": "1", "page": None},
        sections,
    )
    chunks = chunk_documents([doc], tokenizer, ChunkingConfig())
    client = QdrantClient(":memory:")
    index = NCDIndex(client, "unit_test")
    spec = {"dimension": 3, "model": "synthetic-storage-test"}
    vectors = np.array([[1.0, 0.0, 0.0]])
    yield index, chunks, vectors, spec
    client.close()


@pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")
def test_idempotent_upsert_and_safe_reindex(small_index):
    index, chunks, vectors, spec = small_index
    first = index.publish(chunks, vectors, spec)
    second = index.publish(chunks, vectors, spec)
    assert first["collection"] == second["collection"]
    assert index.client.count(index.alias, exact=True).count == 1
    rebuilt = index.publish(chunks, vectors, spec, reindex=True)
    assert rebuilt["collection"] != first["collection"]
    assert index.client.collection_exists(first["collection"])
    assert index.resolve() == rebuilt["collection"]


@pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")
def test_failed_reindex_preserves_published_generation(small_index, monkeypatch):
    index, chunks, vectors, spec = small_index
    first = index.publish(chunks, vectors, spec)

    def fail(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(index.client, "upsert", fail)
    with pytest.raises(RuntimeError):
        index.publish(chunks, vectors, spec, reindex=True)
    assert index.resolve() == first["collection"]
    assert index.client.count(index.alias, exact=True).count == 1


@pytest.mark.parametrize(
    "vectors", [np.array([[np.nan, 0, 0]]), np.array([[1, 0]]), np.zeros((1, 3))]
)
def test_invalid_vectors_fail_without_creating_index(small_index, vectors):
    index, chunks, _, spec = small_index
    with pytest.raises(ValueError):
        index.publish(chunks, vectors, spec)
    assert index.resolve() is None


@pytest.mark.filterwarnings("ignore:Payload indexes have no effect:UserWarning")
def test_filters_and_model_mismatch(small_index):
    index, chunks, vectors, spec = small_index
    index.publish(chunks, vectors, spec)

    class Provider:
        def describe(self):
            return spec

        def embed(self, texts):
            return vectors

    p = Provider()
    assert len(index.search("test query", p, filters={"NCD_id": "test"})) == 1
    assert index.search("test query", p, filters={"NCD_id": "absent"}) == []
    with pytest.raises(ValueError, match="filter"):
        index.search("query", p, filters={"invented": "x"})
    changed = copy.copy(p)
    changed.describe = lambda: {"dimension": 3, "model": "different"}
    with pytest.raises(ValueError, match="configuration"):
        index.search("query", changed)
