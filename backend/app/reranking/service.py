import logging
import math
from time import perf_counter

from app.observability.logging import log_event
from app.reranking.cross_encoder import Reranker

logger = logging.getLogger(__name__)


def rerank(query: str, candidates: list[dict], provider: Reranker, top_k: int = 5) -> list[dict]:
    if not 1 <= top_k <= 20 or len(candidates) > 20:
        raise ValueError("Reranking supports at most 20 candidates and results")
    if len({hit["chunk_id"] for hit in candidates}) != len(candidates):
        raise ValueError("Duplicate reranking candidates")
    if not candidates:
        return []
    start = perf_counter()
    scores = provider.score(
        query, [h["title"] + "\n" + h["section"] + "\n" + h["text"] for h in candidates]
    )
    if len(scores) != len(candidates) or any(
        not math.isfinite(s.score)
        or s.window_count < 1
        or s.token_start < 0
        or s.token_end <= s.token_start
        for s in scores
    ):
        raise ValueError("Invalid reranking output")
    identity = provider.describe()
    hits = [
        hit
        | {
            "rerank_score": score.score,
            "candidate_rank": rank,
            "rerank_window_count": score.window_count,
            "rerank_window_token_start": score.token_start,
            "rerank_window_token_end": score.token_end,
            "reranker": identity,
        }
        for rank, (hit, score) in enumerate(zip(candidates, scores, strict=True), 1)
    ]
    hits.sort(key=lambda hit: (-hit["rerank_score"], hit["chunk_id"]))
    result = [hit | {"rerank_rank": rank} for rank, hit in enumerate(hits[:top_k], 1)]
    # No request_id parameter exists on this function's signature -- and
    # none is added, to keep this a mechanical migration. log_event() picks
    # it up automatically from the ambient request-id context (set by
    # RequestContextMiddleware for the enclosing HTTP request), which is
    # exactly the scenario this context mechanism exists for.
    log_event(
        logger,
        "reranking_complete",
        rerank_enabled=True,
        retrieval_modes=sorted({h.get("retrieval_method", "unknown") for h in candidates}),
        candidate_count=len(candidates),
        top_k=top_k,
        model=identity["model"],
        latency_ms=(perf_counter() - start) * 1000,
        final_chunk_ids=[h["chunk_id"] for h in result],
    )
    return result
