"""Render the JSON written by bench_embeddings.py as Markdown tables."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MODES = {"hybrid": "Híbrida (la del producto)", "vector": "Solo vectores", "text": "Solo texto"}


def _pct(value: float) -> str:
    return f"{100 * value:.0f} %"


def render(report: dict[str, Any]) -> str:
    runs = report["runs"]
    lines = [
        "| Modelo | Fragmentos | Indexado | Fragmentos/s | Consulta (mediana) | Carga |",
        "|---|---|---|---|---|---|",
    ]
    for run in runs:
        lines.append(
            f"| `{run['model']}` | {run['chunks']} | {run['index_seconds']:.0f} s | "
            f"{run['chunks_per_second']:.1f} | {run['query_ms_median']:.0f} ms | "
            f"{run['load_seconds']:.1f} s |"
        )
    for mode, title in MODES.items():
        lines += ["", f"**{title}**: acierto en el top 1 / top 3 / top 5 y MRR@10", ""]
        lines += [
            "| Modelo | Español | Inglés |",
            "|---|---|---|",
        ]
        for run in runs:
            cells = []
            for lang in ("es", "en"):
                s = run["summary"][mode][lang]
                cells.append(
                    f"{_pct(s['hit@1'])} / {_pct(s['hit@3'])} / {_pct(s['hit@5'])} · "
                    f"MRR {s['mrr@10']:.2f}"
                )
            lines.append(f"| `{run['model']}` | {cells[0]} | {cells[1]} |")
    lines += [
        "",
        "Posición del primer archivo correcto por pregunta (híbrida; `—` = fuera del top 10):",
        "",
    ]
    ids = sorted({r["id"] for r in runs[0]["results"]})
    header = "| Pregunta | " + " | ".join(f"`{run['model']}` es / en" for run in runs) + " |"
    lines += [header, "|---|" + "---|" * len(runs)]
    for qid in ids:
        cells = []
        for run in runs:
            ranks = {r["lang"]: r["ranks"]["hybrid"] for r in run["results"] if r["id"] == qid}
            cells.append(
                " / ".join(str(ranks[lang]) if ranks[lang] else "—" for lang in ("es", "en"))
            )
        lines.append(f"| {qid} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    args = parser.parse_args()
    print(render(json.loads(Path(args.report).read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
