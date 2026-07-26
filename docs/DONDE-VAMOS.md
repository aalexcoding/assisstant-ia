# Por dónde vamos

Punto de retomada a **2026-07-26**, HEAD `2442ada`. El detalle de cada tarea
pendiente está en [`PENDIENTE.md`](PENDIENTE.md); esto es el mapa de arriba: qué
está hecho, qué toca ahora y qué depende de ti.

---

## Lo primero, si vuelves después de un tiempo

```bash
.venv/bin/python gui.py                 # la app
.venv/bin/python gui.py --self-test     # comprueba que la ventana se construye
```

**Dos ajustes obligatorios antes de jugar**, o la app no lee nada:

1. **PokerStars con los importes en BIG BLINDS** (ajustes de mesa). La app es
   BB-only: si no está así no lee los stacks y se abstiene, a propósito.
2. **Tapete con color** (el verde va medido al 98%). Un tema gris o negro tiene
   saturación cero y la detección del óvalo falla al 100%; la app lo dice, pero
   no puede trabajar.

Y dos que conviene: el selector **Mesa** en `3-Max` si juegas eso, y la casilla
**"Grabar sesión de testing"** antes de darle a iniciar.

La suite completa (528 checks):

```bash
for t in test_testing_session.py test_gui_notas.py \
         decision/test_action_log.py decision/test_hand_tracker.py \
         decision/test_bugfixes_bb.py decision/test_equity.py \
         decision/test_hand_eval.py decision/test_hand_strength.py \
         decision/preflop/test_actions.py decision/preflop/test_derive.py \
         decision/preflop/test_lookup.py decision/rag/test_postmano.py \
         vision/test_hand_result.py vision/test_in_hand.py \
         vision/test_ocr_pool.py vision/test_seat_watch.py \
         vision/test_table_reference.py; do
  printf '%-34s ' "$t"; .venv/bin/python "$t" 2>/dev/null | tail -1
done
```

Y una casilla más que conviene conocer: **HUD**, que deja solo la recomendación,
la equity y la mano actual, para tenerla al lado de la mesa.

---

## Lo siguiente, por orden

### 1. Validar en vivo lo que se construyó hoy — **te toca a ti**

Es lo único que bloquea. Graba **una sesión** con el código actual y se mide:

- **cuántas acciones se captan por mano** ahora que hay vigilancia a 0,1 s.
  El número de referencia es **5,7 por mano** (medido a 1,48 s de muestreo, con
  una mano de 3-max teniendo típicamente 4-8 acciones). Si sube claramente, el
  buffer cumple; si no, hay que mirar por qué.
- que el **ciclo de 0,68 s** se sostiene en producción con el vigilante corriendo.
- que las nuevas recomendaciones derivadas (`RAISE OVER LIMPERS`, la opción de la
  BB) salen cuando deben y con el color ámbar que las marca como inferidas.

Marca con **"Marcar situación"** cualquier cosa rara. La última nota que dejaste
destapó un bug real y se arregló el mismo día.

### 2. Lo que se puede hacer sin ti

Ya no queda casi nada de la lista anterior: se hicieron todas (comprometido por
calle, squeeze, recortes en memoria, RAG post-mano y modo HUD). Lo que queda:

- **Fase E: ciega vs ciega y 4bet**. El 4bet necesita capturas tuyas (ver abajo);
  el de ciega vs ciega hay que estudiarlo, porque `threebet_call` ya cubre BB vs
  SB y no está claro que haya hueco real.
- **Cachear el chat** por hash de la zona: valdría 0,55 s cuando acierta, pero
  solo es idéntico al frame anterior el 38% de las veces.
- **Corpus etiquetado** (`score_samples.py`): comparar contra etiquetas para
  poder tocar los ~15 umbrales de `vision/seat_map.py` con red.

### 3. La inversión de mayor retorno que queda — **también tuya**

**Digitalizar un gráfico de 4bet**: 20-30 capturas por el mismo `parse_ranges.py`.
Tus 398 imágenes no contienen el eje "responder a agresión" en absoluto y ninguna
estadística lo saca de ahí. Convertiría la peor de las situaciones de la Fase E
en la mejor.

### 4. Decidido: NO tocar

- **Deuda estructural** (empaquetar, unificar las tres ramas de visión, pinear
  requirements). Aparcado por decisión tuya.
- **Detección de tapete por forma**. Aparcado por decisión tuya; mantienes el
  verde.
- **Botón del dealer**. Medido: de sus 175 fallos, solo **1** cuesta una
  recomendación en 49 minutos. No merece la pena (ver §2.0e).

---

## Qué se hizo en la última sesión de trabajo

En orden cronológico, con el commit:

| | |
|---|---|
| `dead35a` | Campo de **nota** para marcar situaciones raras mientras juegas |
| `1b1285b` | **Rastreador**: deducir lo apostado de la bajada de stack |
| `a7958dc` | Paso a **BB-only**: fuera fichas y ciegas |
| `a648e48` | No analizar el frame si no se encuentra la mesa |
| `55cc50c` | Rescatar el rango cuando el OCR devuelve varias líneas |
| `563e84e` | **Asiento fantasma** + tamaño de mesa ajustable |
| `c10f5f6` | **Fase E**: la opción de la BB deja de ser un marcador de posición |
| `17fe44c`, `977d939` | **Fase 2**: caché de rangos + reparto de OCR por idioma |
| `ec9729e` | El verbo de acción deja de robarle el nombre al jugador; board cortado |
| `652e424` | El intervalo es un periodo, no una pausa que se suma al ciclo |
| `1c8ca96` | **Buffer** de captura rápida + **historial de acciones** |
| `7ee31a2` | **Workers de OCR persistentes** |
| `c8a8ef0` | **Fase E**: frente a un limp con el hero fuera de las ciegas |
| `40d1f7f` | Separar lo **comprometido por calle**, no solo por mano |
| `87464f1` | **Fase E: squeeze**, y el raiser que habla después del hero |
| `c625293` | Recortes al worker en memoria: fuera el directorio temporal |
| `2442ada` | **RAG de estudio post-mano** y **modo HUD** |

### Los números que cambiaron

| | antes | ahora |
|---|---|---|
| ciclo de análisis | 3,88 s | **0,68 s** (5,7×) |
| posición detectada | 89% | **95,7%** |
| preflop decidible con recomendación | 20% | **89%** |
| defensas (`threebet_call`) en una sesión | 6 | **33** |
| `CHECK (BB option)` sin mirar las cartas | 36% de las recomendaciones | **0** |
| defensas contra un raiser imposible | 67 de 134 atribuciones | **0** (guarda estructural) |

---

## Tres cosas que conviene no olvidar

Son las que más tiempo han costado de descubrir:

1. **Una señal heredada de una etapa anterior se vuelve un falso positivo cuando
   cambia el contexto.** Ha mordido tres veces: el área del botón del dealer en
   píxeles absolutos, las zonas de apuesta, y el "entero suelto vale como stack"
   que llenaba la mesa de asientos fantasma. Cuando cambies una premisa, repasa
   qué señales dependían de ella.

2. **Medir antes de optimizar, y medir el COSTE, no el porcentaje.** El botón del
   dealer fallaba en el 10% de los frames y parecía urgente; costaba una
   recomendación en 49 minutos. En cambio el 86% de los jobs de OCR eran cartas
   pero solo el 48% del tiempo, y el cuello real era una zona con el modelo
   español cargándose dos veces.

3. **Abstenerse antes que responder con convicción y equivocarse.** Es la regla
   que sostiene el diseño entero: el guard de `stack_unit`, el corte cuando no se
   encuentra la mesa, el "el comprometido nunca crea una subida, solo la
   atribuye", el `completo=False` del historial de acciones y el color ámbar de
   las recomendaciones derivadas son todos la misma idea.
