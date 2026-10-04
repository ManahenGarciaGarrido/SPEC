"""Guarantee: Faro can only read inside the whitelisted folders.

Every way out of a root must be refused: ``..``, absolute paths, symbolic
links, Windows junctions, alternate data streams, device and extended-length
paths, 8.3 short names, and a link swapped between the check and the open.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from faro import safe_fs
from faro.indexing import walker
from faro.safe_fs import (
    CloudPlaceholderError,
    EntryKind,
    FileTooLargeError,
    NotARegularFileError,
    OutsideRootError,
    UnsafePathError,
)
from tests.guarantees.conftest import Layout, symlink_or_skip


def test_reads_inside_the_root(layout: Layout) -> None:
    assert layout.fs.read_file(str(layout.root / "inside.txt"), max_bytes=100) == b"inside"
    root, _ = layout.fs.locate_in_root(layout.root_id, "sub/deep.txt")
    assert root.id == layout.root_id


def test_rejects_dot_dot(layout: Layout) -> None:
    sneaky = str(layout.root / ".." / "outside" / "secret.txt")
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(sneaky, max_bytes=100)
    with pytest.raises(OutsideRootError):
        layout.fs.locate_in_root(layout.root_id, "../outside/secret.txt")
    with pytest.raises(OutsideRootError):
        layout.fs.locate_in_root(layout.root_id, "sub/../../outside/secret.txt")


def test_rejects_absolute_paths_outside(layout: Layout) -> None:
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(str(layout.outside / "secret.txt"), max_bytes=100)
    with pytest.raises(OutsideRootError):
        layout.fs.list_dir(str(layout.outside))


def test_rejects_relative_and_nul_paths(layout: Layout) -> None:
    with pytest.raises(UnsafePathError):
        layout.fs.read_file("inside.txt", max_bytes=100)
    with pytest.raises(UnsafePathError):
        layout.fs.read_file(str(layout.root / "inside.txt") + "\x00.png", max_bytes=100)


def test_root_prefix_is_not_enough(layout: Layout, tmp_path: Path) -> None:
    """``/x/root-evil`` starts with ``/x/root`` but is not inside it."""
    sibling = tmp_path / "root-evil"
    sibling.mkdir()
    (sibling / "f.txt").write_text("evil")
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(str(sibling / "f.txt"), max_bytes=100)


def test_unknown_root_and_blocked_counter(layout: Layout) -> None:
    before = layout.fs.blocked_attempts
    with pytest.raises(OutsideRootError):
        layout.fs.locate_in_root("ffffffffffff", "inside.txt")
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(str(layout.outside / "secret.txt"), max_bytes=100)
    assert layout.fs.blocked_attempts == before + 1


def test_refuses_directories_and_large_files(layout: Layout) -> None:
    with pytest.raises(NotARegularFileError):
        layout.fs.read_file(str(layout.root / "sub"), max_bytes=100)
    with pytest.raises(FileTooLargeError):
        layout.fs.read_file(str(layout.root / "inside.txt"), max_bytes=3)


def test_never_reads_cloud_placeholders(layout: Layout, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safe_fs, "is_placeholder", lambda _st: True)
    with pytest.raises(CloudPlaceholderError):
        layout.fs.read_file(str(layout.root / "inside.txt"), max_bytes=100)
    assert all(entry.placeholder for entry in layout.fs.list_dir(str(layout.root)))


def test_placeholder_attributes_are_detected() -> None:
    class FakeStat:
        st_file_attributes = safe_fs.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS

    assert safe_fs.is_placeholder(FakeStat())  # type: ignore[arg-type]
    FakeStat.st_file_attributes = 0x20  # FILE_ATTRIBUTE_ARCHIVE
    assert not safe_fs.is_placeholder(FakeStat())  # type: ignore[arg-type]


def test_final_path_outside_the_root_is_refused(
    layout: Layout, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a link is swapped between the check and the open, the handle's real path wins."""
    escaped = str(layout.outside / "secret.txt")
    if sys.platform == "win32":
        from faro.safe_fs import _windows

        monkeypatch.setattr(_windows, "read_file", lambda _real, _max: (b"secret", escaped))
    else:
        monkeypatch.setattr(safe_fs, "_read_posix", lambda _real, _max: (b"secret", escaped))
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(str(layout.root / "inside.txt"), max_bytes=100)


# --- Symbolic links (POSIX, and Windows with the privilege) -------------------------


def test_symlink_to_outside_file_is_refused(layout: Layout) -> None:
    link = layout.root / "link.txt"
    symlink_or_skip(layout.outside / "secret.txt", link)
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(str(link), max_bytes=100)
    kinds = {entry.name: entry.kind for entry in layout.fs.list_dir(str(layout.root))}
    assert kinds["link.txt"] is EntryKind.LINK


def test_symlinked_directory_to_outside_is_refused(layout: Layout) -> None:
    link = layout.root / "linkdir"
    symlink_or_skip(layout.outside, link, directory=True)
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(str(link / "secret.txt"), max_bytes=100)
    with pytest.raises(OutsideRootError):
        layout.fs.list_dir(str(link))
    walked = {
        c.rel_path for c in walker.walk_root(layout.fs, layout.fs.roots[0], max_file_bytes=10)
    }
    assert not any(path.startswith("linkdir") for path in walked)


def test_symlink_inside_the_root_is_readable(layout: Layout) -> None:
    link = layout.root / "alias.txt"
    symlink_or_skip(layout.root / "inside.txt", link)
    assert layout.fs.read_file(str(link), max_bytes=100) == b"inside"
