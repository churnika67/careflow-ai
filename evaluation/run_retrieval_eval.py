"""Evaluate frozen development labels against the existing CMS retrieval pipeline."""

import argparse
import json
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from app.core.config import Settings
from app.generation.providers import DeterministicProvider
from app.generation.service import RAGService
from app.reranking.cross_encoder import MiniLMCrossEncoder
from app.reranking.service import rerank
from app.retrieval.search import Retriever, load_corpus
from qdrant_client import QdrantClient

from evaluation.analysis import MODES, eligibility, summarize
from evaluation.dataset import load_dataset, validate_corpus
from evaluation.metrics import first_rank, rank_change
from evaluation.report import render_report
from ingestion.embeddings.providers import SentenceTransformerEmbedding
from ingestion.indexing.qdrant import NCDIndex
from ingestion.models import digest


def repeated(call, repeats):
    previous, samples = None, []
    for _ in range(repeats):
        start = perf_counter()
        current = call()
        samples.append((perf_counter() - start) * 1000)
        if previous is not None and current != previous:
            raise ValueError("Non-reproducible rankings, scores or payloads")
        previous = current
    return previous, samples


def evaluate(dataset, search, provider, settings, repeats):
    timings = {m: [] for m in (*MODES[:3], "hybrid_candidates_with_gate", "rerank_only")}
    observations = []
    # Warm model and all retrieval branches before recording latency.
    query = dataset.cases[0].query
    for mode in MODES[:3]:
        search.search(query, mode, 5)
    warm = search.search(query, "hybrid", 10, for_rag=True)
    rerank(query, warm, provider, 5)
    for case in dataset.cases:
        results = {}
        for mode in MODES[:3]:
            hits, samples = repeated(lambda m=mode, q=case.query: search.search(q, m, 5), repeats)
            timings[mode].extend(samples)
            rag_hits = search.search(case.query, mode, 5, for_rag=True)
            if [h["chunk_id"] for h in hits] != [h["chunk_id"] for h in rag_hits]:
                raise ValueError("Evidence-gate lookup changed retrieval order")
            results[mode] = (hits, rag_hits, samples)
        candidates, samples = repeated(
            lambda q=case.query: search.search(q, "hybrid", 10, for_rag=True), repeats
        )
        timings["hybrid_candidates_with_gate"].extend(samples)
        ranked, samples = repeated(
            lambda q=case.query, rows=candidates: rerank(q, rows, provider, 5), repeats
        )
        timings["rerank_only"].extend(samples)
        results["hybrid_reranked"] = (ranked, ranked, samples)
        record = {
            "case_id": case.case_id,
            "query": case.query,
            "category": case.category,
            "answerable": case.answerable,
            "expected_chunk_ids": case.expected_chunk_ids,
            "candidate_ids": [h["chunk_id"] for h in candidates],
            "modes": {},
        }
        for mode, (hits, rag_hits, samples) in results.items():
            supplied = []

            def retrieve(_, rows=rag_hits, context_ids=supplied):
                context_ids.extend(
                    eligibility(rows, [], settings.rag_min_score, settings.rag_context_chars)[
                        "context_chunk_ids"
                    ]
                )
                return rows

            answer = RAGService(retrieve, DeterministicProvider(), settings).answer(case.query)
            keys = (
                "chunk_id",
                "NCD_id",
                "NCD_vrsn_num",
                "section",
                "score",
                "dense_score",
                "bm25_score",
                "fusion_score",
                "dense_rank",
                "bm25_rank",
                "fusion_rank",
                "rerank_score",
                "rerank_rank",
                "candidate_rank",
                "rerank_window_count",
            )
            record["modes"][mode] = {
                "rank": first_rank(hits, case.expected_chunk_ids) if case.answerable else None,
                "hits": [{k: h[k] for k in keys if k in h} for h in hits],
                "latency_ms": samples,
                "eligibility": eligibility(
                    rag_hits,
                    case.expected_chunk_ids,
                    settings.rag_min_score,
                    settings.rag_context_chars,
                ),
                "generation_context_chunk_ids": supplied,
                "abstained": answer.insufficient_evidence,
                "abstention_reason": answer.abstention_reason,
                "citation_chunk_ids": [c.chunk_id for c in answer.citations],
                "cites_expected": any(
                    c.chunk_id in case.expected_chunk_ids for c in answer.citations
                ),
            }
        record["reranking_change"] = (
            rank_change(
                record["modes"]["hybrid"]["rank"], record["modes"]["hybrid_reranked"]["rank"]
            )
            if case.answerable
            else None
        )
        observations.append(record)
        print(f"Evaluated {case.case_id}", flush=True)
    return observations, timings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("docs/evaluation/golden_retrieval_v1.json")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("docs/evaluation"))
    parser.add_argument("--repeats", type=int, choices=range(2, 11), default=3)
    args = parser.parse_args()
    dataset = load_dataset(args.dataset)
    # Freeze the Phase 6 experiment, independently of mutable API defaults.
    settings = Settings(
        retrieval_candidate_k=10,
        retrieval_rrf_constant=60,
        bm25_k1=1.2,
        bm25_b=0.75,
        rerank_candidate_k=10,
        rag_top_k=5,
        rag_min_score=0.6,
        rag_context_chars=24000,
    )
    with closing(QdrantClient(settings.qdrant_url, timeout=10)) as client:
        index = NCDIndex(client, settings.rag_qdrant_alias)
        collection = index.resolve()
        corpus = load_corpus(index, collection)
        validate_corpus(dataset, corpus)
        if (
            len(corpus),
            len({h["document_version_id"] for h in corpus}),
            len({h["section_id"] for h in corpus}),
        ) != (39, 8, 32):
            raise ValueError("Expected 39 chunks, eight NCD versions, 32 sections")
        embedding = SentenceTransformerEmbedding(settings.rag_model_cache, True)
        provider = MiniLMCrossEncoder(settings.rerank_model_cache, True)
        search = Retriever(index, embedding, 10, 60, 1.2, 0.75)
        cases, timings = evaluate(dataset, search, provider, settings, args.repeats)
        if index.resolve() != collection or load_corpus(index, collection) != corpus:
            raise ValueError("Corpus changed during evaluation")
    summary = summarize(cases, timings)
    stable = [
        {
            k: (
                {
                    mode: {key: value for key, value in val.items() if key != "latency_ms"}
                    for mode, val in v.items()
                }
                if k == "modes"
                else v
            )
            for k, v in c.items()
        }
        for c in cases
    ]
    report = {
        "schema_version": "1.0",
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": digest(dataset.model_dump()),
        "observed_at": datetime.now(UTC).isoformat(),
        "corpus": {
            "fingerprint": digest(corpus),
            "collection": collection,
            "documents": 8,
            "sections": 32,
            "chunks": 39,
            "snapshot_sha256": dataset.snapshot_sha256,
        },
        "configuration": {
            "embedding": embedding.describe(),
            "reranker": provider.describe(),
            "rrf_k": 60,
            "candidate_k": 10,
            "top_k": 5,
            "cosine_threshold": 0.6,
            "context_chars": 24000,
            "bm25_k1": 1.2,
            "bm25_b": 0.75,
            "repeats": args.repeats,
            "generation_provider": "deterministic",
        },
        "stable_observations_sha256": digest(stable),
        **summary,
        "cases": cases,
        "limitations": [
            "Development corpus, not a clinical or production benchmark.",
            "Agent-authored labels, no independent clinical review; eight reused cases.",
            "MRR@5 truncates unobserved ranks; missing is zero reciprocal rank.",
            "Deterministic provider quotes first eligible evidence; citation match is "
            "not answer correctness.",
            "Wall-clock latency and timestamps vary; comparisons assert stable scores "
            "and payloads.",
            "No threshold tuning, corpus changes or retrieval algorithm changes.",
        ],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "retrieval_eval_v1.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    )
    (args.output_dir / "retrieval_eval_v1.md").write_text(render_report(report))
    print(
        json.dumps(
            {
                "metrics": summary["metrics"],
                "abstention": summary["abstention"],
                "reranking": summary["reranking"],
                "latency": summary["latency"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
