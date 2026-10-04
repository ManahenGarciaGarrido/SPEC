# SPEC — Asistente de programación personal, 100 % local

Eres el ingeniero principal de este proyecto. Este documento es la fuente de verdad: léelo entero antes de hacer nada. Si algo es ambiguo o crees que una decisión es mala, dilo y propón una alternativa antes de escribir código; no improvises en silencio.

## 1. Qué estamos construyendo y por qué

Una aplicación de escritorio para Windows que actúa como asistente de programación personal. Responde preguntas apoyándose en dos fuentes: el código del usuario (carpetas que él elige) y una base de documentación técnica descargada previamente. Todo se ejecuta en la máquina del usuario.

El usuario es ingeniero de software full-stack (Flutter/Dart, Node.js, Python, React, Docker). Quiere entender lo que se construye en todo momento, así que explica cada decisión relevante antes de implementarla.

Tres propiedades definen el producto. Si alguna se rompe, el producto ha fallado aunque todo lo demás funcione:

1. **Solo lectura.** La app jamás modifica, crea ni borra nada dentro de las carpetas del usuario.
2. **Sin red en uso normal.** Ninguna pregunta, fragmento de código ni telemetría sale de la máquina.
3. **Respuestas verificables.** Cada respuesta cita los archivos y líneas (o la página de documentación) en que se apoya.

## 2. Hardware objetivo

No hay una única máquina, así que el rendimiento se gestiona con perfiles:

| Perfil | Máquina | Modelo orientativo | Notas |
|---|---|---|---|
| `cpu` | 32 GB RAM, sin GPU | MoE de ~30B en Q4, todo en CPU | Leer contexto es lento: contexto pequeño (8-16K) y pocos fragmentos |
| `gpu-pequeno` | RTX 3070 portátil 8 GB VRAM + 16 GB RAM | ~7B entero en GPU | Rápido pero menos capaz |
| `gpu-hibrido` | 8 GB VRAM + 32 GB RAM | MoE de ~30B repartido GPU/RAM | Objetivo final. Ajustar `--n-cpu-moe` dejando ~700 MB de VRAM libres |

Los nombres de modelo son ejemplos (hoy: `Qwen3-Coder-30B-A3B` en GGUF Q4, `qwen2.5-coder:7b`). No los incluyas en el instalador: el usuario indica la ruta de un GGUF. En el primer arranque, detecta RAM y GPU (`nvidia-smi`) y propón un perfil.

## 3. Arquitectura

```
Ventana Tauri (React)  <--HTTP/SSE en 127.0.0.1-->  Backend Python (FastAPI)
                                                       |-- safe_fs: único acceso a carpetas del usuario
                                                       |-- indexador + búsqueda híbrida
                                                       |-- importador de documentación
                                                       `-- gestor de llama-server (proceso hijo)
```

Decisiones tomadas y su motivo. Respétalas salvo que encuentres un problema real, y en ese caso avisa:

- **Tauri 2** como contenedor, no Electron. Usa el WebView2 del sistema y consume mucha menos RAM, y la RAM hace falta para el modelo.
- **React + TypeScript + Vite** en el frontend. Animaciones con Motion; 3D con three.js mediante react-three-fiber.
- **Python + FastAPI** en el backend, empaquetado con PyInstaller y lanzado por Tauri como sidecar. Escucha solo en `127.0.0.1`, en un puerto libre elegido al arrancar, y exige un token de sesión generado por Tauri.
- **llama.cpp (`llama-server`)** como motor, gestionado como proceso hijo. Sirve para CPU y para GPU con el mismo binario y permite el reparto fino de un modelo MoE. Consulta `llama-server --help` de la versión instalada antes de usar cualquier flag: no supongas que existe. Permite también apuntar a un endpoint local compatible con OpenAI ya existente (por ejemplo, Ollama).
- **Embeddings en CPU** con un modelo pequeño vía ONNX (p. ej. fastembed). La VRAM se reserva entera para el modelo de lenguaje.
- **LanceDB** embebido como almacén vectorial, más búsqueda por palabras exactas, fusionadas (p. ej. RRF). En código, los identificadores exactos importan tanto como la similitud semántica.
- **Troceado con tree-sitter** por función/clase, con alternativa por líneas para lenguajes sin gramática. Prioridad: Dart, TypeScript/JavaScript, Python, Lua/Luau, y Markdown/YAML/JSON.
- **El modelo no tiene herramientas.** Es RAG puro: entra texto, sale texto. No puede leer, escribir ni ejecutar nada por sí mismo.

## 4. Garantías y cómo se demuestran

No basta con cumplirlas: cada una debe tener tests automáticos que fallen si se rompe.

**Solo lectura**
- Un único módulo, `safe_fs`, puede tocar las carpetas del usuario. Solo expone listar y leer, y abre siempre en modo lectura.
- Lista blanca de carpetas raíz. Toda ruta se resuelve a su ruta real y se rechaza si queda fuera (cubre `..`, enlaces simbólicos y junctions de Windows).
- La app solo escribe en su propio directorio de datos (`%LOCALAPPDATA%`): índice, configuración, registros.
- Tests: intentos de salir de la raíz; hash de una carpeta de prueba idéntico antes y después de indexar y consultar; comprobación estática de que ningún otro módulo abre archivos fuera del directorio de datos.

**Sin red**
- Ninguna llamada saliente en uso normal. Fuentes, iconos y librerías van empaquetados; nada de CDN. CSP de Tauri restrictiva. Sin telemetría ni comprobación de actualizaciones.
- Única excepción: las acciones "descargar documentación" y "descargar modelo", iniciadas explícitamente por el usuario, aisladas en un módulo y con indicador visible mientras duran.
- Test: la batería completa pasa con todo el tráfico bloqueado salvo loopback.

**Verificable**
- Cada fragmento recuperado conserva ruta, líneas inicial y final, y origen (código o documentación). La respuesta las muestra y, si no hay fuentes relevantes, lo dice en vez de inventar.

## 5. Interfaz

Tiene que ser una aplicación cuidada, no un chat genérico.

**Funcionalidad**
- Chat con respuesta en streaming, bloques de código con resaltado y botón de copiar, e historial local de conversaciones.
- Citas como etiquetas (archivo y líneas); al pulsarlas se abre un panel de vista previa de solo lectura con el fragmento resaltado.
- Panel de fuentes: añadir y quitar carpetas, estado y progreso del indexado, importación de documentación.
- Ajustes: perfil de hardware, ruta del modelo, tamaño de contexto, y un botón de prueba de rendimiento que muestra tokens/s leyendo y generando.
- Indicadores permanentes de "solo lectura" y "sin conexión" que reflejan el estado real, no un adorno.
- Asistente de primer arranque: perfil, modelo, primera carpeta.

**Dirección visual**
- Antes de implementar la interfaz, propón dos direcciones visuales distintas (paleta, tipografía, forma, carácter del movimiento) con una pantalla de muestra de cada una, y espera a que el usuario elija.
- Tema oscuro por defecto y tema claro. Un sistema de diseño con variables (color, espaciado, radios, duración y curvas de animación), no valores sueltos.
- Animaciones con significado: transiciones entre vistas, aparición de mensajes, progreso del indexado, estados de carga. Respeta `prefers-reduced-motion`.

**Mascota 3D**
- Personaje procedural: construido con geometría y animado por código. No dependas de modelos externos. Define una interfaz `MascotRig` para poder sustituirlo más adelante por un `.glb` con clips de animación sin tocar el resto.
- Máquina de estados ligada al estado real de la app: reposo, escuchando (el usuario escribe), pensando (búsqueda y lectura de contexto), hablando (streaming), contenta (respuesta completada), confusa (error o sin fuentes), dormida (inactividad). Transiciones suaves entre estados.
- Presupuesto gráfico estricto, porque comparte GPU y VRAM con el modelo: geometría ligera, sin posprocesado pesado, 30 fps en reposo, render pausado con la ventana oculta o minimizada, y un "modo ahorro" que la desactiva. Documenta en el README cómo asignar la app a la gráfica integrada en Windows.

## 6. Fases

Trabaja una fase cada vez. Al terminar cada una: tests en verde, un comando o demo para comprobarlo, un resumen en español de qué has hecho y por qué, y un commit. Después **para y espera el visto bueno**.

0. **Plan.** Comprueba los requisitos del sistema (Rust, Node, Python, herramientas de compilación de MSVC, WebView2) y di qué falta sin instalar nada a nivel de sistema por tu cuenta. Presenta el plan detallado, la estructura del repositorio y tus dudas. Crea `CLAUDE.md` con convenciones, comandos y estado de las fases. No escribas código de producto en esta fase.
1. **Núcleo de datos.** `safe_fs`, indexador incremental, embeddings, LanceDB, búsqueda híbrida y una CLI (`index`, `search`). Aceptación: tests de solo lectura y búsquedas que devuelven fragmentos con ruta y líneas.
2. **Motor y RAG.** Gestor de `llama-server`, perfiles, detección de hardware, prueba de rendimiento y endpoint de chat en streaming con citas. Aceptación: una pregunta sobre un repositorio de prueba se responde con citas desde la terminal.
3. **Documentación offline.** Importador desde carpetas locales de Markdown/HTML y acción explícita de descarga. Aceptación: las respuestas distinguen entre código propio y documentación.
4. **Interfaz.** Elección de dirección visual, sistema de diseño, chat, panel de fuentes, vista previa, ajustes. Aceptación: flujo completo usable desde la ventana.
5. **Mascota y pulido.** Mascota con todos sus estados, animaciones, modo ahorro. Aceptación: el consumo de VRAM de la interfaz está medido y documentado.
6. **Empaquetado.** Sidecar, instalador `.exe` de Windows, asistente de primer arranque, README. Aceptación: instala y funciona en un Windows limpio sin conexión.
7. **Evaluación.** Conjunto de unas 20 preguntas reales sobre repositorios del usuario para medir la calidad de la recuperación y ajustar troceado, número de fragmentos y contexto.

## 7. Reglas de trabajo

- Explicaciones en español; código, nombres y comentarios en inglés.
- Comprueba las versiones y APIs actuales en la documentación oficial de cada dependencia en lugar de fiarte de la memoria, y fija las versiones.
- No presentes como terminado nada simulado o a medias. Si algo no se puede hacer o no lo has podido verificar, dilo claramente.
- Tests con pytest en el backend y vitest en el frontend. Los tests automáticos usan un endpoint de modelo simulado; el modelo real solo se usa en la prueba de rendimiento manual.
- Mantén `CLAUDE.md` actualizado al cerrar cada fase.
- Cambios pequeños y revisables. No añadas funcionalidad fuera de esta especificación sin proponerla antes.
