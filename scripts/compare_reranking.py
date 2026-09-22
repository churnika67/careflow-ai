"""Compare identical hybrid candidates before and after cross-encoder scoring."""

import argparse
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter

from app.core.config import Settings
from app.generation.providers import DeterministicProvider
from app.generation.service import RAGService
from app.reranking.cross_encoder import MiniLMCrossEncoder
from app.reranking.service import rerank
from app.retrieval.search import MODES, Retriever, load_corpus
from compare_retrieval import NEGATIVES, expected_rank
from qdrant_client import QdrantClient

from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
    start = perf_counter()
    provider = MiniLMCrossEncoder(settings.rerank_model_cache, True)
    load_ms = 1000 * (perf_counter() - start)
    cases = json.loads(Path("docs/phase3_search_cases.json").read_text())
    observations, times = [], []
    retrieval_times = {mode: [] for mode in MODES}
    with closing(QdrantClient(settings.qdrant_url, timeout=30)) as client:
        index = NCDIndex(client, settings.rag_qdrant_alias)
        collection = index.resolve()
        corpus = load_corpus(index, collection)
        search = Retriever(
            index,
            embedding,
            settings.retrieval_candidate_k,
            settings.retrieval_rrf_constant,
            settings.bm25_k1,
            settings.bm25_b,
        )
        if len(corpus) != 39:
            raise ValueError("Expected the reviewed 39-chunk development corpus")
        depth = max(5, settings.rerank_candidate_k)
        warm = search.search(cases[0]["query"], "hybrid", depth, for_rag=True)
        rerank(cases[0]["query"], warm, provider)
        for mode in MODES:
            search.search(cases[0]["query"], mode, 5)
        for case in cases + [{"query": q} for q in NEGATIVES]:
            query = case["query"]
            baselines = {}
            for mode in MODES:
                samples, baseline = [], None
                for _ in range(3):
                    start = perf_counter()
                    result = search.search(query, mode, 5)
                    samples.append(1000 * (perf_counter() - start))
                    if baseline is not None:
                        assert result == baseline
                    baseline = result
                retrieval_times[mode].extend(samples)
                baselines[mode] = {
                    "top5": baseline,
                    "latency_ms": samples,
                    "expected_evidence_rank": expected_rank(baseline, case, True)
                    if "expected_document_id" in case
                    else None,
                }
            candidates = search.search(query, "hybrid", depth, for_rag=True)
            repetitions, output = [], None
            for _ in range(3):
                start = perf_counter()
                ranked = rerank(query, candidates, provider, 5)
                repetitions.append(1000 * (perf_counter() - start))
                if output is not None:
                    assert ranked == output
                output = ranked
            times.extend(repetitions)
            answer = RAGService(
                lambda _, rows=output: rows, DeterministicProvider(), settings
            ).answer(query)
            if "expected_document_id" not in case:
                assert answer.insufficient_evidence
            before_rank = (
                expected_rank(candidates[:5], case, True)
                if "expected_document_id" in case
                else None
            )
            after_rank = (
                expected_rank(output, case, True) if "expected_document_id" in case else None
            )
            keys = (
                "chunk_id",
                "NCD_id",
                "NCD_vrsn_num",
                "section",
                "source_field",
                "text",
                "score",
                "dense_score",
                "bm25_score",
                "fusion_score",
                "fusion_rank",
                "evidence_gate_score",
                "rerank_score",
                "rerank_rank",
                "candidate_rank",
                "rerank_window_count",
                "rerank_window_token_start",
                "rerank_window_token_end",
            )
            observations.append(
                {
                    "query": query,
                    "expected": case,
                    "baselines": baselines,
                    "before_evidence_rank": before_rank,
                    "after_evidence_rank": after_rank,
                    "candidate_ids": [h["chunk_id"] for h in candidates],
                    "before_top5": [{k: h[k] for k in keys if k in h} for h in candidates[:5]],
                    "after_top5": [{k: h[k] for k in keys if k in h} for h in output],
                    "rerank_latency_ms": repetitions,
                    "rag_response": answer.model_dump(),
                }
            )
        assert collection == index.resolve() and load_corpus(index, collection) == corpus
    report = {
        "label": "Phase 6 development retrieval evaluation, not production accuracy",
        "observed_at": datetime.now(UTC).isoformat(),
        "reranker": provider.describe(),
        "candidate_depth": depth,
        "top_k": 5,
        "collection": collection,
        "chunks": len(corpus),
        "corpus_sha256": digest(corpus),
        "cases": observations,
        "latency": {
            "model_load_ms": load_ms,
            "rerank_only_median_ms": median(times),
            "min_ms": min(times),
            "max_ms": max(times),
            "calls": len(times),
            "method": "3 warm reranking calls per question; excludes retrieval and generation",
        },
        "retrieval_latency": {
            mode: {
                "median_ms": median(values),
                "min_ms": min(values),
                "max_ms": max(values),
                "calls": len(values),
            }
            for mode, values in retrieval_times.items()
        },
        "retrieval_hit_rates": {
            mode: {
                f"Hit@{k}": sum(
                    o["baselines"][mode]["expected_evidence_rank"] is not None
                    and o["baselines"][mode]["expected_evidence_rank"] <= k
                    for o in observations[:8]
                )
                / 8
                for k in (1, 3, 5)
            }
            for mode in MODES
        },
        "hit_rates": {
            phase: {
                f"Hit@{k}": sum(
                    o[f"{phase}_evidence_rank"] is not None and o[f"{phase}_evidence_rank"] <= k
                    for o in observations[:8]
                )
                / 8
                for k in (1, 3, 5)
            }
            for phase in ("before", "after")
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        json.dumps(
            {
                "hit_rates": report["hit_rates"],
                "retrieval_hit_rates": report["retrieval_hit_rates"],
                "retrieval_latency": report["retrieval_latency"],
                "latency": report["latency"],
                "ranks": [
                    (
                        o["expected"].get("expected_document_id"),
                        o["before_evidence_rank"],
                        o["after_evidence_rank"],
                    )
                    for o in observations[:8]
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
