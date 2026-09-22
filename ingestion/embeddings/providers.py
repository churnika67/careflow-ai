from typing import Protocol

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


class EmbeddingProvider(Protocol):
    tokenizer: object

    def describe(self) -> dict: ...

    def embed(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedding:
    def __init__(self, cache_dir: str = ".cache/models", local_only: bool = False):
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(2)
        self.model = SentenceTransformer(
            MODEL_NAME,
            revision=MODEL_REVISION,
            cache_folder=cache_dir,
            device="cpu",
            trust_remote_code=False,
            local_files_only=local_only,
        )
        self.model.eval()
        self.tokenizer = self.model.tokenizer
        self.dimension = self.model.get_sentence_embedding_dimension()
        self.window = self.model.max_seq_length - self.tokenizer.num_special_tokens_to_add()

    def describe(self) -> dict:
        from importlib.metadata import version

        return {
            "provider": "sentence-transformers",
            "model": MODEL_NAME,
            "revision": MODEL_REVISION,
            "dimension": self.dimension,
            "device": "cpu",
            "normalization": "l2",
            "document_input": "title + newline + section + newline + evidence_text",
            "query_input": "unmodified_query",
            "long_text_strategy": "token_weighted_window_mean_v1",
            "window_tokens": self.window,
            "window_overlap": 0,
            "max_seq_length": self.model.max_seq_length,
            "packages": {
                # Linux CPU wheels use +cpu; macOS CPU wheels use the release alone.
                name: version(name).removesuffix("+cpu") if name == "torch" else version(name)
                for name in ("sentence-transformers", "transformers", "torch", "numpy")
            },
        }

    def embed(self, texts: list[str]) -> np.ndarray:
        import torch

        windows, owners, weights = [], [], []
        for owner, text in enumerate(texts):
            tokens = self.tokenizer.encode(
                text, add_special_tokens=False, truncation=False, verbose=False
            )
            if not tokens:
                raise ValueError("Cannot embed empty text")
            for start in range(0, len(tokens), self.window):
                ids = tokens[start : start + self.window]
                windows.append(self.tokenizer.prepare_for_model(ids, truncation=False))
                owners.append(owner)
                weights.append(len(ids))
        sums = np.zeros((len(texts), self.dimension), dtype=np.float32)
        # Token IDs go directly to the model; decode/re-encode would change split wordpieces.
        with torch.inference_mode():
            for start in range(0, len(windows), 32):
                features = self.tokenizer.pad(
                    windows[start : start + 32], padding=True, return_tensors="pt"
                )
                if features["input_ids"].shape[1] > self.model.max_seq_length:
                    raise ValueError("Embedding window exceeds model input limit")
                vectors = self.model(features)["sentence_embedding"].cpu().numpy()
                for j, vector in enumerate(vectors, start):
                    sums[owners[j]] += vector * weights[j]
        norms = np.linalg.norm(sums, axis=1, keepdims=True)
        if not np.isfinite(sums).all() or (norms <= 0).any():
            raise ValueError("Invalid embedding values")
        return sums / norms
