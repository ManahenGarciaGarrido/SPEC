"""Pure path helpers (string manipulation only, never touch the filesystem)."""

from __future__ import annotations

import hashlib
import os
import posixpath


def normalize(path: str) -> str:
    """Normalize separators, redundant parts and case (on case-insensitive systems)."""
    return os.path.normcase(os.path.normpath(path))


def is_within(path: str, root: str) -> bool:
    """Return True when ``path`` is ``root`` itself or lies below it.

    Both arguments must already be canonical (real) absolute paths; this is a
    lexical comparison and does not resolve links.
    """
    p = normalize(path)
    r = normalize(root)
    try:
        return os.path.commonpath([p, r]) == r
    except ValueError:
        # Different drives on Windows, or a mix of absolute and relative paths.
        return False


def to_posix_relative(path: str, root: str) -> str:
    """Relative path from ``root`` to ``path`` using forward slashes."""
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/") if os.sep != "/" else rel


def join_posix_relative(root: str, rel_path: str) -> str:
    """Join a forward-slash relative path onto a native root path (lexically)."""
    parts = [p for p in posixpath.normpath(rel_path).split("/") if p not in ("", ".")]
    return os.path.join(root, *parts) if parts else root


def stable_id(*parts: str, length: int = 16) -> str:
    """Short, stable hexadecimal identifier derived from the given strings."""
    digest = hashlib.blake2b("\0".join(parts).encode("utf-8"), digest_size=16).hexdigest()
    return digest[:length]
