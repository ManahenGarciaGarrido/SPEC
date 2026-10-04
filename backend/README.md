# faro (backend)

Núcleo local de Faro: indexa en **solo lectura** las carpetas que elijas, trocea el código por funciones y clases, calcula *embeddings* en la CPU y responde búsquedas híbridas (semántica + palabras exactas) con **ruta y líneas** de cada fragmento. No usa la red salvo en la descarga explícita de un modelo.

> Especificación: [`../docs/SPEC.md`](../docs/SPEC.md) · Plan y decisiones: [`../docs/PLAN.md`](../docs/PLAN.md)

## Requisitos

- [uv](https://docs.astral.sh/uv/) ≥ 0.12.23 (instala Python 3.12 a nivel de usuario si hace falta).
- Un compilador de C para la gramática de Dart, que se compila desde su código fuente: MSVC en Windows (Visual Studio Build Tools) y gcc o clang en Linux.

## Uso

```bash
uv sync                                      # entorno con las versiones exactas de uv.lock
uv run faro models download jina-code-int8   # única acción con red: descarga verificada por SHA-256
uv run faro roots add /ruta/a/tu/proyecto    # lista blanca (la carpeta solo se lee)
uv run faro index                            # indexado incremental
uv run faro search "¿dónde se valida el correo?"
uv run faro search "getUserById" --json
uv run faro status                           # carpetas, modelo, índice y bloqueo de red
```

Los datos de Faro (configuración, índice, modelos) viven en `%LOCALAPPDATA%\com.manahengarcia.faro` en Windows y en `~/.local/share/com.manahengarcia.faro` en Linux. Se puede cambiar con `--data-dir` o con `FARO_DATA_DIR`.

## Tests

```bash
uv run pytest                     # batería completa; el bloqueo de red está activo toda la sesión
scripts/pytest-offline.sh         # lo mismo dentro de un network namespace sin red (Linux)
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run mypy --platform win32
```

Tests con el modelo real (opcionales en local, obligatorios en el CI):

```bash
FARO_TEST_MODEL_DATA_DIR=<directorio con el modelo instalado> uv run pytest tests/integration
```

| Carpeta | Qué demuestra |
|---|---|
| `tests/guarantees/` | Solo lectura (intentos de escape, huella de la carpeta y *audit hook*), sin red (guardia y descargas), fronteras de módulos (análisis estático del código) |
| `tests/guarantees/test_safe_fs_windows.py` | Escapes propios de Windows (*junctions*, ADS, `\\?\`, 8.3) y apertura compartida. Solo se ejecuta en Windows (CI) |
| `tests/unit/` | Troceado, recorrido, indexado incremental, búsqueda, configuración, modelos, CLI |
| `tests/integration/` | Flujo completo con el modelo de *embeddings* real |
| `tests/regressions/` | Fallo de memoria de tree-sitter 0.26.0 (motivo de fijar 0.25.2) |

## Comparativa de modelos de *embeddings*

```bash
tools/bench/fetch_corpus.sh <dir-corpus>
uv run python tools/bench_embeddings.py --models-data <dir-modelos> --corpus <dir-corpus> \
    --models jina-code-int8 jina-code qwen3-0.6b-int8 --out informe.json
```

Resultados y decisión: [`../docs/benchmarks/`](../docs/benchmarks/).
