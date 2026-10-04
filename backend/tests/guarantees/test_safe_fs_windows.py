"""Guarantee (Windows): escapes that only exist on Windows are refused.

Junctions, alternate data streams, device and extended-length paths,
administrative shares and 8.3 short names; plus the shared read-only handle
that lets editors rename a file while Faro reads it.

Collected only on Windows (see ``collect_ignore`` in conftest.py); the CI runs
it on a Windows runner, where mypy also type-checks it.
"""

from __future__ import annotations

import os
import sys

assert sys.platform == "win32"

import pytest  # noqa: E402

from faro.indexing import walker  # noqa: E402
from faro.safe_fs import EntryKind, OutsideRootError, SafeFSError, UnsafePathError  # noqa: E402
from tests.guarantees.conftest import Layout  # noqa: E402


@pytest.mark.windows_only
def test_junction_to_outside_is_refused(layout: Layout) -> None:
    import _winapi

    junction = layout.root / "junction"
    _winapi.CreateJunction(str(layout.outside), str(junction))
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(str(junction / "secret.txt"), max_bytes=100)
    with pytest.raises(OutsideRootError):
        layout.fs.list_dir(str(junction))
    kinds = {entry.name: entry.kind for entry in layout.fs.list_dir(str(layout.root))}
    assert kinds["junction"] is EntryKind.LINK
    walked = {
        c.rel_path for c in walker.walk_root(layout.fs, layout.fs.roots[0], max_file_bytes=10)
    }
    assert not any(path.startswith("junction") for path in walked)


@pytest.mark.windows_only
def test_alternate_data_streams_are_refused(layout: Layout) -> None:
    with pytest.raises(UnsafePathError):
        layout.fs.read_file(str(layout.root / "inside.txt") + ":hidden", max_bytes=100)
    with pytest.raises(UnsafePathError):
        layout.fs.read_file(str(layout.root / "inside.txt") + "::$DATA", max_bytes=100)


@pytest.mark.windows_only
def test_device_and_extended_paths(layout: Layout) -> None:
    with pytest.raises(UnsafePathError):
        layout.fs.read_file("\\\\.\\" + str(layout.root / "inside.txt"), max_bytes=100)
    with pytest.raises(OutsideRootError):
        layout.fs.read_file("\\\\?\\" + str(layout.outside / "secret.txt"), max_bytes=100)
    # Reserved device names resolve to devices, never to a file inside the root.
    with pytest.raises(SafeFSError):
        layout.fs.read_file(str(layout.root / "CON"), max_bytes=100)


@pytest.mark.windows_only
def test_administrative_share_to_outside_is_refused(layout: Layout) -> None:
    drive, rest = os.path.splitdrive(str(layout.outside / "secret.txt"))
    unc = f"\\\\localhost\\{drive[0]}$" + rest
    with pytest.raises(SafeFSError):
        layout.fs.read_file(unc, max_bytes=100)


@pytest.mark.windows_only
def test_case_insensitive_paths_inside_are_accepted(layout: Layout) -> None:
    upper = str(layout.root).upper() + "\\INSIDE.TXT"
    assert layout.fs.read_file(upper, max_bytes=100) == b"inside"


@pytest.mark.windows_only
def test_short_names_to_outside_are_refused(layout: Layout) -> None:
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(layout.outside), buffer, 1024)
    short = buffer.value if length else ""
    if not short or short == str(layout.outside):
        pytest.skip("8.3 short names are disabled on this volume")
    with pytest.raises(OutsideRootError):
        layout.fs.read_file(short + "\\secret.txt", max_bytes=100)


@pytest.mark.windows_only
def test_windows_read_reports_the_final_path(layout: Layout) -> None:
    from faro import pathutil
    from faro.safe_fs import _windows

    data, final = _windows.read_file(str(layout.root / "inside.txt"), 100)
    assert data == b"inside"
    assert pathutil.normalize(final) == pathutil.normalize(str(layout.root / "inside.txt"))


@pytest.mark.windows_only
def test_read_handle_lets_editors_rename_the_file(layout: Layout) -> None:
    """While Faro holds a file open, an editor saving via "write temp + rename" must work."""
    from faro.safe_fs import _windows

    target = layout.root / "inside.txt"
    handle = _windows.open_shared(str(target))
    try:
        target.rename(layout.root / "renamed.txt")
    finally:
        _windows.close(handle)
    assert (layout.root / "renamed.txt").read_text() == "inside"


@pytest.mark.windows_only
def test_plain_open_would_block_renaming(layout: Layout) -> None:
    """Negative control: Python's open() lacks FILE_SHARE_DELETE, which is why we avoid it."""
    target = layout.root / "inside.txt"
    with target.open("rb"), pytest.raises(PermissionError):
        target.rename(layout.root / "renamed.txt")
