# Poker Assistant IA

Ver [`prompt.md`](./prompt.md) para el objetivo, contexto, inventario de datos y las fases del proyecto.

## Uso (alpha)

`./poker-assistant` — calibra el recuadro de la mesa si hace falta (o con `--recalibrate`
para forzarlo) y arranca `alpha.py`: un lazo de diagnóstico que captura la mesa cada
pocos segundos, corre el reconocimiento de la Fase 3 (mazo de 4 colores) y va imprimiendo
por consola lo que detecta (cartas, board, pot, ciegas, jugadores) para validarlo en vivo
mientras juegas. Todavía no da recomendaciones (eso es la Fase 4/5) ni dispara por cambio
de board (Fase 2) — es solo para comprobar que la visión funciona contra partidas reales.

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
  con opencv en el mismo proceso), invocado desde `ocr_client.py`. `run_samples.py`
  corre el pipeline contra `vision/samples/` y vuelca `vision/results.json`. Esto es
  para el mazo blanco (capturas de YouTube); el mazo real de PokerStars (4 colores,
  fondo de color + texto blanco) tiene su propia rama: `color_card_detector.py`
  (palo por color de fondo, sin plantilla) + `color_rank_ocr.py`, orquestados por
  `table_state.analyze_color_deck()`. `run_samples_pokerstars.py` corre esta rama
  contra `vision/samples_pokerstars/` y vuelca `vision/results_pokerstars.json`.
- `decision/preflop/` — Fase 4.1: digitalización de rangos y tabla de lookup preflop.
  Ver `decision/preflop/parse_ranges.py` (genera `ranges.json` a partir de las capturas
  de ZEROSPOKER.COM en `/mnt/qnap/Poker/CAPTURAS HERRAMIENTAS PREFLOP/`). El OCR de la
  leyenda usa `tesserocr`, que necesita datos de idioma inglés instalados en el sistema
  (`sudo dnf install tesseract-langpack-eng` en Nobara) o, en su defecto, un
  `decision/preflop/tessdata/eng.traineddata` local (no versionado).
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
