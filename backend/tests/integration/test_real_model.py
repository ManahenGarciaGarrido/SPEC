"""End to end with a real embedding model (no fakes), fully offline.

Needs a data directory with the model installed (``faro models download``):

    FARO_TEST_MODEL_DATA_DIR=/path/to/data  [FARO_TEST_MODEL=jina-code-int8]

Without it these tests are skipped, unless ``FARO_REQUIRE_MODEL_TESTS=1``
(set in CI), in which case a missing model is a failure, never a silent skip.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from faro import config
from faro.context import AppContext
from faro.datadir import DataDir
from faro.indexing import embedder as embedder_module
from faro.indexing import models
from faro.indexing.embedder import Embedder
from faro.net import guard

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def real_embedder() -> Embedder:
    path = os.environ.get("FARO_TEST_MODEL_DATA_DIR")
    key = os.environ.get("FARO_TEST_MODEL", config.DEFAULT_EMBEDDING_MODEL)
    if not path or not models.is_installed(DataDir(path), models.get(key)):
        message = f"embedding model {key!r} not available (set FARO_TEST_MODEL_DATA_DIR)"
        if os.environ.get("FARO_REQUIRE_MODEL_TESTS") == "1":
            pytest.fail(message)
        pytest.skip(message)
    return embedder_module.load(DataDir(path), key, threads=2)


def test_vectors_are_normalized_and_sized(real_embedder: Embedder) -> None:
    docs = real_embedder.embed_documents(["def add(a, b):\n    return a + b", "# Título\n\ntexto"])
    query = real_embedder.embed_query("sumar dos números")
    assert docs.shape == (2, real_embedder.dim)
    assert np.allclose(np.linalg.norm(docs, axis=1), 1.0, atol=1e-3)
    assert float(np.linalg.norm(query)) == pytest.approx(1.0, abs=1e-3)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "¿Dónde se comprueba que el correo tiene un formato válido?",
            "lib/auth/auth_repository.dart",
        ),
        ("where is the warehouse stock synchronised with the shop?", "scripts/sync_inventory.py"),
        ("¿Cómo se calcula el daño de un ataque crítico?", "game/combat.luau"),
        ("endpoint that returns a user by id or 404", "server/src/routes/users.ts"),
    ],
)
def test_questions_find_the_right_file(
    real_embedder: Embedder, datadir: DataDir, sample_repo: Path, question: str, expected: str
) -> None:
    app = AppContext.create(datadir, lambda *_: real_embedder)
    settings, _ = config.add_root(datadir, app.settings, str(sample_repo))
    app.save_settings(settings)
    blocked_before = guard.blocked_attempts()
    app.indexer().run()
    top = [hit.rel_path for hit in app.search(question, limit=3)]
    assert expected in top, f"{question!r} -> {top}"
    assert guard.blocked_attempts() == blocked_before, "the model tried to reach the network"
