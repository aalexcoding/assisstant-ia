# Poker Assistant IA

Ver [`prompt.md`](./prompt.md) para el objetivo, contexto, inventario de datos y las fases del proyecto.

## Estructura

- `calibration/` — Fase 0: selector de recuadro y guardado de coordenadas.
- `capture/` — Fase 1: captura continua vía portal ScreenCast + PipeWire.
- `vision/` — Fase 3: reconocimiento del estado de mesa (cartas, stacks, pot...).
- `decision/preflop/` — Fase 4.1: digitalización de rangos y tabla de lookup preflop.
- `decision/rag/` — Fase 4.2-3: transcripción de vídeos, embeddings y motor RAG postflop.
- `hud/` — Fase 5: panel de salida con la recomendación.
- `packaging/` — Fase 6: manifest Flatpak (pendiente hasta tener un core funcional).
- `tests/` — Fase 7: capturas de referencia y tests de regresión.
