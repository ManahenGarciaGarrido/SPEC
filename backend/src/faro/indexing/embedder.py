"""Text embeddings on the CPU (ONNX via fastembed), strictly offline.

The model is always loaded from a local directory with
``local_files_only=True``, and Hugging Face Hub is forced offline with its
telemetry disabled, so loading can never reach the network. fastembed's cache
is pointed at Faro's data directory instead of the system temp folder.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from faro.datadir import DataDir
from faro.indexing import models

Vector = npt.NDArray[np.float32]


class Embedder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dim(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> Vector: ...

    def embed_query(self, text: str) -> Vector: ...


class ModelNotInstalledError(Exception):
    """The embedding model files are not available locally."""


class FastEmbedEmbedder:
    def __init__(
        self,
        spec: models.ModelSpec,
        model_dir: Path,
        cache_dir: Path,
        *,
        threads: int | None = None,
        batch_size: int = 16,
        memory_arena: bool = False,
    ) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        from fastembed import TextEmbedding

        self._spec = spec
        self._batch_size = batch_size
        self._model = TextEmbedding(
            model_name=spec.fastembed_name,
            cache_dir=str(cache_dir),
            threads=threads,
            specific_model_path=str(model_dir),
            local_files_only=True,
            enable_cpu_mem_arena=memory_arena,
        )

    @property
    def model_id(self) -> str:
        return self._spec.model_id

    @property
    def dim(self) -> int:
        return self._spec.dim

    def embed_documents(self, texts: Sequence[str]) -> Vector:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        # Texts are sorted by length (each batch is padded to its longest text)
        # and grouped so that batch_size * tokens^2 stays under a fixed budget:
        # attention memory grows with that product, and long inputs in a full
        # batch made memory peak at several GB. Input order is restored after.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        result = np.empty((len(texts), self.dim), dtype=np.float32)
        for group in batches_by_cost(order, [len(t) for t in texts], self._batch_size):
            vectors = self._model.embed([texts[i] for i in group], batch_size=len(group))
            for index, vector in zip(group, vectors, strict=True):
                result[index] = vector
        return result

    def embed_query(self, text: str) -> Vector:
        vectors = list(self._model.embed([self._spec.query_prefix + text]))
        return np.asarray(vectors[0], dtype=np.float32)


# Budget for batch_size * tokens^2 per batch: 16 texts of 512 tokens.
BATCH_COST_BUDGET = 16 * 512 * 512
CHARS_PER_TOKEN_WORST_CASE = 2.0  # measured: ~2.1 for HTML, 3.4-5.3 for code


def batches_by_cost(
    order: Sequence[int], lengths: Sequence[int], max_batch: int
) -> list[list[int]]:
    """Group indices (already sorted by length) into batches within the cost budget."""
    groups: list[list[int]] = []
    current: list[int] = []
    for index in order:
        tokens = max(1.0, lengths[index] / CHARS_PER_TOKEN_WORST_CASE)
        limit = max(1, min(max_batch, int(BATCH_COST_BUDGET // (tokens * tokens))))
        # Sorted ascending: the newest text is the longest, it sets the padding.
        if current and len(current) + 1 > limit:
            groups.append(current)
            current = []
        current.append(index)
    if current:
        groups.append(current)
    return groups


def default_threads() -> int:
    """Leave half of the cores free: the language model needs them too."""
    return max(1, (os.cpu_count() or 2) // 2)


def load(
    datadir: DataDir, key: str, *, threads: int | None = None, bulk: bool = False
) -> FastEmbedEmbedder:
    """Load the model. ``bulk=True`` is for indexing runs (see below); queries use False.

    onnxruntime's memory arena makes bulk embedding ~1.9x faster but keeps its
    peak (~2 GB measured) allocated for as long as the model lives. Indexing
    uses it and drops the model when done; the long-lived query model does not,
    leaving that RAM to the language model.
    """
    spec = models.get(key)
    if not models.is_installed(datadir, spec):
        raise ModelNotInstalledError(
            f"The embedding model '{key}' is not installed. "
            f"Download it explicitly with: faro models download {key}"
        )
    return FastEmbedEmbedder(
        spec,
        datadir.path(*models.model_parts(spec)),
        datadir.ensure_dir("cache", "fastembed"),
        threads=threads or default_threads(),
        memory_arena=bulk,
    )
