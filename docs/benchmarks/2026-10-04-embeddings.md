# Comparativa de modelos de *embeddings* (2026-10-04)

**Pregunta:** ¿qué modelo de *embeddings* usar por defecto, sabiendo que las preguntas serán normalmente en español sobre código escrito en inglés? ¿Compensa preguntar en inglés? (P2 de `docs/PLAN.md`)

## Decisión

**Por defecto: `qwen3-0.6b-int8`.** Es el único modelo que encuentra bien el código con preguntas en **español** (75 % de acierto en el top 3 y 94 % en el top 5, frente al 44 % y 50 % del modelo de código de Jina). En inglés empata con el mejor (88 % en el top 3).

Su coste es real y lo asumimos a sabiendas:
- **Indexado inicial unas 7 veces más lento** que Jina (0,5 frente a 3,6 fragmentos/s en este entorno de 4 vCPU). Solo ocurre la primera vez: después el indexado es incremental.
- **Más memoria:** pico de unos 3,4 GB mientras indexa y unos 1,4 GB fijos para las consultas. Cabe en el perfil `cpu` (32 GB) junto a un modelo de lenguaje de unos 18,6 GB.
- **~0,6 s por consulta** para vectorizar la pregunta, que es despreciable frente a lo que tarda el modelo de lenguaje en responder.

**Alternativa rápida si prefieres preguntar en inglés:** `faro models use jina-code-int8`. Indexa 7 veces más rápido, usa menos memoria y en inglés acierta igual o más (88 % en el top 3, 100 % en el top 5), pero en español falla con frecuencia.

Así que la respuesta a la P2 es: **preguntar en inglés sí es más eficiente**, porque permite un modelo 7 veces más rápido sin perder calidad. Pero con Qwen3 puedes preguntar en español sin perder casi nada; es lo que dejo por defecto.

## Cómo se ha medido

- **Corpus:** dos repositorios públicos del mismo stack que usas, fijados por commit (`backend/tools/bench/queries.json`):
  - [Wonderous](https://github.com/gskinnerTeam/flutter-wonderous-app) (app Flutter/Dart de gskinner) @ `747b945`
  - [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template) (Python + React/TypeScript) @ `1762ada`
  - En total, 570 archivos indexables y 1.954 fragmentos, indexados juntos: cada pregunta compite contra los dos repositorios.
- **Preguntas:** 16 escritas a mano después de leer el código, cada una en **español** y en **inglés** (32 consultas). Cada pregunta tiene uno o varios archivos que la responden, comprobados a mano.
- **Métrica:** se mira si un archivo correcto aparece entre los *k* primeros archivos distintos (acierto en el top 1/3/5), y el MRR@10 (media de 1/posición del primer acierto). Para un asistente RAG importa sobre todo el **top 3–5**, porque es lo que entra en el contexto del modelo.
- **Modos:** la búsqueda **híbrida** (la que usa el producto: vectores + palabras exactas con fusión RRF), solo vectores y solo texto (BM25).
- **Entorno:** todo **sin red**, dentro de un *network namespace* (el guardia registró 0 intentos de conexión), en el contenedor Linux de esta sesión: 4 vCPU y sin GPU. Los tiempos absolutos de tu máquina serán distintos; lo comparable son las **proporciones** entre modelos.
- **Reproducir:** `tools/bench/fetch_corpus.sh <dir>` y luego `uv run python tools/bench_embeddings.py --models-data <dir-modelos> --corpus <dir> --models … --out informe.json`; las tablas salen de `tools/bench_report.py`.

**Limitaciones:** 32 consultas son pocas para afinar decimales; sirven para ver diferencias grandes, no del 5 %. La evaluación con tus repositorios reales es la Fase 7.

## Resultados

Datos completos en [`2026-10-04-embeddings.json`](2026-10-04-embeddings.json).

| Modelo | Fragmentos | Indexado | Fragmentos/s | Consulta (mediana) | Carga |
|---|---|---|---|---|---|
| `jina-code-int8` | 1954 | 548 s | 3.6 | 41 ms | 0.8 s |
| `qwen3-0.6b-int8` | 1954 | 3676 s | 0.5 | 619 ms | 13.8 s |
| `jina-code` | 1954 | 996 s | 2.0 | 46 ms | 7.6 s |
| `jina-es-int8` | 1954 | 362 s | 5.4 | 32 ms | 1.0 s |

**Híbrida (la del producto)**: acierto en el top 1 / top 3 / top 5 y MRR@10

| Modelo | Español | Inglés |
|---|---|---|
| `jina-code-int8` | 38 % / 44 % / 50 % · MRR 0.45 | 69 % / 88 % / 100 % · MRR 0.80 |
| `qwen3-0.6b-int8` | 56 % / 75 % / 94 % · MRR 0.71 | 75 % / 88 % / 94 % · MRR 0.84 |
| `jina-code` | 38 % / 44 % / 56 % · MRR 0.45 | 69 % / 88 % / 100 % · MRR 0.81 |
| `jina-es-int8` | 38 % / 62 % / 62 % · MRR 0.53 | 62 % / 81 % / 81 % · MRR 0.73 |

**Solo vectores**: acierto en el top 1 / top 3 / top 5 y MRR@10

| Modelo | Español | Inglés |
|---|---|---|
| `jina-code-int8` | 31 % / 38 % / 56 % · MRR 0.40 | 75 % / 75 % / 88 % · MRR 0.79 |
| `qwen3-0.6b-int8` | 69 % / 88 % / 94 % · MRR 0.79 | 56 % / 94 % / 100 % · MRR 0.74 |
| `jina-code` | 31 % / 38 % / 50 % · MRR 0.39 | 75 % / 75 % / 88 % · MRR 0.80 |
| `jina-es-int8` | 38 % / 56 % / 62 % · MRR 0.50 | 38 % / 50 % / 69 % · MRR 0.51 |

**Solo texto**: acierto en el top 1 / top 3 / top 5 y MRR@10

| Modelo | Español | Inglés |
|---|---|---|
| `jina-code-int8` | 6 % / 12 % / 19 % · MRR 0.11 | 50 % / 81 % / 88 % · MRR 0.66 |
| `qwen3-0.6b-int8` | 6 % / 12 % / 19 % · MRR 0.11 | 50 % / 81 % / 88 % · MRR 0.66 |
| `jina-code` | 6 % / 12 % / 19 % · MRR 0.11 | 50 % / 81 % / 88 % · MRR 0.66 |
| `jina-es-int8` | 6 % / 12 % / 19 % · MRR 0.11 | 50 % / 81 % / 88 % · MRR 0.66 |

Posición del primer archivo correcto por pregunta (híbrida; `—` = fuera del top 10):

| Pregunta | `jina-code-int8` es / en | `qwen3-0.6b-int8` es / en | `jina-code` es / en | `jina-es-int8` es / en |
|---|---|---|---|---|
| f1 | 1 / 1 | 2 / 1 | 1 / 1 | 2 / 1 |
| f2 | 5 / 1 | 2 / 1 | 4 / 1 | — / — |
| f3 | 1 / 1 | 1 / 2 | 2 / 1 | 2 / 1 |
| f4 | 7 / 2 | 4 / 1 | 8 / 2 | 7 / 2 |
| f5 | 6 / 4 | 7 / 4 | 5 / 4 | 9 / 8 |
| f6 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| f7 | 2 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| f8 | 1 / 1 | 1 / 1 | 1 / 1 | 2 / 1 |
| w1 | — / 5 | 1 / 6 | — / 5 | — / — |
| w2 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| w3 | — / 2 | 1 / 1 | — / 2 | 7 / 2 |
| w4 | — / 1 | 2 / 1 | — / 1 | 1 / 1 |
| w5 | 9 / 3 | 1 / 2 | 10 / 2 | 8 / 2 |
| w6 | 1 / 1 | 1 / 1 | 1 / 1 | 1 / 1 |
| w7 | — / 1 | 5 / 1 | — / 1 | 1 / 1 |
| w8 | — / 1 | 4 / 1 | — / 1 | 2 / 1 |


Memoria (RSS del proceso) al vectorizar 256 fragmentos reales en modo indexado:

| Modelo | Pico al indexar | Memoria fija para consultas |
|---|---|---|
| `qwen3-0.6b-int8` | 3,4 GB | ~1,4 GB |
| `jina-code-int8` | ~2,2 GB | ~0,4 GB |
| `jina-es-int8` | 1,2 GB | ~0,4 GB |

## Qué se aprende

1. **El idioma de la pregunta importa más que el tamaño del modelo.** Con un modelo entrenado solo en inglés (`jina-code`), pasar la misma pregunta del inglés al español baja el acierto en el top 3 del 88 % al 44 %. Qwen3, multilingüe, lo reduce a un 75 %.
2. **La búsqueda híbrida ayuda en inglés y estorba algo en español.** En inglés, la híbrida mejora a la de solo vectores con Jina (88 % frente a 75 % en el top 3). En español, las palabras de la pregunta casi nunca están en el código: la parte de texto aporta ruido, y con Qwen3 la búsqueda solo por vectores llega al 88 % frente al 75 % de la híbrida. Ajustar el peso de cada parte según el idioma es un candidato para la **Fase 7**, que tendrá tus preguntas reales; con 32 consultas sería sobreajustar.
3. **La cuantización int8 no cuesta calidad aquí.** `jina-code` (fp32) y `jina-code-int8` aciertan exactamente igual, y la versión int8 es 1,8 veces más rápida y 4 veces más pequeña.
4. **El bilingüe `jina-es` es el más rápido** (5,4 fragmentos/s) y mejora el español respecto a Jina código (62 % en el top 3), pero queda por detrás de Qwen3 en ambos idiomas. Es una opción razonable para repositorios muy grandes.
5. **Vectorizar en CPU es el cuello de botella del indexado.** Trocear los 570 archivos lleva 0,6 s; vectorizarlos, minutos. Este estudio llevó a tres correcciones del indexador (`docs/PLAN.md` §11, punto 12).
