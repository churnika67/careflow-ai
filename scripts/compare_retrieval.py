"""Phase 5 development retrieval comparison, not a production benchmark."""

import argparse
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter

from app.core.config import Settings
from app.generation.context import build_context
from app.generation.providers import DeterministicProvider
from app.generation.service import RAGService
from app.retrieval.lexical import TOKENIZER_VERSION, BM25Index
from app.retrieval.search import MODES, Retriever, load_corpus
from qdrant_client import QdrantClient

from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import digest

NEGATIVES = [
    "What dental implant documentation is required?",
    "What chemotherapy regimen treats pancreatic cancer?",
    "How do I configure a Kubernetes ingress controller?",
]


def describe_hits(hits):
    keys = (
        "chunk_id",
        "NCD_id",
        "NCD_vrsn_num",
        "title",
        "section",
        "source_field",
        "text",
        "score",
        "dense_score",
        "bm25_score",
        "fusion_score",
        "dense_rank",
        "bm25_rank",
        "fusion_rank",
        "retrieval_method",
        "retrieval_sources",
    )
    return [{key: hit[key] for key in keys if key in hit} for hit in hits]


def expected_rank(hits, case, evidence):
    for rank, hit in enumerate(hits, 1):
        if (
            hit["NCD_id"] == case["expected_document_id"]
            and hit["NCD_vrsn_num"] == case["expected_version"]
        ):
            if not evidence or (
                hit["source_field"] == "indctn_lmtn"
                and hit["section"] == case["expected_section"]
                and case["expected_evidence_phrase"] in hit["text"]
            ):
                return rank
    return None


def compare(settings, repeats):
    start = perf_counter()
    embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
    model_load_ms = (perf_counter() - start) * 1000
    with closing(QdrantClient(settings.qdrant_url, timeout=30)) as client:
        index = NCDIndex(client, settings.rag_qdrant_alias)
        collection = index.resolve()
        if collection is None:
            raise ValueError("No published CMS index")
        start = perf_counter()
        corpus = load_corpus(index, collection)
        lexical = BM25Index(corpus, settings.bm25_k1, settings.bm25_b)
        corpus_build_ms = (perf_counter() - start) * 1000
        if len(corpus) != 39:
            raise ValueError("Comparison requires the reviewed 39-chunk development corpus")
        retriever = Retriever(
            index,
            embedding,
            settings.retrieval_candidate_k,
            settings.retrieval_rrf_constant,
            settings.bm25_k1,
            settings.bm25_b,
        )
        cases = json.loads(Path("docs/phase3_search_cases.json").read_text())
        latency = {mode: [] for mode in MODES}
        observations = []
        # Warm each path once, including payload reads and lexical rebuilding.
        for mode in MODES:
            retriever.search(cases[0]["query"], mode)
        for case in cases:
            result = {"query": case["query"], "expected": case, "modes": {}}
            for mode in MODES:
                hits = None
                samples = []
                for _ in range(repeats):
                    start = perf_counter()
                    current = retriever.search(case["query"], mode)
                    samples.append((perf_counter() - start) * 1000)
                    if hits is not None and hits != current:
                        raise ValueError("Non-reproducible ranking or scores")
                    hits = current
                latency[mode].extend(samples)
                rank = expected_rank(hits, case, True)
                result["modes"][mode] = {
                    "expected_evidence_rank": rank,
                    "expected_document_rank": expected_rank(hits, case, False),
                    "hits": {str(k): rank is not None and rank <= k for k in (1, 3, 5)},
                    "latency_ms": samples,
                    "top5": describe_hits(hits),
                }
            observations.append(result)
        negatives = []
        for query in NEGATIVES:
            modes = {}
            for mode in MODES:
                raw = retriever.search(query, mode)
                rag_hits = retriever.search(query, mode, for_rag=True)
                answer = RAGService(
                    lambda _, rows=rag_hits: rows, DeterministicProvider(), settings
                ).answer(query)
                modes[mode] = {
                    "top5": describe_hits(raw),
                    "evidence_gate_scores": [
                        hit.get("evidence_gate_score", hit["score"]) for hit in rag_hits
                    ],
                    "rag_response": answer.model_dump(),
                }
                assert answer.insufficient_evidence, (query, mode)
            negatives.append({"query": query, "modes": modes})
        seat = cases[6]
        seat_rag = {}
        for mode in MODES:
            seat_rag[mode] = {}
            for top_k in (1, 5):
                hits = retriever.search(seat["query"], mode, top_k, for_rag=True)
                answer = RAGService(
                    lambda _, rows=hits: rows, DeterministicProvider(), settings
                ).answer(seat["query"])
                context = build_context(hits, settings.rag_min_score, settings.rag_context_chars)
                seat_rag[mode][str(top_k)] = {
                    "response": answer.model_dump(),
                    "context_chunk_ids": [hit["chunk_id"] for hit in context.chunks],
                }
        if index.resolve() != collection or load_corpus(index, collection) != corpus:
            raise ValueError("Corpus changed during comparison; rerun on a stable generation")
        return {
            "label": "Phase 5 development retrieval comparison",
            "observed_at": datetime.now(UTC).isoformat(),
            "corpus": {
                "collection": collection,
                "count": len(corpus),
                "chunk_ids": list(lexical.chunk_ids),
                "payloads_sha256": digest(corpus),
                "snapshot_sha256": corpus[0]["snapshot_sha256"],
                "document_versions": len({c["document_version_id"] for c in corpus}),
                "sections": len({c["section_id"] for c in corpus}),
            },
            "configuration": {
                "tokenizer": TOKENIZER_VERSION,
                "bm25_k1": settings.bm25_k1,
                "bm25_b": settings.bm25_b,
                "rrf_constant": settings.retrieval_rrf_constant,
                "candidate_k": settings.retrieval_candidate_k,
                "top_k": 5,
                "rag_min_cosine": settings.rag_min_score,
                "embedding": embedding.describe(),
            },
            "latency": {
                "model_load_ms": model_load_ms,
                "initial_corpus_build_ms": corpus_build_ms,
                "method": (
                    "Sequential warm calls; includes Qdrant I/O and per-call BM25 rebuild; "
                    "excludes model loading and RAG gate/generation. "
                    "Not concurrent-load performance."
                ),
                "repeats_per_query": repeats,
                "modes": {
                    mode: {
                        "calls": len(samples),
                        "median_ms": median(samples),
                        "min_ms": min(samples),
                        "max_ms": max(samples),
                    }
                    for mode, samples in latency.items()
                },
            },
            "hit_rates": {
                mode: {
                    f"Hit@{k}": sum(case["modes"][mode]["hits"][str(k)] for case in observations)
                    / len(observations)
                    for k in (1, 3, 5)
                }
                for mode in MODES
            },
            "cases": observations,
            "out_of_corpus": negatives,
            "seat_elevation_rag": seat_rag,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3, choices=range(1, 21))
    args = parser.parse_args()
    report = compare(Settings(), args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "hit_rates": report["hit_rates"],
                "latency": report["latency"],
                "seat_ranks": {
                    mode: report["cases"][6]["modes"][mode]["expected_evidence_rank"]
                    for mode in MODES
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
