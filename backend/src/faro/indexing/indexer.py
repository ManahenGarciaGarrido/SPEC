"""Incremental indexing of the whitelisted roots.

For every file the walker yields:

* same size and modification time as in the manifest -> skipped without reading;
* changed metadata but identical content hash -> only the manifest is updated;
* new or changed content -> chunked, embedded and written (old chunks replaced);
* gone from disk -> its chunks and manifest entry are removed.

If the embedding model, chunker or index schema changes, the index is rebuilt
from scratch, because vectors from different models are not comparable.
Writes for a file always go "delete old chunks, add new chunks, then update the
manifest", so an interrupted run is repaired by the next one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from faro import pathutil
from faro.config import Settings
from faro.indexing import chunking, manifest, store, walker
from faro.indexing.embedder import Embedder
from faro.safe_fs import SafeFS, SafeFSError
from faro.search import tokenize

ORIGIN_CODE = "code"
_BINARY_SNIFF = 8192


@dataclass(frozen=True)
class IndexProgress:
    phase: str  # "scan" | "index" | "finalize"
    root_id: str
    files_processed: int
    current: str | None


@dataclass
class IndexReport:
    files_seen: int = 0
    files_indexed: int = 0
    files_unchanged: int = 0
    files_removed: int = 0
    files_unreadable: int = 0
    chunks_written: int = 0
    full_rebuild: bool = False
    cancelled: bool = False
    walk: walker.WalkStats = field(default_factory=walker.WalkStats)
    errors: list[tuple[str, str]] = field(default_factory=list)
    seconds: float = 0.0


@dataclass
class _PendingFile:
    candidate: walker.FileCandidate
    file_id: str
    content_hash: str
    chunks: list[chunking.Chunk]


def decode_text(data: bytes) -> str | None:
    """Decode a source file, or None if it looks binary or cannot be decoded."""
    if b"\x00" in data[:_BINARY_SNIFF]:
        return None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


# Attention memory grows with the square of the input length, times the batch
# size: one single-line 6 KB HTML file (~3,000 tokens) in a batch of 16 needed
# >10 GB and got the process killed. Only the embedding input is capped; the
# chunk is still stored whole, cited whole and full-text indexed whole. Normal
# chunks (<= 1,800 chars + header) are unaffected; ~2 chars/token worst case.
MAX_EMBEDDING_CHARS = 2000


def embedding_text(rel_path: str, chunk: chunking.Chunk) -> str:
    """What the embedding model sees: location first, then the code (capped)."""
    header = f"{rel_path}\n{chunk.symbol}" if chunk.symbol else rel_path
    return f"{header}\n\n{chunk.text}"[:MAX_EMBEDDING_CHARS]


class Indexer:
    def __init__(
        self,
        *,
        fs: SafeFS,
        settings: Settings,
        chunk_store: store.ChunkStore,
        file_manifest: manifest.Manifest,
        embedder: Embedder,
        skip_dirs: Sequence[str] = (),
        chunking_config: chunking.ChunkingConfig = chunking.DEFAULT_CONFIG,
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
        batch_chunks: int = 64,
    ) -> None:
        self._fs = fs
        self._settings = settings
        self._store = chunk_store
        self._manifest = file_manifest
        self._embedder = embedder
        self._skip_dirs = tuple(skip_dirs)
        self._chunking = chunking_config
        self._progress = progress
        self._cancel = cancel or threading.Event()
        self._batch_chunks = batch_chunks

    def identity(self) -> str:
        return json.dumps(
            {
                "embedding_model": self._embedder.model_id,
                "dim": self._embedder.dim,
                "chunker": chunking.CHUNKER_VERSION,
                "chunking": [self._chunking.max_chars, self._chunking.min_chars],
                "schema": store.SCHEMA_VERSION,
            },
            sort_keys=True,
        )

    def run(self, root_ids: Sequence[str] | None = None, *, full: bool = False) -> IndexReport:
        started = time.monotonic()
        report = IndexReport()
        identity = self.identity()
        if full or self._manifest.get_meta("identity") != identity:
            self._store.drop()
            self._manifest.clear()
            report.full_rebuild = True
        self._manifest.set_meta("identity", identity)

        configured = {root.id for root in self._fs.roots}
        for stale in sorted(self._manifest.root_ids() - configured):
            self._store.delete_root(stale)
            self._manifest.delete_root(stale)

        changed = False
        for root in self._fs.roots:
            if root_ids is not None and root.id not in root_ids:
                continue
            changed |= self._index_root(root.id, report)
            if report.cancelled:
                break
        if changed or report.full_rebuild:
            self._emit("finalize", "", report.files_seen, None)
            self._store.finalize()
        report.seconds = time.monotonic() - started
        return report

    def _emit(self, phase: str, root_id: str, processed: int, current: str | None) -> None:
        if self._progress is not None:
            self._progress(IndexProgress(phase, root_id, processed, current))

    def _index_root(self, root_id: str, report: IndexReport) -> bool:
        root = self._fs.root(root_id)
        known = self._manifest.files_for_root(root_id)
        seen: set[str] = set()
        pending: list[_PendingFile] = []
        pending_chunks = 0
        changed = False

        candidates = walker.walk_root(
            self._fs,
            root,
            max_file_bytes=self._settings.max_file_bytes,
            extra_excludes=self._settings.extra_excludes,
            skip_dirs=self._skip_dirs,
            stats=report.walk,
        )
        for candidate in candidates:
            if self._cancel.is_set():
                report.cancelled = True
                break
            seen.add(candidate.rel_path)
            report.files_seen += 1
            self._emit("index", root_id, report.files_seen, candidate.rel_path)
            record = known.get(candidate.rel_path)
            if (
                record is not None
                and record.size == candidate.size
                and record.mtime_ns == candidate.mtime_ns
            ):
                report.files_unchanged += 1
                continue
            try:
                data = self._fs.read_file(
                    candidate.abs_path, max_bytes=self._settings.max_file_bytes
                )
            except (OSError, SafeFSError) as exc:
                report.errors.append((candidate.rel_path, str(exc)))
                continue
            content_hash = hashlib.sha256(data).hexdigest()
            file_id = pathutil.stable_id(root_id, candidate.rel_path)
            if record is not None and record.content_hash == content_hash:
                self._manifest.upsert([_record(candidate, file_id, content_hash, record)])
                report.files_unchanged += 1
                continue
            text = decode_text(data)
            if text is None:
                self._store.delete_files([file_id])
                self._manifest.upsert(
                    [_record(candidate, file_id, content_hash, None, manifest.STATUS_UNREADABLE)]
                )
                report.files_unreadable += 1
                changed = True
                continue
            chunks = chunking.chunk_document(text, candidate.language, self._chunking)
            pending.append(_PendingFile(candidate, file_id, content_hash, chunks))
            pending_chunks += len(chunks)
            if pending_chunks >= self._batch_chunks:
                self._flush(pending, report)
                pending, pending_chunks, changed = [], 0, True
        if pending:
            self._flush(pending, report)
            changed = True

        if not report.cancelled:
            removed = sorted(set(known) - seen)
            if removed:
                self._store.delete_files(known[rel].file_id for rel in removed)
                self._manifest.delete(root_id, removed)
                report.files_removed += len(removed)
                changed = True
        return changed

    def _flush(self, pending: Sequence[_PendingFile], report: IndexReport) -> None:
        texts = [
            embedding_text(item.candidate.rel_path, chunk)
            for item in pending
            for chunk in item.chunks
        ]
        vectors = self._embedder.embed_documents(texts)
        rows = []
        position = 0
        for item in pending:
            candidate = item.candidate
            for ordinal, chunk in enumerate(item.chunks):
                rows.append(
                    {
                        "id": f"{item.file_id}-{ordinal:05d}",
                        "file_id": item.file_id,
                        "root_id": candidate.root_id,
                        "origin": ORIGIN_CODE,
                        "rel_path": candidate.rel_path,
                        "language": candidate.language,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "symbol": chunk.symbol,
                        "text": chunk.text,
                        "search_text": tokenize.search_text(
                            candidate.rel_path, chunk.symbol, chunk.text
                        ),
                        "vector": vectors[position].tolist(),
                    }
                )
                position += 1
        self._store.delete_files(item.file_id for item in pending)
        self._store.add(rows)
        self._manifest.upsert(
            _record(item.candidate, item.file_id, item.content_hash, None, chunks=len(item.chunks))
            for item in pending
        )
        report.files_indexed += len(pending)
        report.chunks_written += len(rows)


def _record(
    candidate: walker.FileCandidate,
    file_id: str,
    content_hash: str,
    previous: manifest.FileRecord | None,
    status: str = manifest.STATUS_INDEXED,
    *,
    chunks: int | None = None,
) -> manifest.FileRecord:
    return manifest.FileRecord(
        root_id=candidate.root_id,
        rel_path=candidate.rel_path,
        file_id=file_id,
        size=candidate.size,
        mtime_ns=candidate.mtime_ns,
        content_hash=content_hash,
        language=candidate.language,
        chunk_count=chunks if chunks is not None else (previous.chunk_count if previous else 0),
        status=previous.status if previous is not None and chunks is None else status,
        indexed_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    )
