"""Embedding providers — the engine of semantic search (Section 4).

Two interchangeable backends behind one interface:

* HashingEmbedder (default): a dependency-free character n-gram + token
  hashing vectoriser. Runs anywhere, instantly, offline. It gives genuine
  fuzzy/semantic-ish matching within a language, and — combined with the
  cross-lingual alias expansion baked into each record — bridges scripts for
  the demo without any model download.

* SentenceTransformerEmbedder (production): a local, open-weight multilingual
  model (default `paraphrase-multilingual-MiniLM-L12-v2`) served on our own
  GCP GPU/CPU. Same interface; auto-selected when `sentence-transformers` is
  installed. This is the path the approach plan specifies; the hashing
  backend is the PoC stand-in so nothing blocks a demo.

Both return L2-normalised vectors, so cosine similarity is a dot product.
No per-token billing in either case — the whole point.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_TOKEN = re.compile(r"[\wऀ-ॿ]+", re.UNICODE)


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, text: str) -> list[float]: ...


def _l2_normalise(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    """Dot product of two already-normalised vectors."""
    return sum(x * y for x, y in zip(a, b))


class HashingEmbedder:
    """Feature-hashing embedder over word tokens and char n-grams.

    Deterministic, no training, no dependencies. Char n-grams give partial
    robustness to morphology and spelling; word tokens capture exact terms.
    """

    name = "hashing-ngram-v1"

    def __init__(self, dim: int = 768, ngram_range: tuple[int, int] = (3, 5)) -> None:
        self.dim = dim
        self.ngram_range = ngram_range

    def _hash(self, feature: str) -> tuple[int, float]:
        h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:6], "big") % self.dim
        sign = 1.0 if h[6] & 1 else -1.0  # signed hashing reduces collisions
        return idx, sign

    def _features(self, text: str):
        tokens = _TOKEN.findall(text.lower())
        for tok in tokens:
            yield f"w:{tok}"
            padded = f"^{tok}$"
            lo, hi = self.ngram_range
            for n in range(lo, hi + 1):
                if len(padded) < n:
                    continue
                for i in range(len(padded) - n + 1):
                    yield f"g:{padded[i:i + n]}"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        if text:
            for feat in self._features(text):
                idx, sign = self._hash(feat)
                vec[idx] += sign
        return _l2_normalise(vec)


class FastEmbedEmbedder:
    """Local multilingual embeddings via fastembed (ONNX, no PyTorch).

    The lightest free path to real semantic + cross-lingual retrieval: the
    default model is `paraphrase-multilingual-MiniLM-L12-v2` (~0.22 GB), the
    exact model the approach plan names. Model weights download once from the
    Hugging Face hub (or a mirror / local path set via HF_HOME); after that it
    is fully offline. No per-token cost.
    """

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        from fastembed import TextEmbedding  # lazy import

        self.name = f"fastembed:{model_name.split('/')[-1]}"
        self._model = TextEmbedding(model_name=model_name)
        self.dim = len(next(iter(self._model.embed(["probe"]))))

    def embed(self, text: str) -> list[float]:
        vec = next(iter(self._model.embed([text or ""])))
        return _l2_normalise([float(x) for x in vec])


class SentenceTransformerEmbedder:
    """Local open-weight multilingual embeddings. Production backend."""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2") -> None:
        from sentence_transformers import SentenceTransformer  # lazy import

        self.name = f"st:{model_name}"
        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def embed(self, text: str) -> list[float]:
        vec = self._model.encode(text or "", normalize_embeddings=True)
        return [float(x) for x in vec]


def get_embedder(prefer: str = "auto") -> Embedder:
    """Select a backend.

    prefer:
      'auto'                  hashing — instant, free, no download (default)
      'hashing'               force the dependency-free backend
      'fastembed'             local multilingual ONNX model (no torch)
      'sentence-transformers' local multilingual model via sentence-transformers

    Model backends are only used when explicitly requested, so 'auto' never
    triggers a surprise model download; each raises if its library or model
    weights are unavailable.
    """
    if prefer == "fastembed":
        return FastEmbedEmbedder()
    if prefer == "sentence-transformers":
        return SentenceTransformerEmbedder()
    return HashingEmbedder()
