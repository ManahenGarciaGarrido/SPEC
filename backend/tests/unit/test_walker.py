from __future__ import annotations

import os
from pathlib import Path

import pytest

from faro import safe_fs
from faro.indexing import walker
from faro.safe_fs import Root, SafeFS


def _walk(repo: Path, **kwargs: object) -> tuple[set[str], walker.WalkStats]:
    real = os.path.realpath(repo)
    fs = SafeFS([Root(safe_fs.root_id_for(real), real)])
    stats = walker.WalkStats()
    found = {
        c.rel_path
        for c in walker.walk_root(
            fs,
            fs.roots[0],
            max_file_bytes=kwargs.pop("max_file_bytes", 1_000_000),  # type: ignore[arg-type]
            stats=stats,
            **kwargs,  # type: ignore[arg-type]
        )
    }
    return found, stats


EXPECTED = {
    "lib/auth/auth_repository.dart",
    "lib/screens/login_screen.dart",
    "lib/models/user.dart",
    "server/src/routes/users.ts",
    "server/src/services/email_service.js",
    "web/src/components/UserCard.tsx",
    "scripts/sync_inventory.py",
    "game/inventory.lua",
    "game/combat.luau",
    "docs/architecture.md",
    "config/app.yaml",
    "config/settings.json",
}


def test_walks_exactly_the_indexable_files(sample_repo: Path) -> None:
    found, stats = _walk(sample_repo)
    assert found == EXPECTED
    # node_modules, build, generated/ and notes_private.md (.gitignore), .env,
    # deploy.pem and user.g.dart are excluded; logo.png is unsupported.
    assert stats.ignored >= 7
    assert stats.unsupported >= 1


def test_gitignore_cannot_re_include_secrets(sample_repo: Path) -> None:
    (sample_repo / ".gitignore").write_text("!.env\n!*.pem\n")
    found, _ = _walk(sample_repo)
    assert ".env" not in found
    assert "server/deploy.pem" not in found


def test_nested_gitignore_is_scoped_to_its_directory(sample_repo: Path) -> None:
    (sample_repo / "game" / ".gitignore").write_text("*.lua\n")
    (sample_repo / "lib" / "keep.lua").write_text("return 1\n")
    found, _ = _walk(sample_repo)
    assert "game/inventory.lua" not in found
    assert "game/combat.luau" in found
    assert "lib/keep.lua" in found


def test_gitignore_negation_inside_a_directory(sample_repo: Path) -> None:
    (sample_repo / "game" / ".gitignore").write_text("*.lua*\n!combat.luau\n")
    found, _ = _walk(sample_repo)
    assert "game/inventory.lua" not in found
    assert "game/combat.luau" in found


def test_extra_excludes_from_settings(sample_repo: Path) -> None:
    found, _ = _walk(sample_repo, extra_excludes=["docs/", "*.yaml"])
    assert "docs/architecture.md" not in found
    assert "config/app.yaml" not in found


def test_too_large_files_are_counted_and_skipped(sample_repo: Path) -> None:
    found, stats = _walk(sample_repo, max_file_bytes=1000)
    assert "config/app.yaml" in found
    assert "lib/auth/auth_repository.dart" not in found
    assert stats.too_large > 0


def test_data_directory_inside_a_root_is_never_walked(sample_repo: Path) -> None:
    data = sample_repo / "faro-data"
    data.mkdir()
    (data / "notes.md").write_text("# index internals\n")
    found, _ = _walk(sample_repo, skip_dirs=[os.path.realpath(data)])
    assert not any(path.startswith("faro-data") for path in found)


def test_cloud_placeholders_are_skipped(sample_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original = safe_fs.is_placeholder
    monkeypatch.setattr(
        safe_fs,
        "is_placeholder",
        lambda st: (
            original(st) or st.st_size == (sample_repo / "lib/models/user.dart").stat().st_size
        ),
    )
    found, stats = _walk(sample_repo)
    assert "lib/models/user.dart" not in found
    assert stats.placeholders >= 1


@pytest.mark.posix_only
def test_links_are_never_followed(sample_repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "stolen.py").write_text("SECRET = 1\n")
    os.symlink(outside, sample_repo / "linked_dir")
    os.symlink(sample_repo / "scripts" / "sync_inventory.py", sample_repo / "alias.py")
    found, stats = _walk(sample_repo)
    assert not any(path.startswith("linked_dir") for path in found)
    assert "alias.py" not in found
    assert stats.links == 2


def test_walk_order_is_deterministic(sample_repo: Path) -> None:
    real = os.path.realpath(sample_repo)
    fs = SafeFS([Root("r", real)])
    first = [c.rel_path for c in walker.walk_root(fs, fs.roots[0], max_file_bytes=10**6)]
    second = [c.rel_path for c in walker.walk_root(fs, fs.roots[0], max_file_bytes=10**6)]
    assert first == second
