from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from faro.indexing import languages
from faro.indexing.chunking import (
    Chunk,
    ChunkingConfig,
    chunk_document,
    normalize_newlines,
    split_lines,
)

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_repo"
SMALL = ChunkingConfig(max_chars=400, min_chars=120)
DEFAULT = ChunkingConfig()


def _chunks(rel: str, config: ChunkingConfig = DEFAULT) -> tuple[list[str], list[Chunk]]:
    text = (SAMPLE / rel).read_text(encoding="utf-8")
    info = languages.detect(rel)
    assert info is not None
    return split_lines(normalize_newlines(text)), chunk_document(text, info.name, config)


def _symbol_of(chunks: list[Chunk], needle: str) -> str:
    for chunk in chunks:
        if needle in chunk.text:
            return chunk.symbol
    raise AssertionError(f"{needle!r} not found in any chunk")


ALL_FILES = sorted(
    p.relative_to(SAMPLE).as_posix()
    for p in SAMPLE.rglob("*")
    if p.is_file() and languages.detect(p.name) is not None
)


@pytest.mark.parametrize("rel", ALL_FILES)
@pytest.mark.parametrize("config", [ChunkingConfig(), SMALL], ids=["default", "small"])
def test_chunks_cite_exact_lines_and_cover_the_file(rel: str, config: ChunkingConfig) -> None:
    lines, chunks = _chunks(rel, config)
    assert chunks
    previous_end = 0
    covered: set[int] = set()
    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line <= len(lines)
        assert chunk.start_line > previous_end, "chunks overlap or are out of order"
        assert chunk.text == "\n".join(lines[chunk.start_line - 1 : chunk.end_line])
        covered.update(range(chunk.start_line, chunk.end_line + 1))
        previous_end = chunk.end_line
    missing = [n for n, line in enumerate(lines, start=1) if line.strip() and n not in covered]
    assert not missing, f"lines with content left out of every chunk: {missing}"


def test_dart_method_travels_with_its_doc_comment_and_signature() -> None:
    _lines, chunks = _chunks("lib/auth/auth_repository.dart", SMALL)
    login = next(c for c in chunks if "Future<User> login(" in c.text)
    assert login.symbol == "AuthRepository > login"
    assert "/// Logs the user in" in login.text, "doc comment separated from the method"
    assert "if (!validateEmail(email))" in login.text, "signature separated from its body"
    tail = next(c for c in chunks if "return _currentUser!;" in c.text)
    assert tail.symbol == "AuthRepository > login"
    assert _symbol_of(chunks, "bool validateEmail") == "AuthRepository > validateEmail"


def test_whole_small_file_is_named_after_its_main_definition() -> None:
    _lines, chunks = _chunks("lib/models/user.dart")
    assert len(chunks) == 1
    assert chunks[0].symbol == "User"


@pytest.mark.parametrize(
    ("rel", "needle", "symbol"),
    [
        ("scripts/sync_inventory.py", "def fetch_items", "InventorySync > fetch_items"),
        ("server/src/routes/users.ts", "export async function getUserById", "getUserById"),
        (
            "server/src/services/email_service.js",
            "async function sendWelcomeEmail",
            "sendWelcomeEmail",
        ),
        ("web/src/components/UserCard.tsx", "export function UserCard", "UserCard"),
        ("game/inventory.lua", "function Inventory:addItem", "Inventory:addItem"),
        ("game/combat.luau", "function Combat.computeDamage", "Combat.computeDamage"),
        ("docs/architecture.md", "## Autenticación", "Arquitectura > Autenticación"),
    ],
)
def test_symbols_per_language(rel: str, needle: str, symbol: str) -> None:
    _lines, chunks = _chunks(rel, ChunkingConfig(max_chars=250, min_chars=60))
    assert _symbol_of(chunks, needle).endswith(symbol)


@pytest.mark.parametrize(
    ("rel", "needle", "symbol"),
    [
        ("config/app.yaml", "pool_size", "database"),
        ("config/settings.json", "lowStockThreshold", "inventory"),
    ],
)
def test_data_files_are_named_by_key_when_split(rel: str, needle: str, symbol: str) -> None:
    _lines, chunks = _chunks(rel, ChunkingConfig(max_chars=60, min_chars=10))
    assert _symbol_of(chunks, needle).endswith(symbol)


def test_languages_without_grammar_use_overlapping_line_windows() -> None:
    text = "\n".join(f"line {i} " + "x" * 40 for i in range(1, 41)) + "\n"
    chunks = chunk_document(text, "go", ChunkingConfig(max_chars=400, fallback_overlap_lines=2))
    assert len(chunks) > 3
    assert all(len(c.text) <= 400 for c in chunks)
    assert chunks[1].start_line == chunks[0].end_line - 1, "windows should overlap by 2 lines"
    assert chunks[-1].end_line == 40
    assert all(c.symbol == "" for c in chunks)


def test_line_numbers_match_editors_for_any_newline_style() -> None:
    lf = "def a():\n    return 1\n\n\ndef b():\n    return 2\n"
    crlf = lf.replace("\n", "\r\n")
    cr = lf.replace("\n", "\r")
    expected = [(c.start_line, c.end_line) for c in chunk_document(lf, "python", SMALL)]
    for variant in (crlf, cr):
        assert [
            (c.start_line, c.end_line) for c in chunk_document(variant, "python", SMALL)
        ] == expected


def test_empty_and_blank_files_produce_no_chunks() -> None:
    assert chunk_document("", "python") == []
    assert chunk_document("\n\n   \n", "dart") == []


def test_a_single_huge_line_is_kept_whole() -> None:
    text = "const data = [" + ", ".join(str(i) for i in range(2000)) + "];\n"
    chunks = chunk_document(text, "javascript", SMALL)
    assert len(chunks) == 1
    assert chunks[0].start_line == chunks[0].end_line == 1


def test_deeply_nested_input_does_not_overflow_the_stack() -> None:
    depth = 3000
    text = "[" * depth + "]" * depth + "\n"
    chunks = chunk_document(text, "json", ChunkingConfig(max_chars=100, min_chars=10))
    assert chunks


def test_every_bundled_grammar_loads_without_deprecation_warnings() -> None:
    languages.grammar.cache_clear()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for name in languages.grammar_languages():
            assert languages.grammar(name) is not None


@pytest.mark.parametrize(
    ("path", "language"),
    [
        ("lib/main.dart", "dart"),
        ("src/App.tsx", "tsx"),
        ("src/index.mts", "typescript"),
        ("a/b/script.PY", "python"),
        ("Dockerfile", "dockerfile"),
        ("docker/Dockerfile.prod", "dockerfile"),
        ("lib/l10n/app_es.arb", "json"),
        ("game/x.luau", "luau"),
    ],
)
def test_language_detection(path: str, language: str) -> None:
    info = languages.detect(path)
    assert info is not None and info.name == language


@pytest.mark.parametrize("path", ["logo.png", "app.exe", ".gitignore", "README", "data.bin"])
def test_unsupported_files_are_not_indexed(path: str) -> None:
    assert languages.detect(path) is None
