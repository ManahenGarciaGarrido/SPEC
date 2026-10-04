"""SQLite manifest of indexed files: what makes indexing incremental."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import astuple, dataclass

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    root_id      TEXT    NOT NULL,
    rel_path     TEXT    NOT NULL,
    file_id      TEXT    NOT NULL,
    size         INTEGER NOT NULL,
    mtime_ns     INTEGER NOT NULL,
    content_hash TEXT    NOT NULL,
    language     TEXT    NOT NULL,
    chunk_count  INTEGER NOT NULL,
    status       TEXT    NOT NULL,
    indexed_at   TEXT    NOT NULL,
    PRIMARY KEY (root_id, rel_path)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

STATUS_INDEXED = "indexed"
STATUS_UNREADABLE = "unreadable"  # binary or undecodable: kept so it is not re-read


@dataclass(frozen=True)
class FileRecord:
    root_id: str
    rel_path: str
    file_id: str
    size: int
    mtime_ns: int
    content_hash: str
    language: str
    chunk_count: int
    status: str
    indexed_at: str


class Manifest:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._db = connection
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def files_for_root(self, root_id: str) -> dict[str, FileRecord]:
        rows = self._db.execute(
            "SELECT root_id, rel_path, file_id, size, mtime_ns, content_hash, language,"
            " chunk_count, status, indexed_at FROM files WHERE root_id = ?",
            (root_id,),
        ).fetchall()
        return {row[1]: FileRecord(*row) for row in rows}

    def root_ids(self) -> set[str]:
        return {row[0] for row in self._db.execute("SELECT DISTINCT root_id FROM files")}

    def upsert(self, records: Iterable[FileRecord]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [astuple(r) for r in records],
            )

    def delete(self, root_id: str, rel_paths: Iterable[str]) -> None:
        with self._db:
            self._db.executemany(
                "DELETE FROM files WHERE root_id = ? AND rel_path = ?",
                [(root_id, rel) for rel in rel_paths],
            )

    def delete_root(self, root_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM files WHERE root_id = ?", (root_id,))

    def clear(self) -> None:
        with self._db:
            self._db.execute("DELETE FROM files")
            self._db.execute("DELETE FROM meta")

    def get_meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        with self._db:
            self._db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))

    def totals(self) -> dict[str, int]:
        row = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM files WHERE status = ?",
            (STATUS_INDEXED,),
        ).fetchone()
        return {"files": int(row[0]), "chunks": int(row[1])}
