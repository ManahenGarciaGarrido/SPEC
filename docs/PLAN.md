# Plan de implementación (Fase 0)

> **Estado:** aprobado el 2026-10-04 (respuestas en la sección 10) · **Fecha:** 2026-10-04
> **Fuente de verdad del producto:** [`docs/SPEC.md`](SPEC.md). Este documento explica *cómo* la vamos a cumplir.
> **Nombre:** **Faro** (paquete Python `faro`, identificador `com.manahengarcia.faro`). Ver P1.

Convención de este documento: **[verificado]** = lo he comprobado hoy en el registro oficial o en el código fuente de la dependencia; **[a verificar en Fn]** = depende de tu máquina Windows o de algo que no puedo ejecutar aquí.

---

## 1. Resumen

- La arquitectura de la especificación se mantiene. No propongo cambiar ninguna pieza grande (Tauri 2, React, FastAPI, llama.cpp, LanceDB, tree-sitter).
- He encontrado **cuatro problemas reales** que, sin tratarlos, romperían la garantía "sin red" o "sin herramientas" sin que se notara (sección 4.1–4.3): una librería de gramáticas que descarga en tiempo de ejecución, una librería de embeddings que descarga de Hugging Face, y `llama-server`, que trae por defecto una interfaz web, un modo agente con herramientas y lectura de opciones desde variables de entorno.
- Propongo varios ajustes de implementación (sección 4.4–4.11) que no cambian la arquitectura: cómo se lanza el sidecar, cómo se pasa el token, WebView2 sin conexión, lectura de archivos en Windows sin bloquear a tu editor, etc.
- Esta sesión corre en un **contenedor Linux en la nube**, no en tu Windows. Lo que es específico de Windows (junctions, WebView2, MSVC, instalador, GPU) no lo puedo ejecutar aquí; para eso dejo un script de comprobación de solo lectura y propongo CI con un runner Windows (**P4**).

---

## 2. Requisitos del sistema

### 2.1 Qué he podido comprobar y dónde

| Elemento | Este contenedor (Linux) | Tu Windows |
|---|---|---|
| Rust | `rustc 1.97.0` ✅ | ❓ ejecuta el script |
| Node | `v22.22.0` ✅ (npm 10.9.4) | ❓ |
| Python | `3.11.15` (uv 0.8.17 puede traer 3.12) | ❓ |
| MSVC Build Tools | no aplica | ❓ |
| WebView2 | no aplica | ❓ |
| GPU / `nvidia-smi` | no hay | ❓ |

No he instalado nada a nivel de sistema. Para revisar tu máquina he escrito [`scripts/check-prereqs.ps1`](../scripts/check-prereqs.ps1): **solo lee** (ejecuta `--version`, consulta el registro y WMI), no instala ni modifica nada, y es compatible con Windows PowerShell 5.1. Aquí he comprobado que el parser de PowerShell 7.5 lo acepta sin errores, que PSScriptAnalyzer no encuentra incompatibilidades con PowerShell 5.1 (solo avisos por `Write-Host`, que es intencionado para la salida en color), que la lógica de sus funciones auxiliares da el resultado esperado con salidas de ejemplo, y que fuera de Windows se detiene con código 2. **No lo he ejecutado en Windows** (no hay Windows en este entorno). Detalle de diseño: fija `RUSTUP_AUTO_INSTALL=0` dentro de su propio proceso, porque `rustc --version` a través de rustup podría instalar una toolchain que falte, y usa `py -0p` (que solo lista) en lugar de lanzar `py -3.12`, que con el nuevo gestor de instalación de Python podría descargar esa versión.

```powershell
# Desde la raíz del repo, en PowerShell (no requiere administrador):
powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1
# Para pegarme el resultado:
powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1 -Json
```

### 2.2 Qué necesita tu Windows para desarrollar

| Requisito | Versión | Para qué | Obligatorio |
|---|---|---|---|
| Windows 10 1809+ / 11, x64 | — | WebView2 y Tauri 2 | Sí |
| Rust (rustup, toolchain `stable-x86_64-pc-windows-msvc`) | ≥ 1.90 (MSRV de `tauri` 2.12.1) **[verificado]** | Shell de Tauri | Sí |
| Visual Studio Build Tools, carga "Desarrollo para el escritorio con C++" (MSVC + Windows SDK) | 2022 o posterior | Compilar Rust en Windows, y la gramática de Dart (ver 4.1) | Sí |
| WebView2 Runtime | cualquiera reciente (Windows 11 ya lo trae) | Ventana de Tauri | Sí |
| Node.js | ≥ 22.12 (lo exige Vite 8) **[verificado]**; recomendado 24 LTS | Frontend | Sí |
| uv | ≥ 0.8 | Entorno y lockfile de Python; instala Python 3.12 **a nivel de usuario** | Sí |
| Python | 3.12 (vía `uv python install 3.12` o python.org) | Backend | Sí (uv puede traerlo) |
| Git | — | — | Sí |
| Modo de desarrollador de Windows | — | Crear enlaces simbólicos en los tests sin ser administrador (los de *junctions* no lo necesitan) | No (si falta, esos tests se saltan con aviso) |
| Driver NVIDIA compatible con CUDA 12.4 | ≥ 551.61 en Windows **[verificado en las notas de CUDA 12.4]** | Perfiles `gpu-*` | Solo con GPU |
| Windows Sandbox (ediciones Pro/Enterprise/Education) o una VM | — | Prueba de aceptación de la Fase 6: "Windows limpio sin conexión" | Recomendado (P5) |

---

## 3. Versiones verificadas hoy

Consultadas hoy en PyPI, npm, crates.io y el repositorio de llama.cpp. Se fijan con lockfiles (`uv.lock` con hashes, `package-lock.json` con `save-exact`, `Cargo.lock`) en la fase en que entra cada dependencia, y se vuelven a comprobar en ese momento.

**Backend (Python 3.12)**

| Paquete | Versión | Nota |
|---|---|---|
| fastapi / uvicorn / pydantic | 0.142.2 / 0.54.0 / 2.13.5 | |
| lancedb | 0.39.0 | Wheel `abi3` para win_amd64. FTS nativo (`use_tantivy=False` por defecto) y `RRFReranker` incluidos **[verificado en el código]**. Sin telemetría (solo OpenTelemetry opcional, que no instalamos) **[verificado]** |
| pyarrow | 25.0.1 | dependencia de LanceDB |
| fastembed / onnxruntime | 0.8.1 / 1.30.0 | ver 4.2 |
| tree-sitter | 0.26.0 | + gramáticas individuales, ver 4.1 |
| pathspec | 1.1.1 | respetar `.gitignore` |
| psutil | 7.2.2 | RAM, procesos, conexiones abiertas (indicador "sin conexión") |
| platformdirs | 4.12.3 | directorio de datos por defecto de la CLI en desarrollo |
| httpx | 0.28.1 | cliente hacia `llama-server` (loopback) y descargas explícitas |
| pyinstaller | 6.22.3 | Fase 6 |
| *dev:* pytest, pytest-socket, pytest-asyncio, respx, ruff, mypy | 9.1.1, 0.8.1, 1.4.0, 0.23.1, 0.16.10, 2.4.0 | |

**Frontend**

| Paquete | Versión | Nota |
|---|---|---|
| react / react-dom | 19.3.0 | Fijado a 19.3.x: `@react-three/fiber` 9.8.1 declara `react >=19 <19.4` **[verificado]** |
| vite / @vitejs/plugin-react | 8.3.2 / 6.1.1 | |
| typescript | **6.0.3** (no 7.0.2) | ver 4.10 |
| motion | 14.0.0 | |
| three / @react-three/fiber | 0.186.1 / 9.8.1 | `drei` solo si hace falta (tamaño) |
| vitest | 5.0.3 | |
| react-markdown / shiki | 10.1.0 / 4.5.0 | Resaltado empaquetado, sin CDN |
| @tauri-apps/cli / api | 2.12.1 | |

**Rust:** `tauri` 2.12.1, `tauri-build` 2.7.1, `tauri-plugin-dialog` 2.8.1 (selector de carpetas), `tauri-plugin-single-instance` 2.5.2. Ya existe Tauri **3.0.0-alpha**: lo descarto, la especificación pide Tauri 2 y una alfa no es base para esto.

**Motor:** llama.cpp build **b11393** (la última hoy). Se fija la build concreta (y su SHA-256) en la Fase 2.

---

## 4. Revisión crítica: problemas encontrados y propuestas

### 4.1 Las gramáticas de tree-sitter no pueden descargarse en tiempo de ejecución

- **Problema [verificado]:** `tree-sitter-language-pack` 1.20.0 (el paquete "todo en uno" habitual) ya no trae las gramáticas dentro: el wheel pesa 2,4 MB para 371 lenguajes y expone `download()`, `download_all()` ("from the remote manifest") y una caché local. Usarlo implicaría tráfico de red en uso normal.
- **Propuesta:** usar los wheels individuales, que sí llevan la gramática compilada dentro (todos `abi3` con wheel `win_amd64` **[verificado]**): `tree-sitter-python` 0.25.0, `-javascript` 0.25.0, `-typescript` 0.23.2 (TS y TSX), `-json` 0.24.8, `-yaml` 0.7.2, `-markdown` 0.5.1, `-lua` 0.5.0, `-luau` 1.2.0. PyInstaller los empaqueta; cero descargas.
- **Dart:** el paquete `tree-sitter-dart` 0.1.0 de PyPI lo publica un particular (no la organización `tree-sitter-grammars`). Dart es tu lenguaje principal y esto es un binario nativo que se ejecuta con tus archivos, así que propongo **compilar nosotros la gramática canónica** (`UserNobody14/tree-sitter-dart`, la que usan los editores **[a verificar en F1]**) fijada a un commit, como mini paquete local. Necesita compilador C, que ya hace falta por Tauri. Alternativa más rápida: revisar ese wheel y fijarlo por hash.
- **Compatibilidad de ABI** entre cada gramática y `tree-sitter` 0.26 **[a verificar en F1]** con un test que cargue todas.

### 4.2 Embeddings: idioma de las preguntas y modelo disponible sin red

- **Problema 1 (calidad):** si preguntas en español sobre código escrito en inglés, un modelo solo-inglés (p. ej. `bge-small-en`, `jina-embeddings-v2-base-code`) empareja peor la parte semántica. La búsqueda por palabras exactas compensa cuando citas identificadores (`AuthRepository`), pero no en "¿dónde se valida el login?".
- **Candidatos en fastembed 0.8.1 [verificado]:**

  | Modelo | Dim. | Tamaño | Idiomas | Licencia |
  |---|---|---|---|---|
  | `jinaai/jina-embeddings-v2-base-code` | 768 | 0,64 GB | inglés + 30 lenguajes de programación | Apache-2.0 |
  | `Qwen/Qwen3-Embedding-0.6B-Q` | 1024 | 1,12 GB | multilingüe (>100 idiomas); su ficha declara recuperación de código y entre idiomas | Apache-2.0 |
  | `google/embeddinggemma-300m` | 768 | 1,24 GB | multilingüe | Gemma Terms |
  | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | 0,22 GB | multilingüe, flojo en código | Apache-2.0 |

- **Propuesta:** interfaz `Embedder`; el modelo usado se guarda en los metadatos del índice (cambiarlo obliga a reindexar, y la app lo detecta). En la Fase 1 hago una mini comparativa (~15 preguntas en español sobre un repo de prueba) entre `jina-v2-base-code` y `Qwen3-Embedding-0.6B-Q`, midiendo acierto (recall@k) y velocidad de indexado en CPU, y elegimos el modelo por defecto con datos, no por intuición.
- **Problema 2 (red) [verificado]:** fastembed descarga el modelo de Hugging Face la primera vez (depende de `huggingface-hub`). Lo cargaremos siempre con `local_files_only=True` / `specific_model_path`, y el proceso arranca con `HF_HUB_OFFLINE=1` y `HF_HUB_DISABLE_TELEMETRY=1`. El modelo llega por una de tres vías: (a) dentro del instalador, (b) la acción explícita "descargar modelo", (c) importar una carpeta local. Para cumplir "funciona en un Windows limpio sin conexión" propongo (a) por defecto: ver **P3**.

### 4.3 `llama-server` trae por defecto cosas que chocan con las garantías

Revisado en `common/arg.cpp` y `common/common.h` de la build b11393 **[verificado]**:

| Comportamiento por defecto | Riesgo | Qué haremos |
|---|---|---|
| Interfaz web activada (`ui = true`) | Superficie innecesaria | `--no-webui` |
| Existe un modo agente con herramientas integradas y proxy MCP (`--agent`, `--tools`, `--mcp-servers-*`); desactivado por defecto | Rompería "el modelo no tiene herramientas" si se activara | `--no-agent` explícito, nunca flags de herramientas, y un test que inspecciona el `argv` real |
| Puede descargar modelos de Hugging Face (`-hf`, cliente HTTPS integrado) | Red | Solo `-m <ruta local>` y `--offline` ("prevents network access") |
| Lee opciones de variables de entorno `LLAMA_ARG_*` (p. ej. `LLAMA_ARG_AGENT`) | Tu entorno podría cambiar el comportamiento sin que lo veamos | Se lanza con un entorno saneado (sin `LLAMA_*` ni `HF_*`) |
| Sin autenticación | Cualquier proceso local podría usarlo | `--api-key` aleatoria por sesión, `--host 127.0.0.1`, puerto libre |

Además:

- **`--fit` (activo por defecto)** ajusta los parámetros que no fijamos para que el modelo quepa en memoria, dejando un margen por dispositivo (1 GiB por defecto, configurable con `--fit-target`). Es justo lo que pide el perfil `gpu-hibrido` ("dejar ~700 MB de VRAM libres"). **Propuesta:** el perfil usa `--fit on --fit-target 700` y permite fijar `--n-cpu-moe` a mano si el ajuste automático no convence. Hay que medirlo en tu portátil **[a verificar en F2]**.
- **Detección de flags:** el gestor ejecuta `llama-server --help` del binario real y solo usa los flags que aparecen (cacheado por hash del binario). Así cumplimos "no supongas que existe" y funciona aunque apuntes a otra build.
- **Plantilla de chat:** `--jinja`, para usar la plantilla incluida en el GGUF.
- **Binarios oficiales para Windows [verificado en `release.yml`]:** `llama-bin-win-cpu-x64.zip` (incluye `llama-server.exe` y los backends de CPU, cargados dinámicamente con `GGML_BACKEND_DL`) + `llama-bin-win-cuda-12.4-x64.zip` (solo `ggml-cuda.dll`) + `cudart-…zip` (runtime de CUDA). El **mismo `llama-server.exe`** usa CUDA si encuentra la DLL y un driver válido, y si no, CPU: cumple "mismo binario para CPU y GPU". Propongo CUDA 12.4 en lugar de 13.x porque exige un driver más antiguo.

### 4.4 Sidecar: PyInstaller `--onedir`, no `--onefile`

- **Problema:** `externalBin` de Tauri espera un único ejecutable, lo que con PyInstaller significa `--onefile`. Ese modo descomprime en `%TEMP%` todo el backend (onnxruntime, pyarrow, LanceDB: cientos de MB) **en cada arranque**: arranque lento y falsos positivos de antivirus frecuentes.
- **Propuesta:** `--onedir`, incluido como `resources` de Tauri y lanzado desde Rust con `std::process::Command`. Conceptualmente sigue siendo un sidecar, y además no necesitamos el plugin `shell` de Tauri (menos permisos en el WebView).
- **Ciclo de vida:** Job Object de Windows con `KILL_ON_JOB_CLOSE`: si la app se cierra o se cuelga, mueren el backend y `llama-server` (los nietos heredan el job). El backend también vigila el PID de su padre.

### 4.5 Arranque, puerto y token

1. Tauri genera un token aleatorio de 256 bits y lanza el backend.
2. El token se pasa por **stdin**, no por argumentos ni variables de entorno (otros procesos del mismo usuario pueden leer la línea de comandos).
3. El backend escucha en `127.0.0.1:0` (el sistema elige un puerto libre, sin condiciones de carrera) e imprime por stdout una línea `{"event":"ready","port":N}`.
4. El frontend obtiene `{baseUrl, token}` con un comando de Tauri y manda `Authorization: Bearer …` en cada petición. El backend compara en tiempo constante, valida la cabecera `Host` (defensa contra *DNS rebinding*) y solo acepta CORS del origen de Tauri.
5. El streaming usa `fetch` + `ReadableStream` con formato SSE, porque `EventSource` no permite enviar la cabecera `Authorization`.

### 4.6 WebView2 en un Windows limpio sin conexión

El modo por defecto del instalador de Tauri descarga WebView2 si falta, y eso necesita Internet. Windows 11 lo trae, pero un Windows 10 limpio puede no tenerlo. **Propuesta:** `webviewInstallMode: offlineInstaller` (el instalador crece unos 130 MB) **[a verificar en F6]**.

### 4.7 "Asignar la app a la gráfica integrada" puede no funcionar como se espera

En WebView2 el render lo hace el proceso `msedgewebview2.exe`, no el `.exe` de la app, así que la preferencia gráfica "por aplicación" de Windows podría no aplicarse. En la Fase 5 probaré qué funciona de verdad (preferencia sobre el ejecutable de WebView2, o un flag de Chromium vía `additionalBrowserArgs`) y documentaré solo lo comprobado **[a verificar en F5]**. En portátiles con Optimus, el WebView suele ir ya en la integrada por defecto.

### 4.8 Endpoint externo (Ollama): solo loopback

La opción de "apuntar a un endpoint compatible con OpenAI" solo aceptará direcciones loopback (`127.0.0.0/8`, `::1`, `localhost` resuelto a loopback). Cualquier otra se rechaza. Si no, la garantía "sin red" dependería de lo que alguien escriba en Ajustes.

### 4.9 Leer en Windows sin estorbar a tu editor

`open()` de Python en Windows no comparte el permiso `FILE_SHARE_DELETE`: mientras leemos un archivo, un editor que guarda con "escribir temporal y renombrar" podría fallar un instante. No modificamos nada, pero interferimos. **Propuesta:** en Windows, `safe_fs` abre con `CreateFileW(GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE)` vía `ctypes`, lee de una vez y cierra.

### 4.10 TypeScript 6.0.3 en lugar de 7.0.2

TypeScript 7 (la reescritura nativa) acaba de publicarse y `typescript-eslint` 8.71 todavía exige `typescript <6.1` **[verificado]**. Vite y Vitest no usan `tsc` para compilar, así que solo afecta a la comprobación de tipos y al lint. Migrar más adelante es trivial.

### 4.11 Probar lo específico de Windows

Junctions, rutas UNC, nombres cortos 8.3, *alternate data streams* (`archivo:flujo`) y el instalador solo se pueden probar en Windows. Los tests correspondientes se marcan `windows_only` y se saltan (con aviso, no en silencio) en Linux. Propuesta: un job de CI en `windows-latest` que los ejecute en cada push (**P4**).

---

## 5. Arquitectura detallada

### 5.1 Procesos

```
faro.exe (Tauri, Rust) ── Job Object (KILL_ON_JOB_CLOSE) ───────────────────────────┐
 │  genera token · lanza backend · lee {"event":"ready","port":N} · CSP restrictiva │
 │                                                                                  │
 ├── WebView2 (React) ──fetch/SSE + Bearer──▶ 127.0.0.1:N                           │
 │                                                                                  │
 └── faro-backend.exe (PyInstaller onedir, FastAPI) ◀── token por stdin             │
       ├── safe_fs ──(solo lectura)──▶ carpetas raíz en lista blanca                │
       ├── datadir ──(única escritura)──▶ %LOCALAPPDATA%\<identificador>\           │
       ├── indexing / search ──▶ LanceDB + SQLite (en datadir)                      │
       ├── net.download ──▶ Internet (solo acción explícita, con indicador)         │
       └── engine ──▶ llama-server.exe (127.0.0.1:M, --api-key, --offline)          │
                        o endpoint externo loopback (Ollama)                        │
────────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Directorio de datos (único sitio donde se escribe)

Tauri lo decide (`app_local_data_dir()` → `%LOCALAPPDATA%\<identificador>`) y se lo pasa al backend. La CLI usa el mismo directorio por defecto (`platformdirs` en Linux para desarrollo).

```
<datadir>\
  config.json           ajustes, perfil, lista blanca de carpetas raíz
  state.db              SQLite: manifiesto de archivos (indexado incremental) e historial de conversaciones
  index\                LanceDB: tabla de fragmentos (código y documentación)
  docs\                 documentación descargada, normalizada
  models\embeddings\    modelo ONNX (si no viene en el instalador)
  cache\                p. ej. capacidades de llama-server (salida de --help por hash del binario)
  logs\                 registros rotativos
```

El GGUF se queda donde lo tengas; solo lo abre `llama-server`, en modo lectura.

### 5.3 Módulos del backend y fronteras

| Módulo | Responsabilidad | Puede tocar |
|---|---|---|
| `faro.safe_fs` | Lista blanca, resolución a ruta real y contención, recorrer, leer. **Sin API de escritura.** | Carpetas del usuario, solo lectura |
| `faro.datadir` | Rutas del directorio de datos; abre/crea archivos y conexiones (SQLite, LanceDB) verificando que quedan dentro | Solo `<datadir>` |
| `faro.net` | `loopback`: cliente HTTP que rechaza cualquier host no loopback. `download`: única salida a Internet (acción explícita, publica su actividad) | Red |
| `faro.indexing` | `walker` (safe_fs + `.gitignore` + exclusiones), `chunking` (tree-sitter + alternativas), `embedder`, `store` (LanceDB), `manifest` (SQLite), `indexer` (orquestación incremental, progreso, cancelación) | Nada directamente: usa los tres de arriba |
| `faro.search` | Búsqueda híbrida (vector + texto + RRF), tokenización de identificadores | — |
| `faro.docs` | Importador Markdown/HTML, fuentes descargables | — |
| `faro.engine` | `hardware` (psutil, `nvidia-smi`), `profiles`, `llama_server` (proceso hijo), `client` (compatible con OpenAI, vía `net.loopback`), `bench` | Lanza `llama-server` |
| `faro.rag` | Presupuesto de contexto, prompt, mapeo de citas | — |
| `faro.api` | FastAPI: auth, `Host`, CORS, rutas, SSE | — |
| `faro.status` | Estado real de los indicadores | — |
| `faro.cli` | `faro roots|index|search|ask|bench|hw|docs|serve` | — |

Las fronteras se comprueban con tests estáticos (sección 6), no solo con buena voluntad.

### 5.4 Indexado (Fase 1)

```
safe_fs.walk(raíz)                      respeta .gitignore; excluye .git, node_modules, build, dist,
  │                                     .dart_tool, .venv, target…; .env* excluido por defecto (secretos);
  │                                     límite de tamaño; detección de binarios; no sigue enlaces
  ▼
manifest: ¿nuevo / cambiado / borrado?  primero tamaño + mtime; si cambian, hash del contenido
  ▼
safe_fs.read_text → chunking            tree-sitter por función/clase (Dart, TS/TSX/JS, Python, Lua/Luau),
  │                                     Markdown por encabezados, YAML/JSON por claves de primer nivel,
  │                                     el resto por ventanas de líneas con solape
  ▼
embedder (CPU, hilos limitados)         cada fragmento lleva una cabecera "ruta > clase > método" para dar contexto
  ▼
store: borrar fragmentos del archivo + insertar; índice de texto sobre `search_text`
```

Esquema de cada fragmento: `id`, `origin` (`code`|`doc`), `root_id`, `rel_path`, `start_line`, `end_line`, `language`, `symbol`, `text`, `search_text`, `vector`, `file_hash`.

`search_text` es el texto con los identificadores también partidos (`getUserById` → `getUserById get user by id`) e índice sin *stemming*: en código, `users` y `user` no son lo mismo y los nombres exactos importan.

En el perfil `cpu`, el indexado se pausa mientras el modelo genera, para no competir por los núcleos.

### 5.5 Pregunta → respuesta con citas (Fase 2)

1. Búsqueda híbrida → fusión RRF → los N mejores según perfil y presupuesto de tokens (`cpu`: pocos fragmentos y contexto de 8–16K) → se quitan solapes del mismo archivo.
2. Si no hay nada por encima del umbral de relevancia → se dice explícitamente "no he encontrado fuentes relevantes" (el umbral se ajusta en la Fase 7).
3. Prompt: instrucciones fijas al principio (aprovecha la caché de prompt de `llama-server`), fuentes numeradas con `ruta:líneas` y origen, pregunta. Se pide citar con `[n]`.
4. Eventos SSE: `retrieval` (fuentes) → `token`… → `done` (citas usadas, tokens/s) | `error`. Las `[n]` que no correspondan a ninguna fuente se descartan.
5. La petición al modelo nunca incluye `tools` ni `tool_choice` (comprobado por test).

Estos eventos son también los que mueven a la mascota: escribir → *escuchando*, `retrieval` → *pensando*, `token` → *hablando*, `done` → *contenta*, `error` o sin fuentes → *confusa*, inactividad → *dormida*.

### 5.6 Indicadores con estado real

- **Sin conexión:** el backend comprueba periódicamente con `psutil` las conexiones de red abiertas de sus propios procesos (backend y `llama-server`). Cualquier extremo remoto no loopback pone el indicador en rojo. Durante una descarga explícita muestra "descargando…".
- **Solo lectura:** muestra las raíces activas y el contador de intentos bloqueados por `safe_fs` (rutas fuera de la lista blanca). `safe_fs` no tiene API de escritura, y eso está garantizado por los tests estáticos.

### 5.7 Frontend y Tauri

- Vistas: chat, fuentes, vista previa de citas, ajustes, primer arranque. Estado global pequeño (propongo Zustand en la Fase 4; lo justificaré entonces).
- Markdown con `react-markdown` y resaltado con `shiki` empaquetado (motor de expresiones regulares en JS, sin WASM ni CDN). Fuentes tipográficas e iconos empaquetados.
- Tauri: plugins `dialog` (elegir carpeta) y `single-instance`. Sin plugins `fs`, `http`, `shell` ni `updater`. CSP aproximada: `default-src 'self'; connect-src 'self' http://127.0.0.1:*; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self'`.
- Vista previa: el backend sirve el fragmento a través de `safe_fs` y avisa si el archivo cambió desde que se indexó (las líneas podrían haberse movido).

### 5.8 Mascota (Fase 5)

`MascotRig` (interfaz) ← `ProceduralRig` (geometría y animación por código). Un futuro `GlbRig` implementaría la misma interfaz con clips de un `.glb`. Máquina de estados con mezcla suave entre estados. Render a demanda limitado a 30 fps en reposo, pausado con la ventana oculta o minimizada, y el modo ahorro desmonta el `<Canvas>` (libera el contexto WebGL y su VRAM).

---

## 6. Garantías → mecanismo → test

| Garantía | Mecanismo | Tests automáticos (fallan si se rompe) |
|---|---|---|
| **Solo lectura** | `safe_fs` sin API de escritura; lista blanca; resolución a ruta real + contención; recorrido sin seguir enlaces ni junctions | **Escape:** `..`, rutas absolutas, symlink hacia fuera, junction hacia fuera *(Windows)*, `\\?\` y UNC *(Windows)*, ADS `archivo:flujo` *(Windows)*, mayúsculas/minúsculas, 8.3 *(Windows)*. **Hash:** nombres, tamaños, mtimes y contenido de una carpeta de prueba, idénticos antes y después de indexar, buscar, preguntar (modelo simulado) y previsualizar. **Estático (AST):** fuera de `safe_fs` y `datadir` nadie llama a `open`, `os.*` de E/S, `pathlib` de E/S, `shutil`, `sqlite3.connect`, `lancedb.connect`… |
| **Solo escribe en datadir** | `datadir` comprueba la contención en cada apertura | Unitarios de `datadir` + el test estático anterior |
| **Sin red** | `faro.net` es el único que importa librerías de red; descargas solo por acción explícita; `llama-server` con `--offline` y entorno saneado; fastembed `local_files_only`; CSP; todo empaquetado | **Toda la batería** corre con `pytest-socket` (`--disable-socket --allow-hosts=127.0.0.1,::1`) activado en la configuración, no como opción. **Job de CI** que la ejecuta dentro de un *network namespace* de Linux con solo loopback (cubre también subprocesos). **Estático:** imports de red solo en `faro.net`. **argv** de `llama-server`. **Frontend:** el `dist/` compilado no contiene URLs externas; la CSP de `tauri.conf.json` es la esperada |
| **Verificable** | Cada fragmento conserva ruta, líneas y origen; mapeo `[n]` → fuente; camino explícito "sin fuentes" | Con modelo simulado: la respuesta trae citas con ruta, líneas y origen; índice vacío → evento "sin fuentes"; `[n]` inválidas descartadas |
| **Sin herramientas** | Petición sin `tools`; `--no-agent`; sin flags de herramientas | Test del payload enviado y del argv |

Los tests usan un **`llama-server` simulado** (un pequeño servidor compatible con OpenAI en loopback, con streaming, `/health` y `/tokenize`) y un **ejecutable falso** para probar el gestor de procesos (argumentos, espera de arranque, caídas). El modelo real solo se usa en la prueba de rendimiento manual.

---

## 7. Estructura del repositorio

```
SPEC/
├── CLAUDE.md                 convenciones, comandos y estado de fases
├── README.md                 (Fase 6)
├── docs/
│   ├── SPEC.md               especificación (fuente de verdad)
│   └── PLAN.md               este documento
├── scripts/
│   └── check-prereqs.ps1     comprobación de requisitos en Windows (solo lectura)
├── backend/                  (Fase 1)
│   ├── pyproject.toml · uv.lock · .python-version
│   ├── src/faro/
│   │   ├── safe_fs/ · datadir.py · net/ · indexing/ · search/
│   │   ├── docs/ · engine/ · rag/ · api/ · status.py · cli.py
│   ├── grammars/             gramática de Dart compilada por nosotros (si se aprueba 4.1)
│   └── tests/
│       ├── guarantees/       solo lectura, sin red, estáticos
│       ├── fakes/            llama-server simulado
│       ├── fixtures/         repo de prueba multilenguaje, documentación de prueba
│       └── unit/
├── app/                      (Fase 4)
│   ├── package.json · package-lock.json · vite.config.ts · tsconfig.json
│   ├── src/
│   │   ├── design/           tokens, temas, curvas y duraciones
│   │   ├── api/              cliente HTTP + lector SSE
│   │   ├── features/         chat · sources · preview · settings · onboarding
│   │   └── mascot/           MascotRig · ProceduralRig · máquina de estados
│   └── src-tauri/
│       ├── Cargo.toml · tauri.conf.json · capabilities/
│       └── src/              main.rs · sidecar.rs (lanzamiento, handshake, job object)
└── .github/workflows/        (si se aprueba P4)
```

Los binarios de llama.cpp y el modelo de embeddings no se versionan: un script los descarga en tiempo de *build*, verificando su SHA-256 fijado.

---

## 8. Fases: entregables y cómo comprobarlas

| Fase | Entregables principales | Comprobación |
|---|---|---|
| **1. Núcleo de datos** | Proyecto `uv`; `datadir`, `safe_fs` (con apertura compartida en Windows), walker, chunking con tree-sitter, embedder offline + comparativa de modelos, LanceDB + FTS, manifiesto incremental, búsqueda híbrida RRF, CLI | `uv run pytest` en verde (incluidas las garantías). Demo: `uv run faro roots add tests/fixtures/sample_repo` → `uv run faro index` → `uv run faro search "dónde se valida el usuario"` devuelve `ruta:inicio-fin` |
| **2. Motor y RAG** | Detección de hardware, perfiles, gestor de `llama-server` (capacidades por `--help`, entorno saneado, job object), endpoint externo loopback, prueba de rendimiento, API FastAPI con auth y SSE, RAG con citas | Tests con modelo simulado. Demo: `uv run faro ask "…"` responde con citas en la terminal. Manual en tu máquina: `uv run faro bench` con tu GGUF |
| **3. Documentación offline** | Importador Markdown/HTML, fragmentos con `origin=doc`, descarga explícita aislada en `faro.net.download` con progreso | Las respuestas separan "tu código" de "documentación" |
| **4. Interfaz** | Dos direcciones visuales con pantalla de muestra → **esperar tu elección** → sistema de diseño, chat, fuentes, vista previa, ajustes, indicadores, shell de Tauri con handshake y CSP | `npm run tauri dev`: flujo completo desde la ventana. `vitest` en verde |
| **5. Mascota y pulido** | `MascotRig`, `ProceduralRig`, todos los estados, presupuesto gráfico, modo ahorro | VRAM medida por proceso con el contador `\GPU Process Memory(*)\Dedicated Usage` y documentada |
| **6. Empaquetado** | Backend `--onedir`, binarios de llama.cpp fijados, instalador NSIS por usuario (sin admin), WebView2 offline, asistente de primer arranque, README (incluida la gráfica integrada) | Instalar y usar en Windows Sandbox con la red desactivada (`<Networking>Disable</Networking>`) o una VM sin red |
| **7. Evaluación** | ~20 preguntas reales tuyas con la respuesta esperada (archivos/líneas); `faro eval` con recall@k, MRR y latencia por perfil; ajustes | Informe antes/después de cada ajuste |

Al cerrar cada fase: tests en verde, comando de demo, resumen en español, commit, `CLAUDE.md` actualizado y **pausa hasta tu visto bueno**.

---

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| Perfil `cpu`: leer el contexto es lento | Pocos fragmentos, contexto pequeño, instrucciones fijas al principio para reutilizar la caché de prompt de `llama-server` |
| Calidad de recuperación con preguntas en español | Comparativa de embeddings en F1, búsqueda híbrida, ajuste en F7 |
| Instalador grande (CUDA ~cientos de MB, WebView2 offline, modelo de embeddings) | Ver P3; posible componente CUDA opcional en el instalador |
| Lo específico de Windows no se puede ejecutar en esta sesión | Tests `windows_only` + CI en Windows (P4) + tus pruebas manuales; nunca lo daré por verificado sin ejecutarlo |
| El WebView consume GPU compartida con el modelo | Presupuesto de la mascota, modo ahorro, medición real en F5 |
| Cadena de suministro (binarios nativos: gramáticas, llama.cpp, onnxruntime) | Versiones fijadas con hash (`uv.lock`, `package-lock.json`, SHA-256 de llama.cpp) |

---

## 10. Preguntas y decisiones (resueltas el 2026-10-04)

| # | Pregunta | Respuesta del usuario | Decisión |
|---|---|---|---|
| P1 | Nombre del producto | "Ponle tú uno" | **Faro**. Paquete Python `faro`, identificador de Tauri `com.manahengarcia.faro`, directorio de datos `%LOCALAPPDATA%\com.manahengarcia.faro` (el mismo que usará Tauri con `app_local_data_dir()`). |
| P2 | Idioma de las preguntas | Español; inglés si resulta más eficiente | La comparativa de embeddings de la Fase 1 mide **las mismas preguntas en español y en inglés** con cada modelo. Así la recomendación de idioma sale de datos, no de intuición. |
| P3 | Contenido del instalador | A mi elección | Instalador completo: llama.cpp (CPU + CUDA 12.4), modelo de embeddings y WebView2 offline. Se revisa en la Fase 6 con los tamaños reales; si CUDA dispara el tamaño, pasa a componente opcional del instalador. |
| P4 | CI con GitHub Actions | Sí, montado profesionalmente | Desde la Fase 1: lint + tipos, tests en Ubuntu **y Windows**, la batería completa dentro de un *network namespace* sin red, acciones fijadas por SHA, permisos mínimos y Dependabot. |
| P5 | Windows Pro / Sandbox | Sí, Windows Pro | Aceptación de la Fase 6 en Windows Sandbox con `<Networking>Disable</Networking>`. |
| P6 | Fuente de documentación | DevDocs | Se implementa en la Fase 3, revisando formato y licencias de cada paquete. |
| P7 | Gramática de Dart | A mi elección | Gramática canónica `UserNobody14/tree-sitter-dart`, compilada desde el código fuente en el commit `be07cf7` (dependencia git fijada en `uv.lock`). Su binding devuelve un puntero entero (API deprecada en `tree-sitter` 0.26); se envuelve en un `PyCapsule` y un test lo vigila. |
| P8 | Salida de `check-prereqs.ps1` | Pendiente | El usuario lo ejecutará en su máquina. No bloquea la Fase 1 (el backend se desarrolla y prueba en Linux y en el CI de Windows). |
