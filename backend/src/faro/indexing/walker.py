"""Walk whitelisted roots through ``safe_fs`` and pick the files worth indexing.

Respects ``.gitignore`` files at every level, never follows links or
junctions, skips cloud placeholders, oversized files and unsupported types,
and always excludes dependencies, build output and secrets. The hard
exclusions are checked before ``.gitignore``, so a repository cannot
re-include, say, ``.env`` with a negated pattern.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from pathspec import GitIgnoreSpec

from faro import pathutil
from faro.indexing import languages
from faro.safe_fs import EntryKind, Root, SafeFS, SafeFSError

GITIGNORE_MAX_BYTES = 256 * 1024

DEFAULT_EXCLUDES: tuple[str, ...] = (
    # Version control and editors
    ".git",
    ".hg/",
    ".svn/",
    ".idea/",
    ".vs/",
    ".vscode/",
    # Dependencies, environments and caches
    "node_modules/",
    "bower_components/",
    ".pnpm-store/",
    ".yarn/",
    ".dart_tool/",
    ".pub-cache/",
    ".pub/",
    ".fvm/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".tox/",
    "*.egg-info/",
    ".gradle/",
    "Pods/",
    # Build output
    "build/",
    "dist/",
    "out/",
    "target/",
    ".next/",
    ".nuxt/",
    ".svelte-kit/",
    ".turbo/",
    ".cache/",
    ".parcel-cache/",
    "coverage/",
    "DerivedData/",
    "**/flutter/ephemeral/",
    "**/Flutter/ephemeral/",
    # Generated or bulky files
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.g.dart",
    "*.freezed.dart",
    "*.mocks.dart",
    "*.pb.dart",
    "*.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    # Secrets: never indexed
    ".env",
    ".env.*",
    "!.env.example",
    "!.env.sample",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "*.kdbx",
    "key.properties",
)


@dataclass(frozen=True)
class FileCandidate:
    root_id: str
    abs_path: str
    rel_path: str  # forward slashes, relative to the root
    language: str
    size: int
    mtime_ns: int


@dataclass
class WalkStats:
    ignored: int = 0
    links: int = 0
    placeholders: int = 0
    too_large: int = 0
    unsupported: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


class _IgnoreRules:
    """``.gitignore`` files found so far, each scoped to its own directory."""

    def __init__(self, layers: tuple[tuple[str, GitIgnoreSpec], ...] = ()) -> None:
        self._layers = layers

    def with_layer(self, base: str, lines: Sequence[str]) -> _IgnoreRules:
        return _IgnoreRules((*self._layers, (base, GitIgnoreSpec.from_lines(lines))))

    def ignored(self, rel_path: str, is_dir: bool) -> bool:
        result: bool | None = None
        for base, spec in self._layers:
            if base:
                if not rel_path.startswith(base + "/"):
                    continue
                sub = rel_path[len(base) + 1 :]
            else:
                sub = rel_path
            check = spec.check_file(sub + "/" if is_dir else sub)
            if check.include is not None:
                result = check.include
        return bool(result)


def walk_root(
    fs: SafeFS,
    root: Root,
    *,
    max_file_bytes: int,
    extra_excludes: Sequence[str] = (),
    skip_dirs: Sequence[str] = (),
    stats: WalkStats | None = None,
) -> Iterator[FileCandidate]:
    """Yield the indexable files below ``root`` in a deterministic order."""
    stats = stats if stats is not None else WalkStats()
    hard = GitIgnoreSpec.from_lines([*DEFAULT_EXCLUDES, *extra_excludes])
    stack: list[tuple[str, str, _IgnoreRules]] = [(root.path, "", _IgnoreRules())]
    while stack:
        abs_dir, rel_dir, rules = stack.pop()
        try:
            entries = fs.list_dir(abs_dir)
        except (OSError, SafeFSError) as exc:
            stats.errors.append((rel_dir or ".", str(exc)))
            continue
        gitignore = next((e for e in entries if e.name == ".gitignore"), None)
        if gitignore is not None and gitignore.kind is EntryKind.FILE:
            try:
                raw = fs.read_file(gitignore.path, max_bytes=GITIGNORE_MAX_BYTES)
                rules = rules.with_layer(rel_dir, raw.decode("utf-8", "replace").splitlines())
            except (OSError, SafeFSError) as exc:
                stats.errors.append((posixpath.join(rel_dir, ".gitignore"), str(exc)))
        subdirs: list[tuple[str, str, _IgnoreRules]] = []
        for entry in entries:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if entry.kind is EntryKind.LINK:
                stats.links += 1
                continue
            if entry.kind is EntryKind.OTHER:
                stats.unsupported += 1
                continue
            is_dir = entry.kind is EntryKind.DIR
            pattern_path = rel + "/" if is_dir else rel
            if hard.check_file(pattern_path).include or rules.ignored(rel, is_dir):
                stats.ignored += 1
                continue
            if is_dir:
                if any(pathutil.is_within(entry.path, skip) for skip in skip_dirs):
                    stats.ignored += 1
                    continue
                subdirs.append((entry.path, rel, rules))
                continue
            if entry.placeholder:
                stats.placeholders += 1
                continue
            info = languages.detect(rel)
            if info is None:
                stats.unsupported += 1
                continue
            if entry.size > max_file_bytes:
                stats.too_large += 1
                continue
            yield FileCandidate(
                root_id=root.id,
                abs_path=entry.path,
                rel_path=rel,
                language=info.name,
                size=entry.size,
                mtime_ns=entry.mtime_ns,
            )
        stack.extend(reversed(subdirs))
