# Trabajo pendiente

Estado a 2026-07-25 (tras 4 sesiones de testing grabadas, ~700 frames). El plan completo del que sale esto está en
[`prompt.md`](../prompt.md) (objetivo y fases originales) y en el README
(qué hace cada módulo hoy).

## Estado actual

| Fase | Estado |
|---|---|
| 0 · Calibración | ✅ |
| 1 · Captura Wayland | ✅ |
| 2 · Detección de cambio de board | ❌ no existe |
| 3 · Visión | 🟡 va bien salvo los importes apostados (ver §2.0) |
| 4.1 · Preflop determinista | ✅ la pieza más sólida |
| 4.2 · Transcripción | ✅ 127 vídeos, 5162 chunks |
| 4.3 · Postflop | ✅ equity por Monte Carlo, validada y cableada al HUD |
| 4.4 · RAG (estudio post-mano) | 🟡 índice construido, sin cablear |
| 5 · HUD | 🟡 panel de control, no el HUD anclado del spec |
| 6 · Flatpak | ❌ |
| 7 · Validación | 🟡 10 scripts de test + modo testing; sin corpus etiquetado |

---

## 1 · Lo que dependía de las capturas en BB (ya desbloqueado)

Había tres trabajos esperando capturas en modo BB. **Ya hay cuatro sesiones
grabadas** (~700 frames) con el modo testing, así que el bloqueo se levantó.

### Las dos incógnitas quedaron resueltas

**¿El cliente muestra los importes en big blinds de forma detectable?** Sí:
`stack_unit = "bb"` por evidencia en el 100% de los frames de las cuatro
sesiones, sin una sola ambigüedad.

**¿Pone PokerStars el sufijo `BB` en los importes de los botones?** Sí:
`to_call` se lee con valores reales (0.5, 1.0, 2.0, 3.26, 3.35, 4.0, 5.0, 7.0).
La red de seguridad contra la subida no atribuida funciona y no hay que aflojar
ningún parseo.

Queda abierta una tercera, que apareció al mirar los datos: **cómo dibuja el
cliente los importes apostados sobre la mesa**, porque en 81 de 101 frames con
`to_call > 1` no se encuentran ni haciendo OCR del tapete entero (ver §2.0b). Si
§2.0 sale bien, deja de importar.

### Cómo grabar más sesiones

Activar **"Grabar sesión de testing"** en la GUI antes de darle a iniciar, y
jugar. Guarda el frame *y* todo lo que la app calculó de él, emparejados por
nombre. Es mejor que `record_samples.py`, que solo guarda la imagen.

Conviene que cubran: preflop con cartas en varias posiciones, un bote sin abrir,
**botes donde enfrentes una subida**, la SB completando, la opción de la BB, y
frames entre manos.

### 1.1 Cablear la equity al HUD — ✅ HECHO (commit 319582e)

Panel "Equity estimada" entre "Mano actual" y "Recomendación".
`engine.postflop_equity()` va separado de `decide()`, que sigue sin dar acción
postflop. Se abstiene cuando no sabe quién sigue en la mano o cuando nadie tiene
cartas, porque el modo de fallo de los dorsos es contar de MENOS y eso infla la
equity.

Nota sobre una decisión que se apartó del plan: **no** se exige que
`state["facing"]` esté leído. Los botones solo se leen en ~20% de los frames, así
que exigirlo dejaría el panel casi siempre vacío; en su lugar se añade un aviso
de que quizá no sea el turno del hero.

### 1.2 Cutover BB-only (Fase A, pasos 4-5)

Ya no está bloqueado: hay cuatro sesiones en modo BB para validarlo. Sigue
siendo el único cambio que altera el comportamiento, así que conviene hacerlo con
el corpus de fichas delante — las 111 capturas antiguas producirán 111
abstenciones por diseño, y eso ES la aserción de seguridad.

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

Depende del cutover y, para los spots de defensa, de §2.0. El diseño completo (con las mediciones que justifican cada
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

### 2.0 · ⭐ Deducir lo apostado de la BAJADA DE STACK entre frames

**La mejor idea que ha salido, y sustituye a los dos apartados de abajo** (leer
las apuestas de la mesa y el historial de la mano). En vez de localizar las
fichas apostadas —que es lo que está fallando— se compara el stack de cada
jugador entre frames: si baja de X a Y, ha puesto X−Y.

**Por qué es mejor que leer la mesa**: los stacks *sí* se leen (73%), las
apuestas no. Y no depende de dónde dibuje el cliente las fichas, así que
sobrevive a recalibrar el recuadro — la clase de fallo que ya ha mordido dos
veces (el área del botón en píxeles, las zonas de apuesta).

#### Medido sobre la sesión del 25-07 (364 frames)

```
stacks leidos:                              73%   (59-83% segun posicion)
pares consecutivos con lectura en ambos:    68%
cambios de stack detectados:               177
deltas mas frecuentes:  1.0 (x25) · 0.5 (x8) · 4.0 · 5.0 · 4.5 · 3.5
```

Los dos deltas más frecuentes son **1.0 y 0.5: la ciega grande y la pequeña**.
Eso confirma que la señal es real y no ruido.

Contrastando el valor derivado contra la apuesta leída en la mesa:

| | |
|---|---|
| coincide | 52 |
| discrepa | 29 |
| derivado 0 (aún sin ver el stack previo) | 114 |

**Y en las discrepancias suele acertar el derivado**, no el leído:

| posición | leído en la mesa | derivado | quién acierta |
|---|---|---|---|
| SB | 1.0 | **0.5** | el derivado: la SB pone media ciega |
| HJ | 1.0 | **1.2** | el derivado: es ciega + ante |
| CO | **2,52** | 3.9 | el leído es basura de OCR |

O sea que además de rellenar el hueco, **corrige lecturas que hoy son erróneas**.

#### La limitación, y por qué encogió

Los 114 "derivado 0" son manos donde aún no se había visto el stack del jugador
*antes* de que actuara. La mediana de esa sesión eran **5 frames por mano**,
porque se grabó a 3,8 s de ciclo. Con el ciclo ya en 1,2 s salen ~3× más frames
por mano, así que la mejora de rendimiento (§2.1) es lo que hace viable esto.

#### Qué hace falta

1. **Exponer el ASIENTO en el `GameState`.** Hoy solo hay `position`, y las
   posiciones **rotan entre manos**; el asiento (`UL`, `MR`…) es la clave
   estable. Un campo más.
2. **Rastreador de mano**: segmentar por frontera (el board deja de extender al
   anterior, o cambia el nº de mano del chat) y llevar `max_stack_visto` por
   asiento. `comprometido = max_visto − stack_actual`. Usar el máximo visto y no
   el delta frame a frame lo hace tolerante a las lecturas que faltan.
3. **Casos a cubrir**: stack que *sube* (ganó el bote), el nameplate que muestra
   el verbo en vez del número justo al actuar, y manos que empiezan a media
   captura.
4. **Usar las dos señales**: el derivado como principal y el leído de la mesa
   como corroboración. Coinciden → confianza alta; discrepan → gana el derivado
   y se anota.

Resuelve a la vez el hueco de las apuestas **y** el historial de la mano (§2.2),
y con eso desbloquea la Fase E.

### 2.0b · Zonas de apuesta: lo que se investigó y NO se cerró

**Prioridad alta.** Medido sobre la sesión del 25-07 (207 frames): `facing="bet"`
se detecta en 51 frames pero `vs_position` solo se resuelve en **6**, y hay 23
abstenciones de *"el botón pide N BB para igualar pero ningún asiento explica la
subida"*. Consecuencia: **las 54 recomendaciones fueron `open_raise`, ninguna
defensa `threebet_call`**.

Lo que lee hoy el OCR en esas zonas es mayormente ruido:

```
TOPC -> ['OB']
UL   -> ['ee@eee', 'ene «©', '1BB ©', '8 @@@ ee * # =', ...]
ML   -> ['DE ise']
MR   -> ['¢ 6 @', '2 @ @', '-_*2e @ #8', ...]
```

**La hipótesis obvia —zonas descalibradas— NO se sostiene**, y conviene dejarlo
escrito para que nadie la repita:

- Una pasada de OCR sobre **el tapete entero** tampoco encuentra el importe que
  pide el botón: 0 de 22 frames. No es un problema de recorte.
- Hipótesis "aritmética" (`to_call` = apuesta del rival − lo que el hero ya
  tenía puesto): **0 casos de 101**.
- Hipótesis "hero cubierto" (`to_call` = stack del hero, porque no puede pagar
  más): explica el frame que se inspeccionó a ojo, pero **solo 1 caso de 101**.

Balance sobre 101 frames con `to_call > 1`: 19 se explican por la apuesta de un
rival, 1 por stack cubierto, y **81 siguen sin explicación**. Falta entender cómo
dibuja el cliente las apuestas en esos casos, y eso no se saca deduciendo desde
los números: hace falta **etiquetar a mano ~15 frames con subida** (abrir la
imagen, anotar qué apostó cada asiento y dónde está escrito) y medir contra esa
verdad, igual que se hizo con `CARD_BACK_ZONES`.

**Si §2.0 sale bien, esto puede dejar de importar**: el comprometido derivado del
stack no necesita leer la mesa. Mantener esta sección solo como corroboración.

#### Detección por elementos (la idea de "vectorizar")

Se probó detectar las **cápsulas oscuras** del tapete como objetos, en vez de
OCR-ear rectángulos fijos. Es viable en principio (~6 cápsulas por frame, que
son los asientos) pero con umbrales de color a ojo **no discrimina**: de 147
cápsulas detectadas, 101 eran ruido y solo 9 apuestas, con valores que resultaron
ser stacks.

Lección: el eje no es "zonas fijas vs. detección de objetos" sino **búsqueda
global vs. búsqueda acotada**. Lo que funciona muy bien son los objetos
detectados *dentro de una zona* (dorsos de carta: separación 13,6× sobre 705
observaciones; botón del dealer: 100% en dos resoluciones). La búsqueda global
por blobs ya se intentó y se abandonó (ver el docstring de `seat_map.py`). Si se
retoma, tiene que ser zona-como-ancla + elemento dentro, y con una medición tan
seria como la de los dorsos.

#### La red de seguridad de `to_call` se abstiene de más

Su premisa es que `to_call` debe coincidir con la apuesta de algún asiento, y ya
se sabe que eso es **falso al menos cuando el hero va cubierto** (solo puede
pagar lo que le queda). Está callándose en 81 frames y no se sabe cuántos son
correctos. Sigue siendo la dirección segura —callar antes que recomendar el rango
de apertura enfrentando una subida— pero merece medirse y afinarse.

### 2.1 Latencia — ✅ HECHO (commit 67b2ab7)

El ciclo bajó de **3,88 s a 1,59 s (2,4×)**:

- **lote de OCR en paralelo** (6 procesos): 3,85 s → 1,45 s. Se dejan 10 núcleos
  libres a propósito; de 6 a 12 procesos solo se ganan 0,18 s más y saturar la
  máquina agrava el lag que se quería quitar.
- **fuera el doble OCR del chat**: −571 ms. El `GameState` ya expone
  `chat_lines`.

Lo que queda de esta sección:

| cambio | ganancia estimada | esfuerzo |
|---|---|---|
| **Fase 2**: hash de las zonas de cartas, saltar si no cambian | los frames entre manos pasan a ~0 | 3-4 h |
| worker OCR **persistente** (proceso vivo, APIs ya cargadas) | quita el init de tesseract de cada frame (~0,55 s por proceso) | 2-3 h |

### 2.2 Historial de acciones de la mano → lo cubre §2.0

Confirmado que **el chat no narra las acciones** (solo resultados, showdown,
turnos y subidas de nivel), así que hay que acumular estado entre frames.

**El rastreador de §2.0 ES esta pieza**: llevar `max_stack_visto` por asiento a
lo largo de una mano da el *comprometido acumulado por jugador*, que es
exactamente lo que hace falta para distinguir open / 3bet / squeeze / resubida
con certeza. Las dos cosas se hacen de una vez.

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
