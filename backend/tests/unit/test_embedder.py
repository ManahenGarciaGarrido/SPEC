"""FastEmbedEmbedder batches texts by length but must return vectors in input order."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import numpy as np

from faro.indexing import models
from faro.indexing.embedder import FastEmbedEmbedder


class _EchoModel:
    """Stands in for fastembed: each vector encodes its own text's length."""

    def __init__(self) -> None:
        self.received: list[str] = []

    def embed(self, texts: Sequence[str], batch_size: int = 16) -> Iterator[np.ndarray]:
        self.received = list(texts)
        for text in texts:
            yield np.full(4, float(len(text)), dtype=np.float32)


def _embedder(model: _EchoModel) -> FastEmbedEmbedder:
    embedder = FastEmbedEmbedder.__new__(FastEmbedEmbedder)
    embedder._spec = models.ModelSpec(
        "echo", "echo", "test", 4, "r", "0" * 40, (), "MIT", query_prefix="Q:"
    )
    embedder._batch_size = 2
    embedder._model = model  # type: ignore[assignment]
    return embedder


def test_vectors_come_back_in_input_order_after_length_sorting() -> None:
    model = _EchoModel()
    texts = ["ccc", "a", "bbbbb", "dd"]
    vectors = _embedder(model).embed_documents(texts)
    assert model.received == ["a", "dd", "ccc", "bbbbb"], "texts were not sorted by length"
    assert [float(v[0]) for v in vectors] == [3.0, 1.0, 5.0, 2.0]


def test_queries_get_the_model_prefix() -> None:
    model = _EchoModel()
    vector = _embedder(model).embed_query("hola")
    assert model.received == ["Q:hola"]
    assert float(vector[0]) == len("Q:hola")


def test_empty_input() -> None:
    assert _embedder(_EchoModel()).embed_documents([]).shape == (0, 4)
