"""Test doubles."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np

from faro.indexing.embedder import Vector
from faro.search import tokenize


class HashEmbedder:
    """Deterministic bag-of-words embedder: texts sharing words get similar vectors.

    Good enough to test ranking and plumbing without a real model.
    """

    def __init__(self, dim: int = 128, model_id: str = "hash-test@1") -> None:
        self._dim = dim
        self._model_id = model_id
        self.documents_embedded = 0

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dim(self) -> int:
        return self._dim

    def _vector(self, text: str) -> Vector:
        vector = np.zeros(self._dim, dtype=np.float32)
        for term in tokenize.expand(text):
            digest = hashlib.blake2b(term.lower().encode(), digest_size=4).digest()
            vector[int.from_bytes(digest, "little") % self._dim] += 1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def embed_documents(self, texts: Sequence[str]) -> Vector:
        self.documents_embedded += len(texts)
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self._vector(t) for t in texts])

    def embed_query(self, text: str) -> Vector:
        return self._vector(text)
