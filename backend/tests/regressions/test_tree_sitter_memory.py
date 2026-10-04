"""Regression: tree-sitter 0.26.0 corrupts the heap with the Markdown grammar.

Found on 2026-10-04 while building the chunker: walking a Markdown tree with
py-tree-sitter 0.26.0 + tree-sitter-markdown 0.5.1 crashed the interpreter
(segfault) intermittently, and deterministically with ``PYTHONMALLOC=debug``.
0.25.2 does not. The reproduction runs in a subprocess so a crash fails this
test instead of killing the whole run. If this fails after upgrading
tree-sitter, keep the pin in pyproject.toml.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

REPRODUCTION = textwrap.dedent(
    """
    import tree_sitter as ts
    import tree_sitter_markdown as tsm

    md = (
        "# Arquitectura\\n\\nIntro.\\n\\n## Backend\\n\\n" + "Texto del backend. " * 30
        + "\\n\\n### Base de datos\\n\\nUsamos SQLite.\\n\\n## Frontend\\n\\nReact.\\n"
    )
    language = ts.Language(tsm.language())
    lines = md.split("\\n")[:-1]
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)

    def rows(node):
        start, end = node.start_point.row, node.end_point.row
        if node.end_point.column == 0 and end > start:
            end -= 1
        return start, end

    def split(node):
        start, end = rows(node)
        if offsets[end + 1] - offsets[start] <= 400:
            return [(start, end)]
        spans = []
        for child in node.children:
            c_start, c_end = rows(child)
            if offsets[c_end + 1] - offsets[c_start] > 400:
                spans.extend(split(child))
            else:
                spans.append((c_start, c_end))
        return spans

    for _ in range(50):
        split(ts.Parser(language).parse(md.encode()).root_node)
    print("ok")
    """
)


def test_markdown_walk_does_not_corrupt_memory() -> None:
    env = {**os.environ, "PYTHONMALLOC": "debug", "PYTHONFAULTHANDLER": "1"}
    result = subprocess.run(
        [sys.executable, "-c", REPRODUCTION],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0 and result.stdout.strip() == "ok", (
        f"tree-sitter crashed (exit {result.returncode}); keep tree-sitter pinned.\n"
        f"{result.stderr[-2000:]}"
    )
