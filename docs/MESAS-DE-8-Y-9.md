# Mesas de 8 y de 9: los asientos, medidos

Estado: **cableado y jugable**. El selector "Mesa" arranca en **Auto** y la
deduce del tapete; también puedes fijarla a mano antes de darle a Iniciar.

**El "auto" volvió el 04-08-2026, y esta vez detecta de verdad.** Se había
quitado con razón: entonces solo quería decir "no acotes y usa la disposición de
6", así que en una mesa de 8 leía 4,69 asientos de 8 y 2 nicks de 10 sin avisar
de nada — una opción que dice deducir algo y no lo deduce invita a dejarla
puesta. El de ahora mira **dónde caen los nameplates** y lo contrasta con las
tres geometrías medidas (`vision/disposicion.py`): sobre las 29 sesiones grabadas
con disposición conocida **acierta 20, se abstiene en 9 y no se equivoca en
ninguna**. Mientras no lo tiene claro usa la de 6 —como antes— pero lo dice, y no
recomienda, que es justo lo que la versión vieja no hacía.

Medido de punta a punta sobre dos sesiones reales de 8-max, reproduciendo los
mismos frames con una disposición y con la otra.

Sesión del 29-07 a las 20:12 (171 frames, ocho jugadores en la mesa):

| | disposición de 6 | **8-Max** |
|---|---|---|
| asientos leídos por frame | 4,69 | **6,34** |
| jugadores en mano | 1,01 | **3,81** |
| recomendaciones | 94 | **111** |
| nicks distintos | **2** | **10** (8 reales + 2 variantes de OCR) |

Sesión del 29-07 a las 19:17 (160 frames):

| | disposición de 6 | **disposición de 8** |
|---|---|---|
| asientos leídos por frame | 3,89 | **7,64** |
| jugadores en mano | 1,02 | **3,71** |
| recomendaciones | 16 | **33** |
| nicks distintos | **1** (solo el hero) | **8** (todos) |

## Qué falla hoy

`seat_map.SEATS` define seis zonas fijas, fracciones del núcleo del tapete
calibradas sobre una mesa de 6. En una de 8 no faltan dos zonas: **las que hay
caen en el sitio equivocado**.

| | mesa de 6 (lo que hay) | mesa de 8 (medido) |
|---|---|---|
| lado izquierdo | **un** asiento en y = +0,72 | **dos**: y = +0,44 y y = +0,93 |
| lado derecho | **un** asiento en y = +0,72 | **dos**: y = +0,44 y y = +0,95 |

El asiento de 6-max en +0,72 cae en el HUECO entre los dos de 8-max. De ahí que
`ML` y `MR` aterricen en tapete vacío y que dos jugadores queden invisibles.

Medido sobre la sesión del 29-07 a las 19:05 (381 frames) y las 19:17 (430):

    asientos leídos por frame     4,62   (hay 6-8 ocupados)
    frames con las cartas del hero  19 %
    frames con recomendación        10 %
    posición del hero              CO 51, SB 23, MP2 22, BB 6, HJ 4, BTN 3
    nicks leídos                   alex_delg ... y "Manos", "Frases", "Mesav",
                                   "Color", que son PESTAÑAS del cliente

## Los ocho asientos

**TRES POR CADA LADO Y DOS ENFRENTADOS**, que es como lo describe el usuario y es
lo que la medición reprodujo por su cuenta, sin saberlo de antemano.

Zonas de nameplate en fracciones del núcleo del tapete `(x0, y0, x1, y1)`,
sacadas de 349 frames. El nameplate mide 0,36 × 0,24 del núcleo, igual que en la
mesa de 6.

                        (x0, y0, x1, y1)                centro      visto
    ENFRENTADOS
      TOPC     (+0.33, -0.28, +0.69, -0.04)      (+0.51, -0.16)      98 %
      HERO     (+0.32, +1.01, +0.68, +1.25)      (+0.50, +1.13)      96 %
    LADO IZQUIERDO
      UL       (-0.14, -0.12, +0.22, +0.11)      (+0.04, -0.01)      82 %
      ML       (-0.23, +0.32, +0.13, +0.56)      (-0.05, +0.44)      93 %
      DL       (-0.14, +0.81, +0.22, +1.05)      (+0.04, +0.93)      52 %
    LADO DERECHO
      UR       (+0.77, -0.12, +1.13, +0.12)      (+0.95, +0.00)      93 %
      MR       (+0.89, +0.32, +1.25, +0.56)      (+1.07, +0.44)      98 %
      DR       (+0.77, +0.82, +1.13, +1.06)      (+0.95, +0.94)      90 %

LOS DOS DEL MEDIO SOBRESALEN, y ese detalle es la mejor señal de que la medición
es real y no ruido ajustado: ML está en -0,05 y MR en +1,07, mientras sus vecinos
de arriba y abajo están en +0,04 y +0,95. Es la panza del óvalo. Unas posiciones
inventadas habrían salido alineadas en columna.

`DL` sale en el 52 % y no en el 90 % porque ese asiento estuvo vacío buena parte
de las dos sesiones, no porque se lea peor.

Verificación a ojo en `casos/mesa8_ocho_asientos_localizados.png`: un frame con
los ocho asientos ocupados (todos poniendo ante) y las ocho zonas encima de su
nameplate, incluida la del jugador *Ausente*.

## Cómo se localizaron

Barriendo, no preguntando en sitios fijos. Misma idea que se usó con el disco del
dealer cuando se pasó de seis puntos fijos a un barrido de la mesa.

1. Máscara de cápsula (`CAPSULA_S_MAX/V_MAX`, ya medidos: un asiento vacío da
   0,005 y uno ocupado 0,357-0,443).
2. **Ventana deslizante del tamaño de un nameplate, con centro menos entorno.**
   Buscar componentes de la máscara NO vale: la cápsula se funde con las sillas,
   con la de al lado y con cualquier panel oscuro que caiga en el recuadro
   (medido: 458×284 para una cápsula de 429×113, y dos cápsulas en un blob de
   737×219). Y solo con el centro, cualquier mancha oscura grande puntúa alto en
   todas sus posiciones. Restando el anillo, una mancha uniforme puntúa ~0.
3. Acumular candidatos de cientos de frames y agrupar. Un frame suelto no basta:
   un asiento vacío no da cápsula.

## Lo que queda

- ~~**El barrido sobredetecta**~~ — sigue siendo cierto (7,83 candidatos por
  frame en la de 8 y 9,12 en una de 6) y por eso **el detector NO usa el barrido
  libre**. Se probó a limpiarlo con el filtro que quedaba apuntado —exigir tapete
  alrededor— y ayuda, pero el panel del cliente de la derecha sigue saliendo como
  cúmulo en casi todas las sesiones. La vía que sí funciona es la contraria:
  preguntarle a cada geometría conocida si SUS zonas tienen cápsula, que es una
  pregunta acotada. Ver `vision/disposicion.py`.
- ~~**La disposición la eliges tú**~~ — **ya se detecta sola** (04-08-2026), con
  abstención: 20 aciertos, 9 abstenciones y 0 errores sobre las 29 sesiones
  etiquetadas. Sigue mandando lo que elijas a mano; en Auto, mientras no hay
  evidencia se usa la de 6 y **no se recomienda**, porque las posiciones salen del
  recuento de ocupados y con la geometría equivocada son plausibles y falsas.
- **La mesa de 7 sigue sin tabla, y no por olvido.** Se buscó a propósito: se
  barrieron las cápsulas de las 53 sesiones grabadas sin partir de ninguna
  geometría, y las 38 con tapete detectable salen todas de 6, 8 o 9 —incluidas las
  12 que no llevan la disposición apuntada en su metadata—. **Una final de 7
  jugadores no es una mesa de 7 plazas**: es una de 9 con dos asientos vacíos, y
  eso ya está cubierto (la geometría sale 9 y el recuento, 7). Medir una tabla de
  7 hace falta el día que aparezca una mesa que de verdad no encaje; mientras
  tanto el detector se abstiene en vez de inventarla.
- **Las zonas de APUESTA siguen siendo derivadas y sin validar.** Se asume por
  cómo se usan: el importe leído ahí nunca crea una subida, solo atribuye una que
  el botón "Igualar" ya ha demostrado que existe, así que una zona mal puesta
  hace que no se atribuya, no que se invente. El método para medirlas **ya está
  probado** —se aplicó a la mesa de 9, ver abajo— y se puede repetir en cuanto
  haya dos sesiones de 8 con apuestas.
- **Las zonas de DORSO están validadas, y DL y DR se RE-MIDIERON** (30-07-2026).
  Entraron derivadas sobre la sesión del 29-07 a las 20:12 y funcionaban, pero
  con menos margen que las demás; barriendo su entorno sobre 339 frames se
  movieron y ganaron el doble de margen:

        asiento   p90 derivado   p90 re-medido   se movió
        DL           0,191          0,341        (+0,10, -0,06)
        DR           0,232          0,342        (-0,10, -0,06)

  Las de arriba y de los lados se quedan como estaban (UL 0,286, UR 0,359).
  Todas bimodales -p50 = 0 cuando no hay cartas- y por encima del umbral (0,10).
- La parte de DECISIÓN ya lo soporta entero: `SEATING_BY_N[8]` da
  `BTN, SB, BB, EP2, MP1, MP2, HJ, CO`, derivado por cuánta gente habla después
  de ti contra los rangos de 9-max digitalizados.


---

# Mesa de 9: cuatro por cada lado y nadie en frente

Estado: **cableada y jugable**. Elige **9 plazas** en el selector "Mesa".
Geometría completa y medida: asientos, dorsos y —desde el 30-07— también las
zonas de apuesta. Dos salvedades que conviene leer antes: *"Heads-up en una mesa
de 9"* y *"El lazo rápido NO usa la geometría de 9"*, más abajo.

Lo describe el usuario así: *"si tenemos como referencia al hero que soy yo
abajo, 4 andan a mi izquierda y otro 4 a la derecha, nadie en frente"*. La
medición lo reprodujo por su cuenta.

**No hay asiento de enfrente.** Los dos de arriba están a los LADOS del centro
(+0,26 y +0,74), no en él, y por eso la tabla de 9 no tiene `TOPC` sino `TL` y
`TR`. Es la diferencia estructural con la de 6 y la de 8, que sí lo tienen.

## Los nueve asientos

Medidos sobre la sesión del 29-07 a las 21:35 barriendo el tapete: salen **nueve
cúmulos, cada uno en el 96-100 % de los frames, y ninguno falso**. Verificado a
ojo en `casos/mesa9_nueve_localizados.png`.

    lado           asiento   centro (fracción del núcleo)
    izquierda      TL        (+0.26, -0.18)
                   UL        (-0.08, +0.07)
                   ML        (-0.09, +0.51)
                   DL        (+0.04, +0.95)
    derecha        TR        (+0.74, -0.15)
                   UR        (+1.09, +0.07)
                   MR        (+1.09, +0.50)
                   DR        (+0.97, +0.97)
    enfrentado     HERO      (+0.51, +1.16)

## Lo que gana, medido

Reproduciendo los 209 frames de esa sesión con una disposición y con la otra:

| | disposición de 6 | **9 plazas** |
|---|---|---|
| asientos leídos por frame | 2,46 | **6,72** |
| jugadores en mano | 0,93 | **3,62** |
| nicks distintos | 4 | **14** (≈10 reales + variantes de OCR) |

Los nueve asientos se leen en 204-209 de los 209 frames.

### Las recomendaciones bajan, y es una mejora

Con la sesión larga (1.885 frames) el patrón se repite y ya se puede explicar:
**64 → 56 recomendaciones**. Los motivos de abstención son idénticos en las dos
disposiciones; lo que cambia es la POSICIÓN que se te asigna. Mirando frame a
frame: **17 recomendaciones se pierden y 9 se ganan.**

Y las que se pierden son las que había que perder. En los frames 0046-0051:

| | te cree | dice |
|---|---|---|
| disposición de 6 | SB | **OPEN RAISE ALL IN** |
| disposición de 9 | BB | se abstiene: *"lo último que se vio en la mesa fue a un rival"* |

En `casos/mesa9_reco_equivocada_con_la_de_6.png` se ve ese frame: el disco está
junto a golfker, un asiento dice **"Subir"**, el hero tiene **J♥ 3♠** y los
botones piden **Igualar 5,13 BB**. O sea que el hero enfrenta una subida y con la
disposición de 6 la app le decía que abriera all-in con J3 desparejado.

Recomendar una APERTURA enfrentando una subida es, en palabras del propio
`decision/engine`, *"el peor fallo posible en esta app"*. Con 4 de 9 asientos
leídos el anillo de posiciones no puede estar bien, y esas 17 recomendaciones
salían de ahí.

## Lo que NO está medido, y hay que saberlo

- **Ocho de las nueve anclas del botón están MEDIDAS** (disco visto en 1.157
  frames de dos sesiones largas). La primera versión las derivaba y se equivocaba
  una media de 0,083 del núcleo, hasta 0,158 en HERO y 0,144 en MR — y el disco se
  atribuye al ancla más cercana, así que a esa distancia el botón se le puede dar
  al vecino. **`ML` sigue derivada, y ya NO es por falta de datos**: se volvió a
  buscar con **4.469 discos de tres sesiones sin muestrear** y ese asiento no
  aparece. Las otras ocho se confirman dentro de 0,01. El único cúmulo nuevo (108
  muestras, 2,4 %) cae entre TR y UR, o sea el disco pillado a medio deslizarse de
  un asiento al siguiente. En esas mesas el medio-izquierda estuvo vacío casi
  siempre y el botón lo saltaba.
- **Las zonas de dorso están validadas** sobre 381 frames. Siete de las ocho
  salieron bien a la primera (p90 entre 0,234 y 0,393 contra un umbral de 0,10);
  **DR se quedaba en 0,123** y se re-midió barriendo su entorno hasta 0,369.
- **Las zonas de apuesta YA ESTÁN MEDIDAS** (ver abajo). Solo queda `DR` sin
  validar.

## Las zonas de apuesta, medidas: 93 → 588 importes leídos

Eran lo único de esta disposición que seguía derivado del desplazamiento del
asiento equivalente de la mesa de 6, y estaban muy mal puestas.

La calibración por contenido no las cubre —no contienen cartas, así que no hay
anchos que comparar— pero tienen una señal propia: **de una zona de apuesta tiene
que salir un importe en BB legible cuando el jugador ha apostado.** Se barrió el
desplazamiento contando importes leídos, sobre dos sesiones (A/B):

    asiento   derivada (A/B)   medida (A/B)
    TL             0 /   0        88 / 167
    UL             5 /   6        39 / 129
    TR             8 /  27        96 / 189
    DL             0 /   0        47 /  58
    ML             1 /  13        16 /  48
    MR             2 /  27        13 /  43
    HERO           0 /   0         8 /  10
    UR             8 /  24        10 /  21   <- se queda como estaba
    DR             0 /   0         0 /   0   <- no lee nada con ninguna posición

Total sobre la misma muestra de la sesión B: **93 → 588 importes leídos.**

**VALIDARLAS EN LAS DOS SESIONES CAMBIÓ EL RESULTADO**, y esa es la parte que
merece quedar escrita. El primer barrido usó UNA sesión y daba para TR y UR unos
desplazamientos que en la otra bajaban a CERO: sobreajuste puro, 23→0 y 24→0.
Barriendo contra las dos a la vez y cogiendo el mínimo, TR sale a otro sitio -y
mejor que el del sobreajuste- y UR resulta que no mejora, así que se deja donde
estaba.

`DR` no lee nada con ninguna de las 16 posiciones probadas. Puede que en esas dos
sesiones ese asiento no apostara de forma visible, o que su importe caiga fuera
del barrido. Queda derivada y sin validar, y es lo único de la tabla que no está
medido. NO ES CRÍTICO por cómo se usan: el importe leído aquí nunca crea una
subida, solo ATRIBUYE una que el botón "Igualar" ya ha demostrado que existe.

### Lo que se aprendió sobre derivar zonas

Derivar el desplazamiento del asiento equivalente de la mesa de 6 **funciona
arriba y en los lados, y se queda corto ABAJO**. Tres asientos entre las dos
mesas lo dicen:

    mesa    asiento   p90 derivado   p90 re-medido   se movió
    9       DR            0,123          0,369       (-0,13, -0,10)
    8       DL            0,191          0,341       (+0,10, -0,06)
    8       DR            0,232          0,342       (-0,10, -0,06)

Los tres se van **hacia dentro y hacia arriba**, en cantidades simétricas: ahí el
cliente dibuja la carta más pegada al nameplate, seguramente porque no tiene
sitio. No son suficientes para llamarlo regla, pero sí para saber que los
asientos de abajo hay que comprobarlos uno a uno.

## La mesa de 9 ensanchó el margen de las cartas reveladas

`REVELADA_MARGEN` pasó de 0,06 a **0,12**, y el motivo salió de esta disposición.

En un torneo donde se ven las manos de todos se perdía el **14 % de las manos
reveladas (24 de 173)**, y casi siempre el mismo asiento: `UR`, que salía con
`revealed=True` y `cards=None`. O sea que el par SÍ se detectaba y los rangos NO
se resolvían. La causa es la misma que cortaba la primera carta del board: la
zona de revelada se deriva de la del DORSO, calibrada para el blob que asoma por
detrás del nameplate -más pequeño que la carta entera-, y **en la mesa de 9 el
asiento UR está lo bastante lejos como para que 0,06 de margen no llegue.**

    margen   pares   ambas resueltas   cajas estrechas
    0,06        61     58  (95%)              8
    0,09        94     88  (94%)              5
    0,12       101    100  (99%)              1
    0,15       114    111  (97%)              2

Los 40 pares que aparecen de más respecto a 0,06 son REALES, no falsos positivos:
se ve porque resuelven los dos rangos. Manos reveladas leídas de 1,77 a 2,01 por
frame.

El comentario anterior decía *"ensanchar más no cambia el resultado, probado
hasta 0,14"*, y **esa medición era correcta PARA SU CONTEXTO**: cuando se hizo, la
única disposición era la de 6. Lo que cambió es que ahora hay mesas de 8 y 9 con
asientos en otros sitios.

## Heads-up en una mesa de 9: arreglado a medias

Sesión del 30-07 a las 03:00, dos jugadores en una mesa de 9 plazas. La app dio
**CERO recomendaciones en 80 frames.**

**Lo que se arregló**, con un mínimo medido detrás de cada constante:

- `REF_MIN_PARA_FIJAR` **10 → 30**. El ancho del núcleo salía 974 en los 80 frames
  -perfectamente estable- y el ALTO era bimodal: 475 en 35 frames y 358 en 27. La
  referencia se fijó en 358, **la minoría**, porque la mediana de las 10 primeras
  cayó ahí. Barrido sobre 17 sesiones: 451 → 434 → 420 → 402 descartes con
  N = 10/20/30/40. Se elige 30 y no 40 porque durante el calentamiento el guardián
  de "la mesa no está donde dice" NO OPERA, y ese guardián existe porque una vez
  apareció un jugador fantasma llamado *"Ciegas"* leído de un panel.
- `REF_SEGUIDAS_PARA_REFIJAR` **15 → 10**. La racha más larga de descartes era 14,
  UNO por debajo del umbral: la app se quedó 14 frames ciega y el contador se
  reseteó sin re-fijar. Barrido: 496 / 468 / 451 / 518 / 469 con N = 15/12/10/8/6.
  Hay mínimo y está en 10.

Efecto en esa sesión: descartes del 50 % al 26 %, jugadores por frame de 0,80 a
1,23. Y en una sesión de 9 sana no empeora nada: 26 % de descartes con 6,67
jugadores por frame y 51 recomendaciones en 120 frames.

**LO QUE SIGUE SIN ARREGLAR, y hay que decirlo: esa sesión sigue dando CERO
recomendaciones.** El alto del núcleo se detecta **15 % corto** -el detector coge
solo la banda central del óvalo- así que las zonas quedan comprimidas y el
nameplate del rival cae **ENTRE `TL` y `UL`**, sin que ninguna lo pille. Capturado
en `casos/mesa9_heads_up_geometria_mal.png` con las zonas pintadas encima.

Es la misma causa de fondo de siempre -la precisión de la referencia- en su forma
más dañina hasta ahora. La conclusión que ya salió de atacarla cinco veces sigue
en pie: **la estrategia correcta es MARGEN EN LAS ZONAS, no precisión en la
referencia.**

## El lazo rápido NO usa la geometría de 9

**Es el hueco abierto de esta disposición, y no está medido.**

Hay dos funciones que reparten geometría en `vision/seat_map.py`, y **solo una
conoce la mesa de 9**:

    zonas(9)        -> 9 asientos   (ZONAS_POR_DISPOSICION, tiene 6, 8 y 9)
    disposicion(9)  -> 6 asientos   (DISPOSICIONES, solo tiene 6 y 8)

`zonas()` es la que usa el análisis pesado (`table_state.analyze_layout`), así que
**todo lo medido en este documento sigue siendo cierto**. Pero `disposicion()`
tiene un único consumidor —`core/analisis.py`, donde construye `self.seats` y con
él **el `SeatWatch` del lazo rápido**— y ahí cae al `.get(..., SEATS_6MAX)`.

O sea que en una mesa de 9 el lazo de 10 Hz que caza los verbos de acción vigila
**las seis zonas de la mesa de 6**. Restando las coordenadas de las dos tablas:

    zona de 6-max          dónde cae en la mesa de 9
    TOPC  (x 0,36-0,69)    el hueco central entre TL y TR: tapete vacío
    ML    (y 0,60-0,85)    el hueco entre ML (y 0,39-0,63) y DL (y 0,83-1,07)
    MR    (y 0,60-0,85)    ídem, entre MR y DR
    UL, UR, HERO           solapan parcialmente, desplazadas ~0,13

Importa porque `vigilar()` escribe en `action_log.observar(seat, accion)`, y de
ahí salen `primera_agresion_seat`, `ultimo_agresor_seat`, `rival_posterior_seat` y
`limper_seats_observed`, que `decision/engine` lee en nueve puntos. Un verbo leído
en el borde de `DL` y etiquetado `ML` **atribuye la agresión al asiento
equivocado**.

Ningún test cubre `disposicion()`: los de `vision/test_disposicion_mesa.py` van
todos contra `zonas()`, que sí tiene el 9. Por eso el hueco pasó desapercibido.

**No está medido cuánto daño hace** —haría falta reproducir una de las sesiones de
9 de `testing/` contando qué asientos emite `vigilar()`— y hasta que lo esté, esto
es una deducción del código, no una medición. El arreglo natural es que
`disposicion()` salga de `ZONAS_POR_DISPOSICION` en vez de un segundo diccionario
que se desincroniza.
