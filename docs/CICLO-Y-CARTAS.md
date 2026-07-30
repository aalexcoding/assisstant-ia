# Ritmo medido, censo de mesa y reconocimiento de cartas

Estado a **2026-07-29**. Es el plan en curso: qué se ha hecho, con qué medida, y qué
queda. Para el mapa general del proyecto, [`DONDE-VAMOS.md`](DONDE-VAMOS.md); para el
detalle de tareas anteriores, [`PENDIENTE.md`](PENDIENTE.md).

## Por qué

Con la suite de tests ya puesta (commits `2ad65b5` y `89ee297`: 1.167 tests, cobertura
87,5 %, regresión de oro sobre las sesiones grabadas), el usuario pidió cinco cambios sobre
el ciclo de análisis. Cuatro salen de notas que dejó jugando.

Al medir para planificarlos, **tres suposiciones que llevaban tiempo escritas en el código
resultaron falsas**, y eso reordenó las prioridades:

| lo que decía el repo | lo medido |
|---|---|
| el ciclo tarda "2-4 s" (README), "0,7 s" (`gui.py`), "~950 ms" (`seat_watch.py`) | **0,45-0,82 s de mediana, 0,83-1,15 s de p95** según sesión |
| el lazo rápido va a 10 Hz | **4,5-6,6 Hz** reales: su propio OCR (91-256 ms) se come el periodo |
| el intervalo elegido en el GUI es el periodo | pides 1,0 s y analiza cada **1,6-1,9 s** (se cuenta desde que TERMINA) |
| quitar el chat ahorra poco (va en trozo paralelo) | **cuesta 281 ms de 875, el 32 % del ciclo** |

Y tres defectos que nadie había visto:

- **`find_reference` se llama dos veces por frame** (`core/analisis.py` y dentro de
  `referencia.de()` en `table_state.py`): 34 ms tirados, y —lo grave— **el lazo rápido vigila
  la referencia CRUDA del frame mientras el lento usa la FIJADA**, así que no hashean las
  mismas cajas que se juzgan.
- **En el frame de frontera de mano, `analyze_layout` recibe el conjunto estable de la mano
  ANTERIOR**, porque `asientos_estables` se calcula antes de que `tracker.update` abra la
  mano nueva. Medido sobre 246 fronteras: **61 (25 %) con `players` ≠ `asientos_leidos`,
  44 asientos añadidos y 35 borrados por memoria**. En Zoom, donde el cliente cambia de mesa
  entre manos, es pintar la mesa vieja encima de la nueva.
- **`FrameBuffer` no tiene ningún lector en producción**: 4,67 MB de `copy()` por tick.

## Decisiones tomadas

- **El chat sale del ciclo, los botones NO.** De los botones salen `facing`, `to_call` y
  `vs_position`; sin ellos desaparece la defensa contra subidas, la guarda de la opción de la
  BB (el 22 % salían mal sin ella) y la red que llevó "sin explicar" del 65 % al 19 %. Y
  reintroduciría el bug que el propio usuario reportó (frame 0181: *"no entiendo por qué me
  dice que suba sobre limpers, yo era ciega"*).
- **Los dos lazos NO se fusionan.** El rápido se queda y *gana* la verificación de mesa.
- **En cartas se hacen las dos cosas**: primero la vara de medir, después el rango a OCR.

---

## El contrato entre los dos lazos

**El hecho que manda**: `Analizador.tick()` solo lo llama `gui.py`. `replay.py`, `alpha.py` y
toda la suite llaman únicamente a `analizar()`. Por tanto **todo lo que el lazo rápido posea
es irreproducible en frío**. Ése es el límite de lo que puede poseer. Ya hay precedente:
`state["acciones"]` y `state["vigilancia"]` los escribe el rápido y están fuera de
`CAMPOS_ORO`.

| nivel | datos | dueño |
|---|---|---|
| **1 · DECIDIR** | `asientos_leidos`, `position`, `stack`, `to_call`, `facing`, `hero_cards`, `board` | **solo el lento** |
| **2 · PINTAR** | nombre del asiento, estado 1-4 | el lento primero, el rápido rellena huecos **en la misma urna** |
| **3 · AVISAR** | "este asiento ha cambiado de ocupante" | el rápido levanta bandera, jamás reescribe |

**La trampa a evitar**: `asientos_estables()` es `{s : _veces[s]*2 >= _frames}` y `_frames`
cuenta frames **lentos**. Si las observaciones rápidas incrementaran `_veces`, la mayoría
degeneraría en la UNIÓN, que está medida en **72,5 % de acierto frente al 89,2 % de la
mayoría**. El rápido deposita votos de NOMBRE, nunca de ocupación. Compartir nombres es seguro
porque *"el nombre NO ENTRA EN LA DECISIÓN: solo se pinta"*.

---

## ✅ Fase 0 — Instrumentar

`vision/table_state._Reloj` cronometra por etapas y lo cuelga de `state["tiempos"]`, así que
va al JSON grabado y **cada sesión futura lleva su propio perfil**. `testing_session.resumen()`
agrega `ciclo_p50_s`, `ciclo_p95_s` y `etapas_p50_s`; `replay.py` lo imprime.

Medido sobre esta máquina, antes de tocar nada:

```
ocr                878.0 ms   90.6%
disco               53.0 ms    5.5%
dorsos              18.0 ms    1.9%
referencia          16.0 ms    1.7%
cartas               2.0 ms    0.2%
```

**El OCR es el 90 % del ciclo.** Todo lo demás junto son migajas.

## ✅ Fase 1 — El chat, espaciado

`analyze_layout(..., leer_chat=True)` es el interruptor; **la política de cuándo vive en
`core/analisis.py`**, que es quien tiene el estado entre frames. Se lee al cerrarse una mano
(pidiéndolo para el frame *siguiente*: la frontera se detecta cuando `analyze_layout` ya
corrió, y además la línea "X gana el bote" tarda en aparecer), en los primeros
`CHAT_FRAMES_INICIALES`, y como guardarraíl cada `CHAT_MAX_S`.

El último `hand_result` **se conserva**: un frame sin lectura no significa "no hay mano
anterior", significa "no se ha vuelto a mirar".

A/B controlado sobre los **mismos 60 frames** de `sesion-2026-07-29_003632`:

| | ciclo p50 | p95 | OCR | recomendaciones |
|---|---|---|---|---|
| chat siempre | 1,003 s | 1,224 s | 858 ms | 24 |
| **chat espaciado** | **0,739 s** | **0,930 s** | **604 ms** | **24** |

**−264 ms por frame (26 %)**, y `replay --diff` sobre 200 frames: **0 pérdidas, 0 ganancias,
0 cambios**.

Sobre 300 frames: lecturas de chat **298 → 15** (−95 %), manos detectadas 13 → 13, frames con
`hand_result` 299 → 299. **Coste honesto: un número de mano de diez se pierde.** Alimenta la
señal `mano_chat` (que no corta) y la firma anti-parpadeo del HUD, así que no cambia ninguna
decisión.

---

## ✅ Fase 2 — La referencia duplicada y el disco solapado  ·  `e9ce22f`

**Cero cambios de campo.** `replay --diff` tiene que dar 0 diferencias.

- **Quitar la segunda `find_reference`**: `Analizador` toma `self._ref` de
  `referencia.fijada`, no de una llamada propia. Gana 17 ms **y** deja a los dos lazos mirando
  las mismas cajas, que la fase 4 necesita.
- **Solapar el disco con el OCR.** `disco_dealer.detectar` (50 ms), `detect_in_hand_seats`
  (17 ms) y el respaldo por anclas (18 ms) son OpenCV puro, no necesitan el resultado del lote
  y hoy corren **en serie después**. Lanzarlos en un `ThreadPoolExecutor` justo antes de
  `batch.run()` —donde el hilo está bloqueado esperando subprocesos— y recogerlos después.

**Evaluado y descartado con datos**: que el lazo rápido vigile el disco. Son 50 ms a 10 Hz, el
50 % de un núcleo, contra un presupuesto de tick de ~1 ms. Si alguien lo intenta con
`mascara_roja` acotada a las 6 anclas, **el criterio se escribe antes de medir**: si no baja de
~5 ms para los seis, no entra.

## ✅ Fase 3 — Re-censo al terminar una mano  ·  `69acd6b`

Es la nota del frame 1333: *"no se han actualizado correctamente los nombres de los jugadores,
hay que actualizar los jugadores al comienzo de cada mano"*.

### 3a. Que la memoria no contradiga la evidencia de ESTE frame

Ya existe una excepción y funciona (*"ni siquiera la memoria borra un asiento con cartas
delante"*). Dos simétricas más, con la evidencia que `_fuerza_ocupacion` ya clasifica:

- **no se BORRA** un asiento cuyo nameplate trae un importe con sufijo `BB` en este frame;
- **no se AÑADE** por memoria un asiento cuya `_capsula_frac` de este frame dice HUECO.

Cuesta 0 ms (la métrica ya está calculada en ese bucle). Si queda contaminación, la
alternativa es decidir la frontera **antes** de `analyze_layout`, que cuesta 50 ms en serie —
se decide con el dato, no antes.

**Esta fase debe bajar los techos de `jugadores_cambian` (0,028) y `posicion_cambia` (0,020)
que se subieron en `tests/test_invariantes_corpus.py`.** Están marcados como provisionales
justo por esto.

### 3b. Qué se olvida al abrir mano

| estado | hoy | propuesta |
|---|---|---|
| `SeatWatch._ultimas` | no se toca; `olvidar()` **sin ningún llamador** | **`re_censar()`** |
| `FrameBuffer` | se escribe, **nadie lo lee** | **quitarlo** hasta que haya consumidor |
| `engine._last_hero_stack` | TTL 90 s, sobrevive a la mano | caducar **solo si no baja el nº de recomendaciones** |
| `gui._ultimo_board` | no se toca | vaciar tras usarlo en el estudio post-mano |
| `referencia`, `plantilla_boton`, `escala_glifo` | no se tocan | **correcto**: son de la ventana, no de la mano |

**`olvidar()` es la primitiva equivocada**, y es la trampa fina: `cambios()` documenta que *"la
PRIMERA vez que se ve un asiento NO cuenta como cambio"*, así que olvidar haría que el
siguiente tick **no OCR-eara ninguna** cápsula — lo contrario de un re-censo.

### 3c. Que el respaldo no pinte un nombre viejo sobre un jugador nuevo

Hoy caduca por **ausencia**; en Zoom no basta, porque el asiento sí se ve pero es otra persona.
Medido: **24,1 % de las filas** muestran un nombre de una mano anterior, y de 859 mano-asiento
con respaldo, **106 resultaron ser otro nombre** (`Conexi6n → anaes`, `Mig070883 → bated`: no
son variantes de OCR).

Regla nueva **por discontinuidad de stack** entre la última lectura de la mano H y la primera
de H+1. **El umbral no se elige, se mide**: distribución sobre las fronteras del corpus,
separada por "mismo nick" y "nick distinto". Si separan, el umbral cae en el valle; **si no
separan, la regla no entra**.

Y **el HUD deja de mentir por omisión**: `name_de_mano_anterior` ya viaja en el state y
`players_markup` lo ignora.

## 🟡 Fase 4 — El lazo rápido verifica la mesa  ·  `19a3640`

Cableada y con test de contrato. **Lo que gana, medido con un A/B controlado
sobre los mismos frames: UNA mano-asiento de 86.** El mecanismo funciona y
cuesta cero, pero el lazo lento ya leía el 96,5% de los nombres. Donde valdría
es en condiciones malas, como la sesión de torneo que perdía el 28,6%.

Presupuesto medido del tick (hoy gasta 91-256 ms cuando OCR-ea):

| candidato | coste | veredicto |
|---|---|---|
| el nombre de la cápsula que **ya** se OCR-ea | **0 ms** | **sí** — hoy se tira |
| `_capsula_frac` × 6 | **0,97 ms** | **sí** |
| `revealed_pair_seats` | 3,19 ms | medir: solo importa en all-in |
| `detect_in_hand_seats` | 12,41 ms | **no a 10 Hz** |
| `disco_dealer.detectar` | 49,47 ms | **no** |

Queda en **fracción de cápsula (1 ms) + los nombres que ya está leyendo (0 ms)**. Ésa es la
respuesta medida, no la que uno querría. El rápido mira las cápsulas **1,6× más** que el lento
y justo cuando cambian, que es el instante en que el verbo se va y el nick vuelve.

Aflora en `state["censo"]`, que va a los campos **no comparados** de `replay.py`.
`gui.players_markup` pinta con el estado: **amarillo** = 3/4 (en mano), **gris** = 2 (sentado
sin jugar) — la nota del frame 254.

**Métrica que manda**: cuántas de las **234** mano-asiento que hoy no leen nombre en toda la
mano pasan a leerlo. Hace falta sesión en vivo: en frío no hay ticks.

## ✅ Fase 5 — Ritmo medido, y fuera el selector  ·  `e9981f1`

Se mide **en caliente**, con los primeros ~30 frames de la sesión. Descartado medir al arrancar
con frames grabados (habría que versionarlos, y el proyecto se niega a eso por diseño) y el
microbenchmark sintético (mide un sustituto, no el ciclo).

```
periodo = max(PERIODO_MIN_S, p95_ciclo + TICKS_MIN_ENTRE_ANALISIS * VIGILANCIA_PERIODO_S)
```

**p95 y no p50** porque el suelo natural es el propio ciclo, y un p50 deja la mitad de los
frames sin hueco (medido: p95/p50 va de 1,4× a 2,1×).

**`TICKS_MIN_ENTRE_ANALISIS` se mide, no se elige**: se barre el hueco contra
`acciones_por_mano` (que ya está agregado) y se coge la rodilla.

**No se guarda en ningún sitio permanente**, y eso se defiende: el ciclo depende de la ventana,
el tema, el mazo y qué más hace la máquina. Un número en disco se quedaría viejo exactamente
igual que los tres que había. Se mide por sesión y se graba en `_sesion.json`.

**Qué sustituye al selector** (`Gtk.SpinButton` de 0,25-10,0 s): una etiqueta de solo lectura.

> `Ritmo: 0,79 s/análisis (p95 1,10) · 1,9 s por vuelta · vigilancia 4,7 Hz`

El usuario deja de elegir y empieza a **ver**. Hoy 8 de los 40 valores del spin son físicamente
imposibles y ninguno describe el periodo real.

## ✅ Fase 6 — Cartas: primero la vara de medir  ·  `6307359`

Con ~7.700 frames grabados y cero etiquetas, la vara sale de **señales que no dependen del
propio detector**:

- **el board solo crece dentro de una mano** y lo visto no se pierde (falla el **9,8 %**);
- **las cartas del hero son constantes** dentro de la mano (**2,4 %**);
- **ninguna carta en dos sitios**, ni repetida en el board;
- **el board tiene 0/3/4/5 cartas** (`board_ilegal`, hoy **1,96 %**);
- **el chat dice la mano ganadora** ("escalera de color, de dos a seis"), etiqueta parcial y
  gratuita del board + las cartas del showdown.

Nuevo `herramientas/score_cartas.py`. Reutiliza `tests/corpus.py` y `core/invariantes.py`.

**Antes de tocar detectores hay que tapar dos huecos**: `_cajas_de_carta` (la regla "gana el
que encuentra más cartas") y `_encolar_cartas` (el orden calco → caché → OCR) **no tienen ni
un test**, y son justo lo que un camino nuevo rompería.

## ✅ Fase 7 — El rango a OCR de verdad, con los dos mazos vivos

**Se midió primero, como manda la fase 6, y la medición cambió la fase.** El plan proponía
elegir entre un clasificador de 13 clases y un tesseract mejor alimentado. No hizo falta
ninguno de los dos: la medición encontró que el camino que ya existía **estaba desconectado en
uno de los dos mazos**.

### Lo que se midió antes de tocar nada

Por qué camino se resuelve cada carta, separado por mazo (sesiones de ≥120 frames):

| mazo | cartas | calco/caché | OCR | sin rango | dieces |
|---|---|---|---|---|---|
| glyph | 186 | **0 · 0 %** | 184 | 2 · 1 % | 4,3 % |
| solid | 1.355 | 593 · 44 % | 723 | 39 · 3 % | 6,6 % |

**El calco no acertaba NI UNA VEZ en el mazo de cara blanca.** No fallaba: se callaba, que es
un camino legítimo —cae al OCR— y por eso no lo veía ningún test. El coste real era pagar OCR
completo en el 99 % de las cartas de ese mazo.

Y una **corrección al plan**: dice que `is_ten` *no puede dispararse* en el mazo nuevo. Se
dispara 4 veces. Los dieces salen al 4,3 % frente al 7,7 % teórico.

### La causa, en aritmética

El atlas era **uno y compartido**, y todas sus mediciones (1.208 y 414 glifos) son del mazo
sólido. Las dos tipografías son distintas: el 4 del mazo nuevo cierra el vértice y el 9 tiene
otra panza. Puesto en números —cada plantilla del mazo nuevo leída con el atlas del sólido—:

    las trece se calcan como mucho al 0,734   ·   el umbral de allí está en 0,95

O sea que no es que funcionara peor: **no podía acertar nunca**. Es el test
`test_NINGUN_glifo_del_mazo_nuevo_lo_sabria_leer_el_atlas_del_solido`, determinista y sin
corpus.

### Un atlas por mazo

`vision/glifos_rango_glyph.png`, 13 glifos de 40×40 en orden de baraja, igual que el otro.
Cosechados de las sesiones reales agrupando por lo que dice el OCR **solo cuando sus 9
variantes coinciden por unanimidad**, y con las cajas mordidas descartadas: una plantilla
sacada de un glifo cortado le enseñaría a la app a reconocer sus propios errores.

**La etiqueta final la puso el ojo**, que es lo que el atlas exige desde el principio (*"ese
descarte lo hace el ojo, no un umbral"*): hoja de contactos de 13 filas, se leen los trece
seguidos y se comprueba que cada fila es lo que dice ser.

**Medoide y no promedio.** El promedio de glifos que no caen en el mismo píxel difumina el
trazo y baja el acuerdo con todos, incluido el suyo. Medida la cohesión de las dos variantes
contra sus ejemplares, el medoide —el glifo real más parecido a sus hermanos— gana o empata en
11 de 13.

### El umbral también es de cada mazo

En el sólido hay un hueco limpio entre lo propio y lo ajeno. Aquí las dos poblaciones **se
solapan**, así que el hueco hay que buscarlo. Medido sobre 288 glifos **dejando uno fuera**
(cada glifo contra un atlas reconstruido sin él):

    la correlación elige el rango correcto      283/288 = 98,3 %
    acuerdo con SU rango           p5 0,555   mediana 0,913
    acuerdo con el MEJOR AJENO    p95 0,806   máximo  0,810

Lo que decide no es el solape sino los **17 casos en que un rango ajeno le gana al propio**,
porque son los únicos que pueden salir mal, y no pasan de **0,738**. La cobertura hace meseta
plana de 0,85 a 0,88 (176 glifos), así que **0,88** no cuesta ni un glifo y deja 14 puntos de
margen. Las 5 elecciones equivocadas de la correlación (`6→8` ×2, `J→3` ×2, `6→5`) las caza el
acuerdo: ninguna llega a 0,85.

El 0,95 del sólido funcionaría igual de bien aquí —también sin errores— pero cubriría el 34,4 %
en vez del 61,1 %, o sea 77 cartas de más pagando OCR completo.

### Qué se ganó, medido — y qué NO

El número de producción sale de espiar `rango_por_calco` dentro del pipeline sobre las dos
sesiones del mazo nuevo enteras (1.472 frames):

| llamadas al calco con `deck="glyph"` | antes | después |
|---|---|---|
| se calla → paga OCR completo | **2.180** | 958 |
| acierta | **0** | **1.222 · 56 %** |

Cero de 2.180. Y con el mazo sólido, idéntico antes y después (91 de 267), que era el requisito.

Que además **acierta**: las 133 cartas que el calco resuelve se enfrentan al voto completo del
OCR como segunda opinión. **133 de 133 coinciden, cero desacuerdos** —no hubo hoja de contactos
que revisar porque no había nada que mirar.

**Y AQUI VA LO QUE NO SE GANO, que es la mitad del resultado.** La vara de la fase 6 sobre esas
mismas 1.472 frames sale **idéntica hasta el decimal**, campo a campo y con el mismo reparto de
rangos:

    board_ilegal 2,38%   board_pierde_carta 3,85%   hero_cambia 0,34%   chat 0/180   J/Q/K 24,6%

La primera vez que salió empate era la ventana de `--muestra`; esta vez no, porque el atlas se
ejercitó 2.180 veces. Así que la conclusión es la que es: **el atlas cambia el COSTE, no la
LECTURA**. Las 1.222 cartas que ahora resuelve el calco daban ya el mismo rango por OCR, que es
justamente lo que dice el 133/133.

**Y EL TIEMPO TAMPOCO SE GANA, que era lo que quedaba.** Primero pareció que sí: p95 del ciclo
de 691 a 567 ms. Repetido **con el orden invertido**, el atlas propio sale a 654 y el compartido
a 624, o sea que los 124 ms eran del orden de ejecución —el primer paso paga el arranque en frío
de los trabajadores de OCR y ese arranque cae justo en la cola, que es donde estaba la
"ganancia"—. Medido bien: **no hay diferencia**.

Y se sabe por qué, que es lo que hace útil el dato. Contados los trabajos del lote de OCR sobre
60 frames:

    927 trabajos en 60 lotes (15,4 por lote; p50 14, máximo 59)
    de rango de carta          81 ·  8,7 %
    nameplates, botones, chat  846 · 91,3 %

El lote corre en **trabajadores en paralelo**, así que quitar el 8,7 % de los trabajos no acorta
el camino crítico. Ahorrar 1.222 llamadas a tesseract es real en número de trabajos e invisible
en tiempo de pared, y **donde está el coste del ciclo es en los nameplates**. Eso es una medición
para otra fase, no para ésta.

Así que el balance de la fase 7, sin adornos: **arregla un camino que estaba muerto en uno de los
dos mazos, con las mismas lecturas y sin regresión, y no acelera nada.** Los aciertos que faltan
están en las cartas que el calco no toca, y ésa es otra medición.

### Lo que queda flojo, y se dice

- **El 7 no lo cubre el calco.** Su plantilla salió de 3 ejemplares —el OCR llega a unanimidad
  en el 7 muchísimo menos que en los demás— y de las 133 cartas resueltas por calco **ninguna
  es un 7**. No es un error: se calla y cae al OCR, que es el camino de siempre. Pero ahí no
  hay ganancia. El 9 (10 ejemplares) y la A (15) están en el mismo grupo flojo.
- **`--muestra` de `score_cartas.py` no sirve para medir este cambio**, y el primer intento
  salió empate exacto por eso: coge un trozo seguido desde el principio (a propósito, por los
  invariantes de serie) y las cartas del mazo nuevo empiezan en el frame 166. En la ventana de
  220 frames había 3 de 210. Sin `--muestra` hay 77.
- **La competición de mazos decide por zona y frame**, no por sesión, y en los primeros 40
  frames de la sesión de glifo —donde todavía no hay cartas del mazo nuevo— gana el sólido con
  cartas fantasma. Es el motivo por el que el usuario tiene selector de mazo en la GUI.

### Lo que NO se hizo, y por qué

Ni el clasificador de 13 clases ni el tesseract de una vista. **Un clasificador entrenado con
los glifos que el calco acierta es el calco con más pasos**, y el propio calco ya resuelve el
58 % con cero errores medidos; el margen que queda está en el OCR de las cartas que el calco no
toca, y eso es otra medición. Se deja anotado, no empezado.

**La compatibilidad se mantuvo donde ya estaba**: `deck` viajaba por toda la cadena y ahora
también indexa `GLIFOS_POR_MAZO` y `GLIFO_UMBRAL_POR_MAZO`. Un tercer mazo entra con una línea
y su PNG.

---

## Verificación

1. **Grabar una sesión antes de cada fase con cambio de comportamiento.** La regresión de oro
   solo compara contra sesiones del commit ACTUAL, así que en cuanto se toca algo se queda sin
   oro y hace `skip`.
2. **Entre fases, `replay.py --diff`** contra las sesiones ya grabadas: tolera la deriva de
   commit y es el instrumento real de antes/después.
3. **La fase 2 no puede cambiar ni un campo.**
4. **Las fases 3a y 3c tocan el recuento de asientos** y por tanto las posiciones y el rango
   servido. Van solas, en su propio commit, con `test_no_se_pierden_recomendaciones` y
   `core/invariantes` delante.
5. **Fijar `--corpus-semilla` durante toda la campaña**: las fases 1 y 4 cambian la
   distribución de `estratos()` y con ella la muestra del E2E.
6. **`LATENCIA_P95_MAX_S = 3.0` hay que bajarlo** al terminar: si el ciclo baja a ~0,5 s, un
   techo de 3 s deja de proteger de nada.
7. **Métrica que manda sobre el lazo rápido**: `acciones_por_mano` **no puede bajar**. Es lo
   único que justifica que exista.
8. **Métrica que manda sobre las cartas**: las cinco señales de la fase 6.

---

## Notas del usuario sin atender

De `testing/sesion-2026-07-28_210655` y `sesion-2026-07-28_224318`:

| frame | nota | destino |
|---|---|---|
| 210655/0025 | *"hay 2 rivales activos"* (la app veía 1) | zona de dorsos de UR: pierde el **12,3 %** de sus detecciones. Es geometría, no umbral: el blob mide lo mismo que el de MR pero la ventana no lo cubre. Agravado porque la métrica divide por el área de la zona, así que el umbral depende del encuadre |
| 210655/0254 | *"activos en amarillo, sentados sin jugar en gris"* | **fase 4** |
| 210655/0560 | *"no se ve mi stack porque mi badge es dorado/plateado/bronce"* | **hecho** (sin commitear): el nameplate tiene nombre oscuro y stack claro pegados y tesseract perdía la mitad clara; se lee la franja aparte. Con badge era **0 de 101**; ahora el stack se lee del 54 % al 89 % de los frames y devuelve **93 recomendaciones** |
| 210655/1333 | *"hay que actualizar los jugadores al comienzo de cada mano"* | **fase 3** |
| 210655/2109 | *"el as de picas no aparece en el board"* | **fases 6/7** |
| 224318/0860 | *"el board es un 5♠ no J♠"* | **fases 6/7** |
| 224318/1531 | *"mesas de 7 puede haber, examina el frame"* | **sin plan todavía**: `seat_map.SEATS` define **seis** asientos, así que hoy hay uno que la app no puede ver siquiera |

---

## Estado al 29-07-2026 (fin de la campaña en frío)

Hecho y commiteado:

| | commit | lo que mide |
|---|---|---|
| Fases 0-2 | `e9ce22f` | ciclo 1,00 → 0,59 s; turno por botones, 0 falsos positivos en 183 frames |
| Palo en el índice | `9166b3a` | Q rescatada; recuentos ilegales de board 67 → 0 en la sesión del mazo nuevo |
| Rango en el índice | `0dbb427` | la K♠ se leía 4♠; J/Q/K 3,6 % → 20,2 % |
| Fase 3 | `69acd6b` | stack cacheado no cruza de mano (mentía el 62,3 % de las veces) |
| Regresión de oro | `a7e0c94` | deja de comparar trozos sueltos, que no son reproducibles |
| Fase 6 | `6307359` | `herramientas/score_cartas.py` + 2 invariantes de cartas + tests de `_cajas_de_carta` y `_encolar_cartas` |
| Fase 4 (frío) | `19a3640` | el nombre gratis del lazo rápido; HUD que distingue quién juega |
| Fase 5 | `e9981f1` | ritmo medido, fuera el selector |

**Descartado con datos, no por olvido:** caducar el respaldo de nombres por
discontinuidad de stack. Las dos poblaciones no separan y ningún umbral baja de
4,5 respaldos buenos tirados por cada cambio acertado (ver `hand_tracker`).

### Lo que falta, y por qué no se puede hacer en frío

`tick()` solo lo llama `gui.py`. `replay.py`, `alpha.py` y toda la suite llaman
únicamente a `analizar()`, así que **nada de lo que produce el lazo rápido existe
sin jugar**. Eso bloquea:

- **La métrica de la fase 4**: cuántas de las 234 mano-asiento que hoy no leen
  nombre en toda la mano pasan a leerlo.
- **`TICKS_MIN_ENTRE_ANALISIS`** (fase 5): el plan dice barrer el hueco y coger la
  rodilla de `acciones_por_mano`. Está puesto a 5 y marcado como provisional.
- **La regresión de oro**: necesita una sesión grabada con el commit actual.
- **Confirmar los arreglos de cartas**: `board_pierde_carta` está medido en 0,97 %
  sobre sesiones grabadas ANTES de ellos, y la del mazo nuevo es la peor (1,48 %).
  Con una sesión nueva tiene que bajar; si no baja, los arreglos no valen lo que
  dicen sus mediciones.

### Pendiente sin tocar

- **Mesas de 9**: `seat_map.SEATS` define seis asientos. En la sesión del torneo
  la app leyó doce nombres distintos en lo que creía una mesa de seis y asignó el
  asiento `HERO` a un rival. Capturas en `docs/casos/`.
- **El 7 del mazo de cara blanca**: su plantilla de calco salió de 3 ejemplares y el calco no
  resuelve ni un 7 en 133 cartas. Cae al OCR, que es lo que hacía antes, pero ahí no hay
  ganancia. Hace falta cosechar más 7 con criterio relajado y revisarlos a ojo.
