from __future__ import annotations

import os
import threading
from pathlib import Path

import pytest

from faro import config
from faro.context import AppContext
from faro.indexing import indexer as indexer_module
from faro.indexing.indexer import decode_text
from faro.search import tokenize
from faro.search.hybrid import reciprocal_rank_fusion
from tests.fakes import HashEmbedder


def _whitelist(app: AppContext, *folders: Path) -> None:
    settings = app.settings
    for folder in folders:
        settings, _ = config.add_root(app.datadir, settings, str(folder))
    app.save_settings(settings)


def _paths(app: AppContext, query: str, **kwargs: object) -> list[str]:
    return [hit.rel_path for hit in app.search(query, **kwargs)]  # type: ignore[arg-type]


def test_first_run_indexes_and_second_run_reads_nothing(
    app: AppContext, sample_repo: Path, embedder: HashEmbedder
) -> None:
    _whitelist(app, sample_repo)
    first = app.indexer().run()
    assert first.files_indexed == 12
    assert first.chunks_written >= 12
    assert first.full_rebuild
    embedded = embedder.documents_embedded

    second = app.indexer().run()
    assert second.files_indexed == 0
    assert second.files_unchanged == 12
    assert not second.full_rebuild
    assert embedder.documents_embedded == embedded, "unchanged files were embedded again"


def test_incremental_changes(app: AppContext, sample_repo: Path, embedder: HashEmbedder) -> None:
    _whitelist(app, sample_repo)
    app.indexer().run()

    target = sample_repo / "scripts" / "sync_inventory.py"
    target.write_text(target.read_text() + "\n\ndef reorder_supplier():\n    return 'acme'\n")
    (sample_repo / "game" / "inventory.lua").unlink()
    touched = sample_repo / "config" / "app.yaml"
    os.utime(touched, ns=(touched.stat().st_atime_ns, touched.stat().st_mtime_ns + 10**9))

    report = app.indexer().run()
    assert report.files_indexed == 1  # only the edited file
    assert report.files_removed == 1
    assert report.files_unchanged == 10  # the touched file kept its content hash
    assert "scripts/sync_inventory.py" in _paths(app, "reorder_supplier")
    assert "game/inventory.lua" not in _paths(app, "Inventory addItem capacity", limit=20)


def test_changing_the_embedding_model_rebuilds_everything(
    datadir: object, sample_repo: Path
) -> None:
    from faro.datadir import DataDir

    assert isinstance(datadir, DataDir)
    first = AppContext.create(datadir, lambda _d, _k: HashEmbedder(model_id="model-a"))
    _whitelist(first, sample_repo)
    first.indexer().run()
    second = AppContext.create(datadir, lambda _d, _k: HashEmbedder(model_id="model-b"))
    report = second.indexer().run()
    assert report.full_rebuild
    assert report.files_indexed == 12


def test_unreadable_files_are_remembered_not_retried(app: AppContext, sample_repo: Path) -> None:
    (sample_repo / "lib" / "blob.dart").write_bytes(b"\x00\x01binary\x00" * 10)
    _whitelist(app, sample_repo)
    first = app.indexer().run()
    assert first.files_unreadable == 1
    second = app.indexer().run()
    assert second.files_unreadable == 0
    assert second.files_unchanged == 13


def test_cancelling_stops_early_and_keeps_existing_entries(
    app: AppContext, sample_repo: Path
) -> None:
    _whitelist(app, sample_repo)
    app.indexer().run()
    cancel = threading.Event()
    cancel.set()
    report = app.indexer(cancel=cancel).run()
    assert report.cancelled
    assert report.files_removed == 0
    assert _paths(app, "getUserById")


def test_removed_root_disappears_from_results_at_once(
    app: AppContext, sample_repo: Path, tmp_path: Path
) -> None:
    other = tmp_path / "other_project"
    other.mkdir()
    (other / "billing.py").write_text("def compute_invoice_total(lines):\n    return sum(lines)\n")
    _whitelist(app, sample_repo, other)
    app.indexer().run()
    assert "billing.py" in _paths(app, "compute_invoice_total")

    settings, _ = config.remove_root(app.settings, str(other))
    app.save_settings(settings)
    assert "billing.py" not in _paths(app, "compute_invoice_total")  # before re-indexing
    app.indexer().run()
    assert "billing.py" not in _paths(app, "compute_invoice_total")


def test_hybrid_search_finds_exact_identifiers(app: AppContext, sample_repo: Path) -> None:
    _whitelist(app, sample_repo)
    app.indexer().run()
    hits = app.search("getUserById", limit=3)
    assert hits[0].rel_path == "server/src/routes/users.ts"
    assert hits[0].text_rank == 1
    assert hits[0].text_score is not None and hits[0].text_score > 0
    assert hits[0].vector_distance is not None
    assert hits[0].start_line >= 1 and hits[0].end_line >= hits[0].start_line
    assert app.search("validateEmail", limit=3)[0].rel_path == "lib/auth/auth_repository.dart"
    # Split identifiers also match their words.
    assert "lib/auth/auth_repository.dart" in _paths(app, "validate email", limit=3)


def test_search_filters_and_edge_cases(app: AppContext, sample_repo: Path) -> None:
    _whitelist(app, sample_repo)
    app.indexer().run()
    assert app.search("   ") == []
    assert app.search("getUserById", origin="doc") == []
    assert app.search("getUserById", root_ids=["ffffffffffff"]) == []
    assert app.search("getUserById", origin="code")


def test_search_without_roots_returns_nothing(app: AppContext) -> None:
    assert app.search("anything") == []


def test_reciprocal_rank_fusion() -> None:
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["b", "d"]], k=60)
    assert max(scores, key=lambda item: scores[item]) == "b"
    assert scores["a"] == pytest.approx(1 / 61)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)


@pytest.mark.parametrize(
    ("token", "parts"),
    [
        ("getUserById", ["get", "User", "By", "Id"]),
        ("get_user_by_id", ["get", "user", "by", "id"]),
        ("HTTPServerError", ["HTTP", "Server", "Error"]),
        ("parseJSON2XML", ["parse", "JSON", "2", "XML"]),
        ("validación", ["validación"]),
        ("validaciónDeUsuario", ["validación", "De", "Usuario"]),
        ("ÁrbolBinario", ["Árbol", "Binario"]),
        ("utf8Decoder", ["utf", "8", "Decoder"]),
    ],
)
def test_split_identifier(token: str, parts: list[str]) -> None:
    assert tokenize.split_identifier(token) == parts


def test_text_query_drops_question_words_in_both_languages() -> None:
    query = tokenize.text_query("¿Cómo se calcula el daño de un ataque crítico?")
    assert query.split() == ["calcula", "daño", "ataque", "crítico"]
    assert tokenize.text_query("Where is the user validated?").split() == ["user", "validated"]
    assert tokenize.text_query("¿Dónde está?") == ""


def test_text_query_is_safe_and_expanded() -> None:
    query = tokenize.text_query('¿Dónde "se" valida getUserById? (AND -x)')
    assert '"' not in query and "(" not in query and "?" not in query
    assert "getuserbyid" in query.split() and "user" in query.split()
    assert len(query.split()) == len(set(query.split()))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"print('hola')\n", "print('hola')\n"),
        ("﻿x = 1\n".encode(), "x = 1\n"),
        ("caf\xe9 = 1\n".encode("cp1252"), "café = 1\n"),
        (b"\x00\x01\x02", None),
    ],
)
def test_decode_text(raw: bytes, expected: str | None) -> None:
    assert decode_text(raw) == expected


def test_embedding_text_puts_location_first() -> None:
    from faro.indexing.chunking import Chunk

    text = indexer_module.embedding_text("lib/a.dart", Chunk(1, 2, "code", "A > b"))
    assert text.startswith("lib/a.dart\nA > b\n\n")
