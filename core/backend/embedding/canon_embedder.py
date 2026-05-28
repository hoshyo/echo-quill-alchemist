"""bge-m3 wrapper for Canon / Plot retrieval and dedup.

Lazy singleton: the model is *not* loaded at import time — first `encode()`
call instantiates the SentenceTransformer, which loads from the local HF
cache if available or downloads ~2.3 GB if not.

In the default install flow `scripts/prefetch_models.py` runs after
`install_deps.py --backend`, so by the time anything calls `encode()` the
weights are already on disk and `model()` is a fast cache hit. The download
branch inside `model()` is a resilience fallback for users who skipped the
prefetch gate or whose HF cache was cleared between sessions — it should not
be the routine path.

Why a separate embedder from `DualTowerJudge`'s MiniLM
------------------------------------------------------
MiniLM-L6-v2 is small, English-leaning, and tuned for short symmetric
similarity — perfect for the dual-tower judge that compares candidate truth.
For Chinese-novel canon retrieval we need something better at:
  - Aliases like "黛玉/林姑娘/颦儿" clustering tightly
  - Asymmetric long↔short retrieval (300-char query vs 30-char entity card)
  - Cross-paraphrase recall ("倒计时闪烁" ↔ "数字仍在跳动")
bge-m3 (1024-d, multilingual) handles all three substantially better.
"""
from __future__ import annotations

from typing import List, Optional

import numpy as np

_MODEL_NAME = "BAAI/bge-m3"


class CanonEmbedder:
    _model = None  # SentenceTransformer instance, set on first encode()

    @classmethod
    def model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer
            print(f"[canon_embedder] loading {_MODEL_NAME} (first run downloads ~2.3GB)…")
            cls._model = SentenceTransformer(_MODEL_NAME)
            print("[canon_embedder] ready.")
        return cls._model

    @classmethod
    def encode(cls, texts: List[str]) -> np.ndarray:
        """Return L2-normalized 1024-d float32 embeddings; shape = (len(texts), 1024)."""
        m = cls.model()
        return m.encode(texts, normalize_embeddings=True, convert_to_numpy=True)

    @classmethod
    def encode_one(cls, text: str) -> np.ndarray:
        return cls.encode([text])[0]

    @classmethod
    def is_loaded(cls) -> bool:
        return cls._model is not None


def cosine_top_k(query: np.ndarray, matrix: np.ndarray, k: int) -> List[tuple[int, float]]:
    """Return the top-k (index, cosine) pairs from `matrix` against `query`.

    Both inputs assumed L2-normalized — cosine reduces to a dot product.
    Brute force, fine up to ~10k vectors at 1024 dims (low ms).
    """
    if matrix.size == 0:
        return []
    scores = matrix @ query
    if k >= len(scores):
        idx = np.argsort(-scores)
    else:
        idx = np.argpartition(-scores, k)[:k]
        idx = idx[np.argsort(-scores[idx])]
    return [(int(i), float(scores[i])) for i in idx]
