# Poker Assistant IA

Ver [`prompt.md`](./prompt.md) para el objetivo, contexto, inventario de datos y las fases del proyecto,
y [`docs/PENDIENTE.md`](./docs/PENDIENTE.md) para lo que queda por hacer y en qué orden.

## Modo testing

La casilla **"Grabar sesión de testing"** de la GUI (se activa antes de darle a
"Iniciar análisis") guarda cada frame junto con TODO lo que la app calculó de él,
emparejados por nombre:

```
testing/sesion-2026-07-25_193012/
    _sesion.json      metadatos: inicio, intervalo, recuadro, commit, nº de frames
    0001.png          el frame tal cual se analizó
    0001.json         GameState completo (con warnings), recomendación, evaluación
                      de mano, equity postflop y resumen de la mano anterior
    0002.png
    0002.json
```

La dupla es por **nombre** (mismo número, distinta extensión), que es lo que
permite abrir el PNG y mirar el JSON de al lado sin cruzar timestamps. El JSON
incluye los `warnings`, que suelen ser lo más informativo cuando algo sale mal, y
el tiempo que tardó el análisis de ese frame.

La **equity postflop se calcula y se graba** aunque todavía no se muestre en el
HUD: es justo el número que hay que contrastar contra frames reales antes de
enseñarlo, así que grabarlo es el paso previo a cablearlo.

`testing_session.resumen(carpeta)` da un agregado de la sesión (frames, cuántos
con recomendación, motivos de abstención más frecuentes) sin abrir los frames uno
a uno. La carpeta `testing/` no se versiona.

## Uso (alpha)

`./poker-assistant` — calibra el recuadro de la mesa si hace falta (o con `--recalibrate`
para forzarlo) y arranca `alpha.py`: un lazo de diagnóstico que captura la mesa cada
pocos segundos, corre el reconocimiento de la Fase 3 (mazo de 4 colores) y va imprimiendo
por consola lo que detecta (cartas, board, pot, ciegas, jugadores) para validarlo en vivo
mientras juegas. Todavía no da recomendaciones (eso es la Fase 4/5) ni dispara por cambio
de board (Fase 2) — es solo para comprobar que la visión funciona contra partidas reales.

`.venv/bin/python gui.py` — panel de control GTK4 (Fase 5): envuelve el mismo flujo que
`alpha.py` en una ventana no bloqueante. El análisis (captura + OCR) corre en un hilo
aparte y actualiza los widgets vía `GLib.idle_add`, así que la UI no se congela. Muestra el
estado detectado (tus cartas, board, bote, jugadores con posición y stack), una sección
"Mano actual" con la mano formada y los proyectos + % que devuelve `decision/hand_strength.py`
(oculta entre manos, cuando no hay cartas del hero), la recomendación de `engine.decide` en
grande (o el motivo si no la hay), una sección "Mano anterior" que resume la última mano
terminada leyendo el resultado del panel de chat (`vision/hand_result.py`: ganador, importe,
mano ganadora, jugadores de showdown y si el hero ganó/perdió/**empató** el bote), un campo de ciegas que escribe
`blinds.local.json` en el mismo formato que `./set-blinds` (intercambiables), y botones para
iniciar/parar el análisis y relanzar la calibración del recuadro. El selector de intervalo baja
hasta 0.25s ("analiza en cuanto pueda"; el ciclo real tarda ~2-4s por el OCR).

## Estructura

- `calibration/` — Fase 0: `select_region.py` toma un frame de referencia (vía
  `capture/portal_capture.py`) y deja dibujar con el ratón el recuadro de la mesa;
  guarda las coordenadas en `calibration/config.local.json` (no versionado).
- `capture/` — Fase 1: `portal_capture.py` abre una sesión de
  `org.freedesktop.portal.ScreenCast` y consume el stream de PipeWire con GStreamer.
  El `restore_token` se guarda en `capture/config.local.json`, aunque en KDE Plasma
  6.7 el selector de pantalla vuelve a aparecer en cada arranque del proceso (no
  evita la interacción, solo el permiso). Necesita `PyGObject`/`GStreamer` del
  sistema — el venv del proyecto se creó con `include-system-site-packages = true`
  en `.venv/pyvenv.cfg` para verlos sin tener que compilarlos aparte.
- `vision/` — Fase 3: reconocimiento del estado de mesa (cartas, stacks, pot...).
  `table_state.py` (`analyze(image_path) -> GameState`) orquesta `table_region.py`
  (localiza el ovalo por el borde rojo), `card_detector.py` (cartas por contorno
  blanco+forma, sin coordenadas fijas ni color de tapete), `suit_classifier.py`
  (palo por color + forma contra las plantillas de `card_templates/`, generadas
  una vez por `generate_card_templates.py`) y `text_extract.py` (pot/ciegas/
  jugador+stack por regex sobre lineas OCR, sin posiciones fijas). El OCR usa
  `tesserocr` aislado en `ocr_worker.py` (mismo motivo que
  `decision/preflop/ocr_worker.py`: evitar corrupcion de memoria al mezclarlo
  con opencv en el mismo proceso), invocado desde `ocr_client.py`. El **idioma
  del OCR se elige por tipo de job**: el texto libre de la UI (nameplates, chat,
  bote, botones, ciegas) se lee con el modelo **espanol** porque el cliente esta
  en castellano — con el modelo ingles los acentos se corrompen
  ("Informaci6n" por "Información") y eso degrada el emparejado de
  `SEAT_STATUS_WORDS`, el parseo del chat y el de ciegas —, mientras el OCR de
  **rango de carta** sigue en ingles (whitelist de digitos+AKQJ, ya ajustado, y
  sin una sola palabra en castellano que ganar). Requiere espanol e ingles en el
  MISMO directorio de tessdata (lo exige tesseract): `sudo dnf install
  tesseract-langpack-spa`, o `vision/tessdata/{spa,eng}.traineddata` local (no
  versionado). Sin espanol disponible cae a ingles para todo, el comportamiento
  anterior. `run_samples.py`
  corre el pipeline contra `vision/samples/` y vuelca `vision/results.json`. Esto es
  para el mazo blanco (capturas de YouTube); el mazo real de PokerStars (4 colores,
  fondo de color + texto blanco) tiene su propia rama: `color_card_detector.py`
  (palo por color de fondo, sin plantilla) + `color_rank_ocr.py`, orquestados por
  `table_state.analyze_color_deck()`. `run_samples_pokerstars.py` corre esta rama
  contra `vision/samples_pokerstars/` y vuelca `vision/results_pokerstars.json`.
  `hand_result.py` parsea el resultado de la última mano terminada de las líneas
  del chat (`parse_hand_result`: nº de mano, ganador(es), importe, mano ganadora y
  showdown; tolerante al ruido del OCR, no inventa). Cubre los **botes divididos**
  ("X empata por el bote", una línea por jugador con el mismo nº de mano →
  `split=True` y `winners` con todos), los **nicks cuyo guión bajo el OCR lee como
  espacio** ("david_sagunt" → "david sagunt": se admite un espacio interno y
  `_norm_name` normaliza para que ambas formas casen) y las **manos con coma**
  ("doble pareja, damas y sietes"). La frase de mano se busca sólo dentro del
  mismo mensaje del chat (hasta el siguiente "Repartidor:"/"Mano n.") en vez de
  en una ventana fija de caracteres, y las líneas se reordenan por posición
  visual antes de unirlas porque el modo `SPARSE_TEXT` de tesseract no las
  devuelve en orden de lectura y OCR-ea la zona del chat por
  su cuenta (`read_chat_lines`, reutilizando `seat_map` + `OcrBatch`, ya que
  `analyze_layout` lee el chat pero no lo expone en el GameState); `hero_outcome`
  decide si el hero ganó/perdió con la evidencia del chat. `test_hand_result.py`
  es un script suelto (sin pytest) que lo verifica con las líneas de chat reales
  más variantes con ruido de OCR. Lo consume el panel "Mano anterior" de `gui.py`.
- `decision/preflop/` — Fase 4.1: digitalización de rangos y tabla de lookup preflop.
  Ver `decision/preflop/parse_ranges.py` (genera `ranges.json` a partir de las capturas
  de ZEROSPOKER.COM en `/mnt/qnap/Poker/CAPTURAS HERRAMIENTAS PREFLOP/`). El OCR de la
  leyenda usa `tesserocr`, que necesita datos de idioma inglés instalados en el sistema
  (`sudo dnf install tesseract-langpack-eng` en Nobara) o, en su defecto, un
  `decision/preflop/tessdata/eng.traineddata` local (no versionado). `lookup.py`
  (`recommend(hero_cards, hero_position, stack_bb, facing, vs_position=None)`) consulta
  `ranges.json`: normaliza las cartas del hero a la notación del rango (orden de rango
  alto primero), busca el stack_bb más cercano entre las claves disponibles para ese
  `facing` y devuelve la etiqueta de acción tal cual salió de la leyenda, o `None` si
  falta algún dato. `test_lookup.py` es un script suelto (sin pytest, el proyecto no lo
  usa) que lo verifica contra casos leídos a mano de `ranges.json`.
- `decision/engine.py` — Fase 4 (primera pieza): dado el `GameState` de `vision/`, si es
  preflop y hay cartas+posición+stack_bb (stack del hero / `blinds["bb"]`), llama a
  `decision/preflop/lookup.py` y devuelve `{action, reasoning, hero_cards, hero_position,
  stack_bb}`. Si falta cualquier dato (sin board vacío, sin ciegas, sin posición...)
  devuelve `None` y anota el motivo en `warnings`. Cuando sí recomienda pero sobre datos
  de fiabilidad reducida, lo **dice** en vez de callarlo: (a) si las ciegas manuales de
  `blinds.local.json` llevan más de 10 min sin actualizar (antigüedad por el `mtime` del
  fichero) avisa de que, si el nivel ya subió, la profundidad en bb —y con ella el
  rango— está mal; (b) si la profundidad real cae a más de 2.6bb de la clave de stack
  que usó `lookup` (p.ej. 100bb al principio de un torneo, que cae en el rango de 40bb,
  el máximo digitalizado) marca la acción como extrapolada. Ambos avisos van a
  `warnings` y al `reasoning` que ve el usuario. Limitación conocida: el `GameState`
  no registra el historial de apuestas de la mano, así que el juicio de si el hero abre
  o responde a una subida se hace con lo que hay dibujado en ese frame (importes
  apostados por asiento), no con el historial real de la calle.
  `alpha.py` ya lo integra: imprime `Recomendacion: <accion>` bajo el resto del estado
  cuando hay recomendación.
- `decision/hand_strength.py` — evaluación de mano para el HUD (no es motor de decisión).
  `evaluate_hand(hero_cards, board)` devuelve (a) la **mano formada** (mejor combinación de 5,
  nombrada en español: "Pareja de Reyes", "Color de corazones", "Doble pareja (Ases y Reyes)"...;
  en preflop, "AK suited"/"Pareja de Ochos") y (b) la lista de **proyectos** (color 9 outs,
  escalera abierta 8, gutshot 4, sobrecartas, doble proyecto color+escalera con outs limpios
  sin solapar) con outs y % de **completar** el proyecto, tanto exacto (combinatoria) como por
  la regla del 2 y 4. **No** es equity contra el rango rival (eso exigiría Monte Carlo): es
  mano actual + probabilidad de ligar, etiquetado así en la UI para no engañar. Pure Python, sin
  dependencias nuevas. `test_hand_strength.py` es un script suelto (sin pytest) con casos a mano.
- `decision/rag/` — Fase 4.2: transcripción de vídeos (Fase 4.3, embeddings/retrieval,
  queda pendiente). `video_index.py` localiza y ordena los vídeos de
  `TORNEOS/6. EL CURSO ABSOLUTO...` y `TORNEOS/5. CONTENIDO DE TEORÍA POSTFLOP...`
  (las dos carpetas prioritarias). `extract_audio.py` saca el audio a WAV mono 16kHz
  con ffmpeg. `transcribe.py` transcribe con `faster-whisper` (modelo `small`, CPU,
  int8 — ver docstring para la comparativa con `medium`). `chunk.py` agrupa las frases
  de Whisper en fragmentos de ~60s. `pipeline.py` encadena los tres pasos por vídeo y
  escribe `decision/rag/transcripts/<video_id>.json` (lista de
  `{video, video_path, chunk_index, start_time, end_time, text}`) más
  `decision/rag/transcripts/_benchmark.json` con el tiempo/tamaño real de cada vídeo
  procesado, usado para extrapolar el coste del corpus completo. El audio intermedio
  (`decision/rag/audio/*.wav`) no se versiona (grande y reproducible desde el vídeo
  fuente); los JSON de `transcripts/` sí, por ser el producto final y pesar poco.
  `run_batch.py` reparte los 126 vídeos prioritarios en N procesos `pipeline.py` en
  paralelo para bajar el tiempo de reloj (cada proceso ya usa varios núcleos, pero no
  todos). Fase 4.3 (embeddings/retrieval) queda pendiente.
- `hud/` — Fase 5: panel de salida con la recomendación.
- `packaging/` — Fase 6: manifest Flatpak (pendiente hasta tener un core funcional).
- `tests/` — Fase 7: capturas de referencia y tests de regresión.
