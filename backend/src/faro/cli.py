"""Command-line interface: ``faro roots | index | search | models | status``.

The network guard is installed before anything else runs, so no command can
reach the network except ``faro models download``, which is an explicit,
visible download.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, replace
from typing import TextIO

from faro import __version__, config, pathutil
from faro.context import AppContext, EmbedderFactory
from faro.datadir import DataDir, DataDirError, default_data_dir
from faro.indexing import models
from faro.indexing.embedder import ModelNotInstalledError
from faro.indexing.indexer import IndexProgress, IndexReport
from faro.net import guard
from faro.net.download import DownloadError, DownloadProgress
from faro.safe_fs import SafeFSError

_MB = 1024 * 1024
_PREVIEW_LINES = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="faro",
        description="Asistente de programación local: indexado y búsqueda (solo lectura, sin red).",
    )
    parser.add_argument("--version", action="version", version=f"faro {__version__}")
    parser.add_argument(
        "--data-dir", help="Directorio de datos de Faro (por defecto, el del usuario)."
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")

    roots = commands.add_parser("roots", help="Carpetas en la lista blanca.")
    roots_cmd = roots.add_subparsers(dest="roots_command", required=True, metavar="ACCIÓN")
    roots_cmd.add_parser("list", help="Lista las carpetas.").set_defaults(handler=cmd_roots_list)
    add = roots_cmd.add_parser("add", help="Añade una carpeta (se leerá, nunca se modificará).")
    add.add_argument("path")
    add.set_defaults(handler=cmd_roots_add)
    remove = roots_cmd.add_parser("remove", help="Quita una carpeta (por id o ruta).")
    remove.add_argument("key")
    remove.set_defaults(handler=cmd_roots_remove)

    index = commands.add_parser("index", help="Indexa (de forma incremental) las carpetas.")
    index.add_argument("--root", action="append", help="Solo esta carpeta (id o ruta).")
    index.add_argument("--full", action="store_true", help="Reconstruye el índice desde cero.")
    index.set_defaults(handler=cmd_index)

    search = commands.add_parser("search", help="Busca fragmentos (híbrida: semántica + texto).")
    search.add_argument("query")
    search.add_argument("-k", "--limit", type=int, default=8, help="Número de resultados.")
    search.add_argument("--origin", choices=["code", "doc"], help="Filtra por origen.")
    search.add_argument("--json", action="store_true", help="Salida en JSON.")
    search.set_defaults(handler=cmd_search)

    model = commands.add_parser("models", help="Modelos de embeddings.")
    model_cmd = model.add_subparsers(dest="models_command", required=True, metavar="ACCIÓN")
    model_cmd.add_parser("list", help="Lista los modelos.").set_defaults(handler=cmd_models_list)
    download = model_cmd.add_parser(
        "download", help="Descarga un modelo (acción explícita que usa la red)."
    )
    download.add_argument("key", choices=sorted(models.REGISTRY))
    download.set_defaults(handler=cmd_models_download)
    use = model_cmd.add_parser("use", help="Elige el modelo (obliga a reindexar).")
    use.add_argument("key", choices=sorted(models.REGISTRY))
    use.set_defaults(handler=cmd_models_use)

    commands.add_parser("status", help="Estado del índice y garantías.").set_defaults(
        handler=cmd_status
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    embedder_factory: EmbedderFactory | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    guard.install()
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    try:
        datadir = DataDir(args.data_dir or default_data_dir())
        ctx = AppContext.create(datadir, embedder_factory)
        return int(args.handler(ctx, args, out, err))
    except (
        config.ConfigError,
        DataDirError,
        DownloadError,
        ModelNotInstalledError,
        SafeFSError,
    ) as exc:
        print(f"Error: {exc}", file=err)
        return 2


# --- roots -------------------------------------------------------------------


def cmd_roots_list(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    if not ctx.settings.roots:
        print("No hay carpetas en la lista blanca.", file=out)
        print("Añade una con: faro roots add <carpeta>", file=out)
        return 0
    for root in ctx.settings.roots:
        print(f"{root.id}  {root.path}", file=out)
    return 0


def cmd_roots_add(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    settings, entry = config.add_root(ctx.datadir, ctx.settings, args.path)
    ctx.save_settings(settings)
    print(f"Carpeta en la lista blanca (solo lectura): {entry.path}  [id {entry.id}]", file=out)
    print("Indexa con: faro index", file=out)
    return 0


def cmd_roots_remove(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    settings, entry = config.remove_root(ctx.settings, args.key)
    ctx.save_settings(settings)
    print(f"Carpeta quitada de la lista blanca: {entry.path}", file=out)
    print("Ya no aparece en las búsquedas.", file=out)
    print("Su parte del índice se limpia en el próximo `faro index`.", file=out)
    return 0


# --- index -------------------------------------------------------------------


def cmd_index(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    root_ids = None
    if args.root:
        root_ids = []
        for key in args.root:
            entry = ctx.settings.find_root(key)
            if entry is None:
                print(f"Error: ninguna carpeta coincide con {key!r}", file=err)
                return 2
            root_ids.append(entry.id)
    interactive = err.isatty()

    def progress(event: IndexProgress) -> None:
        if interactive and event.phase == "index":
            current = (event.current or "")[-60:]
            line = f"Indexando… {event.files_processed} archivos · {current}"
            print(f"\r\x1b[2K{line}", end="", file=err)
        elif interactive and event.phase == "finalize":
            print("\r\x1b[2KOptimizando el índice…", end="", file=err)

    report = ctx.indexer(progress=progress).run(root_ids, full=args.full)
    if interactive:
        print("\r\x1b[2K", end="", file=err)
    if not ctx.settings.roots:
        print("No hay carpetas en la lista blanca (el índice queda vacío).", file=out)
        print("Añade una con: faro roots add <carpeta>", file=out)
        return 0
    _print_report(report, out)
    return 0


def _print_report(report: IndexReport, out: TextIO) -> None:
    if report.full_rebuild:
        print("Índice reconstruido desde cero.", file=out)
    print(
        f"Archivos: {report.files_seen} vistos · {report.files_indexed} indexados · "
        f"{report.files_unchanged} sin cambios · {report.files_removed} eliminados · "
        f"{report.files_unreadable} no legibles",
        file=out,
    )
    walk = report.walk
    print(
        f"Omitidos: {walk.ignored} por exclusiones/.gitignore · {walk.links} enlaces · "
        f"{walk.too_large} demasiado grandes · {walk.placeholders} solo en la nube · "
        f"{walk.unsupported} de tipo no soportado",
        file=out,
    )
    print(f"Fragmentos escritos: {report.chunks_written} · {report.seconds:.1f} s", file=out)
    for path, message in report.errors + walk.errors:
        print(f"  aviso: {path}: {message}", file=out)
    if report.cancelled:
        print("Indexado cancelado: se completará en la próxima ejecución.", file=out)


# --- search ------------------------------------------------------------------


def cmd_search(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    hits = ctx.search(args.query, limit=args.limit, origin=args.origin)
    roots = {root.id: root.path for root in ctx.settings.roots}
    if args.json:
        payload = [
            {**asdict(hit), "path": pathutil.join_posix_relative(roots[hit.root_id], hit.rel_path)}
            for hit in hits
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=out)
        return 0
    if not hits:
        print("Sin resultados. ¿Has indexado alguna carpeta? (faro index)", file=out)
        return 0
    for position, hit in enumerate(hits, start=1):
        path = pathutil.join_posix_relative(roots[hit.root_id], hit.rel_path)
        symbol = f"  {hit.symbol}" if hit.symbol else ""
        ranks = ", ".join(
            label
            for label in (
                f"semántica #{hit.vector_rank}" if hit.vector_rank else "",
                f"texto #{hit.text_rank}" if hit.text_rank else "",
            )
            if label
        )
        print(f"{position}. {path}:{hit.start_line}-{hit.end_line}{symbol}", file=out)
        print(f"   [{hit.origin}] puntuación {hit.score:.4f} ({ranks})", file=out)
        for line in hit.text.splitlines()[:_PREVIEW_LINES]:
            print(f"   │ {line[:110]}", file=out)
    return 0


# --- models ------------------------------------------------------------------


def cmd_models_list(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    for spec in models.REGISTRY.values():
        installed = "instalado" if models.is_installed(ctx.datadir, spec) else "no instalado"
        active = " (en uso)" if spec.key == ctx.settings.embedding_model else ""
        print(
            f"{spec.key}{active}: {spec.size_bytes / _MB:.0f} MB, {installed}, "
            f"{spec.dim} dims, {spec.license}",
            file=out,
        )
        print(f"    {spec.description}", file=out)
    return 0


def cmd_models_download(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    spec = models.get(args.key)
    if models.is_installed(ctx.datadir, spec):
        print(f"El modelo {spec.key} ya está instalado.", file=out)
        return 0
    print(
        f"Descarga explícita: {spec.key} ({spec.size_bytes / _MB:.0f} MB) desde huggingface.co, "
        f"revisión {spec.revision[:12]}. Cada archivo se verifica con SHA-256.",
        file=out,
    )
    interactive = err.isatty()

    def progress(event: DownloadProgress) -> None:
        if interactive:
            percent = 100 * event.received / event.total if event.total else 100.0
            print(
                f"\r\x1b[2K[red activa] {event.name} {percent:5.1f}% "
                f"({event.received / _MB:.0f}/{event.total / _MB:.0f} MB)",
                end="",
                file=err,
            )

    models.install(ctx.datadir, spec, progress)
    if interactive:
        print("\r\x1b[2K", end="", file=err)
    print(f"Modelo {spec.key} instalado y verificado. La conexión se ha cerrado.", file=out)
    return 0


def cmd_models_use(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    ctx.save_settings(replace(ctx.settings, embedding_model=args.key))
    print(f"Modelo de embeddings: {args.key}.", file=out)
    print("El próximo `faro index` reconstruirá el índice.", file=out)
    if not models.is_installed(ctx.datadir, models.get(args.key)):
        print(f"Aún no está instalado: faro models download {args.key}", file=out)
    return 0


# --- status ------------------------------------------------------------------


def cmd_status(ctx: AppContext, args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    spec = models.get(ctx.settings.embedding_model)
    manifest = ctx.manifest()
    try:
        totals = manifest.totals()
    finally:
        manifest.close()
    print(f"Directorio de datos: {ctx.datadir.root}", file=out)
    print(f"Carpetas (solo lectura): {len(ctx.settings.roots)}", file=out)
    for root in ctx.settings.roots:
        print(f"  {root.id}  {root.path}", file=out)
    installed = "instalado" if models.is_installed(ctx.datadir, spec) else "NO instalado"
    print(f"Modelo de embeddings: {spec.key} ({installed})", file=out)
    print(f"Índice: {totals['files']} archivos, {totals['chunks']} fragmentos", file=out)
    state = "activo" if guard.is_installed() else "INACTIVO"
    print(f"Bloqueo de red: {state}, {guard.blocked_attempts()} intentos bloqueados", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
