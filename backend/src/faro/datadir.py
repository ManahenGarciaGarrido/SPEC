"""Faro's own data directory: the only place where the application writes.

Every file Faro creates (configuration, index, manifest, downloaded models,
logs) lives below this directory. Paths are checked for containment before
any write, so a bug elsewhere cannot make Faro write into the user's folders.
This module and ``faro.safe_fs`` are the only modules allowed to touch the
filesystem; ``tests/guarantees/test_static_boundaries.py`` enforces it.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any

import platformdirs

from faro import pathutil

if TYPE_CHECKING:
    import lancedb

APP_IDENTIFIER = "com.manahengarcia.faro"
ENV_DATA_DIR = "FARO_DATA_DIR"


class DataDirError(Exception):
    """A path escaped the data directory or the directory is unusable."""


def default_data_dir() -> Path:
    """Data directory used when none is given explicitly.

    ``%LOCALAPPDATA%\\com.manahengarcia.faro`` on Windows (the same directory the
    Tauri shell uses), ``~/.local/share/com.manahengarcia.faro`` on Linux.
    ``FARO_DATA_DIR`` overrides it.
    """
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir(APP_IDENTIFIER, appauthor=False, roaming=False))


class DataDir:
    """Contained access to the application's data directory."""

    def __init__(self, root: Path | str) -> None:
        absolute = os.path.abspath(os.fspath(root))
        try:
            os.makedirs(absolute, exist_ok=True)
        except OSError as exc:
            raise DataDirError(f"Cannot create the data directory {absolute}: {exc}") from exc
        self._root = os.path.realpath(absolute)

    @property
    def root(self) -> Path:
        return Path(self._root)

    def path(self, *parts: str) -> Path:
        """Absolute path below the data directory; raises if it would escape it."""
        candidate = os.path.realpath(os.path.join(self._root, *parts))
        if not pathutil.is_within(candidate, self._root):
            raise DataDirError(f"Path escapes the data directory: {os.path.join(*parts)}")
        return Path(candidate)

    def contains(self, path: str) -> bool:
        """True when ``path`` (already canonical) is the data directory or below it."""
        return pathutil.is_within(path, self._root)

    def ensure_dir(self, *parts: str) -> Path:
        target = self.path(*parts)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def file_size(self, *parts: str) -> int | None:
        target = self.path(*parts)
        return target.stat().st_size if target.is_file() else None

    def load_text(self, *parts: str) -> str | None:
        target = self.path(*parts)
        if not target.is_file():
            return None
        return target.read_text(encoding="utf-8")

    def load_json(self, *parts: str) -> Any:
        text = self.load_text(*parts)
        return None if text is None else json.loads(text)

    def write_text_atomic(self, text: str, *parts: str) -> None:
        with self.atomic_writer(*parts) as handle:
            handle.write(text.encode("utf-8"))

    def write_json_atomic(self, data: Any, *parts: str) -> None:
        self.write_text_atomic(json.dumps(data, indent=2, ensure_ascii=False) + "\n", *parts)

    @contextlib.contextmanager
    def atomic_writer(self, *parts: str) -> Iterator[IO[bytes]]:
        """Write to a temporary file and move it into place only on success."""
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as handle:
                yield handle
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, target)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp_name)
            raise

    def sha256(self, *parts: str) -> str:
        import hashlib

        digest = hashlib.sha256()
        with self.path(*parts).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def remove_tree(self, *parts: str) -> None:
        """Delete a directory below the data directory (never the directory itself)."""
        if not parts:
            raise DataDirError("Refusing to delete the whole data directory")
        target = self.path(*parts)
        if target.exists():
            shutil.rmtree(target)

    def connect_sqlite(self, *parts: str) -> sqlite3.Connection:
        target = self.path(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target, isolation_level=None, check_same_thread=False)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def connect_lancedb(self, *parts: str) -> lancedb.DBConnection:
        import lancedb

        target = self.ensure_dir(*parts)
        return lancedb.connect(target)
