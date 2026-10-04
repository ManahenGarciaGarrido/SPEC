"""Compare embedding models on real repositories with Spanish and English questions.

Usage (after ``faro models download <key>`` for each model and fetch_corpus.sh):

    python tools/bench_embeddings.py --models-data DIR --corpus DIR \\
        --models jina-code-int8 jina-code qwen3-0.6b-int8 --out report.json

Runs fully offline (the network guard is installed first). For every model it
indexes the corpus from scratch, then asks every question in both languages
and records, per retrieval mode (hybrid, vector only, text only), whether a
gold file appears among the top-k distinct files, plus indexing and query
speed. The index lives in a temporary data directory; the corpus is only read.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from faro.net import guard

guard.install()

from faro import config  # noqa: E402
from faro.context import AppContext  # noqa: E402
from faro.datadir import DataDir  # noqa: E402
from faro.indexing import embedder as embedder_module  # noqa: E402
from faro.search import hybrid, tokenize  # noqa: E402

QUERIES = Path(__file__).parent / "bench" / "queries.json"
DEPTH = 10
MODES = ("hybrid", "vector", "text")


def _distinct_files(rows: list[Any], root_names: dict[str, str]) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []
    for row in rows:
        root_id = row.root_id if hasattr(row, "root_id") else row["root_id"]
        rel = row.rel_path if hasattr(row, "rel_path") else row["rel_path"]
        key = (root_names[root_id], rel)
        if key not in seen:
            seen.append(key)
    return seen


def _rank(files: list[tuple[str, str]], repo: str, gold: list[str]) -> int | None:
    for position, (name, rel) in enumerate(files, start=1):
        if name == repo and rel in gold:
            return position
    return None


def run_model(
    key: str, models_data: DataDir, corpus: Path, spec: dict[str, Any], threads: int
) -> dict[str, Any]:
    started = time.monotonic()
    embedder = embedder_module.load(models_data, key, threads=threads)
    load_seconds = time.monotonic() - started
    with tempfile.TemporaryDirectory(prefix=f"bench-{key}-") as tmp:
        app = AppContext.create(DataDir(tmp), lambda _d, _k: embedder)
        settings = app.settings
        root_names: dict[str, str] = {}
        for repo in spec["corpus"]:
            settings, entry = config.add_root(app.datadir, settings, str(corpus / repo["name"]))
            root_names[entry.id] = repo["name"]
        app.save_settings(settings)
        report = app.indexer().run()
        store = app.store()
        results: list[dict[str, Any]] = []
        latencies: list[float] = []
        for query in spec["queries"]:
            for lang in ("es", "en"):
                text = query[lang]
                t0 = time.monotonic()
                hits = hybrid.hybrid_search(store, embedder, text, limit=DEPTH * 3, candidates=50)
                latencies.append(time.monotonic() - t0)
                by_mode = {
                    "hybrid": _distinct_files(hits, root_names),
                    "vector": _distinct_files(
                        store.vector_search(embedder.embed_query(text), DEPTH * 3), root_names
                    ),
                    "text": _distinct_files(
                        store.text_search(tokenize.text_query(text), DEPTH * 3), root_names
                    ),
                }
                results.append(
                    {
                        "id": query["id"],
                        "lang": lang,
                        "ranks": {
                            mode: _rank(files[:DEPTH], query["repo"], query["gold"])
                            for mode, files in by_mode.items()
                        },
                    }
                )
    return {
        "model": key,
        "model_id": embedder.model_id,
        "load_seconds": round(load_seconds, 2),
        "index_seconds": round(report.seconds, 1),
        "files": report.files_indexed,
        "chunks": report.chunks_written,
        "chunks_per_second": round(report.chunks_written / report.seconds, 2),
        "query_ms_median": round(1000 * statistics.median(latencies), 1),
        "results": results,
    }


def summarize(run: dict[str, Any]) -> dict[str, dict[str, dict[str, float]]]:
    summary: dict[str, dict[str, dict[str, float]]] = {}
    for mode in MODES:
        summary[mode] = {}
        for lang in ("es", "en", "all"):
            ranks = [r["ranks"][mode] for r in run["results"] if lang == "all" or r["lang"] == lang]
            count = len(ranks)
            summary[mode][lang] = {
                "hit@1": sum(1 for x in ranks if x is not None and x <= 1) / count,
                "hit@3": sum(1 for x in ranks if x is not None and x <= 3) / count,
                "hit@5": sum(1 for x in ranks if x is not None and x <= 5) / count,
                "mrr@10": sum(1 / x for x in ranks if x is not None) / count,
            }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models-data", required=True, help="Data dir with the models installed")
    parser.add_argument(
        "--corpus", required=True, help="Dir with the repositories (fetch_corpus.sh)"
    )
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    spec = json.loads(QUERIES.read_text(encoding="utf-8"))
    runs = []
    for key in args.models:
        print(f"== {key}", file=sys.stderr, flush=True)
        run = run_model(key, DataDir(args.models_data), Path(args.corpus), spec, args.threads)
        run["summary"] = summarize(run)
        runs.append(run)
        hy = run["summary"]["hybrid"]
        print(
            f"   {run['chunks']} chunks in {run['index_seconds']} s "
            f"({run['chunks_per_second']}/s); hybrid hit@3 es={hy['es']['hit@3']:.2f} "
            f"en={hy['en']['hit@3']:.2f}",
            file=sys.stderr,
            flush=True,
        )
    payload = {
        "threads": args.threads,
        "cpu": os.cpu_count(),
        "guard_blocked_attempts": guard.blocked_attempts(),
        "runs": runs,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
