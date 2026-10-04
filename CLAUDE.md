# CLAUDE.md

**Faro**: asistente de programación personal para Windows, 100 % local. Paquete Python `faro`, identificador `com.manahengarcia.faro`.

- **Especificación (fuente de verdad):** [`docs/SPEC.md`](docs/SPEC.md). Léela entera antes de cambiar nada.
- **Plan, decisiones y su motivo:** [`docs/PLAN.md`](docs/PLAN.md). La §11 recoge lo que cambió en la Fase 1 y por qué.
- **Comparativas medidas:** [`docs/benchmarks/`](docs/benchmarks/).

## Invariantes (si se rompe uno, el producto ha fallado)

1. **Solo lectura.** Nada se crea, modifica ni borra dentro de las carpetas del usuario.
2. **Sin red en uso normal.** Solo las acciones explícitas "descargar documentación" y "descargar modelo" salen a Internet.
3. **Respuestas verificables.** Cada respuesta cita ruta y líneas (o página de documentación), o dice que no hay fuentes.

Además: **el modelo no tiene herramientas** (RAG puro: entra texto, sale texto).

### Fronteras de módulos del backend (las comprueba `tests/guarantees/test_static_boundaries.py`)

| Solo este módulo… | …puede |
|---|---|
| `faro.safe_fs` | Leer y listar las carpetas del usuario (no tiene API de escritura) |
| `faro.datadir` | Abrir, crear o escribir archivos y conexiones (SQLite, LanceDB), siempre dentro del directorio de datos |
| `faro.net` | Importar librerías de red. `net.guard` bloquea en tiempo de ejecución todo lo que no sea loopback (conexiones, datagramas y DNS); `net.download` es la única salida a Internet |

- Ningún módulo del producto lanza procesos, usa `eval`/`exec` ni importa módulos dinámicamente. La única excepción es el cargador de gramáticas. La Fase 2 añadirá explícitamente el gestor de `llama-server` a la lista de procesos.
- Las APIs de frontera usan **verbos propios** (`SafeFS.read_file/locate/list_dir`, `DataDir.load_text/load_json/path`, `AppContext.create`). Así el test estático puede prohibir los verbos genéricos de disco (`open`, `read_bytes`, `resolve`, `exists`…) en el resto del código. No reutilices esos nombres.
- Si un cambio necesita saltarse una frontera, se para y se propone antes. No se añade una excepción al test.

## Reglas de trabajo

- Explicaciones, documentación y textos de la interfaz en **español**. Código, nombres e identificadores, comentarios y mensajes de commit en **inglés**.
- Antes de usar una dependencia o un flag, **comprobar la versión y la API actuales** en la fuente oficial (registro, código, `--help` del binario instalado). No fiarse de la memoria.
- **Versiones fijadas:** `uv.lock` (con hashes), `package-lock.json` con `save-exact=true`, `Cargo.lock`, y SHA-256 para lo que se descarga (modelos de *embeddings* en `faro/indexing/models.py`; llama.cpp en la Fase 2). Las acciones de GitHub se fijan por SHA de commit.
- **`tree-sitter` se queda en 0.25.2**: la 0.26.0 corrompe la memoria. Lo vigila `tests/regressions/`.
- **Tests:** pytest en el backend y vitest en el frontend. El LLM siempre está **simulado** en los tests automáticos; el real solo se usa en la prueba de rendimiento manual. Los tests de *embeddings* reales (`tests/integration/`) son opcionales en local y **obligatorios en el CI** (`FARO_REQUIRE_MODEL_TESTS=1`).
- Lo que solo puede probarse en Windows va en módulos que empiezan por `assert sys.platform == "win32"` (por ejemplo `tests/guarantees/test_safe_fs_windows.py`). En otros sistemas no se recogen y la cabecera de pytest lo anuncia; el CI de Windows los ejecuta. Los casos sueltos usan el marcador `windows_only`/`posix_only`. **Nunca** se declara verificado algo que no se ha ejecutado.
- Nunca se salta, desactiva ni pone en cuarentena un test para poner la batería en verde.
- Cambios pequeños y revisables. Nada fuera de la especificación sin proponerlo antes.
- Explicar cada decisión relevante **antes** de implementarla.

## Flujo por fases

Una fase cada vez. Al cerrarla: tests en verde (local y CI), comando de demo, resumen en español de qué se hizo y por qué, commit, actualizar este archivo y **parar hasta el visto bueno del usuario**.

| Fase | Estado |
|---|---|
| 0. Plan | ✅ Aprobada (respuestas P1–P8 en `docs/PLAN.md` §10) |
| 1. Núcleo de datos (`safe_fs`, indexador, embeddings, LanceDB, búsqueda híbrida, CLI) | ✅ Entregada, pendiente de visto bueno |
| 2. Motor y RAG (`llama-server`, perfiles, hardware, benchmark, chat SSE con citas) | ⏳ |
| 3. Documentación offline (DevDocs) | ⏳ |
| 4. Interfaz (dos direcciones visuales → elección → implementación) | ⏳ |
| 5. Mascota 3D y pulido | ⏳ |
| 6. Empaquetado (instalador `.exe`, primer arranque, README) | ⏳ |
| 7. Evaluación (~20 preguntas reales) | ⏳ |

Pendiente del usuario: ejecutar `scripts\check-prereqs.ps1 -Json` en su Windows (P8).

## Comandos

```powershell
# Requisitos de desarrollo en Windows (solo lectura, no instala nada)
powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1 -Json
```

```bash
# Backend (desde backend/)
uv sync                                        # versiones exactas de uv.lock (solo necesita PyPI)
uv run pytest                                  # toda la batería con el guardia de red activo
scripts/pytest-offline.sh                      # lo mismo dentro de un network namespace (Linux)
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run mypy --platform win32
FARO_TEST_MODEL_DATA_DIR=<dir> uv run pytest tests/integration   # con el modelo real

uv run faro models download <modelo>           # única acción con red (verificada por SHA-256)
uv run faro roots add <carpeta>                # lista blanca, solo lectura
uv run faro index                              # incremental
uv run faro search "<consulta>" [--json]
uv run faro status

# Comparativa de embeddings
tools/bench/fetch_corpus.sh <dir>
uv run python tools/bench_embeddings.py --models-data <dir> --corpus <dir> --models … --out informe.json
uv run python tools/bench_report.py informe.json

# Previstos: faro ask | bench | hw (Fase 2); app/ con npm + Tauri (Fase 4)
```

## Entorno

- **Objetivo:** Windows 10 1809+/11 x64. Perfiles de hardware `cpu`, `gpu-pequeno` y `gpu-hibrido` (ver la especificación, §2).
- **CI (`.github/workflows/backend.yml`):** lint y tipos (Linux y win32), tests en `ubuntu-24.04` y `windows-2025`, y la batería completa en un *network namespace*. Es la referencia para todo lo que es propio de Windows.
- **Sesiones en la nube de Claude Code:** contenedor Linux efímero de 4 vCPU, sin GPU y sin Windows. Funcionan `unshare -rn` (aunque no hay `ip`: `scripts/netns_check.py` levanta loopback) y las descargas de PyPI y Hugging Face. El proxy bloquea los archivos `github.com/.../archive`. Lo que haya que conservar debe estar commiteado y subido.
- **Rendimiento medido aquí:** vectorizar en CPU es el cuello de botella del indexado (1–2 fragmentos/s con el modelo más ligero en 4 vCPU; ver `docs/benchmarks/`).

## Decisiones registradas

Detalle y motivo en `docs/PLAN.md` §4 (plan) y §11 (cambios de la Fase 1). Resumen:

- Gramáticas de tree-sitter como **wheels individuales**; la de **Dart, copiada sin modificar** en `backend/grammars/tree-sitter-dart`, con `PROVENANCE.md` y un test de hashes.
- Embeddings con fastembed **siempre offline** (`specific_model_path`, `local_files_only`, `HF_HUB_OFFLINE=1`, caché dentro del directorio de datos). Modelo por defecto: ver `faro.config.DEFAULT_EMBEDDING_MODEL` y `docs/benchmarks/`.
- Búsqueda híbrida con RRF; texto sin *stemming*, identificadores partidos (Unicode) y palabras vacías ES/EN quitadas **solo de la consulta**.
- Exclusiones duras de secretos y dependencias; los *placeholders* de OneDrive no se abren nunca; las carpetas quitadas de la lista blanca desaparecen de los resultados al momento.
- `llama-server` siempre con `--no-webui --no-agent --offline --host 127.0.0.1 --api-key <aleatoria>`, entorno sin `LLAMA_*`/`HF_*`, y flags detectados con `--help` del binario real. Perfil híbrido: `--fit on --fit-target 700` (a validar en hardware real).
- Backend con PyInstaller **`--onedir`** lanzado desde Rust como recurso, dentro de un Job Object de Windows.
- Token de sesión por **stdin**; el backend elige el puerto (`127.0.0.1:0`) y lo anuncia por stdout.
- Endpoint externo (Ollama) **solo loopback**.
- TypeScript **6.0.3** (no 7.x todavía), React **19.3.x** (límite de `@react-three/fiber` 9.8).
