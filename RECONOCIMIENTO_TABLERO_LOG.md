# Log de mejoras de reconocimiento del tablero

Fecha: 2026-07-31

## Cambios aceptados

1. **Barrera física contra decisiones preflop falsas**
   - El estado conserva `board_detected_count`.
   - Si visión ve cajas de board pero las cartas aún no están confirmadas, el
     motor se abstiene en vez de recomendar una acción preflop.
   - Validado con prueba de integración y frames reales con 0, 3, 4 y 5 cajas.

2. **Slots de board sin compresión**
   - Se añaden `board_slots` y `board_observed_street`.
   - Una carta ilegible ocupa `None`; las cartas posteriores no cambian de
     posición y una river parcial no se publica como turn.
   - Solo se publica una calle cuando todos sus slots están resueltos.

3. **Estabilización temporal corregible**
   - Una lectura nueva necesita persistencia temporal.
   - Una contradicción aislada no reemplaza el board aceptado.
   - Dos lecturas completas iguales sí pueden corregir una carta previa o su
     prefijo; el tracker ya no queda congelado hasta el final de la mano.
   - Una calle parcial conserva la última calle completa.

4. **Mazo `solid` como ruta principal**
   - Analizador y GUI arrancan con fondo de color y rango blanco.
   - `glyph` y `auto` siguen disponibles como opciones explícitas.
   - Se evita ejecutar ambos detectores y arbitrar entre ellos en la ruta normal.

5. **Lectura del índice superior izquierdo**
   - La máscara de rango `solid` se limita a la zona física donde está el rango.
   - Fichas y manchas blancas de la parte inferior ya no pueden sustituir al
     rango aunque formen un componente mayor.
   - Los frames reales comprobados mantienen correctamente:
     `2d 8c 4s`, `2d 8c 4s 8d` y `2d 8c 4s 8d 8s`.

6. **Sesión de 8 plazas reproducible**
   - `sesion-2026-07-29_190557` declara `max_players: 8` y `mazo: solid`.
   - `replay.py` lee esos datos automáticamente; `--max-players` sigue
     prevaleciendo cuando se proporciona.

## Cambios evaluados y no aplicados

1. **Detección automática de geometría 6/8/9**
   - No se conecta a producción.
   - Con jugadores eliminados o asientos vacíos, varias geometrías comparten las
     mismas posiciones visibles. Además, una zona equivocada puede caer sobre
     otro texto real y producir un nombre o stack aparentemente válido.
   - La captura etiquetada de seis jugadores contiene rectángulos que alteran la
     referencia visual y no sirve como entrada cruda para calibrar el anclaje.
   - Se mantiene la selección explícita de plazas, que es determinista.

2. **Cambiar atlas o umbrales de clasificación de rangos**
   - No se cambian sin un conjunto de crops etiquetados que mida falsos positivos
     por rango. Los JSON históricos son salidas del mismo OCR, no verdad terreno.
   - En los casos etiquetables disponibles la lectura actual ya da el board
     correcto; ajustar umbrales ahí sería una modificación sin evidencia.

## Validación

- Suite rápida completa: `pytest -q -m 'not lento and not corpus'`.
- Pruebas dirigidas de board, estado, GUI, replay y visión.
- Replay secuencial de 60 frames de `sesion-2026-07-29_190557`:
  60 procesados, 0 fallos, mediana de 0,528 s por frame.
- No se usó el corpus histórico completo como etiqueta semántica: sus JSON
  contienen las predicciones antiguas. Se usó para regresión estructural y se
  contrastaron manualmente calles visibles.

## Segunda tanda: regresiones de la sesión 2026-07-31_003011

1. **Frontera de mano tras una animación**
   - El rastreador conserva el último botón realmente visto aunque un frame
     intermedio llegue sin referencia de mesa.
   - Si el botón reaparece en otro asiento, la nueva mano se abre inmediatamente.
   - En el frame 69, `7c 7d` queda ya en la mano 5 con board vacío y sin la
     equity del river anterior.

2. **Runouts rápidos**
   - Flop, turn y river confirman también sus prefijos.
   - El primer prefijo mantiene la confirmación temporal; después, turn y river
     pueden añadir un slot inmediatamente cuando todo el prefijo coincide.
   - Las correcciones de slots existentes siguen necesitando dos lecturas.
   - En los frames 86 y 87 se publican respectivamente turn y river, con equity
     calculada en la calle correcta.

3. **Bloqueo tras actuar el hero**
   - Una acción voluntaria ya registrada del hero bloquea otra recomendación
     preflop dentro de la misma mano.
   - El all-in queda bloqueado de forma persistente aunque después un rival pague.
   - Los frames 82–84 dejan de recomendar `CHECK` después del all-in.

Validación de esta tanda:

- Pruebas dirigidas de rastreo de mano, board, acciones y motor.
- Suite rápida completa.
- Replay instrumentado de los 96 frames: 96 procesados y 0 excepciones.

## Tercera tanda: benchmark, confianza y fusión por casilla

1. **Benchmark visual independiente**
   - Se añadieron etiquetas manuales para 13 estados del board de
     `sesion-2026-07-31_003011`: cinco manos, mesa vacía, flop, turn, river y
     dos runouts que avanzan en frames consecutivos.
   - Las etiquetas se transcribieron mirando los PNG. No proceden de los JSON
     históricos, porque estos contienen predicciones de la propia aplicación.
   - El test compara `board_slots`, antes del estabilizador temporal, para medir
     percepción y no memoria.

2. **Confianza alineada con cada slot**
   - El estado publica `board_slot_confidence`, alineado uno a uno con
     `board_slots`.
   - El calco conserva su acuerdo real con la plantilla.
   - El OCR puntúa el apoyo respecto de todos los votos posibles; una única
     respuesta entre muchas variantes ya no aparenta confianza 1.0.
   - La caché conserva también la confianza de la lectura original.
   - Un rango no resuelto publica confianza 0.0.

3. **Fusión temporal conservadora por posición**
   - Un rango ausente (`None`) no borra el candidato de esa casilla.
   - Solo se rellena un hueco cuando el mismo código se observó al menos dos
     veces en esa posición.
   - Una contradicción reinicia únicamente esa casilla.
   - Todos los candidatos se eliminan al cambiar de mano, por lo que nunca se
     mezclan boards de manos distintas.
   - La confirmación por slot sustituye a la confirmación del board completo;
     no se vuelve a imponer una segunda espera después de confirmar cada carta.

### Evaluado y no aplicado en esta tanda

1. **Aceptar una calle inmediatamente por confianza alta**
   - No se aplica: las cartas correctas etiquetadas dieron valores entre 0,037
     y 0,965. Varias lecturas correctas quedaron en 0,22–0,33.
   - No existe todavía una muestra etiquetada de errores que separe falsos
     positivos de verdaderos. Elegir un umbral ahora eliminaría cartas correctas
     sin demostrar que reduzca errores.

2. **Forzar reconocimiento durante la animación del frame 68**
   - Las cinco cartas siguen visibles, pero la animación tapa el ancla global
     del tapete. La app conserva el último board confirmado y omite la
     percepción cruda por seguridad.
   - Queda como `xfail` estricto y explícito en el benchmark. No se añadió un
     fallback geométrico sin referencia, porque desplazar todas las zonas sería
     un riesgo mayor que perder un frame al final de la mano.
   - Esta limitación quedó resuelta después, en la quinta tanda, mediante un
     fallback que reutiliza exclusivamente la zona del board y no el resto de
     la mesa.

### Validación de esta tanda

- Benchmark manual: 13/13 estados normales exactos; 1 limitación conocida
  marcada como `xfail`.
- Suite rápida completa: todas las pruebas pasan.
- Replay completo de `sesion-2026-07-31_003011`: 96 frames, 0 fallos,
  0,623 s de mediana y 0,873 s de p95 por ciclo.

## Cuarta tanda: sesión 2026-07-31_011143

1. **Distinguir mesa vacía de percepción inválida**
   - El estado declara `table_reference_valid`.
   - Un frame sin referencia del tapete ya no suma para el corte temporal
     `board_vacio`: no observar el board no equivale a observar que no existe.
   - La racha queda pausada y se reanuda con la siguiente observación válida.
   - En los frames 274–276 se conserva la mano 10 y su river
     `Ah 6d 8d 4s 7s`. La mano 11 se abre en el 278, cuando el botón cambia
     realmente de `UR` a `MR` y ya aparecen los antes de la siguiente mano.

2. **Acciones OCR normalizadas por evento**
   - La deduplicación compara la acción canónica, no el texto crudo:
     `Pasar` y `Pasar ~>` son un solo check.
   - `Subir`, `Apostar` o `Igualar` seguidos de la segunda línea `All-in`
     actualizan el evento abierto a all-in en vez de registrar dos decisiones.
   - Si entre ambas vuelve a verse el nick, el evento queda cerrado y las dos
     acciones sí se conservan.
   - En la mano 10 desaparecen el check duplicado, el segundo all-in del rival
     y el call+all-in duplicado del hero.

3. **Protección temporal contrastada con una obstrucción real**
   - En el frame 271 las fichas tapan dos rangos y la percepción cruda devuelve
     `Ah 6d 5d 5s`.
   - El tracker no reemplaza el turn confirmado `Ah 6d 8d 4s`; el frame 272
     recupera la lectura y el 273 añade correctamente `7s`.

### Evaluado y no aplicado en esta tanda

1. **Cambiar perfiles HSV o geometría del detector `solid`**
   - Las seis manos postflop de la sesión detectan exactamente 3/4/5 cajas y
     todos los palos contrastados visualmente son correctos.
   - No hay una población de falsos positivos que permita calibrar un cambio.

2. **Dejar de cachear fallos o lecturas de rango provisionales**
   - El error obstruido del frame 271 no persiste: cambia el recorte, cambia la
     clave y el frame siguiente recupera ambos rangos.
   - Reintentar el mismo recorte determinista solo repetiría el OCR y aumentaría
     el coste sin aportar una señal nueva.

3. **Usar un umbral global de confianza**
   - Se mantiene descartado: en boards correctos de esta sesión hay valores
     desde 0,222, mientras la obstrucción incorrecta llega a 0,556. Las
     poblaciones se solapan y un umbral fijo no las separa.

### Validación de esta tanda

- Sesión íntegra: 290 PNG y 290 JSON, sin huecos ni errores.
- Replay completo con el código nuevo: 290 frames, 0 excepciones.
- Comparación visible: 0 pérdidas, 0 cambios y 2 ganancias intencionadas
  (`board` conservado en los frames 276 y 277).
- Las acciones finales quedan normalizadas sin alterar recomendaciones.

## Quinta tanda: obstrucciones y fallback exclusivo del board

1. **Abstención ante un glifo físicamente tapado**
   - La similitud con la mejor plantilla se usa como medida de integridad de la
     forma, no como confianza global del OCR.
   - Sobre 462 lecturas contrastadas de tres sesiones, las dos obstruidas del
     frame 271 dan 0,507 y 0,545; las 460 correctas empiezan en 0,579.
   - El corte se fija en el hueco, 0,56, y solo se aplica al board del mazo
     `solid`. Las cartas del hero y los otros mazos conservan su ruta anterior.
   - El frame 271 pasa de `Ah 6d 5d 5s` a
     `Ah 6d None None`; el tracker mantiene correctamente
     `Ah 6d 8d 4s`.

2. **Fallback limitado a la zona fijada del board**
   - Cuando la referencia del frame es inválida, se reutiliza la última
     geometría estable únicamente para recortar el board.
   - No se leen jugadores, hero, botón, posiciones, bote ni botones de acción.
   - Se exige una fila de 3/4/5 cajas contiguas, de anchura coherente y alineada.
     Esto rechaza las tres cartas resaltadas y separadas de los frames 275–276.
   - El frame 274 recupera las cinco cartas
     `Ah 6d 8d 4s 7s`.

3. **Benchmark visual ampliado**
   - Se añadieron 19 estados manuales de `sesion-2026-07-31_011143`, incluidas
     calles rápidas, la obstrucción 270–272 y el river final.
   - Se añadió una prueba específica del fallback sobre 274–276.
   - El antiguo `xfail` del frame 68 de `sesion-2026-07-31_003011` ahora pasa:
     la animación pierde el ancla global, pero las cinco cartas se recuperan.

### Validación de esta tanda

- Benchmark de board completo: todos los casos pasan, sin `xfail`.
- Replay completo de la última sesión: 290 frames, 0 excepciones.
- Comparación visible: 0 pérdidas, 0 cambios y las mismas 2 ganancias
  intencionadas de board en 276–277.
- La mano 11 sigue abriéndose correctamente en el frame 278 por movimiento real
  del botón y publicación de antes.

## Sexta tanda: nombres en mayúsculas y estados transitorios

Sesión: `testing/sesion-2026-07-31_022832`.

1. **Usuarios en mayúsculas dentro del nameplate exacto**
   - La extracción general sigue siendo restrictiva para evitar falsos nombres.
   - Dentro de la zona geométrica exacta de un asiento se acepta un token de
     usuario aunque no contenga minúsculas.
   - Esto permite recuperar `BOLIYA16`, que antes era imposible en todas las
     relecturas porque el mismo filtro lo rechazaba siempre.

2. **Textos de estado que no son nombres**
   - `Ciegas`, `Ganado` y `Ganador` se clasifican como estados transitorios del
     asiento.
   - No entran en la votación de identidad ni sustituyen al nombre estable.

### Validación

- 116 pruebas de referencia de mesa/nombres: correctas (incluidas las 16
  focalizadas en esta lectura).
- Lectura directa de los frames reales:
  - 0145: `BOLIYA16`;
  - 0435 y 0441: `BOLIYA16`;
  - `Ciegas`, `Ganado` y `Ganador`: rechazados como nombres.

### No realizado

- No se amplió el filtro general de texto a cualquier cadena en mayúsculas: sin
  la geometría exacta del asiento aumentaría los falsos positivos procedentes de
  overlays y controles de la mesa.
