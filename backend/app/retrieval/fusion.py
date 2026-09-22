import math
from copy import deepcopy

SCORE_FIELDS = {
    "score",
    "dense_score",
    "bm25_score",
    "fusion_score",
    "dense_rank",
    "bm25_rank",
    "fusion_rank",
    "retrieval_method",
    "retrieval_sources",
    "evidence_gate_score",
}


def dense_results(hits: list[dict]) -> list[dict]:
    return [
        hit
        | {
            "dense_score": hit["score"],
            "bm25_score": None,
            "fusion_score": None,
            "dense_rank": rank,
            "bm25_rank": None,
            "retrieval_method": "dense",
            "retrieval_sources": ["dense"],
        }
        for rank, hit in enumerate(hits, 1)
    ]


def reciprocal_rank_fusion(
    dense: list[dict], lexical: list[dict], top_k: int = 5, constant: int = 60
) -> list[dict]:
    if not isinstance(constant, int) or constant <= 0 or not 1 <= top_k <= 20:
        raise ValueError("Invalid RRF constant or top_k")
    merged = {}
    for source, hits in (("dense", dense), ("bm25", lexical)):
        seen = set()
        for rank, hit in enumerate(hits, 1):
            chunk_id = hit["chunk_id"]
            payload = {key: value for key, value in hit.items() if key not in SCORE_FIELDS}
            if chunk_id in merged:
                existing = {
                    key: value for key, value in merged[chunk_id].items() if key not in SCORE_FIELDS
                }
                if existing != payload:
                    raise ValueError("Conflicting provenance for the same chunk ID")
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            score = hit["score"]
            if not math.isfinite(score):
                raise ValueError("Non-finite retrieval score")
            if chunk_id not in merged:
                merged[chunk_id] = deepcopy(payload) | {
                    "dense_score": None,
                    "bm25_score": None,
                    "dense_rank": None,
                    "bm25_rank": None,
                    "fusion_score": 0.0,
                    "retrieval_method": "hybrid",
                    "retrieval_sources": [],
                }
            result = merged[chunk_id]
            result[source + "_score"] = score
            result[source + "_rank"] = rank
            result["retrieval_sources"].append(source)
            result["fusion_score"] += 1 / (constant + rank)
    ranked = sorted(merged.values(), key=lambda hit: (-hit["fusion_score"], hit["chunk_id"]))
    return [
        hit | {"score": hit["fusion_score"], "fusion_rank": rank}
        for rank, hit in enumerate(ranked[:top_k], 1)
    ]
