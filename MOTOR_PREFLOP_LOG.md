# Log de mejoras del motor preflop

Fecha: 2026-07-31  
Sesión principal de validación: `testing/sesion-2026-07-31_011143`

## Cambios realizados

### 1. Reconstrucción ordenada de la agresión preflop

Se añadió `action_log.estado_preflop(state)`, que:

- completa la posición de una acción mediante el asiento estable;
- conserva la última agresión aunque después haya folds o calls;
- deduplica repeticiones antiguas del mismo all-in;
- distingue apertura observada de resubida observada;
- detecta una agresión rival posterior a la última acción del hero;
- expone el resultado como `state["preflop_action"]` para diagnóstico.

Resultado real:

- frame 0096: reconoce `HJ raise -> CO all-in`;
- frame 0209: reconoce `hero raise -> SB all-in`.

### 2. Bloqueo seguro de recomendaciones fuera de las tablas

Cuando se observa una resubida:

- ya no se conserva una recomendación contra el primer raiser;
- ya no se afirma que el hero actuó y no ocurrió nada después;
- se explica si la resubida ocurrió entre rivales o después de la acción del hero;
- el motor se abstiene porque no existen rangos digitalizados de respuesta a
  3-bet/4-bet.

Resultado real:

- frames 0096-0098: se elimina `3BET (9 BB) vs HJ` después del all-in de CO;
- frames 0100-0102: se elimina `RAISE OVER LIMPERS (4 BB)` en el mismo spot;
- frames 0209-0210: se identifica que el all-in de SB devuelve la acción al hero.

### 3. La apuesta visible ya no depende de los botones

El motor ejecuta la detección de raiser aunque `facing` sea `None`. Una apuesta
visible por encima de una ciega es evidencia independiente del OCR de los
botones.

Resultado real:

- frames 0237-0244: la apuesta visible de CO a 3,5 BB permanece clasificada como
  `threebet_call vs CO`; ya no oscila a `open_raise`.

### 4. Guarda conservadora para `to_call`

Un importe para igualar superior al stack restante del hero se marca como
imposible:

- se conserva el valor crudo para diagnóstico;
- no se usa para atribuir una subida;
- no se intenta reparar dividiendo por diez o cien;
- tampoco permite recomendar como si el bote estuviera sin abrir.

Resultado real:

- frame 0099: `126 BB` frente a un stack de 44,1 BB se rechaza como importe
  imposible. La pantalla mostraba 12,6 BB, pero el motor no adivina el decimal.

## Validación

- 577 tests de `decision/`, núcleo, dominio y replay: correctos.
- Tests añadidos para:
  - posiciones ausentes;
  - apertura seguida de all-in rival;
  - fold posterior a una resubida;
  - resubida posterior a una apertura del hero;
  - duplicados antiguos de all-in;
  - pérdida temporal de botones;
  - `to_call` superior al stack.
- Barrido del motor sobre los 290 estados grabados en vivo:
  - 6 recomendaciones eliminadas;
  - las 6 pertenecen al spot incorrecto de los frames 0096-0102;
  - 0 recomendaciones válidas cambiadas;
  - 0 recomendaciones nuevas inventadas.
- Replay de pipeline hasta el frame 0103:
  - 0 errores;
  - corrige la oscilación a `open_raise` de los frames 0100-0102.
- `git diff --check`: correcto.

## No realizado

### Recomendaciones reales frente a 3-bet/4-bet

No se añadieron acciones como call, fold, 4-bet o all-in para esos spots porque
el proyecto solo contiene tablas `open_raise` y `threebet_call`. Inferir una
respuesta usando otra familia de rangos produciría recomendaciones plausibles
pero estratégicamente falsas.

Para habilitarlo hacen falta rangos digitalizados separados, como mínimo:

- respuesta del open-raiser frente a 3-bet;
- respuesta fría frente a open + 3-bet;
- respuesta frente a 4-bet;
- tratamiento de tamaños all-in y stacks efectivos.

### Replay exacto del vigilante rápido

El replay frío solo conserva los PNG de los análisis lentos. En vivo, el
vigilante inspecciona frames intermedios a mayor frecuencia y fue quien capturó
los all-in de los frames 0096 y 0209. Por eso el barrido del motor sobre los JSON
grabados es la validación fiel de estas acciones; el replay únicamente desde PNG
no puede reconstruir eventos que estaban en frames intermedios no guardados.

### Suite visual completa

Se inició, avanzó sin fallos y se detuvo al comprobar que competía por CPU con la
aplicación y sus procesos OCR en ejecución. No se detuvo ni modificó la
aplicación. La tanda afectada quedó cubierta por las 577 pruebas focalizadas y
por los dos barridos de sesión descritos arriba.

---

## Segunda tanda: sesión 2026-07-31_022832

### 1. Frontera entre acciones residuales y el preflop actual

`estado_preflop` conserva ahora el tiempo de cada acción y toma la última
colocación de ciegas/antes como frontera:

- una agresión anterior a la última ciega se considera residual;
- una agresión posterior pertenece al preflop actual;
- una agresión con exactamente el mismo timestamp se marca como ambigua, porque
  el recorrido espacial de los asientos dentro de un frame no prueba orden
  cronológico;
- las acciones residuales dejan de afectar también a la última acción del hero.

Resultado real:

- frame 0311: el falso all-in de HJ fue registrado antes de la ciega posterior
  del HERO; se ignora y se conserva el `CHECK` correcto de la BB;
- no se borran agresiones actuales solo porque después aparezca un fold o call.

### 2. All-in inicial fuera del modelo

Una única agresión `allin` ya no entra en `threebet_call`. Esa familia representa
la respuesta a una apertura estándar; un shove necesita tamaño, stack efectivo
y pot odds específicos.

Resultado real:

- frame 0446: se elimina `CALL` con 9s7h frente al shove de HJ a 19,8 BB;
- frames 0447-0448: el fold posterior ya no borra el all-in ni permite volver a
  `RAISE OVER LIMPERS`;
- el motivo de abstención indica explícitamente que falta un rango frente a
  shove.

### 3. Persistencia de una apertura rival

La señal del historial ya no depende de que `raise` sea literalmente el último
evento. Un fold o call posterior no vuelve a cerrar el bote.

Resultado real:

- frames 0455-0460: se elimina `OPEN RAISE (4 BB)` con una apertura de MP2 y un
  caller ya observados; como el importe visible no permite una atribución
  independiente estable, el motor se abstiene en vez de fingir bote sin abrir.

### 4. Sin `CHECK` estratégico inventado frente a varios limpers

Cuando la BB tiene opción frente a dos o más limpers, `bb_option` no dispone de
una celda donante. El motor antes rellenaba ese hueco con `CHECK` porque pasar es
legal y gratis. Eso confunde una acción legal con una recomendación estratégica.

Resultado real:

- frames 0184-0187: se elimina `CHECK` con KK frente a tres limpers;
- frames 0567-0568 y 0690: también se retira el fallback en botes de tres y
  cuatro limpers;
- el HUD explica que no hay rango multiway digitalizado.

### Validación

- 584 pruebas de `decision/`, núcleo, dominio y replay: correctas.
- Barrido final del motor sobre una instantánea de 1.012 estados de la sesión:
  - 0 excepciones;
  - 16 recomendaciones eliminadas;
  - 7 corresponden al all-in y al falso `CHECK` con KK ya aislados;
  - 6 corresponden a la apertura seguida de caller de los frames 0455-0460;
  - 3 son otros `CHECK` multiway sin tabla;
  - 0 recomendaciones cambiadas por otra acción;
  - 0 recomendaciones nuevas inventadas.
- `git diff --check`: correcto.

### No realizado

- No se inventó una tabla de call/raise/fold frente a shove.
- No se inventó un rango de subida de BB frente a varios limpers.
- En los frames 0455-0460 no se fuerza una atribución usando únicamente el
  historial incompleto: se conserva la evidencia para bloquear el falso
  `open_raise`, pero se exige corroboración para elegir una tabla contra una
  posición concreta.

---

## Tercera tanda: auditoría de fuentes y CALL vs open-push

### Inventario de las capturas originales

Se volvió a leer `/mnt/qnap/Poker/CAPTURAS HERRAMIENTAS PREFLOP/` sin usar los
comentarios de `docs/`:

- `OPEN RAISE`: 88 imágenes individuales, 11 profundidades y 8 posiciones;
  cobertura completa.
- `3BET-CALL`: 244 spots esperados después de la reparación.
- `3BET-CALL/10BB/1BB (My position)`: sigue vacío en el material fuente; no se
  rellenó por analogía.
- El montaje original muestra más familias que nunca se capturaron: respuesta
  del open-raiser frente a 3-bet, `CALL VS OPEN-PUSH`, `SQUEEZE/CALL`,
  `COLD4BET/FARHA` y variantes frente a limp/ROL.

### 1. Spot original recuperado: BB vs MP1 a 20 BB

La captura
`3BET-CALL/20BB/1BB (My position)/6.png` sí existía. El `ranges.json` antiguo
había perdido el spot completo aunque el digitalizador actual lo identifica como
`BB vs MP1`.

Cambios:

- se redigitalizaron las 169 celdas desde esa captura;
- `ranges.json` vuelve a contener `threebet_call["20"]["BB"]["MP1"]`;
- se añadió `--refresh PNG [...]` al digitalizador para reparar imágenes
  concretas sin procesar todo el corpus;
- una posición OCR duplicada ya no puede sobrescribir silenciosamente otra:
  conserva la primera y registra un fallo.

Cobertura final del material original:

- 88 spots `open_raise`;
- 244 spots `threebet_call`;
- 0 spots esperados ausentes;
- 169 clases de mano en el spot recuperado.

### 2. Nueva familia suplementaria: CALL vs open-push

Fuente pública separada:
`RangeConverter — 8-Max MTT 10BB Tournament Poker Charts`.

No se mezcló con `ranges.json`. Vive en `supplemental_ranges.json` con nombre,
URL, fecha, formato y supuestos explícitos.

Cobertura:

- 28 enfrentamientos posibles de respuesta en 8-max;
- desde `MP1 vs EP2` hasta `BB vs SB`;
- acción `CALL`, `FOLD` implícito y cinco clases de mano mixtas conservadas como
  `CALL 50% / FOLD 50%`.

El motor solo consulta este suplemento cuando demuestra todos sus supuestos:

- mesa configurada como 8-max;
- ocho posiciones realmente asignadas, no una mesa 8-max ya acortada;
- primera agresión observada igual a all-in;
- ningún limp anterior y ningún caller posterior;
- shove/profundidad efectiva entre 9,5 y 10,5 BB;
- ante total visible de 1 BB, inferido de las 2 BB obligatorias de la BB
  (ciega + BB-ante).

Si cualquiera falta, se abstiene. No redondea a 10 BB, no cae en
`threebet_call` y no traslada el rango a 6-max/9-max.

La GUI distingue la procedencia con color azul y el texto «guía pública
complementaria»; las tablas originales siguen verdes y las inferencias siguen
naranjas.

### Validación

- Comparación independiente del JSON contra las imágenes del PDF:
  - 28 gráficos;
  - 0 discrepancias de celdas;
  - mezclas 50/50 preservadas.
- Suite focalizada de preflop, motor, action log, dominio, núcleo y GUI:
  correcta.
- Auditoría estructural de `ranges.json`:
  - 88/88 spots de apertura;
  - 244/244 spots de defensa;
  - 0 ausencias;
  - 169/169 manos en `BB vs MP1` a 20 BB.
- Barrido de estados grabados:
  - sesión `011143`: 290 estados, 0 excepciones;
  - sesión `022832`: 1.012 estados, 0 excepciones;
  - ambas son 6-max, por lo que el suplemento 8-max no se activó;
  - el shove real de 19,8 BB de los frames 0446-0448 sigue sin recibir una
    recomendación de 10 BB ni de `threebet_call`.
- Casos sintéticos positivos:
  - 8-max/10 BB/ante 1 BB devuelve CALL o FOLD según la tabla;
  - las celdas mixtas llegan al HUD sin convertirse en una acción pura;
  - formato, ante, profundidad, limper o caller incompatibles bloquean la tabla.
- `git diff --check`: correcto.

### No realizado y por qué

- No se rellenó `BB vs apertura` a 10 BB de las capturas ZeroS: la carpeta
  original está vacía. El nuevo open-push no reemplaza ese spot porque responde
  a un all-in, no a un min-raise.
- No se importaron tablas Nash heads-up: cambian el número de jugadores y los
  supuestos de equilibrio.
- No se añadieron aún respuesta del open-raiser frente a 3-bet all-in,
  cold-4bet, squeeze/call ni rangos multi-limper. Requieren familias separadas y
  que el reconocimiento demuestre secuencia, sizing, jugadores y profundidad;
  copiar una celda de otra familia sería una falsa mejora.
- La suite visual completa se detuvo: estaba compitiendo por CPU con la
  aplicación en ejecución y, además, había empezado antes de regenerar el spot
  recuperado. La tanda cambiada queda cubierta por la suite focalizada, la
  comparación directa con las fuentes y los dos barridos de sesión.

---

## Cuarta tanda: BB multi-limper y simulación de sesiones recientes

### 1. Corrección estrecha para la opción de la BB con varios limpers

La abstención añadida en la segunda tanda evitaba fingir una tabla multiway,
pero también dejaba a `KK` sin ninguna recomendación. Se añadió una regla
separada y trazable, no mezclada con las tablas ZeroS:

- solo `AA/KK` suben por valor;
- tamaño total: 3 BB base + 1 BB por limper + 1 BB por estar fuera de posición;
- si el stack no cubre el tamaño, la acción es `ALL IN`;
- el resto conserva `CHECK`, pero con procedencia `safety_default`, confianza
  baja y una advertencia explícita de que no es una solución GTO ni afirma que
  no existan otros raises rentables.

La fuente pública usada para esa heurística es:
`Preflop Wizard — Poker Isolation Raise Strategy`.

Resultado en `sesion-2026-07-31_022832`:

- frames 0184-0187, `KK` en BB frente a 3 limpers:
  `CHECK (BB option)` -> `RAISE OVER LIMPERS (7 BB)`;
- frames 0567-0568, `72o` frente a 3 limpers:
  `CHECK`, ahora identificado como fallback legal de confianza baja;
- frame 0690, `A3s` frente a 4 limpers:
  mismo `CHECK` conservador y trazable.

### 2. Una defensa heads-up ya no se reutiliza si hay caller

La simulación sobre sesiones anteriores descubrió un segundo fallo: cuando
había una apertura y al menos un caller, `derive.squeeze` no tiene donante para
las ciegas. El motor interpretaba ese `None` como permiso para continuar con la
tabla `threebet_call` heads-up.

Resultado real:

- `sesion-2026-07-31_020108`, frames 0352-0353;
- hero `K6s` en BB, BTN abre y SB paga;
- antes: `ALL IN` procedente de la defensa heads-up;
- ahora: abstención explícita por spot squeeze/multiway sin rango compatible.

También se corrigió el recuento del caller desde SB: pagar una apertura a 2 BB
añade exactamente 1,5 BB sobre la media ciega ya puesta. El límite anterior era
estrictamente mayor que 1,5 y por eso ignoraba ese pago.

### 3. Simulación reproducible mano por mano

Se añadió `simulate_preflop.py`. Reutiliza los estados ya reconocidos, ejecuta
el motor actual con un contexto nuevo por sesión y agrupa las salidas por
`mano_seguida`. Distingue:

- acciones procedentes de tabla;
- heurística pública;
- fallback legal de baja confianza;
- abstenciones y su motivo;
- diferencias exactas frente a la recomendación grabada, con sus frames.

No calcula ganancias contrafactuales: una acción distinta cambiaría la respuesta
de los rivales y el desarrollo posterior. Además, `hand_result` queda repetido
en varios JSON antiguos y no es una fuente válida para repartir ese mismo bote
a manos posteriores.

Informe generado:
`SIMULACION_PREFLOP_2026-07-31.md`.

Cobertura:

- `sesion-2026-07-31_011143`: 11 ventanas de mano;
- `sesion-2026-07-31_014709`: 13;
- `sesion-2026-07-31_020108`: 38;
- `sesion-2026-07-31_022832`: 39;
- total: 101 ventanas de mano.

### Validación

- 674 pruebas del motor, preflop, RAG, núcleo, dominio y replay: correctas.
- 192 pruebas focalizadas después de la guarda squeeze/multiway: correctas.
- Replay integral de `sesion-2026-07-31_022832`:
  - 1.012 frames;
  - 0 fallos;
  - 149 frames con recomendación;
  - 8 recomendaciones antiguas retiradas;
  - 0 recomendaciones nuevas inesperadas;
  - 7 cambios: cuatro raises correctos con `KK` y tres `CHECK` cuya procedencia
    ahora es explícita;
  - p50 0,552 s y p95 0,701 s.
- Barrido de los estados guardados de las cuatro sesiones: 101 ventanas de mano
  simuladas sin excepción.
- `py_compile` y `git diff --check`: correctos.

### No realizado y por qué

- No se creó un rango completo de raise/check para BB contra varios limpers:
  la guía pública respalda subir premiums y aumentar el tamaño, pero no aporta
  una matriz compatible para todas las manos, stacks y números de limpers.
- No se añadió una acción para las ciegas frente a open + caller: hace falta una
  familia squeeze/cold-call propia. Hasta digitalizarla, abstenerse es más seguro
  que trasladar una defensa heads-up.
- No se simuló cuánto dinero se habría ganado siguiendo cada consejo. Ese
  resultado requiere modelar respuestas rivales y líneas postflop que no están
  observadas; presentarlo como hecho sería inventar datos.

---

## Quinta tanda: calls positivos completan el conteo de limpers

### Problema real

En `sesion-2026-07-31_022832`, frames 0184-0187, el historial había observado
cuatro calls antes de que el hero actuase con `KK` en BB:

- MP2;
- CO;
- BTN;
- SB.

Los importes visibles solo permitían contar tres porque la SB todavía mostraba
0,5 BB aunque su nameplate ya hubiese enseñado `Igualar`. El motor recomendaba
7 BB en vez de las 8 BB que corresponden a cuatro limpers con la heurística
vigente.

### Corrección

`action_log.estado_preflop` expone ahora `limper_seats_observed`:

- solo usa calls posteriores a la última colocación de ciegas;
- cuenta cada asiento una vez aunque el mismo cartel aparezca en varios frames;
- usa la última acción voluntaria, por lo que un fold posterior elimina al
  asiento;
- excluye al hero y a jugadores que el estado marca fuera de la mano;
- solo produce limpers cuando no existe agresión observada.

`engine._contar_limpers` une esos asientos con los limpers reconocidos por
importe. El historial añade evidencia positiva, pero su ausencia nunca borra un
limper visible.

### Resultado

- `KK`, frames 0184-0187: `RAISE OVER LIMPERS (8 BB)`;
- el razonamiento enumera cuatro limpers y conserva la fuente pública;
- `72o` y `A3s` mantienen `CHECK`, ahora con tres y cuatro calls demostrados;
- frames 0810-0811, `T8s` en BB: el segundo call observado reclasifica el
  `CHECK` derivado como fallback multiway de baja confianza;
- algunas aperturas marginales de sesiones anteriores se endurecen al
  demostrarse más limpers, sin crear raises nuevos con manos no premium.

La simulación contrafactual también cambia en
`sesion-2026-07-31_020108`, mano 11:

- hero `Q5s` en BTN;
- recomendación actual: `fold` frente a varios limpers;
- acción real: call y 51,5 BB comprometidas después;
- otro jugador ganó el bote;
- a unas 90 fichas por BB, el fold habría evitado aproximadamente 4.635 fichas
  de inversión.

### Validación

- 201 pruebas focalizadas: correctas.
- 679 pruebas del motor, preflop, RAG, núcleo, dominio y replay: correctas.
- Replay integral de `sesion-2026-07-31_022832`:
  - 1.012 frames;
  - 0 fallos;
  - 149 frames con recomendación;
  - 8 recomendaciones antiguas retiradas;
  - 0 recomendaciones nuevas inesperadas;
  - 7 cambios visibles;
  - p50 0,520 s y p95 0,656 s.
- Barrido de cuatro sesiones:
  - 101 ventanas de mano;
  - 18 con diferencias de acción o procedencia frente a la versión grabada;
  - sin excepciones.
- `py_compile` y `git diff --check`: correctos.

### Informes regenerados

- `SIMULACION_PREFLOP_2026-07-31.md`;
- `ANALISIS_CONTRAFACTUAL_TORNEO_2026-07-31.md`.
