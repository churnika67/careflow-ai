import math
from statistics import median

from pydantic import Field, model_validator

from evaluation.dataset import StrictModel


def first_rank(hits: list[dict], expected: list[str]) -> int | None:
    acceptable = set(expected)
    return next((i for i, h in enumerate(hits, 1) if h["chunk_id"] in acceptable), None)


def retrieval_metrics(ranks: list[int | None]) -> dict:
    if not ranks:
        return {"count": 0, "Hit@1": None, "Hit@3": None, "Hit@5": None, "MRR@5": None}
    return {
        "count": len(ranks),
        **{
            f"Hit@{k}": sum(r is not None and r <= k for r in ranks) / len(ranks) for k in (1, 3, 5)
        },
        "MRR@5": sum(1 / r for r in ranks if r is not None and r <= 5) / len(ranks),
    }


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
