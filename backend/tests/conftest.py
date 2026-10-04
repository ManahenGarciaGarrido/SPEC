"""Shared fixtures.

The production network guard is installed for the whole session, before any
test runs, and checked around every test: the suite exercises the same
mechanism that protects the application.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from faro.context import AppContext
from faro.datadir import DataDir
from faro.net import guard
from tests.fakes import HashEmbedder

FIXTURES = Path(__file__).parent / "fixtures"

# Windows-only modules start with ``assert sys.platform == "win32"`` (so mypy
# skips them elsewhere); they are not collected on other systems, and the
# report header says so: they are never silently dropped.
WINDOWS_ONLY_MODULES = ["guarantees/test_safe_fs_windows.py"]
collect_ignore = [] if sys.platform == "win32" else WINDOWS_ONLY_MODULES


def pytest_report_header(config: pytest.Config) -> str | None:
    modules = ", ".join(WINDOWS_ONLY_MODULES)
    notice = f"Windows-only modules not collected here (run in the Windows CI): {modules}"
    return None if sys.platform == "win32" else notice


def pytest_configure(config: pytest.Config) -> None:
    guard.install()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "windows_only" in item.keywords and sys.platform != "win32":
            item.add_marker(
                pytest.mark.skip(reason="solo Windows (se ejecuta en el CI de Windows)")
            )
        if "posix_only" in item.keywords and sys.platform == "win32":
            item.add_marker(pytest.mark.skip(reason="solo POSIX (se ejecuta en el CI de Linux)"))


@pytest.fixture(autouse=True)
def _network_guard_in_place() -> Iterator[None]:
    assert guard.is_installed(), "the network guard is not installed"
    yield
    assert guard.is_installed(), "a test removed the network guard"


def make_untracked_files(repo: Path) -> None:
    """Files that cannot live in git (ignored by .gitignore files) but must be skipped."""
    (repo / "node_modules" / "left-pad").mkdir(parents=True)
    (repo / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1;\n")
    (repo / "build").mkdir()
    (repo / "build" / "main.dart.js").write_text("var compiled = true;\n")
    (repo / "generated").mkdir()
    (repo / "generated" / "api.ts").write_text("export const generated = true;\n")
    (repo / "notes_private.md").write_text("# Private\n\nnot for the index\n")
    (repo / ".env").write_text("API_KEY=fake-key-for-tests\n")
    (repo / "server" / "deploy.pem").write_text("-----BEGIN FAKE KEY-----\n")
    (repo / "assets").mkdir()
    (repo / "assets" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00binary")
    (repo / "lib" / "models" / "user.g.dart").write_text("// GENERATED CODE\n")


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """A writable copy of the sample repository (tests may build escape traps in it)."""
    dest = tmp_path / "sample_repo"
    shutil.copytree(FIXTURES / "sample_repo", dest)
    make_untracked_files(dest)
    return Path(os.path.realpath(dest))


@pytest.fixture
def datadir(tmp_path: Path) -> DataDir:
    return DataDir(tmp_path / "faro-data")


@pytest.fixture
def embedder() -> HashEmbedder:
    return HashEmbedder()


@pytest.fixture
def app(datadir: DataDir, embedder: HashEmbedder) -> AppContext:
    return AppContext.create(datadir, lambda *_: embedder)
