# Trabajo pendiente

Estado a 2026-07-25. El plan completo del que sale esto está en
[`prompt.md`](../prompt.md) (objetivo y fases originales) y en el README
(qué hace cada módulo hoy).

## Estado actual

| Fase | Estado |
|---|---|
| 0 · Calibración | ✅ |
| 1 · Captura Wayland | ✅ |
| 2 · Detección de cambio de board | ❌ no existe |
| 3 · Visión | 🟡 funciona; sigue midiéndose contra 141 capturas |
| 4.1 · Preflop determinista | ✅ la pieza más sólida |
| 4.2 · Transcripción | ✅ 127 vídeos, 5162 chunks |
| 4.3 · Postflop | 🟡 equity por Monte Carlo lista y validada, **sin cablear** |
| 4.4 · RAG (estudio post-mano) | 🟡 índice construido, sin cablear |
| 5 · HUD | 🟡 panel de control, no el HUD anclado del spec |
| 6 · Flatpak | ❌ |
| 7 · Validación | 🟡 8 scripts de test; sin corpus etiquetado |

---

## 1 · BLOQUEADO: hacen falta capturas en modo BB

Tres trabajos dependen de lo mismo y no se pueden hacer sin ellas.

### Cómo grabarlas

Con el cliente de PokerStars configurado para mostrar los importes en **big
blinds** (Configuración → Mesa):

```bash
.venv/bin/python capture/record_samples.py --out-dir vision/samples_bb --interval 2
```

Verificado que funciona: el filtro de tapete acepta tu mesa con holgura (fracción
de verde 0,41 frente a un umbral de 0,08). Con ~40 frames basta, cubriendo:

- preflop con cartas del hero en 3 posiciones distintas
- un bote sin abrir
- **un bote donde enfrentes una subida** ← el más importante, ver la incógnita abajo
- la SB completando
- la opción de la BB
- un frame entre manos
- un asiento vacío y uno con nick ilegible

Alternativa mejor ahora que existe el modo testing: activar
**"Grabar sesión de testing"** en la GUI y jugar. Guarda el frame *y* todo lo que
la app calculó de él, que es más útil que la captura sola.

### La incógnita que resuelven

**¿Pone PokerStars el sufijo `BB` en los importes apostados sobre la mesa**, como
lo pone en los stacks? De eso depende que la defensa `threebet_call` siga
funcionando o se abstenga siempre.

Si resulta que **no** lo lleva: no se afloja el parseo. La salida honesta es que
todo bote subido se abstenga por la red de seguridad de `to_call`, y se documente
como hueco pendiente de recalibrar las zonas de apuesta. Aceptar un "entero
desnudo" reintroduciría exactamente la clase de fallo que se eliminó en la Fase 0
(leer la denominación impresa en una ficha como si fuera una apuesta).

### 1.1 Cablear la equity al motor y a la GUI

Todo lo de debajo ya está hecho y validado; falta la última capa.

- `decision/engine.py`: nuevo `postflop_equity(state)` — **separado** de
  `decide()`, que debe seguir sin devolver acción postflop. Cuenta los rivales
  como los jugadores no-hero con `in_hand`; se abstiene si el campo no está
  (GameState viejo) en vez de adivinar. Solo calcula si `state["facing"]` no es
  `None` — eso es además la guarda de showdown (ver limitación abajo).
- `gui.py`: panel "Equity estimada" entre "Mano actual" y "Recomendación":

  ```
  Ganar 14%  ·  Empatar 3%  ·  Perder 83%      (±1 pp, 10.000 simulaciones)
  Rivales activos: 2 (BTN, BB) — rangos de tu tabla: BTN 47%, BB 91%
  Con rivales de mano aleatoria seria 28%: 14 puntos vienen de que tienen rango.
  ```

  Nunca más dígitos de los que soporta `std_error_pp`. **La orden grande sigue
  vacía en postflop**: no se inventa una acción a partir de una probabilidad.
- Editar la nota de "Mano actual" para que cruce referencia con la nueva: las dos
  cifras van a quedar a centímetros y confundirlas es el error más probable.
- Reescribir el motivo postflop de `_no_reco_reason` (hoy dice que el postflop
  "es la parte del RAG, todavía pendiente", que ya no es cierto).

### 1.2 Cutover BB-only (Fase A, pasos 4-5)

Es el único cambio que altera el comportamiento, y hoy no hay con qué
comprobarlo: las 111 capturas son 100% modo fichas y tras el cutover producirán
111 abstenciones por diseño.

- `analyze_layout`: quitar el fork de unidad; `stack_unit = "bb"` literal.
  Se comenta **con su razón** todo lo que documenta medición (el bloque
  `_UNIT_LATCH` entero, `CORNER_BLINDS_*`, `parse_bet_amount`, `has_bb_marker`,
  `find_blinds_chat`) y se borra solo la fontanería.
- Se liberan **dos jobs de OCR por frame** (`chat_idx` y `corner_idx` solo
  alimentaban las ciegas y la detección de unidad; `hand_result` OCR-ea el chat
  por su cuenta).
- Motor: se queda solo la rama bb; fuera `_manual_blinds`, `blinds.local.json`,
  `_MANUAL_BLINDS_STALE_S`, el parámetro `unit` del caché. El guard pasa de
  `unit is None` a `unit != "bb"`.
- GUI: fuera el panel de ciegas entero. `players_markup` debe mostrar `44,5 BB`,
  no `44.5` a secas.
- Borrar `./set-blinds`. Actualizar README y `prompt.md`.
- `alpha.py:48` lee `state["blinds"]` **con corchetes** → `KeyError` si no se
  actualiza en el mismo commit.

Aserción de seguridad: los 111 estados de fichas alimentados a `engine.decide`
deben dar **0 recomendaciones y 111 abstenciones**.

### 1.3 Fase E: respaldo probabilístico del preflop

Depende del cutover. El diseño completo (con las mediciones que justifican cada
constante) está en el plan; resumen:

Todo lo que responde sale de una de tres operaciones sobre las 331 celdas
digitalizadas: usar otra celda real (cambio de fila), recortar una celda real por
un umbral copiando sus etiquetas, o reescalar la anchura con elasticidades
medidas en las propias celdas. **Una etiqueta nunca se recalcula**: el 94% de los
buckets no son contiguos en el orden de fuerza, así que asignar acciones por
tramos daría un rango que no es el estilo del usuario.

| situación | método | desacuerdo esperado | confianza |
|---|---|---|---|
| frente a un limp (hero ≠ BB) | cambio de fila: es una celda real | ~9/169 | media-alta |
| BB con 1 limper | fila SB tal cual, `fold`/`LIMP` → `CHECK` | ~10/169 | media |
| squeeze | umbral `0.86^L` sobre la celda de 3bet | 6-14/169 | media-baja |
| BB con ≥3 limpers | reescalado de la forma SB | 15-25/169 | baja |
| ciega vs ciega, agresor después | espejo `BB vs SB` × 0.85 | 6-10, no en la frontera | baja-media |
| 4bet | escalada 0.26 sobre el rango de 3bet | no acotable | **baja** |

Constantes, todas medidas sobre `ranges.json`: elasticidad por asiento **0.86**
(media 0.859, sd 0.046, n=66); encogimiento estructural **0.85** (el único
holdout disponible muestra que extrapolar a una familia nueva sesga un 19% a
suelto, ratio 0.81-0.88 en 6 profundidades).

Efecto secundario valioso: las **176 celdas hoy inalcanzables** (`MP1`, `MP2`,
`EP2` — el 53% de los datos, inalcanzables porque la visión solo tiene 6
asientos) pasan a ser las **filas donantes**.

Cuatro etiquetas nuevas para la capa bilingüe: `CHECK`,
`RAISE OVER LIMPERS (x BB)`, `MARGINAL RAISE OVER LIMPERS`, `SQUEEZE (x BB)`.

También arregla dos bugs de camino: `facing="check"` sin ser BB ya abstiene (Fase
0), pero falta la **regla del ante** en el clasificador de spots y el gating por
calidad de las apuestas.

---

## 2 · No bloqueado

### 2.1 Latencia (el mayor salto de experiencia)

Hoy ~3,4 s por frame. Medido: **añadir un solo init de tesseract costó +0,55 s**,
así que inicializar el motor es una fracción grande del total y se paga en cada
frame.

| cambio | ganancia | esfuerzo |
|---|---|---|
| worker OCR **persistente** (proceso vivo, APIs ya cargadas) | quita el init de todos los frames | 2-3 h |
| paralelizar los ~106 jobs en `min(8, nproc-2)` procesos | 2× medido con 6 jobs, más con 106 | 2 h |
| **Fase 2**: hash de las zonas de cartas, saltar si no cambian | los frames entre manos pasan a ~0 | 3-4 h |
| exponer `chat_lines` en el GameState (quitar el doble OCR) | −0,3 s y un subproceso | 30 min |

Los cuatro son compatibles. Juntos: de 3,4 s a sub-segundo en los frames que
importan, y el intervalo de 0,25 s deja de ser decorativo.

### 2.2 Historial de acciones de la mano

~1-2 días. Confirmado que **el chat no narra las acciones** (solo resultados,
showdown, turnos y subidas de nivel), así que hay que acumular estado entre
frames — pero el importe apostado por asiento ya se lee. Es requisito para
distinguir open / 3bet / squeeze / resubida con certeza, y para cualquier cosa
postflop más fina.

### 2.3 Corpus etiquetado

El modo testing ya recoge la materia prima. Falta un `score_samples.py` que
compare contra etiquetas y diga si un cambio de umbral mejora o rompe. Sin eso no
se pueden tocar con seguridad los ~15 umbrales de `vision/seat_map.py`.

### 2.4 Deuda estructural

- **Empaquetar de verdad** (`pyproject.toml`, paquete real en vez de 4
  `sys.path.insert`): hoy bloquea pytest *y* el Flatpak de la Fase 6. Además hay
  dos `ocr_worker.py` con el mismo basename en el path, que solo no colisionan
  por suerte (se invocan por ruta, no por import).
- **Unificar las 3 ramas de visión**: `analyze` y `analyze_color_deck` ya no son
  producción; mantenerlas triplica la superficie.
- **HUD real** (sin bordes, always-on-top, anclado bajo el recuadro) y separar UI
  de lógica en `gui.py`.
- Pinear `requirements.txt` y añadir lo que falta (`onnxruntime`, PyGObject,
  `ffmpeg`, el langpack de tesseract).
- Rotar `decision/decisions.local.jsonl`.

### 2.5 Sacarle más a los rangos

- **Celdas de frecuencia mixta**: `parse_ranges.py` colapsa "80% 3bet / 20% call"
  al color dominante. Recuperar la frecuencia permitiría decir *"3bet 80% / call
  20%"*. Requiere volver a las 398 capturas originales.
- **La colisión sin resolver** (`20BB, BB vs MP1`) es 1 escenario, 20 min a mano.
  Los otros 8 huecos están vacíos en origen.
- **Rango propio de 4bet**: capturar y digitalizar 20-30 imágenes con el mismo
  `parse_ranges.py`. Es **la inversión de mayor retorno del plan entero**: sus 398
  imágenes no contienen el eje "responder a agresión" en absoluto, y ninguna
  cantidad de estadística lo saca de ahí. Convertiría la peor de las cinco
  situaciones de la Fase E en la mejor.

---

## 3 · Investigar aparte

### Deriva 9-max / 6-max en las etiquetas de posición

Las etiquetas de `ranges.json` son de mesa de **9 plazas** (`CANON9`), pero la
visión etiqueta una de **6** por el recuento de asientos ocupados
(`SEATING_BY_N`). Consecuencia: **a UTG de 6-max se le sirve el rango de UTG de
9-max** (8 jugadores detrás en vez de 5), que es bastante más tight. El 6-max UTG
equivale más bien a `MP2`/`MP1`. Falla en silencio porque las posiciones se
emparejan por cadena de texto.

También afecta a heads-up: `SEATING_BY_N[2] = ["BTN", "BB"]`, así que la SB de HU
recibe el rango de BTN de 9-max en vez del de SB.

Decidir el mapeo correcto requiere criterio de poker y contrastar con las
capturas originales, por eso va aparte. **La Fase E no depende de que se arregle**
(su cambio de fila opera sobre el eje `CANON9`, no sobre el número real de
jugadores), y cuando se corrija ambas componen:
`fila = idx(hero) + corrección_deriva + L·LIMPER_SEAT_EQUIV`. Conviene dejar la
resolución de fila en **una sola función** para que el arreglo futuro toque un
solo sitio.

### `NAME_BLACKLIST` con coincidencia de subcadena

`vision/text_extract.py` rechaza nicks legítimos: `"make"` mata `makeao31`, y
cualquier nick que contenga `hand`/`call`/`bet`/`table`/`won`. Como las posiciones
se derivan del **recuento** de asientos ocupados, es una fuente independiente de
posiciones equivocadas. El fix 0.3 lo tapa cuando el stack en BB es legible, pero
la regla merece su propio arreglo (exigir frontera de palabra, o aplicar la regla
de subcadena solo a entradas de ≥6 caracteres).

---

## 4 · Qué NO se va a hacer, y por qué

- **RAG en tiempo real.** Recuperar transcripciones de vídeo para justificar una
  acción en una mano en vivo sería presentar prosa recuperada como consejo sobre
  *ese* board concreto: inverificable. El índice se conserva para **estudio
  post-mano** (Fase 4.4), donde la latencia no importa y el marco es honesto.
- **Multiplicador posicional sobre la equity.** El número de rivales ya está
  modelado simulándolos, así que multiplicar por un factor extra lo contaría dos
  veces; y la posición no cambia la equity sino su *realización*, para lo que no
  hay datos con los que calibrar. Es la forma más fácil de que el módulo mienta.
- **Aflojar un parseo para ganar cobertura.** Repetidamente: una recomendación
  plausible y falsa es peor que una abstención.
