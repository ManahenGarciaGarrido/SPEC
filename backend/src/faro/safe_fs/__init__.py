"""Read-only, whitelisted access to the user's folders.

This is the only module allowed to touch the user's folders, and it only
exposes listing and reading. There is deliberately no write, rename or delete
API. Every path is resolved to its real path (following ``..``, symbolic links
and Windows junctions) and rejected unless it lies inside a whitelisted root.
After a file is opened, the path of the *opened handle* is checked again, so a
link swapped between the check and the open cannot be used to escape.

On Windows, files are opened with ``FILE_SHARE_READ | FILE_SHARE_WRITE |
FILE_SHARE_DELETE`` so that reading never gets in the way of an editor saving
the same file, and cloud placeholders (OneDrive "online-only" files) are never
opened, because reading them would make the sync client download them.
"""

from __future__ import annotations

import enum
import os
import stat
import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass

from faro import pathutil

# Windows file attributes that mark cloud placeholders: opening or reading such
# a file makes the sync provider fetch its content from the network.
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
_PLACEHOLDER_ATTRIBUTES = (
    FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

_IS_WINDOWS = sys.platform == "win32"


class SafeFSError(Exception):
    """Base class for every refusal of ``SafeFS``."""


class OutsideRootError(SafeFSError):
    """The path resolves outside every whitelisted root."""


class UnsafePathError(SafeFSError):
    """The path is malformed or uses a form Faro never reads (devices, streams...)."""


class NotARegularFileError(SafeFSError):
    """The path is not a regular file (directory, device, pipe, link...)."""


class FileTooLargeError(SafeFSError):
    """The file is larger than the requested limit."""


class CloudPlaceholderError(SafeFSError):
    """The file is an online-only cloud placeholder; reading it would download it."""


class EntryKind(enum.StrEnum):
    FILE = "file"
    DIR = "dir"
    LINK = "link"  # symbolic link or junction: never followed while walking
    OTHER = "other"


@dataclass(frozen=True)
class Root:
    id: str
    path: str  # canonical real path


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    kind: EntryKind
    size: int
    mtime_ns: int
    placeholder: bool


def root_id_for(canonical_path: str) -> str:
    """Stable identifier of a root, derived from its canonical path."""
    return pathutil.stable_id(pathutil.normalize(canonical_path), length=12)


def canonical_directory(path: str) -> str:
    """Resolve a directory the user wants to whitelist to its canonical real path."""
    _check_syntax(path)
    if not os.path.isabs(path):
        raise UnsafePathError(f"Root folders must be absolute paths: {path}")
    try:
        real = os.path.realpath(path, strict=True)
    except OSError as exc:
        raise SafeFSError(f"Folder not found: {path}") from exc
    if not os.path.isdir(real):
        raise NotARegularFileError(f"Not a folder: {path}")
    return real


def is_placeholder(st: os.stat_result) -> bool:
    attributes = getattr(st, "st_file_attributes", 0)
    return bool(attributes & _PLACEHOLDER_ATTRIBUTES)


def _check_syntax(path: str) -> None:
    if "\x00" in path:
        raise UnsafePathError("Path contains a NUL character")
    if _IS_WINDOWS:
        if path.startswith(("\\\\.\\", "//./", "\\\\?\\GLOBALROOT", "\\??\\")):
            raise UnsafePathError(f"Device paths are not allowed: {path}")
        _drive, rest = os.path.splitdrive(path.removeprefix("\\\\?\\"))
        if ":" in rest:
            raise UnsafePathError(f"Alternate data streams are not allowed: {path}")


class SafeFS:
    """Read-only access restricted to a whitelist of root folders."""

    def __init__(self, roots: Iterable[Root]) -> None:
        self._roots = tuple(roots)
        self._lock = threading.Lock()
        self._blocked = 0

    @property
    def roots(self) -> tuple[Root, ...]:
        return self._roots

    @property
    def blocked_attempts(self) -> int:
        """Number of refused accesses outside the whitelist (shown in the UI)."""
        with self._lock:
            return self._blocked

    def root(self, root_id: str) -> Root:
        for root in self._roots:
            if root.id == root_id:
                return root
        raise OutsideRootError(f"Unknown root: {root_id}")

    def locate(self, path: str) -> tuple[Root, str]:
        """Resolve ``path`` to its real path and return it with its root."""
        _check_syntax(path)
        if not os.path.isabs(path):
            raise UnsafePathError(f"Only absolute paths are accepted: {path}")
        try:
            real = os.path.realpath(path, strict=True)
        except OSError as exc:
            raise SafeFSError(f"Path not found: {path}") from exc
        return self._root_containing(real), real

    def locate_in_root(self, root_id: str, rel_path: str) -> tuple[Root, str]:
        """Resolve a forward-slash path relative to the given root."""
        root = self.root(root_id)
        return self.locate(pathutil.join_posix_relative(root.path, rel_path))

    def _root_containing(self, real: str) -> Root:
        for root in self._roots:
            if pathutil.is_within(real, root.path):
                return root
        with self._lock:
            self._blocked += 1
        raise OutsideRootError(f"Outside the whitelisted folders: {real}")

    def list_dir(self, path: str) -> list[DirEntry]:
        """List a directory without following links."""
        _root, real = self.locate(path)
        if not os.path.isdir(real):
            raise NotARegularFileError(f"Not a folder: {path}")
        entries: list[DirEntry] = []
        with os.scandir(real) as iterator:
            for entry in iterator:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                entries.append(
                    DirEntry(
                        name=entry.name,
                        path=os.path.join(real, entry.name),
                        kind=_classify(entry),
                        size=st.st_size,
                        mtime_ns=st.st_mtime_ns,
                        placeholder=is_placeholder(st),
                    )
                )
        entries.sort(key=lambda e: e.name)
        return entries

    def read_file(self, path: str, *, max_bytes: int) -> bytes:
        """Read a whole regular file (at most ``max_bytes``) in read-only mode."""
        root, real = self.locate(path)
        st = os.stat(real)
        if not stat.S_ISREG(st.st_mode):
            raise NotARegularFileError(f"Not a regular file: {path}")
        if is_placeholder(st):
            raise CloudPlaceholderError(f"Online-only cloud file, not read: {path}")
        if st.st_size > max_bytes:
            raise FileTooLargeError(f"{path} is {st.st_size} bytes (limit {max_bytes})")
        final_path: str | None
        if sys.platform == "win32":
            from faro.safe_fs import _windows

            data, final_path = _windows.read_file(real, max_bytes)
        else:
            data, final_path = _read_posix(real, max_bytes)
        if final_path is not None and not pathutil.is_within(final_path, root.path):
            with self._lock:
                self._blocked += 1
            raise OutsideRootError(f"The opened file is outside its root: {final_path}")
        if len(data) > max_bytes:
            raise FileTooLargeError(f"{path} grew beyond {max_bytes} bytes while reading")
        return data


def _classify(entry: os.DirEntry[str]) -> EntryKind:
    if entry.is_symlink() or entry.is_junction():
        return EntryKind.LINK
    if entry.is_dir(follow_symlinks=False):
        return EntryKind.DIR
    if entry.is_file(follow_symlinks=False):
        return EntryKind.FILE
    return EntryKind.OTHER


def _read_posix(real: str, max_bytes: int) -> tuple[bytes, str | None]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = os.open(real, flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise NotARegularFileError(f"Not a regular file: {real}")
        final_path = _final_path_posix(fd, real, st)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            block = os.read(fd, min(remaining, 1024 * 1024))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks), final_path
    finally:
        os.close(fd)


def _final_path_posix(fd: int, real: str, opened: os.stat_result) -> str | None:
    proc_link = f"/proc/self/fd/{fd}"
    if os.path.exists(proc_link):
        return os.readlink(proc_link)
    # Without /proc, make sure the handle is the file that was checked.
    try:
        checked = os.stat(real, follow_symlinks=False)
    except OSError as exc:
        raise OutsideRootError(f"The file changed while opening it: {real}") from exc
    if (checked.st_dev, checked.st_ino) != (opened.st_dev, opened.st_ino):
        raise OutsideRootError(f"The file changed while opening it: {real}")
    return None
