# Trabajo pendiente

Estado a 2026-07-26. Para el mapa de arriba —qué está hecho, qué toca ahora y qué
depende de ti— empieza por [`DONDE-VAMOS.md`](DONDE-VAMOS.md); esto es el detalle
de cada tarea. El plan completo del que sale todo está en
[`prompt.md`](../prompt.md) (objetivo y fases originales) y en el README
(qué hace cada módulo hoy).

## Estado actual

| Fase | Estado |
|---|---|
| 0 · Calibración | ✅ |
| 1 · Captura Wayland | ✅ |
| 2 · Detección de cambio de board | ✅ caché de rangos + vigilancia a 0,1 s (§2.1, §2.2b) |
| 3 · Visión | 🟡 va bien; los importes los cubre el rastreador (§2.0) y las acciones el historial (§2.2) |
| 4.1 · Preflop determinista | ✅ la pieza más sólida; + capa derivada: opción de la BB, frente a un limp y squeeze (§1.3) |
| 4.2 · Transcripción | ✅ 127 vídeos, 5162 chunks |
| 4.3 · Postflop | ✅ equity por Monte Carlo, validada y cableada al HUD |
| 4.4 · RAG (estudio post-mano) | ✅ cableado al panel "Mano anterior" |
| 5 · HUD | ✅ modo HUD (casilla) que deja solo lo que se mira en mano |
| 6 · Flatpak | ❌ |
| 7 · Validación | 🟡 17 scripts de test (528 checks) + modo testing; sin corpus etiquetado |

---

## 1 · Lo que dependía de las capturas en BB (ya desbloqueado)

Había tres trabajos esperando capturas en modo BB. Con las sesiones grabadas en
modo testing el bloqueo se levantó, y los tres están hechos (§1.1 y §1.2) o
listos para empezar (§1.3).

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

### 1.2 Cutover BB-only — ✅ HECHO

La app trabaja solo con el cliente configurado en **big blinds**. El stack leído
ya *es* la profundidad, así que no hace falta ningún nivel de ciegas.

**La aserción de seguridad pasa**: las 111 capturas reconocidas en modo fichas
dan **0 recomendaciones** (daban 4). Está como test, `A-3b`.

Qué se retiró: el bloque `_UNIT_LATCH` + `_detect_stack_unit` + `_chips_style_stack`,
`CORNER_BLINDS_ZONE/SCALE`, `seat_map.parse_bet_amount` y `has_bb_marker`, la rama
de fichas del motor con `_manual_blinds`/`blinds.local.json`/`./set-blinds`, y el
panel de ciegas de la GUI. El campo `state["blinds"]` desaparece del esquema de
`analyze_layout` (las rutas de diagnóstico lo conservan, porque sus importes sí
están en fichas).

**`stack_unit` sobrevive como guarda, no como interruptor.** `analyze_layout` lo
pone a `"bb"` literal y `decide()` rechaza todo lo que no lo declare: las rutas de
diagnóstico siguen produciendo fichas enteras, y leer 3955 fichas como 3955bb daría
una recomendación con convicción y falsa.

Una corrección al plan original, que decía que se liberaban **dos** jobs de OCR:
solo se libera **uno** (`corner_idx`). El del chat es ahora imprescindible — además
del panel "Mano anterior" alimenta el **número de mano**, que es la señal de
frontera más fiable del rastreador (§2.0). Medido tras el cambio: 1,13 s por frame,
y 15 de 15 capturas reales dan un resultado idéntico al de antes.

La razón de fondo, conservada en el código para que no se reintente: se probó
**detectar** la unidad frame a frame y la detectada oscilaba dentro de una misma
sesión de 34 min (bbx30, chipsx17, bbx24, chipsx37) sin que la config del cliente
hubiera cambiado. La garantía ahora es que `parse_amount_bb` **exige el sufijo
`BB` literal**: si el cliente no está en ese modo no se lee nada y la app se
abstiene. Por eso el parseo no se puede aflojar a "el mayor entero de la zona" —
eso leería la denominación impresa en una ficha (25, 100) como un importe.

### 1.3 Fase E: respaldo probabilístico del preflop — 🟡 la BB hecha

**Hecho: la opción de la BB** (`decision/preflop/derive.py`). Era la casilla que
más pesaba: el `CHECK (BB option)` era el **36% de todas las recomendaciones** de
una sesión real (227 de 624) y respondía siempre lo mismo *sin mirar las cartas
ni el stack* — con AA y 5bb decía lo mismo que con 72o.

El donante es **su propia fila de la SB** a la misma profundidad, la única de sus
tablas con la forma del spot (subida arriba, `LIMP` en medio, `fold` mínimo)
porque es la única posición desde la que digitalizó "entrar sin subir". El mapeo
no es una elección sino una consecuencia de las reglas:

```
OPEN RAISE (x BB)   -> RAISE OVER LIMPERS (x BB)     LIMP -> CHECK
MARGINAL OPEN RAISE -> MARGINAL RAISE OVER LIMPERS   fold -> CHECK
OPEN RAISE ALL IN   -> ALL IN
```

Las dos de la derecha son forzadas: **con la opción nunca se retira uno**, porque
pasar es gratis. Un `fold` del donante significa "no metas más dinero" = `CHECK`.
Está fijado como test sobre las 169 manos × 11 profundidades: ni una respuesta es
fold.

**Efecto sobre la sesión**: los 227 `CHECK (BB option)` pasan a 159 respuestas
derivadas (118 pasar, **41 subir**), 19 se quedan en el `CHECK` de siempre (2+
limpers, sin donante válido) y **49 pasan a abstención** — eran contradictorios,
los botones pedían *Igualar* y la app decía "pasa, es tu opción". Esa guarda
simétrica faltaba y ahora existe.

**Corrección al plan**, medida: desplazar la fila un asiento por limper de más
(SB → BTN → CO) **no aprieta el rango, lo ensancha**. A partir de 20bb la fila BTN
sube el 37-56% de los combos frente al 19-29% de la SB, porque en profundo la SB
mete su rango medio en `LIMP`. Sin un segundo donante válido, con 2+ limpers no se
deriva.

Anchos de lo que ahora recomienda subir (de 169 manos): 4bb 82,8% · 10bb 56,2% ·
20bb 30,8% · 40bb 26,0%.

#### Frente a un limp, con el hero fuera de las ciegas — ✅ HECHO

`derive.vs_limp()`. El donante es **otra celda real suya**: su rango de apertura
desde la posición que está `limpers` asientos más temprana. Un limper ya metido
equivale, a efectos de cuánta gente queda y de cuánto hay que apretar, a estar un
asiento antes.

Medido sobre `ranges.json`, ratio de anchura entre asientos adyacentes: **n=77,
media 0,802, sd 0,114**. Cada asiento hacia EP aprieta el rango ~20%, y es
monótono en las once profundidades.

**La SB queda fuera del eje**, como donante y como hero: su fila es la única
construida sobre `LIMP` (78-90% de no-fold frente al 15-56% del resto), así que
meterla rompería la monotonía — mover de SB a BTN no aprieta, *ensancha*. Para la
BB su forma es justo la que hace falta; para este spot, no.

Diferencia clave con la opción de la BB: **aquí sí se puede foldear**, porque el
hero no está en la BB y entrar cuesta dinero.

El motor solo lo usa con un recuento **positivo** de limpers. Con `None` no se
sabe si hay alguien dentro, y ahí lo correcto sigue siendo el rango de apertura.

**Lo que falta de la Fase E**: squeeze, ciega vs ciega y 4bet. El 4bet sigue
necesitando que se digitalicen 20-30 capturas de un gráfico propio: sus 398
imágenes no contienen el eje "responder a agresión" y ninguna estadística lo saca
de ahí. El diseño completo (con las mediciones que justifican cada
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

### 2.0 · Deducir lo apostado de la BAJADA DE STACK entre frames — ✅ HECHO

`decision/hand_tracker.py`. En vez de localizar las fichas apostadas sobre el
tapete —que es lo que está fallando— se compara el stack de cada jugador entre
frames: si baja de X a Y, ha puesto X−Y.

#### El resultado, re-analizando una sesión entera (1.173 frames) con el código actual

En los 98 frames **preflop donde el botón "Igualar" pide más de 1 BB**, que son
exactamente los que hoy hacían abstenerse al motor:

| quién explica la subida | |
|---|---|
| el importe leído en la mesa | 35% |
| el comprometido derivado | **59%** |
| alguno de los dos | **81%** |
| nadie (el motor se abstiene) | **19%** — antes 65% |

Y de punta a punta, con el motor entero: las **defensas (`threebet_call`) pasan
de 13 a 33** (2,5×), que era el agujero señalado en §2.0b (*"las 54
recomendaciones fueron `open_raise`, ninguna defensa"*). Las recomendaciones
totales suben de 278 a 298.

**El cambio es puramente aditivo: 20 nuevas, 0 cambiadas, 0 perdidas.** Ninguna
recomendación que ya existía se altera. Está fijado como test.

#### La regla de seguridad, que es lo que hace esto viable

El comprometido es una **cota inferior**: si la mano ya había empezado cuando se
vio al asiento por primera vez, la base ya está rebajada. Medido: en la mitad de
las manos la SB sale con 0 comprometido en vez de 0,5, porque la frontera de mano
se detecta unos frames tarde y para entonces las ciegas ya están puestas.

Quedarse corto es la dirección peligrosa. De ahí la asimetría:

> el comprometido **nunca crea** una subida, solo **atribuye** una que el botón
> "Igualar" ya ha demostrado que existe.

Así, un comprometido inflado por una frontera que se pasó por alto no puede
inventarse un raiser: sin botón que pida nada, no se mira. Y se exige además un
único candidato, igual que ya hacía `detect_raiser`.

Corroboración: cuando disparan las dos señales apuntan al **mismo asiento 12 de
13 veces** (son fuentes independientes: OCR del nameplate vs OCR de la zona de
apuesta). El HUD marca en verde lo comprometido cuando coinciden.

#### Lo que se probó y NO funcionó, para que nadie lo repita

- **Exigir que un valor se confirme 2 o 3 veces** antes de aceptarlo parecía lo
  prudente y medido era peor **en todo**: la cobertura bajaba del 91% al 79% y al
  68%, y el acuerdo con el bote leído del 37% al 15% y al 8%. El preflop se
  resuelve en pocos frames y esperar confirmación se lo pierde entero.
- **Cortar la mano cuando sube un stack** parecía la señal ideal (en poker solo se
  ganan fichas al acabar la mano). Mirando las 12 subidas dentro de manos ya
  etiquetadas por el chat, **son errores gordos de OCR**: `106.5 → 1065.0` (el
  punto decimal perdido), `30.3 → 130.3` (un "1" fantasma). No cortan; se exponen
  como `lecturas_descartadas` para desconfiar de ese asiento.
- **Cortar por el board**: 3 de sus 3 cortes no tenían respaldo ni del chat ni de
  las cartas del hero. Además un board de longitud ilegal (`7cAc`, 2 cartas, 9 de
  403 frames) partía una mano en dos. No corta, y las longitudes ilegales se
  ignoran.
- **Filtro de mediana** sobre la serie de stacks: apenas ayuda (12 subidas → 11).
  Los errores no son picos aislados, son lecturas malas que persisten frames.

Las señales que **sí** cortan: las **cartas del hero** (precisa pero de poco
alcance —el hero se retira mucho— 2 cortes en 267 frames) y el **número de mano
del chat** (legible en el 70% de los frames, 13 cortes en 267). Llega con unos
frames de retraso, que es justo por lo que las ciegas suelen quedar fuera.

#### Lo que queda abierto

- La frontera llega tarde, así que las **ciegas casi nunca entran en la base**.
  Validado contra las reglas del poker: la SB sale como 0,5±0,3 solo en el 19% de
  las manos. No importa para atribuir subidas (la subida ocurre después de las
  ciegas) pero impide usar el comprometido como cuenta absoluta del bote.
- La suma de lo comprometido cuadra con el bote leído dentro del 25% en el 37% de
  los frames. Sirve como aviso, no como cuenta.

### 2.0c · Detección del tapete: solo funciona con temas CON COLOR

Salió jugando: cambiar el tapete a un tema **gris oscuro** rompió la app entera.
`find_reference` localiza el núcleo del tapete exigiendo píxeles saturados y con
brillo (`S≥45`, `V≥60`), y un gris tiene saturación **cero**.

| tapete | S | V | óvalo detectado |
|---|---|---|---|
| verde | 200 | 115 | **98%** (999 frames) |
| gris oscuro | **0** | 34 | **0%** (101 frames) |

Como **todas** las zonas son fracciones del núcleo, sin referencia todas quedan
desplazadas. Medido: de los 21 frames que cayeron en el fallback durante una
sesión con tapete verde, **cero** dieron cartas, botón, posición, stack o
recomendación (frente a 52%/95%/95%/48%/26% en los 978 con óvalo). O sea que el
fallback no aporta ni un frame útil.

**Ya arreglado a medias**: `analyze_layout` ahora **corta** en vez de seguir con
las zonas desplazadas, y el aviso nombra las dos causas que el usuario puede
arreglar (tema oscuro / recalibrar). Ahorra además ~1,1 s de OCR por frame.
Test sintético en `vision/test_table_reference.py`.

**Lo que queda**: hacer la detección independiente del color, para poder usar
cualquier tema. La vía obvia —el borde marrón del óvalo— se probó con umbrales de
color y **no** discrimina (0 componentes grandes, tanto en el tema verde como en
el oscuro), así que hace falta otra cosa: probablemente la **forma** (elipse
grande y uniforme) en vez del color. Sin eso, la restricción es real y hay que
documentarla al usuario: **el tapete tiene que tener color**. Solo el verde está
medido.

### 2.0d · Asiento fantasma: el fallo más caro que ha tenido la app — ✅ ARREGLADO

Salió revisando una sesión de un torneo **3-Max**. La app detectaba **4 jugadores
en el 34% de los frames** y le asignaba al hero la posición **CO**, que en una
mesa de 3 no existe. Como las posiciones se derivan del **recuento** de asientos
ocupados, un asiento de más las desplaza *todas*: alrededor de un tercio de las
624 recomendaciones de esa sesión usaron la fila de rango equivocada, con total
convicción y sin un solo aviso.

**Causa**: `_plate_occupied` aceptaba "un entero suelto" como stack. Era de la
época en que los importes podían estar en fichas. La **textura de puntos del
tapete** se OCR-ea como un número: la zona del asiento MR —tapete vacío, ni un
carácter— leía `'60668'` en los 60 frames muestreados.

**Efecto de quitarlo**, sobre 160 frames al azar:

| | antes | ahora |
|---|---|---|
| 3 jugadores (correcto) | 84 | **132** |
| 4 jugadores (imposible) | 58 | **9** |
| hero en CO (imposible) | 28 | **1** |

**Y un ajuste manual de tamaño de mesa** (`auto` / 2 / 3-Max / 6-Max / 9), en la
GUI. Si se detectan más asientos de los que caben, es una contradicción
demostrable: se suelta el de evidencia más débil —y solo si el corte es
inequívoco; si empata, no se dan posiciones—. El orden de evidencia es: hero y
asiento del botón (intocables) > dorso de carta o importe en BB > nombre legible
> solo un verbo de acción.

Verificado sobre los 9 frames que aún daban un recuento imposible: con
`max_players=3`, **7 se corrigen** (3 de ellos recuperan posición; los otros 4 no
la tienen porque en esos frames no se ve el botón del dealer) y **2 activan la
rama honesta** —no hay corte inequívoco, así que no se dan posiciones—. **Ninguno
queda con una lectura imposible.** El balance completo:

```
frames con recuento imposible (>3 en un 3-Max), muestra de 160
    antes                       58
    sin el entero suelto         9
    + tope manual en 3-Max       0
```

Lección general, la tercera vez que muerde lo mismo: **una señal heredada de una
etapa anterior se vuelve un falso positivo cuando cambia el contexto.** Ya pasó
con el área del botón en píxeles absolutos y con las zonas de apuesta.

### 2.0b · Zonas de apuesta: lo que se investigó y NO se cerró

**Prioridad ya baja: §2.0 lo tapa en gran parte** (las defensas pasaron de 6 a 18
y las abstenciones por subida no atribuida del 59% al 16%). Se conserva escrito
para que nadie repita las hipótesis descartadas, y porque el importe leído en la
mesa sigue siendo la **corroboración** del derivado.

Medido sobre la sesión del 25-07 (207 frames): `facing="bet"`
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

### 2.0e · Botón del dealer: medido, NO merece la pena tocarlo

Parecía el segundo problema más gordo: no se detecta en **175 frames (10%)** y es
la causa del 93% de los frames sin posición. Desglosado por lo que **cuesta**:

| | |
|---|---|
| sin mesa de verdad (lobby, estadísticas, entre manos) | 65 |
| con mesa visible → fallo real del detector | 110 |
| …de esos, **preflop con cartas → pierde la recomendación** | **1** |
| …postflop con cartas → degrada la equity (rangos genéricos) | 7 |
| …sin cartas del hero → no cuesta nada | 103 |

**Un frame en toda una sesión de 49 minutos.** La posición solo importa cuando el
hero tiene cartas, y en el 94% de los fallos no las tiene. Tocar el detector aquí
sería optimizar un número (10% → 1%) sin cambiar nada de lo que el usuario ve, y
con el riesgo de aflojar umbrales que hoy aciertan el 90%.

Se deja escrito para que nadie lo vuelva a priorizar por el porcentaje.

Efecto lateral que sí conviene saber: `find_reference` **no** rechaza una ventana
brillante que no sea una mesa (la de estadísticas de SharkScope pasa la guarda).
No hace daño —sin asientos ocupados no hay posiciones ni recomendación— pero es
el mismo hueco que §2.0c: la referencia se busca por color, no por forma.

### 2.1 Latencia — ✅ HECHO (commits 67b2ab7, 17fe44c, 977d939)

El ciclo bajó de **3,88 s a 0,96 s (4,0×)**. Primero de 3,88 a 1,59:

- **lote de OCR en paralelo** (6 procesos): 3,85 s → 1,45 s. Se dejan 10 núcleos
  libres a propósito; de 6 a 12 procesos solo se ganan 0,18 s más y saturar la
  máquina agrava el lag que se quería quitar.
- **fuera el doble OCR del chat**: −571 ms. El `GameState` ya expone
  `chat_lines`.

**Fase 2 (caché de rangos) y reparto por idioma — ✅ HECHO.** Perfilando el ciclo
apareció un reparto de costes que no era el que se suponía:

```
batch.run (OCR)                     0,937 s   83%
preparar + escribir los PNG         0,120 s   11%
find_reference                      0,029 s    3%
todo lo demas (imread, boton, dorsos, deteccion de cartas)  < 0,04 s
```

Y dentro del OCR, los rangos de carta son el **86% de los jobs** (90 de 105) pero
solo el **48% del tiempo**: 15 jobs de no-cartas cuestan 0,834 s frente a 0,759 s
de los 90 de cartas. El desglose por zona señala a una sola culpable:

| zona | jobs | tiempo |
|---|---|---|
| **chat (escala 2, español)** | 1 | **0,551 s** |
| botones (escala 2, español) | 1 | 0,346 s |
| nameplates | 6 | 0,380 s |
| zonas de apuesta | 6 | 0,249 s |
| chat en **inglés**, para comparar | 1 | 0,291 s |

Esos 0,26 s de diferencia son **cargar el modelo español**, y con el reparto
intercalado los dos únicos jobs que lo necesitan caían en procesos distintos, así
que se cargaba **dos veces**. Juntarlos en un trozo propio: 1,202 s → 0,888 s
(−26%) en el lote, verificado sobre 60 frames con **0 diferencias** en ningún
campo del `GameState`.

La caché de rangos aporta lo suyo por otro lado (81% de los recortes de carta se
repiten, con la clave sobre el interior del recorte).

**Las dos juntas, sobre los mismos 60 frames consecutivos:**

```
ANTES (intercalado, sin cache)   1,40 s/frame
AHORA (por idioma + cache)       0,96 s/frame     -31%
frames con resultado distinto:   0
```

Acumulado desde el principio del proyecto: **3,88 s → 0,96 s (4,0x)**.

Lo que queda de esta sección:

**Worker de OCR persistente — ✅ HECHO.** Los procesos viven entre lotes
(`ocr_worker --serve`) y las APIs de tesseract se cargan una vez por sesión en
vez de una por lote:

| | antes | ahora |
|---|---|---|
| lote de 6 jobs | 0,145 s | **0,005 s** |
| lote de 105 jobs | 0,22 s | **0,074 s** |
| OCR de una cápsula de nameplate | ~250 ms | **39 ms** |
| **ciclo completo** | 0,96 s | **0,684 s** |

Un worker que muere se reemplaza y el lote se reintenta **una** vez; a la segunda
se propaga el fallo, porque reintentar sin límite con un job que mata al worker
sería un bucle. El pool está acotado a `MAX_PROCS` y se cierra con `atexit` y al
cerrar la ventana.

**Acumulado del proyecto: 3,88 s → 0,68 s (5,7×).**

Lo que queda de esta sección:

**Recortes en memoria — ✅ HECHO, pero NO por velocidad.** Los recortes viajan
dentro del JSON en base64 en vez de por un PNG temporal. Medido con 105 recortes:
escribirlos a disco son **54 ms** y codificarlos en memoria **39 ms**, o sea 15 ms
de 690 — indistinguible. El 0,12 s que se le atribuía en el perfil era casi todo
el preprocesado (CLAHE, escalado), no el fichero.

Lo que sí gana: **desaparece el directorio temporal entero**. Antes cada job
escribía un PNG a un `tmpdir` que había que limpiar en un `finally`, y cuando ese
`finally` no estaba, cada fallo dejaba un `/tmp/vision_ocr_*` huérfano que en un
lazo en vivo se acumulaba. Verificado: **0 directorios temporales** en una corrida
de 60 frames.

Lo que queda de esta sección:

| cambio | ganancia estimada | esfuerzo |
|---|---|---|
| cachear el **chat** por hash de la zona | 0,55 s cuando acierta, pero solo es idéntica al frame anterior el 38% de las veces | 1 h |

### 2.2b · Buffer de captura rapida para leer las acciones — evaluado, con datos

Idea del usuario: capturar cada 0,1 s a un buffer circular de 10 frames, usar el
**verbo que el cliente pone en el nameplate** (`Pasar`, `Igualar`, `Subir`) para
saber quien hace qué, quedarse solo con el frame que cierra la jugada y descartar
el resto para no acumular memoria.

**La base ya está hecha**: el verbo se expone como `player["action"]` y ya no
contamina el nombre (commit `ec9729e`).

**Lo que cuesta, medido:**

| | |
|---|---|
| hashear los 6 nameplates (detectar que algo cambió, sin OCR) | **0,8 ms/frame** |
| buffer de 10 frames en memoria | **38 MB** |
| OCR de los 6 nameplates de un frame "interesante" | 0,38 s |

O sea que capturar a 10 Hz y filtrar por hash es perfectamente viable; solo se
OCR-ea el frame en que un nameplate cambia.

**Pero la ganancia es menor de lo que parece, y conviene saberlo antes de
construir nada.** Medido sobre la sesión del 26-07 (53 manos, muestreo real
1,48 s): se captan **300 apariciones distintas de un verbo, 5,7 por mano**, y una
mano de 3-max tiene típicamente 4-8 acciones. O sea que ya se está viendo la
mayor parte de lo que pasa; el buffer añadiría fiabilidad y **orden preciso**, no
un salto de cobertura.

**Antes de construirlo hay un arreglo gratis**, ya hecho: el selector de
intervalo era una PAUSA que se sumaba al ciclo, no un periodo. Con 0,5 s
configurado el muestreo real era 1,48 s; ahora se espera solo lo que falte, así
que baja a ~1,0 s — un 32% más de resolución temporal sin tocar la arquitectura.

**✅ HECHO** (`vision/seat_watch.py`). El lazo de captura pasa a ser el primario:
se captura cada **0,1 s** y de cada frame solo se comprueba si alguna cápsula ha
cambiado; el análisis completo se lanza cuando toca.

Dos decisiones que salieron de medir:

- **Se hashea solo la banda del nombre** (el 45% de arriba), no la cápsula
  entera: abajo va el stack, que cambia cada vez que se mueven fichas y disparaba
  un OCR sin que nadie hubiera actuado. Medido: cápsula entera 3,6 cambios/frame,
  banda del nombre 1,9-2,2.
- **Tope de seguridad** `VIGILANCIA_OCR_MIN_S`. Con los workers persistentes el
  coste de mirar una cápsula bajó de ~250 ms a **39 ms**, así que el tope está en
  0,12 s: ~8 miradas por segundo, de sobra para un cartel que dura más de 0,5 s.

**Queda por medir en vivo**: cuántas acciones se captan ahora frente a las 5,7
por mano de antes. Hace falta una sesión grabada con el código nuevo.

### 2.2 Historial de acciones de la mano — ✅ HECHO

`decision/action_log.py`. El chat **no** narra las acciones (solo resultados,
showdown, turnos y subidas de nivel), pero el cliente sí: cuando un jugador actúa
le **sustituye el nick por lo que ha hecho** (`Pasar`, `Igualar`, `Subir`). Esa
información se estaba tirando —peor, se leía como si fuera el nombre—.

Las dos piezas son complementarias:

```
hand_tracker   CUANTO ha puesto cada uno    (bajada de stack)
action_log     QUE hizo y EN QUE ORDEN      (verbo del nameplate)
```

El comprometido no distingue "pagar 4bb" de "subir a 4bb", y el orden no se
deduce de un total.

Lo delicado es la **deduplicación**: el mismo verbo está en pantalla varios
frames y contarlo dos veces convertiría una subida en dos. Se compara con lo
último visto *en ese asiento*, así que `Subir, Subir, (nick), Subir` son dos
subidas: volver a ver el nick cierra el evento.

`acciones()` marca **siempre `completo=False`**: el cartel dura menos que el
periodo de muestreo, así que faltan acciones por construcción.

**Comprometido por calle — ✅ HECHO.** El total de la mano no dice si hay una
apuesta que igualar *ahora*: en el turn, lo que un rival puso en el flop ya está
en el bote. `hand_tracker` expone ahora `comprometido_calle` junto al de la mano,
y el `GameState` lleva `calle_seguida`.

La calle se mide por el número de cartas de board y **solo puede avanzar**: el
board no encoge en una mano real, así que un board más corto —o ausente— es una
lectura perdida, no una calle anterior. Ignorarlo evita que una lectura floja
reinicie la cuenta y borre lo que un rival lleva puesto en la calle en curso.

**Preflop los dos números coinciden**, así que nada de lo que ya funcionaba
cambia; el valor está en postflop y en poder distinguir un squeeze de una
resubida.

Lo que queda de esta pieza: **usarlo**. El motor todavía razona con el total de la
mano porque solo decide preflop, donde son lo mismo.

### 2.3 · Marcar una situación con una nota mientras se juega — ✅ HECHO

Panel **"Marcar una situación para revisarla después"** en la GUI, entre "Mano
anterior" y las ciegas.

**Va en dos pasos, y ahí está todo el diseño**: el usuario ve la rareza y *luego*
escribe; con el ciclo en ~1,2 s, para cuando termina la frase ya han pasado
varios frames. Si la nota se pegara al frame del momento de guardar, apuntaría al
frame equivocado y la función no serviría de nada. Así que **"Marcar situación"**
fija de inmediato el frame que se está viendo —y lo guarda en disco en ese
momento— y el texto se aplica a ése, se tarde lo que se tarde en escribirlo. El
panel dice cuál está marcado y qué había en él (`Marcado el frame 0042 (23:41:07)
— Ah Kd · CO · FOLD`).

Se guarda en dos sitios: `nota` **dentro** del JSON del frame (la dupla sigue
siendo autocontenida: se abre el PNG y al lado está todo) y un índice
`_notas.jsonl` de la sesión para verlas de un vistazo. `_sesion.json` lleva la
lista de frames marcados y `resumen()` devuelve las notas enteras.

Casos cubiertos: **modo testing apagado** → crea `testing/notas-<fecha>/` al
vuelo y guarda ahí el frame marcado con su PNG y su JSON (marcar una anomalía es
justo cuando más falta hace tenerla guardada); **nada analizado todavía** → el
botón está apagado y lo dice; **guardar sin haber marcado** → la nota va al frame
actual pero se avisa en mayúsculas de que puede no ser el de la anomalía (negarse
fijaría el mismo frame y encima perdería el texto); **varias notas sobre el mismo
frame** → se acumulan, no se pisan.

Tests: `test_gui_notas.py` (20) simula el caso que justifica el diseño —marcar en
el frame 1, dejar pasar cuatro frames, escribir— y exige que la nota acabe en el
0001 y **no** en el 0005. `test_testing_session.py` sube a 38.

Estas notas son **exactamente las etiquetas que le faltan al proyecto** (§2.3b):
cada una es un caso real, elegido porque algo no cuadraba, con el frame y el
estado calculado al lado, generado jugando y sin sesiones de etiquetado aparte.

### 2.3c · Estabilizar la lectura entre frames — 🟡 los dos primeros hechos

**Hechos: la frontera de mano y el recuento de asientos.** Lo que queda de la
tabla de abajo: board, `facing`, `in_hand`, cartas del hero y stack.

#### La frontera de mano: 59% → 92% de aciertos

Se eligieron las señales midiendo contra el número de mano del chat sobre 3.300
frames de tres sesiones:

| juego de señales | cortes reales detectados |
|---|---|
| `chat` + cartas distintas (lo que había) | 44/75 = **59%** |
| `chat` + cartas que aparecen | 58/75 = 77% |
| `chat` + cartas aparecen + board vacío | **68/75 = 91%** |
| …y añadir "cartas distintas" a eso | 68/75, **+1 falso** |

Dos conclusiones que contradicen lo que se creía:

- **"Cartas distintas" era de las peores señales**, no la mejor. Acierta 3 de 52,
  y en una sesión sus 4 disparos fueron **todos falsos**: el OCR lee mal una carta
  del hero el 2,4% de los frames y ahí ve una mano nueva donde solo hay una
  lectura floja. Además es redundante — "cartas que aparecen" cubre el caso sin
  el ruido. **Retirada.**
- **"El board se vacía" se había descartado por miedo**, sobre 267 frames. Con
  3.300 resulta ser de las mejores: 35 de 52 y **cero** disparos sin respaldo.

Y un **mínimo de 4 frames por mano**, porque las señales se solapan (el board se
vacía, se reparten cartas y el chat cambia el número en un par de segundos) y sin
él una frontera real abría varias manos: el rastreador veía **110 manos donde el
chat contaba 53**.

#### El recuento de asientos: la posición del hero pasa de 3,9% a 1,8% de cambios

`hand_tracker.asientos_estables()` devuelve los asientos vistos en **al menos la
mitad** de los frames de la mano, y `analyze_layout` los acepta como parámetro:
mandan sobre lo que se lea en un frame concreto. Nadie se levanta a mitad de
mano, así que el conjunto es constante por las reglas del juego y lo que varía es
ruido.

Medido sobre 2.811 frames contra el conjunto **modal** de cada mano:

| criterio | acierta |
|---|---|
| lectura cruda (lo que había) | 85,7% |
| **unión** de todo lo visto | **72,5%** ← peor: acumula cada falso positivo |
| **mayoría** | **89,2%** |

La unión era la opción intuitiva y es la mala.

**Confirmado de punta a punta** sobre 270 frames reales, ejecutando el pipeline
completo dos veces (con y sin realimentación):

| | sin realimentar | con realimentar |
|---|---|---|
| cambios de nº de asientos dentro de la mano | 9 | **0** |
| cambios de posición del hero | 1 | 1 |
| manos detectadas | 5 | 5 (el chat dice 4) |

El recuento de asientos, que era el objetivo, queda **en cero**. El número de
posición sale 1 en los dos porque esa sesión son 3,5 minutos y hay poco que
medir; el dato fiable de la posición es el de las 2.568 transiciones (3,9% →
1,8%).

---

### 2.3c-bis · Lo que queda por estabilizar — medido y priorizado

La lección del nombre que bailaba generaliza: **casi todo lo que se lee tiene una
invariante dentro de una mano**, y cada violación es un error detectable sin
etiquetar nada. Medido sobre ~3.000 frames de tres sesiones:

| invariante dentro de la mano | rompe | de | % |
|---|---|---|---|
| **nº de asientos ocupados** (nadie se levanta a mitad de mano) | 287 | 2.756 | **10,4%** |
| **board** (solo crece, y lo visto no se pierde) | 130 | 1.324 | **9,8%** |
| botones (`facing`) | 46 | 676 | 6,8% |
| quién sigue en la mano (se retiran, no vuelven) | 180 | 2.756 | 6,5% |
| posición del hero | 126 | 2.639 | 4,8% |
| cartas del hero (constantes en la mano) | 44 | 1.805 | 2,4% |
| stack de un jugador (solo baja) | 235 | 11.265 | 2,1% |

**Ordenado por COSTE, no por frecuencia** (la lección del botón del dealer):

1. **Nº de asientos.** El más frecuente *y* el más caro: las posiciones salen del
   recuento, así que un asiento que parpadea desplaza **todas** y con ellas la
   fila de rango. Explica además buena parte del 4,8% de la posición del hero.
2. **Board.** Corrompe la equity. El patrón medido no es "otro board" sino
   **cartas que se pierden** (`5h 2h 6h Kd 8s` → `6h Kd 8s` → vuelve).
3. **Cartas del hero.** Solo el 2,4%, pero cuando falla cambia la recomendación
   entera. Barato de arreglar: mayoría dentro de la mano, igual que el nombre.
4. **Quién sigue en la mano.** Es el nº de rivales de la equity. Un rival que
   "resucita" la infla o la desinfla.
5. **Stack.** El rastreador ya rechaza las subidas internamente, pero lo que se
   muestra —y lo que elige la fila de rango para el hero— es la lectura cruda.

**El arreglo es el mismo para todas y ya está probado**: el rastreador guarda
estado por mano, así que puede imponer la invariante (mayoría para lo constante,
monotonía para lo que solo crece o solo baja). Con el nombre eso bajó el parpadeo
un 80%.

**Un aviso para no engañarse midiendo esto**: parte de las violaciones no son
lecturas malas sino **fronteras de mano que no se detectaron**, y ahí lo que hay
que arreglar es la segmentación, no la lectura. Conviene separarlas antes de
atribuirse una mejora.

### 2.3b Corpus etiquetado

El modo testing ya recoge la materia prima y las notas de §2.3 aportan los casos
interesantes. Falta un `score_samples.py` que compare contra etiquetas y diga si
un cambio de umbral mejora o rompe. Sin eso no se pueden tocar con seguridad los
~15 umbrales de `vision/seat_map.py`.

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

### Deriva 9-max / 6-max en las etiquetas de posición — ✅ ARREGLADO

Las etiquetas de `ranges.json` son de mesa de **9 plazas**, pero la visión
etiqueta según el recuento de asientos ocupados. La tabla `SEATING_BY_N` estaba
escrita a mano y a partir de 6 jugadores le daba `EP1` al primero en hablar
—siempre—. Pero **EP1 de una mesa de 9 tiene ocho jugadores detrás y el primero
de una de 6 solo tiene cinco**.

La regla correcta, y ahora `seat_map._posiciones` la deriva en vez de tenerla a
mano: **la equivalencia es por cuántos jugadores quedan detrás**, que es lo que
determina la anchura de un rango de apertura. Importa cuánta gente puede
despertarse después de ti, no cómo se llame tu silla.

| jugadores | primero en hablar, antes | ahora |
|---|---|---|
| 6 | `EP1` | **`MP2`** |
| 7 | `EP1` | **`MP1`** |
| 8 | `EP1` | **`EP2`** |
| 2 (heads-up) | `BTN` | **`SB`** |

Las filas de 3, 4, 5 y 9 ya eran correctas y siguen igual.

**Lo que costaba**, medido sobre `ranges.json` a 20bb: abrir desde UTG en 6-max
servía un rango del **17,0%** de las manos donde tocaba uno del **25,0%** — un
tercio más tight, en todas las manos abiertas desde esa posición. Y fallaba en
silencio, porque las posiciones se emparejan por cadena de texto.

El heads-up también mejora: el botón **es** la ciega pequeña, habla primero y
tiene un solo rival detrás, exactamente como la SB de una mesa de 9 —que además
es la única fila con `LIMP` digitalizado, la forma que pide ese spot—.

De camino se unificó la tabla: `dealer_button` tenía una **copia escrita a mano**
que se habría quedado con el mapeo viejo. Ahora importa la de `seat_map`.

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
  *ese* board concreto: inverificable. El índice se usa solo para **estudio
  post-mano** (`decision/rag/postmano.py`, ✅ hecho): al terminar la mano ofrece
  vídeos que hablan de situaciones *parecidas*, con el minuto exacto para poder
  comprobarlo, y el texto dice que no son de esa mano. La consulta se construye
  **solo con lo observado** —board, textura, mano ganadora, si hubo showdown—;
  enriquecerla con iniciativa o tipo de rival buscaría una mano que no es la que
  se jugó. Y hay umbral de similitud: sin él, una mano rara acabaría con tres
  referencias irrelevantes presentadas como si vinieran a cuento.
- **Multiplicador posicional sobre la equity.** El número de rivales ya está
  modelado simulándolos, así que multiplicar por un factor extra lo contaría dos
  veces; y la posición no cambia la equity sino su *realización*, para lo que no
  hay datos con los que calibrar. Es la forma más fácil de que el módulo mienta.
- **Aflojar un parseo para ganar cobertura.** Repetidamente: una recomendación
  plausible y falsa es peor que una abstención.
