"""Fixtures shared by the guarantee tests."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from faro import safe_fs
from faro.safe_fs import Root, SafeFS


@dataclass
class Layout:
    fs: SafeFS
    root: Path
    outside: Path

    @property
    def root_id(self) -> str:
        return self.fs.roots[0].id


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "inside.txt").write_text("inside")
    (root / "sub" / "deep.txt").write_text("deep")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    real_root = os.path.realpath(root)
    fs = SafeFS([Root(safe_fs.root_id_for(real_root), real_root)])
    return Layout(fs, Path(real_root), Path(os.path.realpath(outside)))


def symlink_or_skip(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except OSError as exc:  # Windows without Developer Mode or admin rights
        pytest.skip(f"cannot create symbolic links here: {exc}")
