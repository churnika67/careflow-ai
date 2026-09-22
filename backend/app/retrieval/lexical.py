import math
import re
import unicodedata
from collections import Counter
from copy import deepcopy

TOKENIZER_VERSION = "cms-lexical-v1"
FILTERS = {"NCD_id", "NCD_vrsn_num", "source_field", "coverage_code", "document_version_id"}


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    text = re.sub(r"\b([^\W_]+)'s\b", r"\1", text)
    return re.findall(r"[^\W_]+(?:\.[^\W_]+)*", text)


def validate_search(query: str, top_k: int, filters: dict | None) -> dict:
    if len(query) > 4000 or not 1 <= top_k <= 20:
        raise ValueError("Query must be at most 4000 characters; top_k must be 1–20")
    filters = filters or {}
    if set(filters) - FILTERS or any(not isinstance(v, str) or not v for v in filters.values()):
        raise ValueError("Unsupported metadata filter")
    return filters


class BM25Index:
    """Small in-memory Okapi index with positive IDF and explicit chunk mapping."""

    def __init__(self, chunks: list[dict], k1: float = 1.2, b: float = 0.75):
        if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError("Invalid BM25 parameters")
        self.k1, self.b = k1, b
        self.chunks = tuple(sorted(deepcopy(chunks), key=lambda chunk: chunk["chunk_id"]))
        self.chunk_ids = tuple(chunk["chunk_id"] for chunk in self.chunks)
        if len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise ValueError("Duplicate chunk IDs")
        self.frequencies = []
        for chunk in self.chunks:
            if not chunk["chunk_id"] or not chunk["text"].strip():
                raise ValueError("Empty chunk ID or evidence")
            text = chunk["title"] + "\n" + chunk["section"] + "\n" + chunk["text"]
            self.frequencies.append(Counter(tokenize(text)))
        self.lengths = [sum(counts.values()) for counts in self.frequencies]
        self.average_length = sum(self.lengths) / len(self.chunks) if self.chunks else 0
        document_frequency = Counter(term for counts in self.frequencies for term in counts)
        self.idf = {
            term: math.log1p((len(self.chunks) - count + 0.5) / (count + 0.5))
            for term, count in sorted(document_frequency.items())
        }

    def search(self, query: str, top_k: int = 5, filters: dict | None = None) -> list[dict]:
        filters = validate_search(query, top_k, filters)
        terms = sorted(set(tokenize(query)) & self.idf.keys())
        if not terms or not self.average_length:
            return []
        scored = []
        for chunk, counts, length in zip(self.chunks, self.frequencies, self.lengths, strict=True):
            if any(chunk.get(key) != value for key, value in filters.items()):
                continue
            norm = self.k1 * (1 - self.b + self.b * length / self.average_length)
            score = sum(
                self.idf[term] * counts[term] * (self.k1 + 1) / (counts[term] + norm)
                for term in terms
                if counts[term]
            )
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1]["chunk_id"]))
        return [
            deepcopy(chunk)
            | {
                "score": score,
                "bm25_score": score,
                "dense_score": None,
                "fusion_score": None,
                "bm25_rank": rank,
                "dense_rank": None,
                "retrieval_method": "bm25",
                "retrieval_sources": ["bm25"],
            }
            for rank, (score, chunk) in enumerate(scored[:top_k], 1)
        ]
