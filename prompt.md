# Poker Assistant IA — Prompt de proyecto

## Objetivo
Construir una app de Linux (empaquetada como Flatpak, compatible con Bazaar) que:
1. Capture una región de pantalla definida por el usuario (una ventana de máquina virtual Windows donde corre PokerStars con skin estándar).
2. Reconozca automáticamente el estado de la mesa de Texas Hold'em (cartas propias, board, pot, stacks, posición, acciones disponibles) cada vez que el tablero cambia.
3. Compare ese estado con un motor de decisión ("caja negra") entrenado/alimentado con el estilo de juego del usuario.
4. Muestre una recomendación de acción (fold/call/raise + sizing) en un panel tipo HUD anclado bajo la ventana capturada, con una latencia máxima aceptable de 5 segundos.

## Contexto y decisiones ya tomadas
- Sala: PokerStars, skin/tema estándar (no se cambia).
- Sesión gráfica: Wayland (Nobara Linux).
- La región capturada corresponde a una ventana de una máquina virtual Windows (donde corre el cliente de PokerStars), ajustada para mostrar solo la ventana del juego. La app no necesita saber nada de la VM: solo captura los píxeles de esa región del escritorio host, igual que si PokerStars corriera nativamente en Linux.
- Disparo del análisis: automático, cuando el motor detecta que cambió el board (nueva calle o nueva mano). No hay disparo manual.
- Salida: panel HUD fijo, anclado justo debajo del recuadro capturado (no overlay transparente encima de las cartas, no ventana suelta en otro sitio).
- Datos disponibles para entrenar el motor de decisión: `/mnt/qnap/Poker/` (ver inventario abajo). NO hay hand histories (logs mano a mano con decisiones reales) todavía.
- Tolerancia de latencia: hasta 5 segundos entre detectar el cambio de board y mostrar la recomendación.
- Empaquetado: Flatpak, para que sea instalable/visible desde Bazaar.
- Formato: **torneos** (confirmado). El material de cash se descarta como fuente de entreno para v1; la Fase 4 se prioriza 100% para torneos, incluyendo la posibilidad de añadir lógica ICM (burbuja, mesa final) más adelante.

## Aviso importante (ToS)
Usar un asistente que da recomendaciones en tiempo real durante partidas de dinero real en PokerStars entra dentro de lo que la sala define como "Real-Time Assistance" (RTA), explícitamente prohibido en sus Términos de Servicio, con riesgo de cierre de cuenta. Es un buen encaje para estudio, revisión post-mano, mesas play-money o partidas privadas. Si se usa en dinero real, queda bajo criterio y responsabilidad del usuario.

## Inventario de datos (`/mnt/qnap/Poker/`)

### `CAPTURAS HERRAMIENTAS PREFLOP/` — gráficos de rango preflop (398 PNG)
- `OPEN RAISE/` (100 imágenes) y `3BET-CALL/` (300 imágenes), cada una subdividida por profundidad de stack efectivo (`OPEN RAISE`: 4/6/8/10/12.5/15/20/25/30/35/40 BB; `3BET-CALL`: 10/15/20/25/30/35/40 BB) y dentro de cada stack, una imagen por posición (BB, SB, BTN, CO, HJ, MP2, MP1, EP2...).
- Cada PNG es previsiblemente una matriz 13x13 de manos iniciales coloreada por acción (raise/call/fold/mixta) — es decir, **el rango exacto del usuario para esa posición + profundidad**, no vídeo ni texto libre.
- Esto es oro para el preflop: en vez de un rules-engine genérico o un LLM, se puede **digitalizar cada imagen** (clasificar el color de cada una de las 169 celdas) y construir una tabla de lookup `(posición, stack_bb, acción) → rango exacto`. Determinista, sin ambigüedad, sin necesidad de IA para preflop.
- `OPEN RAISE/NOTAS IMPORTANTES.txt` ya contiene una regla explícita y directamente codificable: **open raise siempre a 2BB en todas las posiciones, excepto en la ciega pequeña (SB), donde varía entre 3-4BB según el nivel de ciegas**. Este tipo de nota debe extraerse y convertirse en config, no en texto libre para un RAG.
- Los rangos llegan como máximo a 40BB efectivos, coherente con torneos (en cash normalmente se juega a ~100BB de stack efectivo).

### `VIDEOS ZEROS POKER/` — curso "Zeros Poker" (240 mp4 + 5 flv + 2 mkv)
- Dos ramas: `CASH GAMES/` (28 archivos, descartada — v1 es solo torneos) y `TORNEOS/` (230 archivos, la fuente a usar).
- `TORNEOS/` está organizado por nivel: iniciación (35 vídeos), escalando niveles (27), teoría postflop intermedio (23), **el curso absoluto de juego postflop avanzado (101 vídeos — el grueso del material)**, contenidos adicionales de juego con iniciativa (20), más productividad/gestión personal (10) y software de apoyo/hotkeys (2).
- Los dos últimos módulos (productividad/gestión personal y software de apoyo) no son estrategia de juego — para el motor de decisión se pueden excluir o dejar en una categoría aparte de baja prioridad.
- `TORNEOS/1. CONTENIDOS DE INICIACIÓN...` tiene los 35 mp4 reales con los básicos.
- Este material (una vez transcrito) es la base de la Fase 4.3 (RAG postflop): no hay rangos exactos como en preflop, es contenido explicativo en vídeo que hay que convertir a texto (Whisper) y trocear para recuperación semántica.

## Fases de implementación

### Fase 0 — Calibración
Herramienta simple (ventana GTK con selector de recuadro tipo "screenshot region picker") para dibujar una vez el rectángulo sobre la ventana de la VM. Guarda en config: monitor/output, x, y, ancho, alto. La posición del panel HUD (Fase 5) se calcula automáticamente como "justo debajo de ese recuadro", así no hace falta rastrear la ventana de la VM en tiempo real (en Wayland no hay una API estándar para que una app consulte la posición de ventanas de otras apps).

### Fase 1 — Captura continua (Wayland)
- Portal `org.freedesktop.portal.ScreenCast` + PipeWire para un stream persistente (cachear el `restore_token` para no repetir el diálogo de permiso en cada captura).
- Frame rate bajo (1-2 fps es de sobra dado el margen de 5s).
- Recortar cada frame a la región calibrada.

### Fase 2 — Detección de cambio de board
- Comparar (hash/diff) las subregiones de cartas comunitarias y cartas propias entre frames.
- Al detectar cambio → disparar Fase 3 (evita reconocer en cada frame, que sería caro).
- Abierto: ¿el disparo también debe activarse cuando aparecen los botones de acción disponibles (turno del héroe), o solo con cambio de board? De momento se implementa solo "cambio de board".

### Fase 3 — Visión: reconocimiento del estado de mesa
- Dado que el skin es fijo y estándar, usar template matching (rango+palo de cartas, botón de dealer) + OCR (Tesseract) para textos (stacks, pot, ciegas, sizings) — más rápido y fiable que una CNN para un skin que no cambia.
- Mantener estado acumulado de la mano completa (no solo el frame actual): acciones de cada jugador en cada calle, para tener el historial de apuestas completo que necesita el motor de decisión.
- Calcular el **stack efectivo en BB** (stack propio y del rival relevante, dividido por la ciega grande) — es el índice que hace falta para consultar la tabla de rangos preflop de la Fase 4.1.
- Salida: estructura `GameState` (JSON) con hero_cards, board, pot, stacks, stack_efectivo_bb, posición, ciegas, historial de acciones de la mano, acción que enfrenta el héroe.

### Fase 4 — Motor de decisión ("caja negra") v1
Enfoque híbrido, construido a partir del inventario real de `/mnt/qnap/Poker/` (no red neuronal entrenada desde cero, no hay hand histories):
1. **Preflop (determinista)**: digitalizar las 398 imágenes de `CAPTURAS HERRAMIENTAS PREFLOP/` en una tabla de lookup `(posición, stack_efectivo_bb, open-raise/3bet-call) → rango exacto de manos`. Sizing de open-raise codificado directamente desde `NOTAS IMPORTANTES.txt` (2BB en todas las posiciones, 3-4BB desde SB). Sin IA, sin ambigüedad, cobertura hasta 40BB efectivos.
2. **Postflop (RAG)**: transcribir (Whisper) los ~240 vídeos de `VIDEOS ZEROS POKER/` (priorizando `TORNEOS/6. El curso absoluto de juego postflop` y `TORNEOS/5. Teoría postflop`, que son el grueso del contenido de estrategia), trocear y generar embeddings. Excluir o separar los módulos de productividad/gestión personal y software/hotkeys (no son estrategia de juego).
3. En tiempo real: si la mano sigue en preflop → responder con la tabla de lookup (instantáneo). Si ya hay flop/turn/river → convertir el `GameState` a descripción en lenguaje natural, recuperar fragmentos relevantes de las transcripciones y generar la recomendación + justificación con un LLM (viable en tiempo, dado el margen de 5s).
4. Registrar cada recomendación (y, si hay feedback del usuario, la acción que realmente tomó) para poder afinar el modelo más adelante si se consiguen hand histories.

**Auditoría de `decision/preflop/ranges.json` (2026-07-24)**: verificación estructural completa (331 escenarios, 0 errores: cada uno suma 169 manos, sin manos duplicadas ni inválidas) + coherencia con teoría de poker (el rango de open-raise crece monótonamente EP1→SB en las profundidades probadas, colapsa a shove-or-fold puro a 8bb) + comparación manual celda-por-celda contra las capturas originales en varios escenarios (coincidencia exacta). Limitaciones conocidas y aceptadas:
- Faltan 9 de 340 combinaciones posibles: 8 porque `3BET-CALL/10BB/1BB (My position)/` está vacía de verdad en el origen (no es un fallo de digitalización), y 1 por una colisión sin resolver (`20BB, BB vs MP1`).
- Las celdas de frecuencia mixta (ej. una mano jugada "80% 3bet / 20% call") se clasifican por el color dominante, perdiendo el matiz de la frecuencia exacta — razonable para un motor de decisión binario (acción única por mano), pero es una simplificación real frente al rango original.

### Fase 5 — HUD de salida
Panel GTK sin bordes, "always on top", posicionado en coordenadas fijas justo debajo del recuadro calibrado. Muestra: resumen del estado detectado + recomendación (acción + sizing) + justificación breve.

### Fase 6 — Empaquetado Flatpak / Bazaar
- Manifest Flatpak con permisos de portal (`--talk-name=org.freedesktop.portal.ScreenCast`), sin acceso a filesystem más allá de su directorio de config, acceso de red si se usa LLM/RAG.
- Metadata AppStream correcta para que se vea bien en Bazaar. Nota: Bazaar muestra catálogos tipo Flathub/remotos configurados — si esto es una app personal (no publicada en Flathub), lo más simple es un repo Flatpak local o instalar el `.flatpak`/`.flatpakref` directamente; "compatible con Bazaar" en la práctica significa "Flatpak bien empaquetado", no necesariamente publicado públicamente.

### Fase 7 — Validación
- Set de capturas de referencia (por calle) para tests de regresión del módulo de visión.
- Medir latencia end-to-end (debe quedar bajo 5s).
- Revisión manual: comparar recomendación de la IA vs. lo que el usuario habría hecho, para ir refinando el perfil/reglas.

## Pendiente de decidir más adelante
- Si el disparo también debe activarse cuando aparecen los botones de acción (turno del héroe), o solo con cambio de board.
- Si en algún momento se pueden exportar hand histories reales para pasar a entreno supervisado.
- Si más adelante interesa añadir lógica ICM (burbuja, mesa final) al motor de decisión de torneos.
- Nombre de la app / identificador Flatpak (`org.usuario.PokerAssistant` o similar).
