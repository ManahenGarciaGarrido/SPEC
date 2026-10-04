from __future__ import annotations

import hashlib
import io
import json
import os
import re
from pathlib import Path

import httpx
import pytest

from faro import cli, config
from faro.datadir import DataDir, DataDirError
from faro.indexing import manifest, models
from faro.indexing.embedder import ModelNotInstalledError, load
from faro.indexing.store import ChunkStore, in_filter, table_exists

# --- DataDir --------------------------------------------------------------------


def test_paths_cannot_escape_the_data_dir(datadir: DataDir) -> None:
    assert datadir.path("index", "x").is_relative_to(datadir.root)
    with pytest.raises(DataDirError):
        datadir.path("..", "outside.txt")
    with pytest.raises(DataDirError):
        datadir.path("/etc/passwd")
    with pytest.raises(DataDirError):
        datadir.remove_tree()


def test_atomic_writes_leave_no_partial_files(datadir: DataDir) -> None:
    datadir.write_json_atomic({"a": 1}, "config.json")
    assert datadir.load_json("config.json") == {"a": 1}
    with pytest.raises(RuntimeError), datadir.atomic_writer("config.json") as handle:
        handle.write(b"{broken")
        raise RuntimeError("interrupted")
    assert datadir.load_json("config.json") == {"a": 1}
    assert not [p for p in datadir.root.iterdir() if p.name.startswith(".tmp-")]


def test_missing_files_and_sizes(datadir: DataDir) -> None:
    assert datadir.load_text("nope.txt") is None
    assert datadir.file_size("nope.txt") is None
    datadir.write_text_atomic("hola", "a.txt")
    assert datadir.file_size("a.txt") == 4
    assert datadir.sha256("a.txt") == hashlib.sha256(b"hola").hexdigest()


# --- Settings and roots -----------------------------------------------------------


def test_roots_are_canonical_and_persisted(datadir: DataDir, sample_repo: Path) -> None:
    messy = str(sample_repo / "lib" / "..")
    settings, entry = config.add_root(datadir, config.Settings(), messy)
    assert entry.path == os.path.realpath(sample_repo)
    config.save(datadir, settings)
    assert config.load(datadir) == settings
    again, same = config.add_root(datadir, settings, str(sample_repo))
    assert same == entry and again == settings
    assert settings.find_root(entry.id) == entry
    assert settings.find_root(str(sample_repo)) == entry


def test_overlapping_roots_are_rejected(datadir: DataDir, sample_repo: Path) -> None:
    settings, _ = config.add_root(datadir, config.Settings(), str(sample_repo / "lib"))
    with pytest.raises(config.ConfigError):
        config.add_root(datadir, settings, str(sample_repo / "lib" / "auth"))
    with pytest.raises(config.ConfigError):
        config.add_root(datadir, settings, str(sample_repo))


def test_data_dir_cannot_be_whitelisted(datadir: DataDir) -> None:
    inner = datadir.ensure_dir("index")
    with pytest.raises(config.ConfigError):
        config.add_root(datadir, config.Settings(), str(inner))


def test_remove_root(datadir: DataDir, sample_repo: Path) -> None:
    settings, entry = config.add_root(datadir, config.Settings(), str(sample_repo))
    settings, removed = config.remove_root(settings, entry.id)
    assert removed == entry and settings.roots == ()
    with pytest.raises(config.ConfigError):
        config.remove_root(settings, entry.id)


def test_unknown_config_version_is_refused(datadir: DataDir) -> None:
    datadir.write_json_atomic({"version": 99}, config.CONFIG_FILE)
    with pytest.raises(config.ConfigError):
        config.load(datadir)


# --- Store and manifest -------------------------------------------------------------


def test_store_rejects_non_hex_ids_in_filters() -> None:
    assert in_filter("file_id", ["ab12"]) == "file_id IN ('ab12')"
    with pytest.raises(ValueError):
        in_filter("file_id", ["x' OR '1'='1"])


def test_empty_store_answers_empty(datadir: DataDir) -> None:
    db = datadir.connect_lancedb("index")
    store = ChunkStore(db, dim=8)
    assert store.count() == 0
    assert store.vector_search([0.0] * 8, 5) == []  # type: ignore[arg-type]
    assert store.text_search("anything", 5) == []
    store.finalize()
    assert not table_exists(db)


def test_manifest_roundtrip(datadir: DataDir) -> None:
    files = manifest.Manifest(datadir.connect_sqlite("state.db"))
    record = manifest.FileRecord(
        "r1", "a.py", "ab", 10, 5, "h", "python", 3, manifest.STATUS_INDEXED, "now"
    )
    files.upsert([record])
    assert files.files_for_root("r1") == {"a.py": record}
    assert files.totals() == {"files": 1, "chunks": 3}
    files.set_meta("identity", "x")
    assert files.get_meta("identity") == "x"
    files.delete("r1", ["a.py"])
    assert files.root_ids() == set()
    files.clear()
    assert files.get_meta("identity") is None
    files.close()


# --- Model registry ------------------------------------------------------------------


def test_registry_is_consistent_with_fastembed() -> None:
    from fastembed import TextEmbedding

    supported = {m["model"]: m for m in TextEmbedding.list_supported_models()}
    for spec in models.REGISTRY.values():
        described = supported[spec.fastembed_name]
        assert described["dim"] == spec.dim, spec.key
        local_paths = [f.local_path for f in spec.files]
        assert described["model_file"] in local_paths, f"{spec.key}: fastembed needs that file"
        assert "tokenizer.json" in local_paths and "tokenizer_config.json" in local_paths
        assert len(set(local_paths)) == len(local_paths)
        assert re.fullmatch(r"[0-9a-f]{40}", spec.revision)
        for file in spec.files:
            assert re.fullmatch(r"[0-9a-f]{64}", file.sha256), (spec.key, file.remote_path)
            assert file.size > 0
    assert config.DEFAULT_EMBEDDING_MODEL in models.REGISTRY


def test_loading_a_missing_model_explains_how_to_download(datadir: DataDir) -> None:
    with pytest.raises(ModelNotInstalledError, match="faro models download"):
        load(datadir, "jina-code-int8")


def test_model_install_downloads_pinned_files(
    datadir: DataDir, monkeypatch: pytest.MonkeyPatch
) -> None:
    contents = {"weights.onnx": b"onnx", "tokenizer.json": b"{}"}
    fake = models.ModelSpec(
        key="tiny",
        fastembed_name="none",
        description="test",
        dim=4,
        repository="org/tiny",
        revision="0" * 40,
        files=tuple(
            models.ModelFile(name, f"sub/{name}", len(body), hashlib.sha256(body).hexdigest())
            for name, body in contents.items()
        ),
        license="MIT",
    )
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, content=contents[request.url.path.rsplit("/", 1)[-1]])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert not models.is_installed(datadir, fake)
    models.install(datadir, fake, client=client)
    assert models.is_installed(datadir, fake)
    assert all(url.startswith("https://huggingface.co/org/tiny/resolve/0000") for url in requested)
    models.install(datadir, fake, client=client)  # nothing missing: no new requests
    assert len(requested) == 2


# --- CLI ---------------------------------------------------------------------------


def _cli(datadir: DataDir, embedder: object, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(
        ["--data-dir", str(datadir.root), *argv],
        embedder_factory=lambda _d, _k: embedder,  # type: ignore[arg-type,return-value]
        out=out,
        err=err,
    )
    return code, out.getvalue(), err.getvalue()


def test_cli_end_to_end(datadir: DataDir, embedder: object, sample_repo: Path) -> None:
    code, out, _ = _cli(datadir, embedder, "roots", "list")
    assert code == 0 and "No hay carpetas" in out
    code, out, _ = _cli(datadir, embedder, "roots", "add", str(sample_repo))
    assert code == 0 and "solo lectura" in out
    code, out, _ = _cli(datadir, embedder, "index")
    assert code == 0 and "12 indexados" in out
    code, out, _ = _cli(datadir, embedder, "search", "getUserById", "-k", "2")
    assert code == 0
    assert f"{sample_repo / 'server' / 'src' / 'routes' / 'users.ts'}:" in out
    code, out, _ = _cli(datadir, embedder, "search", "getUserById", "--json")
    hits = json.loads(out)
    assert hits[0]["rel_path"] == "server/src/routes/users.ts"
    assert hits[0]["path"].endswith("users.ts") and hits[0]["start_line"] >= 1
    code, out, _ = _cli(datadir, embedder, "status")
    assert code == 0 and "Bloqueo de red: activo" in out and "12 archivos" in out
    code, out, _ = _cli(datadir, embedder, "models", "list")
    assert code == 0 and "jina-code-int8" in out and "no instalado" in out


def test_cli_reports_errors_with_exit_code_2(datadir: DataDir, embedder: object) -> None:
    code, _, err = _cli(datadir, embedder, "roots", "add", "/definitely/not/here")
    assert code == 2 and "Error" in err
    code, _, err = _cli(datadir, embedder, "roots", "remove", "nope")
    assert code == 2
    code, _, err = _cli(datadir, embedder, "index", "--root", "nope")
    assert code == 2


def test_cli_models_use_changes_the_setting(datadir: DataDir, embedder: object) -> None:
    code, out, _ = _cli(datadir, embedder, "models", "use", "qwen3-0.6b-int8")
    assert code == 0 and "no está instalado" in out.replace("Aún no", "no")
    assert config.load(datadir).embedding_model == "qwen3-0.6b-int8"
