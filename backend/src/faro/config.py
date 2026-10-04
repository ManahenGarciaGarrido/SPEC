"""User settings stored in the data directory: whitelisted roots and options."""

from __future__ import annotations

import datetime as dt
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from faro import pathutil, safe_fs
from faro.datadir import DataDir

CONFIG_FILE = "config.json"
CONFIG_VERSION = 1
DEFAULT_EMBEDDING_MODEL = "qwen3-0.6b-int8"  # docs/benchmarks/2026-10-04-embeddings.md


class ConfigError(Exception):
    """Invalid configuration change (for example, overlapping roots)."""


@dataclass(frozen=True)
class RootEntry:
    id: str
    path: str
    added_at: str


@dataclass(frozen=True)
class Settings:
    roots: tuple[RootEntry, ...] = ()
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    max_file_bytes: int = 1024 * 1024
    extra_excludes: tuple[str, ...] = field(default_factory=tuple)

    def safe_roots(self) -> list[safe_fs.Root]:
        return [safe_fs.Root(id=r.id, path=r.path) for r in self.roots]

    def find_root(self, key: str) -> RootEntry | None:
        """Find a root by id or by (canonical) path."""
        for root in self.roots:
            if root.id == key or pathutil.normalize(root.path) == pathutil.normalize(key):
                return root
        return None


def load(datadir: DataDir) -> Settings:
    raw = datadir.load_json(CONFIG_FILE)
    if raw is None:
        return Settings()
    if not isinstance(raw, dict) or raw.get("version") != CONFIG_VERSION:
        raise ConfigError(f"Unsupported configuration file: {datadir.path(CONFIG_FILE)}")
    return Settings(
        roots=tuple(RootEntry(**r) for r in raw.get("roots", [])),
        embedding_model=str(raw.get("embedding_model", DEFAULT_EMBEDDING_MODEL)),
        max_file_bytes=int(raw.get("max_file_bytes", Settings.max_file_bytes)),
        extra_excludes=tuple(raw.get("extra_excludes", ())),
    )


def save(datadir: DataDir, settings: Settings) -> None:
    data: dict[str, Any] = {"version": CONFIG_VERSION, **asdict(settings)}
    datadir.write_json_atomic(data, CONFIG_FILE)


def add_root(datadir: DataDir, settings: Settings, path: str) -> tuple[Settings, RootEntry]:
    """Whitelist a folder. Rejects overlaps and folders inside the data directory."""
    canonical = safe_fs.canonical_directory(path)
    if datadir.contains(canonical):
        raise ConfigError("That folder is inside Faro's own data directory")
    for existing in settings.roots:
        if pathutil.normalize(existing.path) == pathutil.normalize(canonical):
            return settings, existing
        if pathutil.is_within(canonical, existing.path):
            raise ConfigError(f"Already covered by the whitelisted folder {existing.path}")
        if pathutil.is_within(existing.path, canonical):
            raise ConfigError(f"Contains the whitelisted folder {existing.path}; remove it first")
    entry = RootEntry(
        id=safe_fs.root_id_for(canonical),
        path=canonical,
        added_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    )
    return replace(settings, roots=(*settings.roots, entry)), entry


def remove_root(settings: Settings, key: str) -> tuple[Settings, RootEntry]:
    entry = settings.find_root(key)
    if entry is None:
        raise ConfigError(f"No whitelisted folder matches {key!r}")
    return replace(settings, roots=tuple(r for r in settings.roots if r.id != entry.id)), entry
