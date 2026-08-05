# olmOCR contra tesseract: la medición

Medido el 05-08-2026 en un MacBook Pro (Apple Silicon, macOS 26.6) con
**olmOCR-2-7B-1025 Q4_K_M** servido por Ollama, contra las dos sesiones grabadas
en `testing/`. La herramienta es
[`herramientas/comparar_ocr.py`](../herramientas/comparar_ocr.py):

```bash
herramientas/comparar_ocr.py --n 40 --semilla 3 --modo seguidos --reanalizar
```

## Cómo se puntúa sin etiquetas

El mismo problema que en `score_cartas.py`: hay miles de frames y cero etiquetas.
Así que se puntúa con señales que no dependen de ningún OCR: la **estabilidad del
nick** (un jugador no se cambia de nombre a mitad de sesión), los **saltos
imposibles de stack** (perder el 90 % del stack y recuperarlo en el frame
siguiente no es una jugada), la **cobertura** (abstenerse también se paga) y la
**latencia**. Los desacuerdos se vuelcan con la ruta del PNG, porque cuando los
dos motores discrepan la única verdad disponible es la imagen.

### Dos trampas de método, las dos pisadas antes de acertar

**1. El `state` grabado no es el tesseract de hoy.** La sesión
`2026-08-04_210545` se grabó con el commit `1e93ddf`, o sea el ANTERIOR a
266f72c ("tu stack se leía 6,8 donde ponía 196,8"). Puntuar contra lo grabado le
regalaba a olmOCR un fallo arreglado hacía cuatro commits: salía ganando por
goleada en stacks del hero que hoy tesseract ya lee bien. Es el mismo cuidado que
se toma la regresión de oro del E2E, que solo compara contra sesiones del mismo
commit. De ahí `--reanalizar`, que vuelve a pasar los PNG por el pipeline actual.

**2. Un trozo suelto arranca en frío.** Reproducir 40 frames del medio de una
sesión con un `Analizador` limpio da 2,25 nombres por frame donde en vivo se
leían 6,0 — no porque el código haya empeorado, sino porque todavía no ha fijado
la referencia del tapete ni sabe qué mesa es. En vivo eso había pasado hacía
rato. De ahí `--calentar`, que analiza N frames previos sin puntuarlos:

| frames de calentamiento | nombres/frame | stacks/frame |
|---|---|---|
| 0 | 2,25 | 2,05 |
| 60 | 7,58 | 5,12 |
| 200 | 7,20 | 5,00 |

## El cara a cara, ya honesto

40 frames seguidos de `2026-08-04_210545`, los dos motores sobre las mismas
imágenes y con el código de hoy:

| | tesseract | olmOCR |
|---|---|---|
| nombres por frame | 7,58 | **8,25** |
| **stacks por frame** | 5,12 | **7,92** |
| frames con bote | **35/40** | 34/40 |
| estabilidad del nick | **99,0 %** | 97,3 % |
| saltos imposibles de stack | 0 | 0 |
| **ciclo completo** | **0,32 s** (p50) | 9,8 s (p50) |

Y un dato que vale por sí solo: **cuando los dos leen un stack, no discrepan ni
una vez**. El truncamiento por la izquierda que arregló 266f72c está muerto. Todo
el hueco es tesseract **absteniéndose** en asientos concretos — y muy
concentrado: `colas2888` en 23 de los 40 frames, `reaper201751` en 7.

Lo que olmOCR hace mal, también medido: inventa variantes de nick con pinta de
verdad (`crocodundee1963` por `crocodiles1963`, `troymccluer` por `troymccher`,
tres formas distintas de `denchin1593`), se deja asientos que tesseract sí lee
(`carlosteide` en 27 frames), lee los botones de acción como si fueran jugadores
(`igualar`, `subir`) y se equivoca en botes (`5,57` donde pone `7,57`). Es la
diferencia entre un OCR que se abstiene y un modelo generativo que siempre
contesta algo.

**Veredicto: olmOCR no entra en el ciclo en vivo.** 9,8 s por frame contra 0,32 s
es un factor 30, y una recomendación que llega ocho segundos después de que te
toque actuar no es un asistente. Queda como herramienta de estudio (abajo).

## Lo que sí salió de la comparación: el PSM de la cápsula

Persiguiendo el asiento que tesseract no leía (`colas2888`, 23 frames) se ve el
recorte y el fallo es evidente: el nick va en banda **oscura** y el importe en
banda **clara**, porque el cliente RESALTA al jugador al que le toca actuar. Con
el mismo recorte y el mismo preprocesado, cambiando solo el modo de segmentación:

| PSM | líneas | leído |
|---|---|---|
| `SPARSE_TEXT` (el de siempre) | 1 | `Colas2888` — el stack, perdido |
| `SINGLE_BLOCK` | 1 | `208,2 BB` — ahora falta el nick |
| `AUTO` | 2 | `Colas2888` / `208,2 BB «&` |
| `SINGLE_COLUMN` | 2 | `Colas2888` / `208,2 BB` |

Es el mismo fallo que ya tenía documentado el hero en `table_state` (el badge de
torneo le aclara la franja del stack), donde se parcheó con un job extra sobre la
franja de abajo. Aquel comentario decía "a los RIVALES no les pasa": les pasa. Lo
que no pasaba era el badge, que es raro; el resaltado del turno lo tiene alguien
en casi todos los frames.

**Pero `SINGLE_COLUMN` a secas es peor**, y por eso se mide antes de cambiar:

| sobre los mismos 40 frames | nombres | stacks | nick estable |
|---|---|---|---|
| solo `SPARSE_TEXT` | 7,58 | 5,12 | 99,0 % |
| solo `SINGLE_COLUMN` | 6,15 | 3,25 | 94,3 % |
| **los dos, juntando líneas** | **7,58** | **5,80** | **99,0 %** |

Así que la cápsula se lee DOS VECES, con los dos modos, y las lecturas se juntan
— la misma idea de "cubrir con un recorte lo que falla en el otro" que el código
ya usaba con la zona y la cápsula, aplicada al PSM en vez de a la geometría.
A/B sobre tres tramos distintos:

| tramo | stacks sin | stacks con |
|---|---|---|
| semilla 3 (hay cápsula resaltada) | 5,12 | **5,80** |
| semilla 11 | 2,95 | 3,02 |
| semilla 23 | 4,38 | 4,33 |

O sea: la ganancia está donde se buscaba y es neutro donde no hay resaltado, sin
tocar nombres ni estabilidad y con el ciclo igual (p50 0,32 s). No cierra todo el
hueco con olmOCR (5,80 contra 7,92), pero es lo que se puede cobrar sin pagar
treinta veces el ciclo.

## olmOCR queda, solo para estudiar casos

```bash
ver_frame.py testing/sesion-<fecha> 1274 --olmocr    # segunda opinión, ~8 s
herramientas/comparar_ocr.py --n 40 --modo seguidos --reanalizar
```

`ver_frame.py --olmocr` es lo barato: UNA llamada al frame entero
(`ocr_vlm.leer_mesa`) y la lectura al lado de la de la app. Sirve para la
pregunta que antes no tenía respuesta: cuando algo no se lee, ¿es el OCR o es la
geometría? Si el modelo lee lo que la app no lee, el recorte está donde debe.

`ocr_vlm.usar_para_estudio()` pone el modelo como OCR del pipeline entero. Son
minutos por frame, así que es para un caso, no para una sesión. **No se puede
encender por variable de entorno a propósito**: una app de jugar que se vuelve
mil veces más lenta porque alguien exportó algo no es un modo, es un accidente.

El servidor:

```bash
ollama serve
ollama pull hf.co/bartowski/allenai_olmOCR-2-7B-1025-GGUF:Q4_K_M
```

Se habla la API de OpenAI, que es la que sirven Ollama, vLLM y LM Studio y la
misma por la que olmOCR upstream acepta un servidor externo. `POKER_OCR_VLM_URL`
y `POKER_OCR_VLM_MODELO` cambian a dónde se pregunta, así que repetir esta
medición con otro modelo es una variable de entorno.

Dónde se va el tiempo, por si alguien quiere apretarlo: casi todo es **prefill de
la imagen** (2.050 tokens en 9,2 s, ~223 tok/s) contra 90 tokens de respuesta en
2,0 s (~46 tok/s). Bajar la imagen a la mitad casi lo divide por dos sin cambiar
una letra; por debajo de la mitad no se gana nada —el modelo reescala a un
presupuesto fijo de tokens, 1.105 con 1/2, 1/3 y 1/4— y se empieza a perder texto
(`DannySann1D1`, `silvagamer0`, el bote `2.1` por `2,1`).
