"""The vendored Dart grammar matches its provenance record, file by file."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

GRAMMAR = Path(__file__).resolve().parents[2] / "grammars" / "tree-sitter-dart"


def _recorded() -> dict[str, str]:
    text = (GRAMMAR / "PROVENANCE.md").read_text(encoding="utf-8")
    return {
        path: digest
        for digest, path in re.findall(r"^([0-9a-f]{64})  \./(\S+)$", text, flags=re.MULTILINE)
    }


def test_every_vendored_file_matches_its_recorded_hash() -> None:
    recorded = _recorded()
    assert recorded, "PROVENANCE.md lists no hashes"
    present = {
        p.relative_to(GRAMMAR).as_posix()
        for p in GRAMMAR.rglob("*")
        if p.is_file()
        and p.name != "PROVENANCE.md"
        and "__pycache__" not in p.parts
        and not p.name.endswith((".so", ".pyd", ".o", ".obj"))
        and "build" not in p.relative_to(GRAMMAR).parts
        and not any(part.endswith(".egg-info") for part in p.parts)
    }
    assert present == set(recorded), "files added or removed without updating PROVENANCE.md"
    for path, digest in recorded.items():
        actual = hashlib.sha256((GRAMMAR / path).read_bytes()).hexdigest()
        assert actual == digest, f"{path} differs from the vendored upstream copy"
