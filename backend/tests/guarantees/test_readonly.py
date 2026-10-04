"""Guarantee: Faro never creates, modifies or deletes anything in the user's folders.

1. A fingerprint of the folder (names, types, sizes, modification times and
   SHA-256 of every file) is identical before and after the whole flow
   (whitelist, index, search, incremental re-index, read every file, remove).
2. A Python audit hook records every write-mode open and every
   create/delete/rename/chmod made from Python while the flow runs; all of
   them must fall inside Faro's data directory.
"""

from __future__ import annotations

import hashlib
import io
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from faro import cli, pathutil
from faro.context import AppContext
from faro.datadir import DataDir
from tests.fakes import HashEmbedder

_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_MUTATING_EVENTS = {
    "os.remove",
    "os.rename",
    "os.rmdir",
    "os.mkdir",
    "os.chmod",
    "os.chown",
    "os.utime",
    "os.truncate",
    "os.symlink",
    "os.link",
    "shutil.rmtree",
    "shutil.copyfile",
    "shutil.move",
    "sqlite3.connect",
}


class _Recorder:
    def __init__(self) -> None:
        self.active = False
        self.events: list[tuple[str, str]] = []

    def __call__(self, event: str, args: tuple[Any, ...]) -> None:
        if not self.active:
            return
        if event == "open":
            path, mode, flags = args
            writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and mode is None and flags & _WRITE_FLAGS
            )
            if writes and isinstance(path, (str, bytes, os.PathLike)):
                self.events.append((event, os.fsdecode(path)))
        elif event in _MUTATING_EVENTS:
            for arg in args[:2]:
                if isinstance(arg, (str, bytes, os.PathLike)):
                    self.events.append((event, os.fsdecode(arg)))


_RECORDER = _Recorder()
sys.addaudithook(_RECORDER)


def fingerprint(folder: Path) -> dict[str, tuple[int, int, int, str | None]]:
    result: dict[str, tuple[int, int, int, str | None]] = {}
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        for name in [*dirnames, *filenames]:
            full = os.path.join(dirpath, name)
            st = os.lstat(full)
            digest = None
            if stat.S_ISREG(st.st_mode):
                with io.open(full, "rb") as handle:  # noqa: UP020 - explicit read-only
                    digest = hashlib.sha256(handle.read()).hexdigest()
            result[os.path.relpath(full, folder)] = (
                stat.S_IFMT(st.st_mode),
                st.st_size,
                st.st_mtime_ns,
                digest,
            )
    top = os.lstat(folder)
    result["."] = (stat.S_IFMT(top.st_mode), 0, top.st_mtime_ns, None)
    return result


@pytest.fixture
def recorder() -> Iterator[_Recorder]:
    _RECORDER.events.clear()
    _RECORDER.active = True
    try:
        yield _RECORDER
    finally:
        _RECORDER.active = False


def _is_bytecode_cache(path: str) -> bool:
    return "__pycache__" in path or path.endswith(".pyc")


def test_full_flow_never_writes_into_the_user_folder(
    sample_repo: Path, tmp_path: Path, recorder: _Recorder
) -> None:
    data_root = tmp_path / "faro-data"
    embedder = HashEmbedder()

    def run(*argv: str) -> None:
        out = io.StringIO()
        code = cli.main(
            ["--data-dir", str(data_root), *argv],
            embedder_factory=lambda *_: embedder,
            out=out,
            err=io.StringIO(),
        )
        assert code == 0, out.getvalue()

    before = fingerprint(sample_repo)

    run("roots", "add", str(sample_repo))
    run("index")
    run("search", "validar el formato del correo")
    run("search", "getUserById", "--json")
    (sample_repo / "lib" / "auth" / "auth_repository.dart").stat()  # no-op on purpose
    run("index")
    run("status")

    ctx = AppContext.create(DataDir(data_root), lambda *_: embedder)
    fs = ctx.fs()
    for dirpath, _dirs, files in os.walk(sample_repo):
        for name in files:
            path = os.path.join(dirpath, name)
            if os.path.getsize(path) < 1_000_000:
                fs.read_file(path, max_bytes=1_000_000)
    run("roots", "remove", str(sample_repo))
    run("index")

    recorder.active = False
    after = fingerprint(sample_repo)
    assert after == before, "the user folder changed"

    data_real = os.path.realpath(data_root)
    repo_real = str(sample_repo)
    touched_repo = [
        e for e in recorder.events if pathutil.is_within(os.path.realpath(e[1]), repo_real)
    ]
    assert not touched_repo, f"writes inside the user folder: {touched_repo}"
    outside_data = [
        e
        for e in recorder.events
        if not _is_bytecode_cache(e[1])
        and not pathutil.is_within(os.path.realpath(e[1]), data_real)
    ]
    assert not outside_data, f"writes outside the data directory: {outside_data}"
    assert recorder.events, "the audit hook recorded nothing: it is not working"
