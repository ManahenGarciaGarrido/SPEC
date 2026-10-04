# CLAUDE.md

Asistente de programación personal para Windows, 100 % local (nombre provisional **Faro**; ver P1 en el plan).

- **Especificación (fuente de verdad):** [`docs/SPEC.md`](docs/SPEC.md). Léela entera antes de cambiar nada.
- **Plan, decisiones y su motivo:** [`docs/PLAN.md`](docs/PLAN.md).

## Invariantes (si se rompe uno, el producto ha fallado)

1. **Solo lectura.** Nada se crea, modifica ni borra dentro de las carpetas del usuario.
2. **Sin red en uso normal.** Solo las acciones explícitas "descargar documentación" y "descargar modelo" salen a Internet.
3. **Respuestas verificables.** Cada respuesta cita ruta y líneas (o página de documentación), o dice que no hay fuentes.

Además: **el modelo no tiene herramientas** (RAG puro: entra texto, sale texto).

### Fronteras de módulos del backend (se comprueban con tests estáticos)

| Solo este módulo… | …puede |
|---|---|
| `faro.safe_fs` | Leer y listar carpetas del usuario (sin API de escritura) |
| `faro.datadir` | Abrir, crear o escribir archivos y conexiones (SQLite, LanceDB), siempre dentro del directorio de datos |
| `faro.net` | Importar librerías de red. `net.loopback` rechaza hosts no loopback; `net.download` es la única salida a Internet |

Si un cambio necesita saltarse una frontera, se para y se propone antes; no se añade una excepción al test.

## Reglas de trabajo

- Explicaciones, documentación y textos de la interfaz en **español**; código, nombres e identificadores, comentarios y mensajes de commit en **inglés**.
- Antes de usar una dependencia o un flag, **comprobar la versión y la API actuales** en la fuente oficial (registro, código, `--help` del binario instalado). No fiarse de la memoria.
- **Versiones fijadas:** `uv.lock` (con hashes), `package-lock.json` con `save-exact=true`, `Cargo.lock`, y SHA-256 para binarios externos (llama.cpp, modelo de embeddings).
- **Tests:** pytest en el backend y vitest en el frontend. Los automáticos usan un endpoint de modelo **simulado**; el modelo real solo se usa en la prueba de rendimiento manual.
- Los tests que solo pueden correr en Windows se marcan `windows_only` y se saltan con aviso en otros sistemas. **Nunca** se declara verificado algo que no se ha ejecutado.
- Nunca se salta, desactiva ni pone en cuarentena un test para poner la batería en verde.
- Cambios pequeños y revisables. Nada fuera de la especificación sin proponerlo antes.
- Explicar cada decisión relevante **antes** de implementarla.

## Flujo por fases

Una fase cada vez. Al cerrarla: tests en verde, comando de demo, resumen en español de qué se hizo y por qué, commit, actualizar este archivo y **parar hasta el visto bueno del usuario**.

| Fase | Estado |
|---|---|
| 0. Plan | ✅ Entregada, pendiente de visto bueno y de las respuestas a las preguntas P1–P8 de `docs/PLAN.md` |
| 1. Núcleo de datos (`safe_fs`, indexador, embeddings, LanceDB, búsqueda híbrida, CLI) | ⏳ No iniciada |
| 2. Motor y RAG (`llama-server`, perfiles, hardware, benchmark, chat SSE con citas) | ⏳ |
| 3. Documentación offline | ⏳ |
| 4. Interfaz (dos direcciones visuales → elección → implementación) | ⏳ |
| 5. Mascota 3D y pulido | ⏳ |
| 6. Empaquetado (instalador `.exe`, primer arranque, README) | ⏳ |
| 7. Evaluación (~20 preguntas reales) | ⏳ |

## Comandos

Disponibles ahora:

```powershell
# Comprobar requisitos de desarrollo en Windows (solo lectura, no instala nada)
powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1
powershell -ExecutionPolicy Bypass -File scripts\check-prereqs.ps1 -Json
```

Previstos (se activarán en su fase; hasta entonces no existen):

```bash
# Backend (desde backend/), Fase 1+
uv sync                                   # entorno con versiones fijadas
uv run pytest                             # toda la batería, con la red bloqueada salvo loopback
uv run ruff check . && uv run ruff format --check . && uv run mypy src
uv run faro roots add <carpeta> | faro index | faro search "<consulta>"
uv run faro ask "<pregunta>" | faro bench | faro hw          # Fase 2+

# Frontend y app (desde app/), Fase 4+
npm ci
npm test                                  # vitest
npm run tauri dev                         # app en desarrollo (solo Windows)
npm run tauri build                       # instalador (Fase 6)
```

## Entorno

- **Objetivo:** Windows 10 1809+/11 x64. Perfiles de hardware `cpu`, `gpu-pequeno` y `gpu-hibrido` (ver la especificación, §2).
- **Sesiones en la nube de Claude Code:** contenedor Linux efímero, sin GPU y sin Windows. Aquí se pueden ejecutar los tests de backend y frontend, el lint y `cargo check`. No se puede ejecutar nada específico de Windows (junctions, WebView2, MSVC, instalador) ni medir rendimiento real: eso lo valida el CI de Windows (si se aprueba) o el usuario en su máquina.
- Lo que haya que conservar debe estar commiteado y subido: el contenedor se pierde.

## Decisiones registradas

Detalle y motivo en `docs/PLAN.md` §4. Resumen:

- Gramáticas de tree-sitter como **wheels individuales** (el "language pack" descarga en tiempo de ejecución). Dart: gramática canónica compilada por nosotros (pendiente de P7).
- Embeddings con fastembed **siempre offline** (`local_files_only`, `HF_HUB_OFFLINE=1`); el modelo por defecto se elige por comparativa en F1.
- `llama-server` siempre con `--no-webui --no-agent --offline --host 127.0.0.1 --api-key <aleatoria>`, entorno sin `LLAMA_*`/`HF_*`, y flags detectados con `--help` del binario real. Perfil híbrido: `--fit on --fit-target 700` (a validar en hardware real).
- Backend con PyInstaller **`--onedir`** lanzado desde Rust como recurso, dentro de un Job Object de Windows.
- Token de sesión por **stdin**; el backend elige el puerto (`127.0.0.1:0`) y lo anuncia por stdout.
- Endpoint externo (Ollama) **solo loopback**.
- TypeScript **6.0.3** (no 7.x todavía), React **19.3.x** (límite de `@react-three/fiber` 9.8).
