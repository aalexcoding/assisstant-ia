# Mejoras postflop — 2026-07-31

## Implementado y validado

- Auditadas las 126 transcripciones contra los 126 vídeos prioritarios:
  116 contienen texto y 10 corresponden a vídeos con audio digitalmente
  silencioso (`mean/max -91 dB`). No se inventa texto para esos diez.
- Reparado el índice semántico: manifiesto compatible con `fastembed 0.8.0`,
  5.142 fragmentos estratégicos y comando correcto
  `python -m decision.rag.build_index`.
- Excluidos del índice dos vídeos que solo anuncian contenido futuro
  (3bet/4bet y juego con iniciativa); no son lecciones estratégicas.
- Añadidos metadatos derivados de la ruta: IP/OOP, iniciativa, tipo de bote y
  nivel del curso. El título se incorpora al embedding y el contexto observado
  desempata la recuperación.
- El estudio post-mano conserva hero, board, mano formada, calle, posición,
  iniciativa, tipo de bote, SPR y acciones observadas por calle. La GUI enseña
  título, minuto, similitud, extracto y enlace al vídeo original.
- Un índice ausente/incompatible se muestra como avería. Ya no se confunde con
  “no hay vídeos suficientemente parecidos”.
- El historial de acciones guarda calle y snapshots observados de bote,
  comprometido y apuesta visible. No los denomina “incremento” ni calcula un
  sizing cuando falta el frame anterior.
- Añadida ayuda matemática en vivo: cantidad a pagar, bote final, equity mínima,
  stack efectivo, SPR actual, margen de equity bruta y EV bruto de check-down.
  No devuelve CALL/FOLD.
- La equity se oculta si las cartas del hero están apagadas o `in_hand=False`.
- Añadido un catálogo de 15 fichas estructuradas de estudio postmano:
  14 contrastadas con guías públicas y una extraída de la lección local de
  probe turn tras check-check flop. Cada ficha declara condiciones, principio,
  puntos a revisar, errores a evitar, límites y fuente enlazada.
- Cubiertos los huecos generales de multiway, c-bet SRP con iniciativa IP/OOP,
  defensa de ciegas, cold-call IP, agresor/caller IP/OOP en botes 3-bet,
  caller OOP en bote 4-bet y bluff-catch de river.
- La selección exige evidencia positiva: dos cartas observadas del hero,
  calle/tipo de bote/iniciativa/posición compatibles y, cuando corresponde,
  importe de call menor o igual al stack efectivo. Un squeeze observado excluye
  las fichas de 3-bet heads-up.
- La GUI separa “claves para revisar este spot” de los vídeos recuperados por
  similitud. Un índice semántico averiado ya no oculta fichas estructuradas que
  sí se pueden verificar.

## Validación

- Índice reconstruido: 5.142 vectores, carga correcta y consulta real operativa.
- Consulta de control `river + call flop + check-check turn + IP + sin
  iniciativa`: primera referencia, la lección específica de pagar river en esa
  secuencia.
- Tests focalizados de RAG, fichas y GUI: aprobados.
- Suite rápida completa: aprobada.
- Invariantes de las sesiones JSON: 24 aprobados.
- Replay completo real `sesion-2026-07-31_022832`:
  1.012 frames, 0 fallos, p50 0,529 s, p95 0,652 s.
- Barrido de fichas sobre la sesión completa: 216 frames postflop conservaban
  dos cartas observadas del hero; hubo 158 coincidencias multiway, dos de
  defensa OOP y una de c-bet IP en board dinámico. No se activó la ficha de
  3-bet sobre un frame donde el hero ya no tenía cartas.
- Frames postflop reales:
  - 0400: bote 5,75 BB, call 1 BB, bote final 6,75 BB, equity mínima 14,8%.
  - 0596/0597: bote 4,83 BB, call 1 BB, bote final 5,83 BB, equity mínima 17,2%.

El replay completo detectó 15 pérdidas de recomendación preflop, siempre hacia
abstención y nunca hacia otra acción: 0184–0187 (`CHECK BB option`), 0447–0448
(`RAISE OVER LIMPERS`), 0455–0460 (`OPEN RAISE`), 0567–0568 y 0690
(`CHECK BB option`). No hubo ganancias ni cambios. Son diferencias entre la
versión grabada y cambios preflop anteriores; esta tanda solo modifica
`decision/rag/`, la presentación postmano y clasificación contextual, rutas que
`replay.py` no usa para decidir preflop. Quedan registradas, no ocultas.

## Fuentes externas usadas

- GTO Wizard, *What are Pot Odds in Poker?*:
  https://blog.gtowizard.com/what-are-pot-odds-in-poker/
- GTO Wizard, *Stack-to-Pot Ratio*:
  https://blog.gtowizard.com/stack-to-pot-ratio/
- GTO Wizard, *Mathematical Misconceptions in Poker*:
  https://blog.gtowizard.com/mathematical-misconceptions-in-poker/
- GTO Wizard, *10 Tips for Multiway Pots in Poker*:
  https://blog.gtowizard.com/10-tips-multiway-pots-in-poker/
- GTO Wizard, *Flop Heuristics: IP C-Betting in MTTs*:
  https://blog.gtowizard.com/flop-heuristics-ip-c-betting-in-mtts/
- GTO Wizard, *Exploiting Excessive C-Betting by OOP*:
  https://blog.gtowizard.com/exploiting-excessive-c-betting-by-oop/
- GTO Wizard, *C-Betting IP/OOP in 3-Bet Pots*:
  https://blog.gtowizard.com/c-betting-ip-in-3-bet-pots/ y
  https://blog.gtowizard.com/c-betting-oop-in-3-bet-pots/
- GTO Wizard, *Mastering Three-Bet Pots In/Out of Position in MTTs*:
  https://blog.gtowizard.com/mastering-three-bet-pots-in-position-in-mtts/ y
  https://blog.gtowizard.com/mastering-three-bet-pots-out-of-position-in-mtts/
- GTO Wizard, *4-Bet Pots OOP as the Preflop Caller*:
  https://blog.gtowizard.com/4-bet-pots-oop-as-the-preflop-caller/
- GTO Wizard, *Flop Heuristics for Defending the Blinds / IP Cold-Caller*:
  https://blog.gtowizard.com/flop-heuristics-for-defending-the-blinds-in-mtts/ y
  https://blog.gtowizard.com/flop-heuristics-ip-cold-caller-in-mtts/
- GTO Wizard, *Understanding Blockers in Poker*:
  https://blog.gtowizard.com/understanding-blockers-in-poker/

Se usaron para contrastar `equity requerida = call / bote después del call`,
`SPR = stack efectivo / bote` y, especialmente, para no presentar equity bruta
como una decisión cuando faltan equity realization, rango de apuesta, rake,
implied odds, futuras apuestas e ICM.

## No implementado todavía y motivo

- **Recomendaciones live BET/CHECK/CALL/FOLD:** las nuevas reglas son
  heurísticas de estudio, no rangos por combo. Aún faltan el rango rival
  condicionado por toda la secuencia, tamaños legales fiables, rake/ICM y
  planes de calles futuras; por eso no se conectan a `engine.decide`.
- **Sizing exacto por acción:** se guarda lo observado, pero el muestreo puede
  perder el frame anterior. Un comprometido acumulado no siempre es el
  incremento de una subida.
- **Botes limpeados:** se localizaron guías públicas útiles, pero la lista de
  acciones se declara incompleta. Cero agresiones observadas no demuestra un
  limp, así que no se activa una ficha de este spot hasta disponer de evidencia
  positiva.
- **4-bet más allá del caller OOP:** las guías encontradas son muy dependientes
  de posición, cash/MTT y profundidad. `4bet_plus` agrupa además 4-bet y 5-bet;
  no se generalizó una regla común.
- **Turn/river salvo probe y bluff-catch:** el corpus local tiene muchas
  secuencias útiles, pero las condiciones dependen de acciones de calles
  anteriores que el muestreo puede perder. Se irán incorporando una a una con
  timestamp y test de secuencia, como la ficha de probe.
- **Los 10 vídeos silenciosos:** pueden contener contenido visual, pero no hay
  voz que transcribir. Cubrirlos requeriría revisar/OCR de sus diapositivas.
