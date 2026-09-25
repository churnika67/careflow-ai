import math
from enum import StrEnum
from statistics import median

from pydantic import Field, model_validator

from evaluation.dataset import StrictModel


class FailureCategory(StrEnum):
    """Formalizes only failure categories already produced by this
    codebase's own existing analysis logic (analysis.py's flag strings) —
    not a wishlist. Each value below has a real, currently-observable
    detector; categories requiring labels this project does not have
    (LEXICAL_MISMATCH, SEMANTIC_MISMATCH, UNSUPPORTED_ANSWER, VALIDATOR_MISS,
    UNNECESSARY_REVIEW, MISSED_REVIEW) are deliberately excluded until a
    defensible label source exists for them."""

    NO_RELEVANT_IN_TOP_K = "no_relevant_in_top_k"
    BELOW_EVIDENCE_THRESHOLD = "below_evidence_threshold"
    RERANK_REGRESSION = "rerank_regression"
    INCORRECT_ABSTENTION = "incorrect_abstention"


def first_rank(hits: list[dict], expected: list[str]) -> int | None:
    acceptable = set(expected)
    return next((i for i, h in enumerate(hits, 1) if h["chunk_id"] in acceptable), None)


def retrieval_metrics(ranks: list[int | None]) -> dict:
    if not ranks:
        result: dict = {"count": 0, "MRR@5": None}
        for k in (1, 3, 5):
            result[f"Hit@{k}"] = None
            result[f"Hit@{k}_hits"] = 0
            result[f"Hit@{k}_total"] = 0
        return result
    total = len(ranks)
    result = {"count": total}
    for k in (1, 3, 5):
        hits = sum(r is not None and r <= k for r in ranks)
        result[f"Hit@{k}"] = hits / total
        result[f"Hit@{k}_hits"] = hits
        result[f"Hit@{k}_total"] = total
    result["MRR@5"] = sum(1 / r for r in ranks if r is not None and r <= 5) / total
    return result


def aggregate(cases: list[dict], mode: str) -> dict:
    positives = [c for c in cases if c["answerable"]]
    return {
        "overall": retrieval_metrics([c["modes"][mode]["rank"] for c in positives]),
        "categories": {
            category: retrieval_metrics(
                [c["modes"][mode]["rank"] for c in positives if c["category"] == category]
            )
            for category in sorted({c["category"] for c in cases})
        },
    }


def derived_abstention_rates(entry: dict, positive_cases: int) -> dict:
    """False-answer rate and false-abstention rate, with explicit
    denominators, computed from the same confusion counts the existing
    abstention table already produces (entry: negative_cases,
    incorrect_answer_attempts=FN, positive_abstentions=FP). Both are
    independently computed, not derived from precision/recall, so the two
    framings can be cross-checked against each other. Null when the
    denominator is zero — never a fabricated ratio."""
    negatives = entry["negative_cases"]
    return {
        "false_answer_rate": (
            entry["incorrect_answer_attempts"] / negatives if negatives else None
        ),
        "false_abstention_rate": (
            entry["positive_abstentions"] / positive_cases if positive_cases else None
        ),
    }


def rank_change(before: int | None, after: int | None) -> dict:
    # Missing from the observed top five is censored at six, not a measured rank.
    b, a = before or 6, after or 6
    return {
        "classification": "improved" if a < b else "degraded" if a > b else "unchanged",
        "observed_rank_delta": before - after if before and after else None,
    }


class Latency(StrictModel):
    calls: int = Field(ge=1)
    median_ms: float = Field(ge=0, allow_inf_nan=False)
    p95_ms: float = Field(ge=0, allow_inf_nan=False)
    min_ms: float = Field(ge=0, allow_inf_nan=False)
    max_ms: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered(self):
        if not self.min_ms <= self.median_ms <= self.p95_ms <= self.max_ms:
            raise ValueError("Invalid latency ordering")
        return self


def latency_summary(samples: list[float]) -> dict:
    if not samples or any(not math.isfinite(x) or x < 0 for x in samples):
        raise ValueError("Invalid latency samples")
    values = sorted(samples)
    return Latency(
        calls=len(values),
        median_ms=float(median(values)),
        p95_ms=float(values[math.ceil(0.95 * len(values)) - 1]),
        min_ms=float(values[0]),
        max_ms=float(values[-1]),
    ).model_dump()
