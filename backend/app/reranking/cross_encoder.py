from dataclasses import dataclass
from importlib.metadata import version
from typing import Protocol

import numpy as np

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L6-v2"
MODEL_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


class RerankQueryError(ValueError):
    pass


@dataclass(frozen=True)
class PassageScore:
    score: float
    window_count: int
    token_start: int
    token_end: int


class Reranker(Protocol):
    def describe(self) -> dict: ...
    def score(self, query: str, passages: list[str]) -> list[PassageScore]: ...


def token_windows(length: int, capacity: int, overlap: int):
    if length < 1 or not 0 <= overlap < capacity:
        raise ValueError("Invalid window dimensions")
    start = 0
    while start < length:
        end = min(start + capacity, length)
        yield start, end
        if end == length:
            break
        start = end - overlap


class MiniLMCrossEncoder:
    def __init__(self, cache: str = ".cache/models", offline: bool = True):
        import torch
        from sentence_transformers import CrossEncoder

        torch.set_num_threads(2)
        self.encoder = CrossEncoder(
            MODEL_NAME,
            revision=MODEL_REVISION,
            device="cpu",
            max_length=512,
            cache_folder=cache,
            local_files_only=offline,
            trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        self.encoder.model.eval()
        self.tokenizer = self.encoder.tokenizer
        self.max_length, self.query_limit, self.overlap, self.batch_size = 512, 128, 64, 8

    def describe(self) -> dict:
        return {
            "model": MODEL_NAME,
            "revision": MODEL_REVISION,
            "device": "cpu",
            "max_pair_tokens": self.max_length,
            "max_query_tokens": self.query_limit,
            "window_overlap": self.overlap,
            "batch_size": self.batch_size,
            "input": "query paired with title + newline + section + newline + text",
            "aggregation": "maximum_raw_window_logit_v1",
            "score_type": "raw_logit",
            "packages": {
                name: version(name).removesuffix("+cpu")
                for name in ("sentence-transformers", "transformers", "torch", "numpy")
            },
        }

    def score(self, query: str, passages: list[str]) -> list[PassageScore]:
        import torch

        query_ids = self.tokenizer.encode(
            query, add_special_tokens=False, truncation=False, verbose=False
        )
        if not query_ids or len(query_ids) > self.query_limit:
            raise RerankQueryError("Reranking requires 1–128 query tokens")
        if not passages:
            return []
        capacity = (
            self.max_length - len(query_ids) - self.tokenizer.num_special_tokens_to_add(pair=True)
        )
        pairs, traces = [], []
        for owner, passage in enumerate(passages):
            ids = self.tokenizer.encode(
                passage, add_special_tokens=False, truncation=False, verbose=False
            )
            for start, end in token_windows(len(ids), capacity, self.overlap):
                pairs.append(
                    self.tokenizer.prepare_for_model(
                        query_ids, pair_ids=ids[start:end], truncation=False
                    )
                )
                traces.append((owner, start, end))
        scores = []
        with torch.inference_mode():
            for start in range(0, len(pairs), self.batch_size):
                batch = self.tokenizer.pad(
                    pairs[start : start + self.batch_size], padding=True, return_tensors="pt"
                )
                logits = self.encoder.model(**batch).logits.squeeze(-1).cpu().numpy()
                scores.extend(logits.tolist())
        if len(scores) != len(traces) or not np.isfinite(scores).all():
            raise ValueError("Invalid cross-encoder scores")
        results = []
        for owner in range(len(passages)):
            windows = [
                (score, start, end)
                for score, (index, start, end) in zip(scores, traces, strict=True)
                if index == owner
            ]
            score, start, end = max(windows, key=lambda item: item[0])
            results.append(PassageScore(float(score), len(windows), start, end))
        return results
