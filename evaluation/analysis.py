from collections import Counter
from statistics import mean

from app.generation.context import build_context, substantive_text

from evaluation.metrics import aggregate, latency_summary

MODES = ("dense", "bm25", "hybrid", "hybrid_reranked")


def eligibility(hits, expected, threshold, context_chars):
    context = build_context(hits, threshold, context_chars)
    supplied = {h["chunk_id"] for h in context.chunks}
    rows = []
    for rank, hit in enumerate(hits, 1):
        score = (
            hit.get("evidence_gate_score") if hit["retrieval_method"] != "dense" else hit["score"]
        )
        rows.append(
            {
                "chunk_id": hit["chunk_id"],
                "rank": rank,
                "expected": hit["chunk_id"] in expected,
                "cosine": score,
                "threshold": threshold,
                "cosine_eligible": score is not None and score >= threshold,
                "substantive": bool(substantive_text(hit)),
                "in_context": hit["chunk_id"] in supplied,
            }
        )
    return {"hits": rows, "context_chunk_ids": [h["chunk_id"] for h in context.chunks]}


def summarize(cases, timings):
    metrics = {mode: aggregate(cases, mode) for mode in MODES}
    negatives = [c for c in cases if not c["answerable"]]
    abstention = {}
    for mode in MODES:
        tp = sum(c["modes"][mode]["abstained"] for c in negatives)
        fp = sum(c["modes"][mode]["abstained"] for c in cases if c["answerable"])
        abstention[mode] = {
            "negative_cases": len(negatives),
            "correct_abstentions": tp,
            "incorrect_answer_attempts": len(negatives) - tp,
            "positive_abstentions": fp,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / len(negatives) if negatives else None,
        }
    changes = [c["reranking_change"] for c in cases if c["answerable"]]
    deltas = [c["observed_rank_delta"] for c in changes if c["observed_rank_delta"] is not None]
    failures = []
    for c in cases:
        ranks = {m: c["modes"][m]["rank"] for m in MODES}
        flags = []
        if c["answerable"]:
            flags += [
                f"{m}: expected absent from top5" for m, rank in ranks.items() if rank is None
            ]
            for a, b in [("bm25", "dense"), ("dense", "bm25")]:
                if ranks[a] is not None and ranks[b] is None:
                    flags.append(f"{a} succeeds where {b} misses top5")
            for a, b in [("bm25", "dense"), ("dense", "bm25")]:
                if ranks[a] == 1 and ranks[b] != 1:
                    flags.append(f"{a} Hit@1 succeeds where {b} does not")
            if any((ranks["hybrid"] or 6) > (ranks[m] or 6) for m in ("dense", "bm25")):
                flags.append("hybrid worse than at least one component")
            if c["reranking_change"]["classification"] == "degraded":
                flags.append("reranker degraded first acceptable rank")
        for mode, result in c["modes"].items():
            if any(
                h["expected"] and not h["cosine_eligible"] for h in result["eligibility"]["hits"]
            ):
                flags.append(f"{mode}: retrieved expected evidence rejected by cosine gate")
            if any(not h["substantive"] and h["rank"] <= 3 for h in result["eligibility"]["hits"]):
                flags.append(f"{mode}: non-substantive evidence in top3")
            if c["answerable"] and not result["abstained"] and not result["cites_expected"]:
                flags.append(f"{mode}: answer cites no expected evidence")
            if not c["answerable"] and result["hits"]:
                flags.append(f"{mode}: negative question retrieves nonanswer evidence")
        if flags:
            failures.append({"case_id": c["case_id"], "query": c["query"], "flags": flags})
    return {
        "metrics": metrics,
        "abstention": abstention,
        "reranking": {
            "counts": dict(Counter(c["classification"] for c in changes)),
            "mean_observed_rank_delta": mean(deltas) if deltas else None,
            "both_found_count": len(deltas),
        },
        "latency": {m: latency_summary(v) for m, v in timings.items()},
        "failures": failures,
    }
