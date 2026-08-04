# Poker Assistant IA

Ver [`prompt.md`](./prompt.md) para el objetivo, contexto, inventario de datos y las fases del proyecto,
y [`docs/PENDIENTE.md`](./docs/PENDIENTE.md) para lo que queda por hacer y en qué orden.

## Tests

Todo el proyecto es un **paquete de Python**: los módulos se importan por su ruta
completa (`from vision import seat_map`) y no hay ni un `sys.path.insert`. Eso
tiene dos consecuencias prácticas:

- Un módulo suelto **no se lanza por ruta**, se lanza con `-m` desde la raíz:
  `python -m calibration.select_region`, `python -m decision.rag.pipeline`. Por
  ruta fallaría al importar a sus hermanos. (Los dos `ocr_worker.py` — el de
  `vision/` y el de `decision/preflop/` — comparten nombre a propósito y solo se
  distinguen así.)
- `pytest` desde la raíz ejecuta todo lo disponible sin configurar nada. Los
  tests GTK se saltan automáticamente si no hay display; para incluirlos en CI
  hay que ejecutarlos bajo Xvfb.

### Dos velocidades

```bash
pytest -m "not lento and not corpus"    # ~1.000 tests en 8 s
pytest                                  # todo, ~8 min
```

La primera es la de después de cada cambio: toda la lógica de decisión, sin
tesseract, sin cv2 pesado y sin tocar `testing/`. La segunda añade los tests de
imagen, el E2E sobre frames reales y los invariantes sobre las 26 sesiones
grabadas; es la de antes de commitear.

Marcas (`pyproject.toml`): `lento` (segundos por test), `vision` (necesita
opencv), `gtk` (necesita PyGObject y display; se salta sin él), `corpus`
(necesita `testing/`).

### El corpus no se versiona

Los tests marcados `corpus` trabajan sobre las sesiones que la app ya ha grabado
jugando (`testing/`, ~9.200 frames, 14 GB). **No hay ni una imagen en el repo**:
`tests/corpus.py` recalcula en cada ejecución una muestra estratificada por lo
que cada frame tiene de interesante (board 0/3/4/5, cartas apagadas, multiway,
bote dividido, cada motivo de abstención distinto...), así que 500 frames cubren
el espacio de comportamiento en vez de cinco minutos seguidos de una partida.

La selección va sembrada y se vuelca en `testing/_seleccion.local.json`, para
poder repetir una ejecución que salió roja:

```bash
pytest --corpus-n 200                                  # muestra más pequeña
pytest --corpus-semilla 42                             # reproducible
pytest --corpus-seleccion testing/_seleccion.local.json  # exactamente la anterior
```

### Entorno reproducible

`requirements.txt` fija las dependencias directas y `pylock.toml` contiene la
resolución transitiva para la plataforma/Python con que se generó. Se regenera
tras cambiar dependencias con `python -m pip lock -r requirements.txt -o
pylock.toml`. La comprobación de contratos se ejecuta con `python -m mypy
domain`; la CI ejecuta además toda la suite rápida bajo Xvfb, incluidos los
tests GTK.

Sin `testing/` esos tests salen como **skipped** con el motivo, nunca como
passed.

### Cobertura

```bash
pytest --cov=decision --cov=core --cov=vision --cov-report=term-missing
```

Medido con la suite entera: **core 97,6 %**, **decision 93,7 %**, **vision
86,4 %** (87 % total). El tope de `fail_under` está por debajo de eso, para
proteger de que baje. Quedan fuera `capture/` (portal/PipeWire), `decision/rag/`
(estudio offline) y las rutas de diagnóstico de `vision/` — ver el `omit` de
`pyproject.toml`, donde está escrito el porqué de cada exclusión.

## Los cuatro estados de un asiento

Es la especificación de la que sale el recuento de jugadores, y de ese recuento
salen **todas** las posiciones y con ellas el rango que se sirve:

| estado | qué se ve | ¿sentado? | ¿en la mano? |
|---|---|---|---|
| 1 | hueco, tapete pelado | no | no |
| 2 | cápsula **oscurecida**, sin cartas | sí | no (se retiró) |
| 3 | cápsula + **dorsos** | sí | sí |
| 4 | cápsula + **cartas boca arriba** | sí | sí (all-in / showdown) |

Lo que aporta es **separar dos preguntas con señales distintas**: *"¿sentado?"*
son los estados 2/3/4 y *"¿en la mano?"* los 3/4. Antes "sentado" dependía de que
el OCR leyera el nick, y sobre una cápsula oscurecida —un jugador ya retirado—
eso falla a menudo: el asiento desaparecía del recuento y corría todas las
posiciones.

Medido sobre 13.900 observaciones de asiento de las 26 sesiones, con verdad de
terreno que **no sale de la app** (un asiento con cartas está ocupado; una
fracción de cápsula < 0,005 es tapete pelado):

| | inestabilidad | recall | precisión |
|---|---|---|---|
| antes | 0,3 % | 99,0 % | **64,8 %** |
| ahora | 2,4 % | 99,8 % | **87,9 %** |

Se contaba tapete pelado como jugador **1 de cada 3 veces**; ahora 1 de cada 8.
El 0,3 % de inestabilidad de antes no era una virtud sino un **candado**: el
rastreador votaba sobre su propia salida, así que una vez fijado el conjunto no
podía cambiar (medidas 187 rachas de asientos sostenidos solo por esa memoria, la
más larga de 261 frames seguidos). Ese bucle está roto —el voto va sobre
`state["asientos_leidos"]`, la lectura cruda del frame— y el precio es que ahora
el recuento puede moverse dentro de una mano. **Es un cambio abierto**: reducirlo
sin perder precisión pasa por fijar el conjunto al abrir la mano (medido offline:
0 % de inestabilidad con 98,7 % de recall y 86,3 % de precisión).

## Herramientas de desarrollo

```bash
python replay.py testing/sesion-<fecha> --diff     # ¿mi cambio altera lo que la app dijo?
python ver_frame.py testing/sesion-<fecha> 485     # ¿de DÓNDE sacó ese número?
python vigilar_sesion.py                           # avisa en vivo de lo que merece mirarse
```

`replay.py` vuelve a pasar los PNG grabados por el mismo `core.Analizador`, sin
portal ni GTK, y con `--diff` compara frame a frame contra lo que se calculó
entonces. Es la prueba de que un refactor no cambió el comportamiento.

`ver_frame.py` dibuja sobre la imagen las zonas que el algoritmo mira y las
colorea según lo que encontró en cada una. **Ojo con la referencia del tapete**:
se fija con la mediana de las primeras diez lecturas buenas de la sesión, así que
un frame suelto se analiza en frío y puede colocar todas las zonas desplazadas —
la herramienta avisa cuando eso pasa, y con una carpeta de sesión la calienta
como en vivo.

## Modo testing

La casilla **"Grabar sesión de testing"** de la GUI (se activa antes de darle a
"Iniciar análisis") guarda cada frame junto con TODO lo que la app calculó de él,
emparejados por nombre:

```
testing/sesion-2026-07-25_193012/
    _sesion.json      metadatos: inicio, intervalo, recuadro, commit, nº de frames
    0001.png          el frame tal cual se analizó
    0001.json         GameState completo (con warnings), recomendación, evaluación
                      de mano, equity postflop y resumen de la mano anterior
    0002.png
    0002.json
```

La dupla es por **nombre** (mismo número, distinta extensión), que es lo que
permite abrir el PNG y mirar el JSON de al lado sin cruzar timestamps. El JSON
incluye los `warnings`, que suelen ser lo más informativo cuando algo sale mal, y
el tiempo que tardó el análisis de ese frame.

La **equity postflop se calcula, se graba y se muestra** en el HUD. Si el hero
enfrenta una apuesta y se leen bote y cantidad a pagar, el mismo panel añade el
precio del call, la equity mínima y el SPR actual. Esa comparación se etiqueta
como orientativa: la equity es de check-down y no actualiza el rango rival por
haber apostado, por lo que nunca se convierte automáticamente en CALL/FOLD.

`testing_session.resumen(carpeta)` da un agregado de la sesión (frames, cuántos
con recomendación, motivos de abstención más frecuentes) sin abrir los frames uno
a uno. La carpeta `testing/` no se versiona.

## Uso (alpha)

`./poker-assistant` — calibra el recuadro de la mesa si hace falta (o con `--recalibrate`
para forzarlo) y arranca `alpha.py`: un lazo de diagnóstico que captura la mesa cada
pocos segundos, corre el reconocimiento de la Fase 3 (mazo de 4 colores) y va imprimiendo
por consola lo que detecta (cartas, board, pot, ciegas, jugadores) para validarlo en vivo
mientras juegas. Todavía no da recomendaciones (eso es la Fase 4/5) ni dispara por cambio
de board (Fase 2) — es solo para comprobar que la visión funciona contra partidas reales.

`.venv/bin/python gui.py` — panel de control GTK4 (Fase 5): envuelve el mismo flujo que
`alpha.py` en una ventana no bloqueante. El análisis (captura + OCR) corre en un hilo
aparte y actualiza los widgets vía `GLib.idle_add`, así que la UI no se congela. Muestra el
estado detectado (tus cartas, board, bote, jugadores con posición y stack), una sección
"Mano actual" con la mano formada y los proyectos + % que devuelve `decision/hand_strength.py`
(oculta entre manos, cuando no hay cartas del hero), la recomendación de `engine.decide` en
grande (o el motivo si no la hay), un panel **"Guía postflop (GTO)"** justo debajo —que es
donde `engine.decide` se queda en blanco a propósito— con la textura del board, alpha, MDF
y el tamaño o la acción que proponen las heurísticas de `decision/postflop_gto.py`, en azul
porque su procedencia **no** son las tablas digitalizadas, una sección "Mano anterior" que resume la última mano
terminada leyendo el resultado del panel de chat (`vision/hand_result.py`: ganador, importe,
mano ganadora, jugadores de showdown y si el hero ganó/perdió/**empató** el bote), un panel
para **marcar una situación** rara y anotarla mientras juegas (fija el frame en el momento y
la nota se le pega después, se tarde lo que se tarde en escribirla), y botones para
iniciar/parar el análisis y relanzar la calibración del recuadro.

### Cuánto tarda un ciclo

**No hay un número: hay un rango, y se mide en cada sesión.** Medido sobre cinco sesiones
reales, el ciclo va de **0,45 a 0,82 s de mediana** y de **0,83 a 1,15 s de p95** — depende del
tamaño de ventana, del tema de mesa, del mazo, de cuántos asientos hay ocupados y de qué más
esté haciendo la máquina. Cualquier cifra fija que se escriba aquí se queda vieja; de hecho el
repo llegó a tener tres a la vez, y las tres estaban mal.

Por eso cada frame graba su propio desglose (`state["tiempos"]`, ver
`vision/table_state._Reloj`) y `testing_session.resumen()` da `ciclo_p50_s` / `ciclo_p95_s` por
sesión. Para verlo sobre una sesión ya grabada:

```bash
python replay.py testing/sesion-<fecha> --hasta 200
```

**El OCR es ~90 % del ciclo.** El resto (disco del dealer 50 ms, dorsos 17, referencia 16) son
migajas en comparación. Por eso el chat **no se lee en cada frame**: era el job más caro
—264 ms medidos en un A/B sobre los mismos frames, el 26 % del ciclo— y lo que se saca de él
(quién ganó la mano anterior y su número) cambia una vez por mano. Se lee al cerrarse una mano,
en los primeros frames y como mucho cada `CHAT_MAX_S`; el último resumen se conserva, así que el
panel "Mano anterior" no pierde ni un frame.

## Estructura

- `calibration/` — Fase 0: `select_region.py` toma un frame de referencia (vía
  `capture/portal_capture.py`) y deja dibujar con el ratón el recuadro de la mesa;
  guarda las coordenadas en `calibration/config.local.json` (no versionado).
  **Calibrar pregunta SIEMPRE qué pantalla** (`elegir_pantalla=True`, o sea que no
  manda el `restore_token` guardado): es el momento en que se decide dónde está la
  mesa, y con dos monitores el recuadro se estaba dibujando sobre la pantalla que
  tocó la vez anterior. La elección nueva se guarda, así que el análisis sigue
  arrancando sin preguntar.
- `capture/` — Fase 1: `portal_capture.py` abre una sesión de
  `org.freedesktop.portal.ScreenCast` y consume el stream de PipeWire con GStreamer.
  El `restore_token` se guarda en `capture/config.local.json`, aunque en KDE Plasma
  6.7 el selector de pantalla vuelve a aparecer en cada arranque del proceso (no
  evita la interacción, solo el permiso). Necesita `PyGObject`/`GStreamer` del
  sistema — el venv del proyecto se creó con `include-system-site-packages = true`
  en `.venv/pyvenv.cfg` para verlos sin tener que compilarlos aparte.
- `vision/disposicion.py` — **qué mesa es**, leído del tapete en vez de elegido a
  mano. A cada geometría conocida (6, 8 y 9 plazas) se le pregunta si SUS zonas
  tienen cápsula de nameplate y cuánto se descentra, y se penaliza la que deje
  cápsulas sin explicar —que es lo único que separa una mesa de 6 de una de 8, que
  comparten asientos—. Detecta la GEOMETRÍA, no cuánta gente hay sentada: un
  6-max con tres jugadores sigue siendo un 6-max. **Se abstiene cuando no está
  claro**, y entonces se usa la de 6 y no se recomienda, porque las posiciones
  salen del recuento de ocupados y con la geometría equivocada serían plausibles y
  falsas. Sobre las 29 sesiones grabadas con disposición conocida: 25 aciertos, 4
  abstenciones, **0 errores**. El selector "Mesa" arranca en Auto; elegirla a mano
  sigue mandando (y entonces el detector solo avisa si no cuadra).
- `vision/` — Fase 3: reconocimiento del estado de mesa (cartas, stacks, pot...).
  `table_state.py` (`analyze(image_path) -> GameState`) orquesta `table_region.py`
  (localiza el ovalo por el borde rojo), `card_detector.py` (cartas por contorno
  blanco+forma, sin coordenadas fijas ni color de tapete), `suit_classifier.py`
  (palo por color + forma contra las plantillas de `card_templates/`, generadas
  una vez por `generate_card_templates.py`) y `text_extract.py` (pot/ciegas/
  jugador+stack por regex sobre lineas OCR, sin posiciones fijas). El OCR usa
  `tesserocr` aislado en `ocr_worker.py` (mismo motivo que
  `decision/preflop/ocr_worker.py`: evitar corrupcion de memoria al mezclarlo
  con opencv en el mismo proceso), invocado desde `ocr_client.py`. El **idioma
  del OCR se elige por tipo de job**: el texto libre de la UI (nameplates, chat,
  bote, botones, ciegas) se lee con el modelo **espanol** porque el cliente esta
  en castellano — con el modelo ingles los acentos se corrompen
  ("Informaci6n" por "Información") y eso degrada el emparejado de
  `SEAT_STATUS_WORDS`, el parseo del chat y el de ciegas —, mientras el OCR de
  **rango de carta** sigue en ingles (whitelist de digitos+AKQJ, ya ajustado, y
  sin una sola palabra en castellano que ganar). Requiere espanol e ingles en el
  MISMO directorio de tessdata (lo exige tesseract): `sudo dnf install
  tesseract-langpack-spa`, o `vision/tessdata/{spa,eng}.traineddata` local (no
  versionado). Sin espanol disponible cae a ingles para todo, el comportamiento
  anterior. `run_samples.py`
  corre el pipeline contra `vision/samples/` y vuelca `vision/results.json`. Esto es
  para el mazo blanco (capturas de YouTube); el mazo real de PokerStars (4 colores,
  fondo de color + texto blanco) tiene su propia rama: `color_card_detector.py`
  (palo por color de fondo, sin plantilla) + `color_rank_ocr.py`, orquestados por
  `table_state.analyze_color_deck()`. `run_samples_pokerstars.py` corre esta rama
  contra `vision/samples_pokerstars/` y vuelca `vision/results_pokerstars.json`.
  PokerStars ofrece **dos** mazos de 4 colores y el usuario los cambia desde las
  opciones sin que la app se entere, así que hay un detector por cada uno y
  `table_state._cajas_de_carta()` elige solo, probando primero el nuevo:
  `glyph_card_detector.py` cubre el de **cara blanca con la tinta del color del
  palo** (♠ negro, ♥ rojo, ♣ verde, ♦ azul), donde el palo sale del color del
  glifo y no del fondo, y las cartas contiguas hay que separarlas por perfil de
  columnas porque sus caras blancas se funden en un solo contorno. Ese detector
  además marca `dimmed`: el cliente **apaga** tus cartas cuando ya no estás en la
  mano (cara V=255 → V=77), y el motor se abstiene ahí en vez de recomendar sobre
  una mano abandonada. `color_rank_ocr` lee el rango de los dos con el mismo voto
  y la misma detección del '10'; lo único que cambia es la polaridad de la tinta
  (`deck="solid"` / `deck="glyph"`).
  `hand_result.py` parsea el resultado de la última mano terminada de las líneas
  del chat (`parse_hand_result`: nº de mano, ganador(es), importe, mano ganadora y
  showdown; tolerante al ruido del OCR, no inventa). Cubre los **botes divididos**
  ("X empata por el bote", una línea por jugador con el mismo nº de mano →
  `split=True` y `winners` con todos), los **nicks cuyo guión bajo el OCR lee como
  espacio** ("david_sagunt" → "david sagunt": se admite un espacio interno y
  `_norm_name` normaliza para que ambas formas casen) y las **manos con coma**
  ("doble pareja, damas y sietes"). La frase de mano se busca sólo dentro del
  mismo mensaje del chat (hasta el siguiente "Repartidor:"/"Mano n.") en vez de
  en una ventana fija de caracteres, y las líneas se reordenan por posición
  visual antes de unirlas porque el modo `SPARSE_TEXT` de tesseract no las
  devuelve en orden de lectura y OCR-ea la zona del chat por
  su cuenta (`read_chat_lines`, reutilizando `seat_map` + `OcrBatch`, ya que
  `analyze_layout` lee el chat pero no lo expone en el GameState); `hero_outcome`
  decide si el hero ganó/perdió con la evidencia del chat. `test_hand_result.py`
  es un script suelto (sin pytest) que lo verifica con las líneas de chat reales
  más variantes con ruido de OCR. Lo consume el panel "Mano anterior" de `gui.py`.
- `decision/preflop/` — Fase 4.1: digitalización de rangos y tabla de lookup preflop.
  Ver `decision/preflop/parse_ranges.py` (genera `ranges.json` a partir de las capturas
  de ZEROSPOKER.COM en `/mnt/qnap/Poker/CAPTURAS HERRAMIENTAS PREFLOP/`). El OCR de la
  leyenda usa `tesserocr`, que necesita datos de idioma inglés instalados en el sistema
  (`sudo dnf install tesseract-langpack-eng` en Nobara) o, en su defecto, un
  `decision/preflop/tessdata/eng.traineddata` local (no versionado). `lookup.py`
  (`recommend(hero_cards, hero_position, stack_bb, facing, vs_position=None)`) consulta
  `ranges.json`: normaliza las cartas del hero a la notación del rango (orden de rango
  alto primero), busca el stack_bb más cercano entre las claves disponibles para ese
  `facing` y devuelve la etiqueta de acción tal cual salió de la leyenda, o `None` si
  falta algún dato. `test_lookup.py` es un script suelto (sin pytest, el proyecto no lo
  usa) que lo verifica contra casos leídos a mano de `ranges.json`.
- `decision/engine.py` — Fase 4 (primera pieza): dado el `GameState` de `vision/`, si es
  preflop y hay cartas+posición+stack, llama a `decision/preflop/lookup.py` y devuelve
  `{action, reasoning, hero_cards, hero_position, stack_bb}`. Si falta cualquier dato
  (hay board, no hay posición, no se lee el stack...) devuelve `None` y anota el motivo
  en `warnings`. **La app es BB-only**: el stack leído ya viene en big blinds, así que
  no hace falta ningún nivel de ciegas; `stack_unit` sobrevive como **guarda**, y todo
  `GameState` que no declare `"bb"` se rechaza (las rutas de diagnóstico producen fichas
  enteras, y leerlas como bb daría una recomendación convincente y falsa). Cuando sí
  recomienda pero sobre datos de fiabilidad reducida, lo **dice** en vez de callarlo: si
  la profundidad real cae fuera de la rejilla de esa tabla (p.ej. 100bb al principio de
  un torneo, que sale del gráfico de 40bb, el máximo digitalizado) marca la acción como
  extrapolada; si cae entre dos claves que sí existen, lo nombra como interpolación. Los
  avisos van a `warnings` y al `reasoning` que ve el usuario. Limitación conocida: el `GameState`
  no registra el historial de apuestas de la mano, así que el juicio de si el hero abre
  o responde a una subida se hace con lo que hay dibujado en ese frame (importes
  apostados por asiento), no con el historial real de la calle.
  `alpha.py` ya lo integra: imprime `Recomendacion: <accion>` bajo el resto del estado
  cuando hay recomendación.
- `decision/hand_strength.py` — evaluación de mano para el HUD (no es motor de decisión).
  `evaluate_hand(hero_cards, board)` devuelve (a) la **mano formada** (mejor combinación de 5,
  nombrada en español: "Pareja de Reyes", "Color de corazones", "Doble pareja (Ases y Reyes)"...;
  en preflop, "AK suited"/"Pareja de Ochos") y (b) la lista de **proyectos** (color 9 outs,
  escalera abierta 8, gutshot 4, sobrecartas, doble proyecto color+escalera con outs limpios
  sin solapar) con outs y % de **completar** el proyecto, tanto exacto (combinatoria) como por
  la regla del 2 y 4. **No** es equity contra el rango rival (eso exigiría Monte Carlo): es
  mano actual + probabilidad de ligar, etiquetado así en la UI para no engañar. Pure Python, sin
  dependencias nuevas. `test_hand_strength.py` es un script suelto (sin pytest) con casos a mano.
- `decision/hand_tracker.py` — estado **entre frames**: cuánto ha comprometido cada jugador,
  deducido de cómo le baja el stack (`comprometido = stack al empezar − stack actual`), en vez
  de intentar leer las fichas de la mesa. Lo lleva por mano **y por calle**, porque en el turn lo
  que un rival puso en el flop ya está en el bote. Es una **cota inferior** —si la mano ya había
  empezado cuando se le vio, la base ya está rebajada— así que la regla de uso es estricta: el
  comprometido **nunca crea** una subida, solo **atribuye** una que el botón "Igualar" ya ha
  demostrado. También repone el nick cuando el cliente lo tapa con el verbo de la acción, y solo
  dentro de la misma mano (en Zoom el asiento puede cambiar de dueño entre manos).
- `decision/action_log.py` — **qué** hizo cada uno y **en qué orden**, reconstruido de los verbos
  que el cliente pone en el nameplate (`Pasar`, `Igualar`, `Subir`). Complementa al rastreador:
  uno dice cuánto, el otro qué. Es lo único capaz de distinguir al que sube del que paga cuando
  los dos tienen el mismo importe puesto, que es exactamente el spot del squeeze. La lista se
  marca **siempre** como incompleta: el cartel dura menos que el periodo de muestreo.
- `decision/preflop/derive.py` — Fase E: capa **derivada** para spots que las tablas no cubren
  (la opción de la BB, frente a un limp, squeeze). Todo lo que responde sale de **otra celda real**
  del usuario; nunca se recalcula una etiqueta, porque el 94% de sus buckets no son contiguos en
  el orden de fuerza. Cada respuesta viaja con su procedencia (`source`, `confidence`, `donor`) y
  el HUD la pinta en **ámbar** para que no se confunda con una lectura de tabla.
- `vision/seat_watch.py` — vigilancia rápida: el lazo de captura va a 0,1 s y de cada frame solo
  comprueba, con un hash, si alguna cápsula de nameplate ha cambiado (0,8 ms para las seis). Solo
  entonces se paga un OCR, y solo el de esa cápsula. Existe porque el cartel de acción de un rival
  dura menos de 1,5 s, o sea menos que el ciclo de análisis completo. Incluye el buffer circular
  de frames, acotado.
- `decision/rag/postmano.py` — Fase 4.4: **estudio post-mano**. Al terminar la mano busca en las
  transcripciones los trozos que hablan de situaciones *parecidas*, con el vídeo y el minuto para
  poder comprobarlo. Lo acompaña `strategy_cards.py`, un catálogo de fichas de estudio con
  condiciones explícitas, principio, límites y fuente enlazada. Las fichas cubren multiway,
  iniciativa IP/OOP en SRP, defensa de ciegas/cold-call, roles principales de 3-bet, caller OOP
  de 4-bet, probe turn y bluff-catch river. No entran en `engine.decide` ni emiten una acción
  live. La consulta incorpora solo contexto observado: hero, board, mano formada,
  calle, posición IP/OOP cuando es inequívoca, iniciativa, tipo de bote, SPR y acciones
  capturadas por calle. El título/ruta del curso aporta metadatos verificables para no mezclar
  spots opuestos. Hay umbral de similitud y los resultados muestran extracto, score y enlace al
  vídeo. Un índice roto se muestra como avería, no como “sin coincidencias”, y no impide mostrar
  una ficha estructurada cuya condición sí se haya demostrado.
- `decision/postflop_math.py` — precio matemático de un call: `call / bote final`,
  además de stack efectivo y SPR del instante capturado. Nunca emite una acción. El bote
  mostrado por PokerStars ya incluye la apuesta rival (contrastado contra frames reales);
  las fórmulas y sus límites están documentados en el propio módulo. Desde la entrada de
  `decision/gto.py` acompaña el precio con `alpha`, `mdf`, `value_to_bluff` y
  `bet_pct_of_pot` del **mismo** tamaño.
- `decision/gto.py` — aritmética de equilibrio, sin cartas ni `GameState`: alpha
  (`riesgo/(riesgo+recompensa)`), MDF (`1-alpha`), fracción de farol y ratio valor:farol
  por tamaño (33%→4:1, 50%→3:1, 66%→2,5:1, 100%→2:1), alpha de una **subida** —que no es
  la misma cuenta que la de una apuesta— y EV de un farol. Convive con **los dos convenios
  de bote** (el de la literatura, sin la apuesta dentro; el de la pantalla, con ella) en
  funciones separadas y nombradas, porque confundirlos da un número plausible y
  equivocado. Fuente: <https://blog.gtowizard.com/mdf-alpha/>.
- `decision/board_texture.py` — textura del board por los tres ejes con los que están
  enunciadas las heurísticas: emparejamiento, conexión y palos, más la carta alta. La
  conexión se razona por **ventanas de escalera reales** y no por la distancia entre dos
  cartas: A y K están a distancia 1 y no son un proyecto abierto (JQKA solo se completa
  con el T). Devuelve `None` con un board ilegible en vez de una textura neutra.
- `decision/postflop_gto.py` — la guía postflop, y **la única pieza que propone una acción
  postflop**. Dos ramas: *defensa* (hay apuesta que igualar → precio, alpha, MDF, mezcla
  de equilibrio, y acción comparando con la equity estimada) y *c-bet* (el hero fue el
  agresor preflop y nadie ha apostado → banda de frecuencia y tamaño según textura). Lo
  deja en `state["gto"]`; el HUD lo pinta en un panel propio, en azul, para que no se
  confunda con lo que sale de las tablas digitalizadas del usuario. Distingue lo exacto
  (alpha y MDF salen del bote y la apuesta) de lo aproximado (las bandas traducen una
  ordenación cualitativa, no son frecuencias de solver) y de lo prestado (el ajuste
  multiway es propio; la fuente resuelve heads-up y en posición). Fuentes:
  <https://blog.gtowizard.com/flop-heuristics-ip-c-betting-in-cash-games/> y
  <https://blog.gtowizard.com/the-mechanics-of-c-bet-sizing/>.
- `decision/preflop/gto_baseline.py` — RFI de referencia a 100 BB para mesas de 6 y 9,
  usado **solo** por encima de 70 BB (el punto medio con la tabla digitalizada de 40) y
  solo donde no llega nada mejor: antes, una mesa de 9 a 100 BB recibía el rango de 40 BB
  estirado. Las etiquetas de posición se traducen por **cuánta gente queda detrás** y no
  por el nombre (el primero en hablar de una mesa de 6 es `MP2` aquí y `UTG` en el
  gráfico). Las posiciones que la fuente no publica no se interpolan. Fuente:
  <https://www.preflopwizard.app/blog/preflop-charts>.
- `decision/rag/` — Fase 4.2: transcripción de vídeos. El retrieval está construido y
  cableado al estudio post-mano (ver `postmano.py` arriba). `video_index.py` localiza y ordena los vídeos de
  `TORNEOS/6. EL CURSO ABSOLUTO...` y `TORNEOS/5. CONTENIDO DE TEORÍA POSTFLOP...`
  (las dos carpetas prioritarias). `extract_audio.py` saca el audio a WAV mono 16kHz
  con ffmpeg. `transcribe.py` transcribe con `faster-whisper` (modelo `small`, CPU,
  int8 — ver docstring para la comparativa con `medium`). `chunk.py` agrupa las frases
  de Whisper en fragmentos de ~60s. `pipeline.py` encadena los tres pasos por vídeo y
  escribe `decision/rag/transcripts/<video_id>.json` (lista de
  `{video, video_path, chunk_index, start_time, end_time, text}`) más
  `decision/rag/transcripts/_benchmark.json` con el tiempo/tamaño real de cada vídeo
  procesado, usado para extrapolar el coste del corpus completo. El audio intermedio
  (`decision/rag/audio/*.wav`) no se versiona (grande y reproducible desde el vídeo
  fuente); los JSON de `transcripts/` sí, por ser el producto final y pesar poco.
  `run_batch.py` reparte los 126 vídeos prioritarios en N procesos `pipeline.py` en
  paralelo para bajar el tiempo de reloj (cada proceso ya usa varios núcleos, pero no
  todos). `build_index.py` calcula los embeddings de los 5.142 chunks estratégicos y `query.py` los
  consulta por similitud coseno; se usan **solo** desde `postmano.py`, después de la mano.
- `hud/` — Fase 5: panel de salida con la recomendación.
- `packaging/` — Fase 6: manifest Flatpak (pendiente hasta tener un core funcional).
- `tests/` — Fase 7: capturas de referencia y tests de regresión.
