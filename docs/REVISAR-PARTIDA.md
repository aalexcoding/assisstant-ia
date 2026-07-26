# Protocolo de revisión de una partida

Cuando el usuario diga **"prueba hecha, revisa"**, esto es lo que hay que mirar y
en qué orden. Está escrito para ir a tiro hecho: cada comprobación lleva su
**referencia medida**, su **procedencia** y **qué significa si falla**.

La sesión está en `testing/sesion-<fecha>/`, con una dupla `NNNN.png` + `NNNN.json`
por frame y `_sesion.json` con los metadatos. La más reciente es la última por
nombre.

---

## Revisar MIENTRAS se juega

`vigilar_sesion.py` lee la carpeta que la GUI va escribiendo y saca **una línea
por hallazgo, con la ruta del PNG al lado**, para poder abrir la imagen y
comprobarlo con los ojos. Ese emparejamiento es el punto: un aviso sin su frame
no se puede verificar.

```bash
.venv/bin/python vigilar_sesion.py                        # en vivo, la última sesión
.venv/bin/python vigilar_sesion.py --repasar testing/...  # repasar una ya grabada
```

Solo **lee** ficheros, así que no toca la captura ni compite por el stream del
portal.

Es **selectivo a propósito**: una anomalía dura decenas de frames, así que avisa
una vez por racha. Medido sobre una sesión de 270 frames: 26 avisos, la mayoría
al principio (cada motivo de abstención nuevo salta una sola vez).

Dos tipos de línea:

- **`[BUG]`** — contradicción demostrable. Siempre hay que mirarla.
- **`[REVISAR]`** — correcto pero conviene verlo con la imagen: una recomendación
  **derivada** (la capa de la Fase E, que no sale de tus tablas) o un motivo de
  abstención que no había aparecido antes en esa sesión.

Cuando el usuario está jugando, esto se arranca con **Monitor** para que cada
línea llegue como notificación; entonces se abre el PNG del frame y se juzga con
la imagen delante, en vez de esperar al final.

---

## 0 · Contexto antes de mirar nada

De `_sesion.json`: `commit` (con qué versión se grabó — si es viejo, la mitad de
lo que salga ya está arreglado), `duracion_s`, `intervalo_s`, `max_players` (si
está fijado, explica la mitad de lo que se vea) y `notas`.

**Descartar los frames sin mesa** antes de calcular nada: los que llevan
`"encuentra la mesa"` o `"ovalo"` en `state.warnings` son lobby, ventana de
estadísticas o escritorio. La app corta ahí a propósito. Todos los porcentajes de
abajo van sobre los frames **con mesa**.

**Si de golpe no hay NINGUNA carta en toda la sesión, mirar el mazo antes que
nada.** Pasó el 26-07-2026: el usuario cambió el mazo en las opciones del cliente
y la app se quedó ciega 267 frames seguidos, porque el detector miraba el color
del *fondo* de la carta y el mazo nuevo lo pinta blanco. Un vistazo al PNG lo
resuelve en diez segundos; deducirlo del JSON cuesta media hora. Hoy hay un
detector por mazo y `table_state._cajas_de_carta()` elige solo, así que el
síntoma no debería repetirse — pero si vuelve a salir cero, es la primera
hipótesis.

`state["hero_cards_dimmed"]` es un dato, no un fallo: el cliente **apaga** tus
cartas cuando te retiras y las deja visibles para que sigas la mano. El motor se
abstiene ahí a propósito ("ya no estás en esta mano"). Fueron el 21% de los
frames de esa sesión, así que no es un caso raro.

---

## 1 · Lo primero: contradicciones

No son "peor de lo esperado": son cosas que **no pueden pasar** en una mano de
verdad. Si aparece alguna, es un bug y va primero.

| comprobación | qué es | historia |
|---|---|---|
| `len(set(board)) < len(board)` | board con una carta repetida | Salió con `9♣ Q♣ 4♥` leído `['9c','9c','4h']`: `BOARD_ZONE` cortaba las cartas por abajo y la Q sin cola se lee como 9. Arreglado subiendo el borde de 0,54 a 0,60. Si vuelve, el recorte se come otra vez el glifo |
| `len(board)` en 1 o 2 | board de longitud imposible | En Hold'em el board es 0, 3, 4 o 5. Con el mazo de fondo sólido salían **24 de 61** frames con board de 1 o 2 (se perdían cartas); con el de cara blanca, **0 de 37**. Si reaparece, el detector está perdiendo cartas del board |
| `set(board) & set(hero_cards)` | una carta tuya también en el board | Imposible, hay 52 cartas. Lectura de rango o palo equivocada |
| `vs_position` habla después que `hero_position` | raiser imposible | Orden preflop: EP1 EP2 MP1 MP2 HJ CO BTN SB BB. Eso no es una defensa sino una resubida a la apertura propia. El motor ya lo rechaza; si aparece, la atribución falla por otro sitio |
| `len(players) > max_players` | más jugadores de los que caben | Solo si el selector Mesa está fijado. Contradicción entre lo dicho y lo visto |
| `hero_position` que no existe con ese nº de jugadores | p.ej. `CO` en una mesa de 3 | Fue el bug más caro: un entero suelto del tapete contaba como asiento ocupado y desplazaba **todas** las posiciones |
| un rango que sale muy por encima del 7,7% | 13 rangos son equiprobables | La **T** salió al 10,7% con el mazo de cara blanca: eran dieces inventados por el borde de la carta y por los pips. Referencia tras el arreglo: 6,6% |
| manos seguidas que comparten botón con la anterior | el botón se mueve **una** vez por mano | Es la única vara para medir la PRECISION de los cortes, no solo cuántos se aciertan. Referencia: **12%**; con `cartas_aparecen` cortando era el 42% |
| nº de manos seguidas vs nº de manos reales | los números de mano **distintos** del chat son la verdad de campo | `len({parse_hand_result(f)["hand_number"]})` sobre todos los frames. Referencia: **+7%** de más (111 seguidas contra 104 reales). Llegó a estar en +107% |

---

## 2 · La medida que decide si esta tanda cumple

**Acciones vistas por mano.** Es lo único que valida la vigilancia rápida a 0,1 s.

```python
import testing_session as t
r = t.resumen("testing/sesion-<fecha>")
r["manos"], r["acciones_por_mano"], r["vigilancia"], r["ciclo_medio_s"]
```

| | valor | procedencia |
|---|---|---|
| **referencia** | **5,7 por mano** | sesión del 26-07, 53 manos, muestreo real 1,48 s |
| contexto | una mano de 3-max tiene 4-8 acciones | |

**Debe subir claramente.** Si se queda igual: ¿está corriendo el lazo rápido
(`vigilancia.ticks` ≫ nº de frames)? ¿el tope lo está frenando
(`vigilancia.saltadas` alto)? ¿o el cartel dura menos de lo medido?

Si sale `None`, la sesión es anterior al historial de acciones: **no se midió**,
que no es lo mismo que no se viera nada.

---

## 3 · Las métricas de siempre, con su referencia

| | referencia | procedencia | si baja |
|---|---|---|---|
| ciclo medio | **0,68 s** | tras los workers persistentes (3,88 → 1,59 → 0,96 → 0,68) | mirar si la vigilancia está comiendo tiempo |
| posición detectada | **95,7%** | sesión del 26-07 tras el asiento fantasma (antes 89%) | mirar el selector Mesa primero |
| preflop decidible con recomendación | **89%** | sesión del 26-07 (al principio del proyecto, 20%) | mirar los motivos de abstención |
| tus 2 cartas cuando las tienes | **99%** | no confundir con el % sobre todos los frames (~66%), que incluye manos en las que no juegas | |

**Procedencia de las recomendaciones**: `chart` (tablas digitalizadas) frente a
`derived` (Fase E: opción de la BB, frente a un limp, squeeze). Las derivadas
salen en ámbar y nombran la celda donante.

**Motivos de abstención**: lo más informativo del JSON. Dos son normales y no hay
que perseguir — *"hay board"* (el motor solo decide preflop) y *"faltan las 2
cartas"* (no estás en esa mano).

---

## 4 · Las notas del usuario

`_notas.jsonl`, y el campo `nota` dentro del JSON de cada frame marcado.

**Es lo más valioso de la sesión.** Cada una es un caso real elegido porque algo
no cuadraba, con el frame y todo lo calculado al lado. Hay que abrir el PNG y
mirar la imagen, no solo el JSON: la primera nota que se dejó (*"hay un 2
trébol"*) destapó un bug que se arregló el mismo día, y solo se vio abriendo el
recorte de la carta.

---

## 5 · Cómo mirar un frame concreto

```python
import json, cv2
d = json.load(open("testing/sesion-<fecha>/0167.json"))
d["state"]["board"], d["state"]["hero_cards"], d["state"]["warnings"]
d["recommendation"], d["equity"], d["state"]["players"]
```

Y para volver a analizarlo con el código actual (la forma de saber si algo ya
está arreglado):

```python
import sys; sys.path.insert(0, "vision")
import table_state as ts
ts.analyze_layout("testing/sesion-<fecha>/0167.png", max_players=None)
```

Para bajar al detalle de una carta: `color_card_detector.find_card_boxes` sobre
la zona, y `color_rank_ocr.add_rank_jobs` / `resolve_rank` para ver las 18
lecturas y por qué votaron lo que votaron.

---

## Lo que NO hay que perseguir

Ya está medido y decidido; volver a plantearlo es perder el tiempo:

- **El botón del dealer**, aunque falle en el 10% de los frames. De sus 175
  fallos en una sesión, solo **1** costaba una recomendación: la posición solo
  importa cuando tienes cartas, y en el 94% de los fallos no las tienes.
- **Los frames sin mesa.** Son lobby y ventanas de estadísticas; cortar ahí es lo
  correcto.
- **El peso del voto del OCR de rango** (`FULL_VOTE_WEIGHT = 2`). Barrido con
  pesos 1, 2 y 3 sobre 110 frames: los imposibles son los mismos y con peso 1
  quedan 9 cartas sin resolver frente a 4.
