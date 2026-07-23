# Poker Assistant IA

Ver [`prompt.md`](./prompt.md) para el objetivo, contexto, inventario de datos y las fases del proyecto.

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
- `decision/preflop/` — Fase 4.1: digitalización de rangos y tabla de lookup preflop.
  Ver `decision/preflop/parse_ranges.py` (genera `ranges.json` a partir de las capturas
  de ZEROSPOKER.COM en `/mnt/qnap/Poker/CAPTURAS HERRAMIENTAS PREFLOP/`). El OCR de la
  leyenda usa `tesserocr`, que necesita datos de idioma inglés instalados en el sistema
  (`sudo dnf install tesseract-langpack-eng` en Nobara) o, en su defecto, un
  `decision/preflop/tessdata/eng.traineddata` local (no versionado).
- `decision/rag/` — Fase 4.2-3: transcripción de vídeos, embeddings y motor RAG postflop.
- `hud/` — Fase 5: panel de salida con la recomendación.
- `packaging/` — Fase 6: manifest Flatpak (pendiente hasta tener un core funcional).
- `tests/` — Fase 7: capturas de referencia y tests de regresión.
