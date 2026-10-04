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
        vectors = list(self._model.embed(list(texts), batch_size=self._batch_size))
        return np.asarray(np.stack(vectors), dtype=np.float32)

    def embed_query(self, text: str) -> Vector:
        vectors = list(self._model.embed([self._spec.query_prefix + text]))
        return np.asarray(vectors[0], dtype=np.float32)


def default_threads() -> int:
    """Leave half of the cores free: the language model needs them too."""
    return max(1, (os.cpu_count() or 2) // 2)


def load(datadir: DataDir, key: str, *, threads: int | None = None) -> FastEmbedEmbedder:
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
    )
