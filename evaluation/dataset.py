import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingestion.models import digest

Category = Literal[
    "exact_lexical",
    "semantic",
    "mixed",
    "ambiguous",
    "out_of_corpus",
    "hard_negative",
    "known_failure",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceReference(StrictModel):
    chunk_id: str = Field(min_length=1)
    ncd_id: str = Field(min_length=1)
    ncd_version: str = Field(min_length=1)
    section: str = Field(min_length=1)
    quote: str = Field(min_length=8)
    source_url: str = Field(min_length=1)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_record_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class GoldenCase(StrictModel):
    case_id: str = Field(pattern=r"^cms-v1-\d{3}$")
    query: str = Field(min_length=1, max_length=4000)
    category: Category
    expected_chunk_ids: list[str]
    evidence: list[EvidenceReference]
    answerable: bool
    notes: str = Field(min_length=10)

    @model_validator(mode="after")
    def consistent_labels(self):
        ids = [e.chunk_id for e in self.evidence]
        if not self.query.strip() or len(set(ids)) != len(ids):
            raise ValueError("Blank query or duplicate evidence")
        if self.expected_chunk_ids != ids or self.answerable != bool(ids):
            raise ValueError("Answerability, expected IDs and evidence must agree")
        if self.category in {"ambiguous", "out_of_corpus"} and self.answerable:
            raise ValueError("Ambiguous/out-of-corpus cases must not be answerable")
        return self


class GoldenDataset(StrictModel):
    schema_version: Literal["1.0"]
    dataset_version: Literal["cms-retrieval-v1"]
    corpus_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    label_method: str = Field(min_length=10)
    cases: list[GoldenCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cases(self):
        ids = [c.case_id for c in self.cases]
        queries = [c.query.strip().casefold() for c in self.cases]
        if len(set(ids)) != len(ids) or len(set(queries)) != len(queries):
            raise ValueError("Duplicate case ID or query")
        return self


def load_dataset(path: Path) -> GoldenDataset:
    return GoldenDataset.model_validate(json.loads(path.read_text()))


def validate_corpus(dataset: GoldenDataset, corpus: list[dict]) -> None:
    by_id = {h["chunk_id"]: h for h in corpus}
    if len(by_id) != len(corpus):
        raise ValueError("Duplicate corpus chunk")
    for case in dataset.cases:
        for ref in case.evidence:
            hit = by_id.get(ref.chunk_id)
            if hit is None:
                raise ValueError(f"{case.case_id}: missing chunk {ref.chunk_id}")
            if (hit["NCD_id"], hit["NCD_vrsn_num"], hit["section"]) != (
                ref.ncd_id,
                ref.ncd_version,
                ref.section,
            ):
                raise ValueError(f"{case.case_id}: metadata mismatch")
            if ref.quote not in hit["text"] or digest(hit["text"]) != ref.text_sha256:
                raise ValueError(f"{case.case_id}: evidence mismatch")
            if (
                hit["source_record_sha256"] != ref.source_record_sha256
                or hit["viewer_url"] != ref.source_url
                or hit["snapshot_sha256"] != dataset.snapshot_sha256
            ):
                raise ValueError(f"{case.case_id}: provenance mismatch")
    if digest(corpus) != dataset.corpus_sha256:
        raise ValueError("Canonical corpus fingerprint mismatch")
