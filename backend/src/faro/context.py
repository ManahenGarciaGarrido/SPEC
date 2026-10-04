"""Composition root: builds the components from the data directory and settings."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from faro import config
from faro.datadir import DataDir
from faro.indexing import embedder as embedder_module
from faro.indexing.embedder import Embedder
from faro.indexing.indexer import Indexer, IndexProgress
from faro.indexing.manifest import Manifest
from faro.indexing.store import ChunkStore
from faro.safe_fs import SafeFS
from faro.search import hybrid

INDEX_DIR = "index"
STATE_DB = "state.db"

EmbedderFactory = Callable[[DataDir, str], Embedder]


def _load_embedder(datadir: DataDir, key: str) -> Embedder:
    return embedder_module.load(datadir, key)


@dataclass
class AppContext:
    datadir: DataDir
    settings: config.Settings
    embedder_factory: EmbedderFactory = _load_embedder
    _embedder: Embedder | None = field(default=None, init=False)

    @classmethod
    def create(
        cls, datadir: DataDir, embedder_factory: EmbedderFactory | None = None
    ) -> AppContext:
        return cls(datadir, config.load(datadir), embedder_factory or _load_embedder)

    def save_settings(self, settings: config.Settings) -> None:
        config.save(self.datadir, settings)
        self.settings = settings

    def fs(self) -> SafeFS:
        return SafeFS(self.settings.safe_roots())

    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = self.embedder_factory(self.datadir, self.settings.embedding_model)
        return self._embedder

    def manifest(self) -> Manifest:
        return Manifest(self.datadir.connect_sqlite(STATE_DB))

    def store(self) -> ChunkStore:
        return ChunkStore(self.datadir.connect_lancedb(INDEX_DIR), self.embedder().dim)

    def indexer(
        self,
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> Indexer:
        return Indexer(
            fs=self.fs(),
            settings=self.settings,
            chunk_store=self.store(),
            file_manifest=self.manifest(),
            embedder=self.embedder(),
            skip_dirs=[str(self.datadir.root)],
            progress=progress,
            cancel=cancel,
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 8,
        origin: str | None = None,
        root_ids: Sequence[str] | None = None,
    ) -> list[hybrid.SearchHit]:
        # Only whitelisted roots are ever searched: a folder removed from the
        # whitelist disappears from results at once, before the next re-index.
        allowed = {root.id for root in self.settings.roots}
        scope = [r for r in (root_ids or allowed) if r in allowed]
        if not scope:
            return []
        return hybrid.hybrid_search(
            self.store(), self.embedder(), query, limit=limit, origin=origin, root_ids=scope
        )
