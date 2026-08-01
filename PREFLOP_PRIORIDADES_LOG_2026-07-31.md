# Preflop: ejecución por prioridades (31-07-2026)

## Línea base

Sesiones comparadas:

- `sesion-2026-07-31_011143`
- `sesion-2026-07-31_014709`
- `sesion-2026-07-31_020108`
- `sesion-2026-07-31_022832`

Sobre 761 frames con dos cartas del hero y lista de board vacía, el motor
mantiene 419 recomendaciones. La métrica incluye algunos frames de transición
que `board_detected_count` bloquea correctamente como no-preflop.

## 1. Stack efectivo real — implementado

- El stack para elegir tabla vuelve a sumar lo ya comprometido, sin sumar dos
  veces `bet`, `committed` y `committed_calle`.
- Se conserva por asiento el stack inicial de la mano y se usa
  `min(hero, agresor)`.
- El cache no duplica una apuesta posterior cuando el stack del nameplate queda
  oculto.
- Un comprometido residual imposible antes de la primera acción del hero queda
  fuera. Caso real: 40 BB residuales en `011143/0031`.

Resultado medido: AA en BB contra HJ (`011143/0084-0095`) pasa de consultar
44,1 BB y sugerir 3-bet a 9 BB a usar 27,3 BB efectivos y sugerir 6,5 BB.
No cambia fold/call/raise; corrige el tamaño.

## 2. Hero RFI y respuesta a 3-bet — implementado con guardas

Fuente: PDF públicos RangeConverter MTT 8-max, ante total 1 BB, chip-EV.

- 6 profundidades: 20, 30, 40, 50, 60 y 100 BB.
- 28 emparejamientos de posiciones por profundidad; 168 gráficos.
- 28.392 celdas importadas.
- Se conservan mezclas al 50 %.
- `NOT_IN_RFI` no se convierte en fold: el motor se abstiene porque esa línea
  está fuera del árbol publicado.
- 20 BB solo se usa contra 3-bet all-in; 30+ solo contra 3-bet normal.
- Se exige open corroborado entre 1,5 y 4,5 BB, importe de la 3-bet, stack
  efectivo y ausencia de cold callers.
- En 6-max solo se admite como adaptación de confianza media el subárbol de
  posiciones tardías con el mismo orden.

Validación de las sesiones: no se añade ninguna orden en los frames antiguos.
En dos casos el cliente mostró primero `Subir` y después `All-in`; recomendar en
el primer frame habría usado la familia equivocada. El motor espera un importe
confirmado y se abstiene.

No cubre cold 4-bet, respuesta a 4-bet/5-bet ni squeeze tras un cold caller.

## 3. RFI profundo — implementado

De los mismos PDF se importaron 41 gráficos RFI (6.929 celdas). El PDF de
50 BB no contiene SB; el extractor detecta la zona vacía y no fabrica 169
folds.

En las cuatro sesiones, 50 frames de 13 manos dejan de depender exclusivamente
de extrapolar la tabla local de 40 BB y pasan a una fuente pública de
40/50/60/100 BB. La categoría estratégica observada (fold/limp/raise) coincide
con la recomendación anterior en esas manos. Fuera de la rejilla pública se
mantiene la tabla local con su aviso explícito de extrapolación.

El tamaño numérico del open/4-bet no se extrae cuando la tipografía del PDF no
permite hacerlo con fiabilidad; se muestra la acción genérica. No se acepta un
OCR que confundía, por ejemplo, 17,4 con 174 BB.

## 4. Squeeze — revisado, no ampliado

La capa heurística existente sigue etiquetada como derivada. Las fuentes
gratuitas encontradas explican definición y sizing, pero no publican la matriz
completa por posición, stack, ante, opener y caller.

Para completarlo hace falta una exportación HRC o RangeConverter con:
stack vector, posiciones, secuencia, tamaños, frecuencias, EV, formato y ante.
No se han copiado rangos de cash ni se ha estrechado un rango heads-up por un
porcentaje arbitrario adicional.

## 5. Open-shove, call y reshove — revisado, no ampliado

Se conserva el suplemento exacto existente de call vs open-push
8-max/10 BB/ante 1 BB. Los PDF públicos de 20 BB cubren respuesta a 3-bet
all-in, no call contra un open-shove de cualquier posición y profundidad.
No se extrapola el gráfico de 10 BB.

## 6. Iso-limp y botes limpeados — revisado, no ampliado

HRC documenta cómo modelar `+1 BB por limper`, flats, completes y closing
actions, pero esa configuración no proporciona por sí sola los rangos. Se
mantienen los fallbacks conservadores actuales hasta disponer de una solución
exportada; no se presentan como GTO.

## Artefactos y validación

- Datos: `decision/preflop/rangeconverter_ranges.json`
- Importador reproducible:
  `decision/preflop/import_rangeconverter.py`
- Lookup: `decision/preflop/rangeconverter.py`
- Pruebas nuevas: `decision/preflop/test_rangeconverter.py`
- Simulación actual:
  `SIMULACION_PREFLOP_RANGOS_2026-07-31.md`

La simulación actual contiene 101 ventanas de mano y 28 con alguna diferencia
frente a la recomendación que quedó grabada. Esa cifra incluye arreglos
anteriores de esta misma jornada; el efecto aislado de esta tanda conserva las
419 recomendaciones y corrige procedencia/profundidad, con el cambio de sizing
de AA descrito arriba.

## 7. Interpolación probabilística conservadora — implementada

Se ha añadido una capa de respaldo que combina las frecuencias de dos tablas
públicas solo cuando:

- pertenecen a la misma familia, posiciones, formato, ante y secuencia;
- la profundidad objetivo queda entre ambas (nunca fuera);
- los donantes están separados como máximo 20 BB;
- ninguna celda es `NOT_IN_RFI`;
- la distancia de variación total entre acciones es como máximo 0,50.

La recomendación conserva el vector de probabilidades, las dos profundidades,
las acciones donantes, el peso lineal y el desacuerdo. No se sortea ni se
convierte silenciosamente una mezcla en una acción pura. Una tabla exacta sigue
teniendo prioridad.

El hueco de SB a 50 BB queda cubierto en 168 de las 169 clases de mano usando
los gráficos SB de 40 y 60 BB. J7o queda sin estimación porque los donantes se
contradicen por completo. Ejemplo validado: A5s pasa a
`OPEN RAISE 75% / LIMP 25%`.

Para respuesta a 3-bet se permiten solo pares de tablas normales de 30+ BB.
Nunca se mezcla la tabla de 20 BB contra shove con las de 30+ BB contra 3-bet
normal. En las profundidades intermedias 35/45/55 BB se cubren respectivamente
1.319, 1.673 y 1.636 de las 4.732 combinaciones mano/posiciones; el resto se
rechaza de forma explícita por desacuerdo o por salir del RFI de un donante.

Simulación aislada sobre las cuatro sesiones: una sola mano cambia respecto a
la versión inmediatamente anterior. K5s en SB con 52,2 BB pasa de `LIMP` puro
por tabla vecina a `LIMP 50% / OPEN RAISE 50%`, porque los dos donantes (40 y
60 BB) coinciden en esa mezcla. Las 101 ventanas pasan de 28 a 29 diferencias
frente a lo originalmente grabado.

No se ha interpolado:

- squeeze, cold 4-bet, respuesta a 4-bet/5-bet ni botes multiway;
- chip-EV hacia ICM/PKO;
- 6-max temprano desde posiciones 8-max;
- call contra open-shove desde la única tabla de 10 BB;
- el salto de 60 a 100 BB, por superar el máximo de 20 BB.

Artefactos:

- interpolador: `decision/preflop/interpolate.py`;
- lookup e integración: `decision/preflop/rangeconverter.py`,
  `decision/engine.py`;
- traducción de mezclas arbitrarias: `decision/preflop/actions.py`;
- pruebas: `decision/preflop/test_interpolate.py`,
  `decision/preflop/test_rangeconverter.py`,
  `decision/preflop/test_actions.py`;
- simulación: `SIMULACION_PREFLOP_INTERPOLACION_2026-07-31.md`.

Validación estable: 1.527 pruebas superadas excluyendo
`tests/test_e2e_corpus.py`. Ese corpus visual se valida aparte porque ya
contenía cuatro expectativas históricas desactualizadas antes de esta tanda.
La reproducción completa de 3.086 frames confirma los mismos cuatro fallos:
board (24 diferencias), `mano_seguida` (4), recomendación (178) y recuento
(568 grabadas frente a 532 actuales). Ninguno nace en esta interpolación.
