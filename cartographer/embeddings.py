"""CPU code embeddings (ONNX via fastembed) with a pure-numpy fallback.

Default model: jinaai/jina-embeddings-v2-base-code (768-d, trained on code + docstrings,
8k context). Runs on CPU; no GPU required. If the model cannot be loaded (offline,
missing package) we fall back to a hashed bag-of-subtokens projection so the pipeline
still runs end-to-end.
"""

from __future__ import annotations

import hashlib
import logging
import os

import numpy as np

from . import config
from .textutil import code_tokens

log = logging.getLogger(__name__)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


class HashingEmbedder:
    """Deterministic fallback: signed feature hashing of code sub-tokens (+ bigrams)."""

    name = "hashing-1024"
    dim = 1024

    def embed(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = code_tokens(t)
            feats = toks + [a + "_" + b for a, b in zip(toks, toks[1:])]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest()[:8], 16)
                out[i, h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-6)


class FastEmbedder:
    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name, cache_dir=config.MODEL_CACHE)
        self.name = model_name
        self.dim = None

    def embed(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        vecs = np.array(list(self.model.embed(texts, batch_size=config.EMBED_BATCH)), dtype=np.float32)
        self.dim = vecs.shape[1] if len(vecs) else self.dim
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-6)


_EMBEDDER = None


def get_embedder():
    global _EMBEDDER
    if _EMBEDDER is not None:
        return _EMBEDDER
    name = config.EMBED_MODEL
    if name and name.lower() not in ("none", "hashing"):
        try:
            _EMBEDDER = FastEmbedder(name)
            return _EMBEDDER
        except Exception as exc:  # pragma: no cover - depends on environment
            log.warning("Falling back to hashing embedder (%s): %s", name, exc)
    _EMBEDDER = HashingEmbedder()
    return _EMBEDDER
