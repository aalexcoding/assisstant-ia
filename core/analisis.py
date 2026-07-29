"""
EL NUCLEO DE LA APP: un ciclo de analisis de un frame de la mesa.

Esto es lo que la aplicacion HACE. Antes vivia dentro de
gui.AnalysisWorker._analyze_and_publish, o sea dentro de un metodo de un hilo de
GTK que terminaba en GLib.idle_add, y eso tenia dos consecuencias:

  - no se podia ejecutar un ciclo sin abrir una ventana y sin el portal de
    captura, asi que no habia forma de comprobarlo contra los frames grabados;
  - la GUI era duenya de la logica, y quien quisiera el mismo analisis fuera
    (alpha.py, un replay, un test) tenia que repetir la secuencia a mano y
    arriesgarse a que se desincronizara.

Aqui no hay GTK, ni portal, ni hilos. Se le da un frame y devuelve un Analisis.

EL ORDEN DE LAS LLAMADAS ES SIGNIFICATIVO y se conserva tal cual estaba:

    analyze_layout -> parse_hand_result -> tracker.update -> hand_tracker.aplicar
    -> action_log -> engine.decide -> evaluate_hand -> postflop_equity

El chat se parsea ANTES del rastreador a proposito: el numero de mano que sale
del chat es la señal de frontera mas fiable que hay, y el rastreador la
necesita para saber si esta mirando una mano nueva. Y el rastreador va antes del
motor porque decide() usa lo que cada rival lleva comprometido.

ESTADO ENTRE FRAMES. Un Analizador no es una funcion suelta porque el analisis
no lo es: la referencia del tapete, la plantilla del boton y la escala del
glifo se aprenden de los primeros frames y se reutilizan, y el rastreador y el
registro de acciones son memoria de la mano en curso. Crear un Analizador nuevo
equivale a empezar de cero, que es justo lo que pasa al parar y volver a
iniciar el analisis.

LOS FALLOS NO SE PROPAGAN, igual que antes: el resumen de la mano anterior, el
rastreador y la equity van cada uno en su try. Un OCR que devuelve basura o un
chat ilegible degradan el resultado de ese frame, no tumban el ciclo.
"""
import os
import time
from dataclasses import dataclass, field

import cv2

from decision import action_log as alog
from decision import engine
from decision import hand_strength as hstr
from decision import hand_tracker
from vision import hand_result as hr
from vision import rango_directo
from vision import seat_map
from vision import seat_watch as sw
from vision import table_state as ts
from vision.ocr_client import OcrBatch
from vision.text_extract import parse_tsv_lines

# Cada cuanto se captura para VIGILAR (no para analizar). Ver vision/seat_watch.py:
# el cartel de accion de un rival dura menos de 1,5 s, asi que a un periodo
# parecido al del analisis se pierden acciones.
VIGILANCIA_PERIODO_S = 0.1

# Tope de seguridad: no se lanza un OCR de vigilancia mas a menudo que esto, pase
# lo que pase, para que un frame muy movido no encadene OCRs y se coma la maquina
# (el sintoma de lag que ya se arreglo una vez).
#
# Con los workers de OCR PERSISTENTES el coste de mirar una capsula bajo de ~250 ms
# a 39 ms -el suelo era arrancar el proceso y cargar tesseract, no el trabajo-,
# asi que el tope puede ser mucho mas bajo que antes: a 0,12 s caben ~8 miradas
# por segundo, mas que suficiente para no perderse un cartel que dura mas de 0,5 s,
# y aun asi el vigilante se queda muy por debajo de un nucleo.
VIGILANCIA_OCR_MIN_S = 0.12

# Cada cuanto se lee el CHAT como muy tarde, aunque el rastreador no haya visto
# ninguna frontera de mano.
#
# El chat es el job de OCR mas caro del frame: medido, 281 ms de un ciclo de 875,
# o sea el 32%. Y lo unico que se saca de ahi -quien gano la mano anterior y su
# numero- cambia UNA VEZ POR MANO. Leerlo en cada frame era pagar el 32% del
# ciclo por un dato que no se mueve.
#
# Esto es el guardarrail, no la regla: lo normal es que se lea al cerrarse una
# mano. Existe por si el detector de frontera enmudece -una mesa parada, un
# tapete que deja de reconocerse- para que el panel no se quede congelado sin
# que nadie se entere. Una mano tipica dura 21-45 frames de mediana, asi que 30 s
# deja pasar varias manos antes de forzar una lectura: es un suelo, no un ritmo.
CHAT_MAX_S = 30.0

# --- el LATIDO, que se mide en vez de elegirse ------------------------------
#
# El analisis se dispara por SUCESOS (que te toque a ti, que se vea el disco).
# El latido es el suelo: lo que cubre lo que el lazo rapido no ve -que crezca el
# board, que acabe la mano- y lo que garantiza que el HUD no se congele si el
# detector de turno se equivoca.
#
# HASTA AHORA LO ELEGIA EL USUARIO EN LA VENTANA, con un spin de 0,25 a 10 s, y
# ese numero no describia nada:
#
#   - 8 de sus 40 valores son fisicamente imposibles: el ciclo tarda 0,72 s de
#     mediana, asi que pedir 0,25 s no acelera nada, solo hace que el latido
#     venza siempre y el analisis encadene sin parar.
#   - el periodo real nunca fue el elegido, porque se cuenta desde que TERMINA
#     el analisis: pidiendo 1,0 s la app analizaba cada 1,6-1,9 s.
#   - y el repo decia tres cosas distintas del ciclo -"2-4 s" en el README,
#     "0,7 s" en gui.py, "~950 ms" en seat_watch.py-, ninguna medida.
#
# Ahora se mide en caliente y se enseña. El ciclo depende del tamaño de ventana,
# del tema de mesa, del mazo y de que mas este haciendo la maquina, asi que un
# numero guardado en disco se quedaria viejo EXACTAMENTE IGUAL que esos tres.
#
#     latido = max(PERIODO_MIN_S, p95_del_ciclo + TICKS_MIN * VIGILANCIA_PERIODO_S)
#
# P95 Y NO P50 porque el suelo natural es el propio ciclo: con un p50, la mitad
# de los analisis no cabe en su hueco y el lazo rapido se queda sin correr.
# Medido sobre las 6 sesiones grabadas (8.908 frames), el ciclo va de 0,717 s de
# mediana a 1,076 de p95, y el cociente p95/p50 va de 1,4 a 2,1 segun sesion: esa
# dispersion es justo lo que un p50 se comeria.
#
# TICKS_MIN_ENTRE_ANALISIS ES PROVISIONAL y esta escrito para que se note. El
# plan dice medirlo barriendo el hueco y cogiendo la rodilla de acciones_por_mano,
# y ese barrido necesita ticks de verdad: tick() solo lo llama gui.py, asi que en
# frio no hay nada que barrer. 5 ticks son 0,5 s de vigilancia entre analisis,
# que es el orden de lo que ya se observaba (1,36 capturas rapidas por analisis
# antes de arreglar el conteo, ~5 despues).
PERIODO_MIN_S = 0.5
TICKS_MIN_ENTRE_ANALISIS = 5
RITMO_MUESTRAS = 30      # ciclos recientes con los que se estima el p95


class Ritmo:
    """Mide el ciclo y dice cada cuanto conviene latir.

    Se queda con los ultimos RITMO_MUESTRAS ciclos y no con todos: si la ventana
    cambia de tamaño o el cliente se pone a tirar animaciones, el ritmo tiene que
    seguirlo, y una media de toda la sesion tardaria en enterarse."""

    def __init__(self, fijo=None):
        self._muestras = []
        self._fijo = fijo          # --interval, para reproducir una cadencia vieja
        self.total = 0

    def anota(self, duracion_s):
        if not isinstance(duracion_s, (int, float)) or duracion_s <= 0:
            return
        self.total += 1
        self._muestras.append(float(duracion_s))
        if len(self._muestras) > RITMO_MUESTRAS:
            del self._muestras[0]

    def _p(self, q):
        if not self._muestras:
            return None
        v = sorted(self._muestras)
        return v[min(len(v) - 1, int(q * len(v)))]

    @property
    def periodo_s(self):
        """El latido. Mientras no haya medidas se usa PERIODO_MIN_S, que es el
        suelo: arrancar latiendo rapido no hace daño porque los primeros ciclos
        son justo los que hay que medir."""
        if self._fijo:
            return self._fijo
        p95 = self._p(0.95)
        if p95 is None:
            return PERIODO_MIN_S
        return max(PERIODO_MIN_S,
                   p95 + TICKS_MIN_ENTRE_ANALISIS * VIGILANCIA_PERIODO_S)

    def a_dict(self):
        return {"ciclo_p50_s": self._p(0.50), "ciclo_p95_s": self._p(0.95),
                "periodo_s": self.periodo_s, "muestras": len(self._muestras),
                "fijo": self._fijo}

    def etiqueta(self):
        """Lo que se pinta en la ventana, en vez del selector que habia."""
        p50, p95 = self._p(0.50), self._p(0.95)
        if p50 is None:
            return "Ritmo: midiendo..."
        fijo = " (latido fijo)" if self._fijo else ""
        return (f"Ritmo: {p50:.2f} s/analisis (p95 {p95:.2f}) · "
                f"latido {self.periodo_s:.1f} s · "
                f"vigilancia {1 / VIGILANCIA_PERIODO_S:.0f} Hz{fijo}")

# Frames del arranque en los que SI se lee el chat, para que el panel "Mano
# anterior" no salga vacio mientras se juega la primera mano.
CHAT_FRAMES_INICIALES = 3


@dataclass
class Analisis:
    """Todo lo que la app calculo de UN frame.

    Es la unidad que se enseña en el HUD y la que se graba en modo testing, y por
    eso a_dict() produce exactamente la forma que ya tienen los JSON de
    testing/sesion-*/NNNN.json: cambiarla invalidaria las sesiones grabadas."""
    state: dict
    recommendation: dict | None = None
    hand: dict | None = None
    equity: dict | None = None
    hand_result: dict | None = None
    duracion_analisis_s: float = 0.0

    def a_dict(self):
        return {"duracion_analisis_s": self.duracion_analisis_s,
                "state": self.state, "recommendation": self.recommendation,
                "hand": self.hand, "equity": self.equity,
                "hand_result": self.hand_result}


@dataclass
class Vigilancia:
    """Contadores del lazo rapido. Van dentro del state para poder juzgar despues
    si la vigilancia estuvo haciendo su trabajo en esa sesion."""
    ticks: int = 0          # capturas rapidas hechas
    capsulas_ocr: int = 0   # capsulas OCR-eadas por el vigilante
    saltadas: int = 0       # veces que el tope de seguridad freno un OCR

    def a_dict(self):
        return {"ticks": self.ticks, "capsulas_ocr": self.capsulas_ocr,
                "saltadas": self.saltadas, "periodo_s": VIGILANCIA_PERIODO_S}


@dataclass
class Analizador:
    """Un ciclo de analisis, con la memoria que ese ciclo necesita.

    max_players: cuantos jugadores caben en la mesa (3 en un 3-Max, 6 en un
        6-Max...). Opcional pero MUY recomendable: las posiciones se derivan del
        RECUENTO de asientos ocupados y un asiento fantasma las desplaza todas.
    seed_equity: semilla del Monte Carlo. None en produccion (cada frame es una
        simulacion distinta, que es lo correcto); fija en los tests, porque sin
        ella la misma entrada da un numero distinto cada vez.
    tmp_frame: donde se vuelca el recorte cuando se pasa un array, porque
        table_state.analyze_layout trabaja sobre una RUTA. Pasandole una ruta
        directamente -lo que hace el replay- este fichero no se toca.
    """
    max_players: int | None = None
    # MAZO de cartas configurado en el cliente: "glyph" (cara blanca, rango
    # de color), "solid" (fondo de color, rango blanco) o None para que
    # compitan los dos detectores, que es lo que se hacia siempre.
    mazo: str | None = None
    seed_equity: int | None = None
    tmp_frame: str = "/tmp/poker_frame_analisis.png"

    # --- memoria de vision: se aprende de los primeros frames y se reutiliza ---
    # El disco del dealer recortado de ESTA mesa, para encontrarlo cuando el color
    # y la forma no llegan. Vive en la sesion: guardarlo en disco se quedaria viejo
    # el dia que cambie el tema de mesa. Ver seat_map.PlantillaBoton.
    plantilla_boton: seat_map.PlantillaBoton = field(default_factory=seat_map.PlantillaBoton)
    # El ovalo del tapete no se mueve mientras juegas: se fija con las primeras
    # lecturas buenas y se reutiliza. Ver seat_map.ReferenciaFijada.
    referencia: seat_map.ReferenciaFijada = field(default_factory=seat_map.ReferenciaFijada)
    # El tamaño del numero de las cartas tampoco cambia mientras no cambie la
    # ventana: se busca con los primeros frames y se fija, en vez de barrer 21
    # escalas en cada uno. Ver rango_directo.EscalaGlifo.
    escala_glifo: rango_directo.EscalaGlifo = field(default_factory=rango_directo.EscalaGlifo)

    # --- memoria de decision: es de la mano en curso ---------------------------
    tracker: hand_tracker.HandTracker = field(default_factory=hand_tracker.HandTracker)
    action_log: alog.ActionLog = field(default_factory=alog.ActionLog)

    # --- lazo rapido ----------------------------------------------------------
    watch: sw.SeatWatch = field(default_factory=sw.SeatWatch)
    # LA DISPOSICION DE LA MESA (6 u 8 plazas), derivada de max_players en
    # __post_init__. Se guarda en el Analizador y no en un global de seat_map
    # PORQUE HAY VARIOS A LA VEZ: la regresion de oro crea uno por sesion en el
    # mismo proceso, asi que con un global una sesion de 8 contaminaria a la
    # siguiente de 6 y el fallo saldria como una regresion fantasma.
    seats: dict = field(init=False, default=None)

    def __post_init__(self):
        self.seats = seat_map.disposicion(self.max_players)
        # el vigilante mira las mismas capsulas que el analisis, o se dedicaria a
        # hashear tapete vacio mientras los asientos de verdad pasan sin mirar
        self.watch = sw.SeatWatch(self.seats)
    # NO HAY FrameBuffer, y es una retirada deliberada. Existia un anillo de 10
    # frames que se llenaba en cada tick (0,23 ms de copia, 47 MB retenidos) y que
    # NADIE LEIA en produccion: su unico proposito declarado -mirar hacia atras
    # cuando la frontera de mano se detecta tarde- nunca se llego a cablear.
    # Guardar por si acaso no es una funcionalidad. Vuelve el dia que haya un
    # consumidor concreto, y entonces se medira lo que aporta.
    vigilancia: Vigilancia = field(default_factory=Vigilancia)

    _mano_vista: int | None = None
    _ref: tuple | None = None       # referencia del tapete del ultimo analisis
    _ultimo_ocr: float = 0.0
    # ¿habia botones en la ultima mirada rapida? Sirve para detectar el FLANCO
    # (empieza el turno del hero), que es lo que dispara el analisis completo.
    _turno: bool = False

    # --- lectura espaciada del chat (ver CHAT_MAX_S) ---------------------------
    # Empieza en True: el primer frame lo lee, para no arrancar con el panel en
    # blanco. Lo vuelve a poner a True el cierre de una mano.
    _leer_chat: bool = True
    _frames_analizados: int = 0
    _ultimo_chat: float = 0.0
    # El ultimo resumen de mano leido, que se devuelve en TODOS los frames aunque
    # ese frame no haya mirado el chat. Si no, el panel "Mano anterior" se
    # vaciaria entre lecturas y parpadearia una vez por mano en vez de
    # actualizarse: peor que antes, y por una optimizacion.
    _ultimo_resultado: dict | None = None

    # ------------------------------------------------------------------ analisis
    def analizar(self, frame):
        """Un ciclo completo. `frame` es un array BGR o la ruta de una imagen.

        Devuelve un Analisis. No lanza salvo que falle analyze_layout: lo demas
        (chat, rastreador, equity) esta acotado, porque cada uno es una capa de
        informacion adicional y perder una no justifica perder el frame."""
        t0 = time.perf_counter()
        ruta, bgr = self._como_ruta_y_array(frame)

        # ¿toca leer el chat en este frame? Ver CHAT_MAX_S: es el job mas caro
        # (32% del ciclo) y lo que se saca de el cambia una vez por mano.
        ahora = time.monotonic()
        leer_chat = (self._leer_chat
                     or self._frames_analizados < CHAT_FRAMES_INICIALES
                     or ahora - self._ultimo_chat >= CHAT_MAX_S)
        self._frames_analizados += 1

        # los asientos estables de la mano en curso se realimentan al
        # reconocimiento: ver table_state.analyze_layout
        state = ts.analyze_layout(ruta, max_players=self.max_players,
                                  mazo=self.mazo,
                                  asientos_estables=self.tracker.asientos_estables(),
                                  plantilla_boton=self.plantilla_boton,
                                  referencia=self.referencia,
                                  escala_glifo=self.escala_glifo,
                                  leer_chat=leer_chat)
        if leer_chat:
            self._leer_chat = False
            self._ultimo_chat = ahora

        # La referencia del tapete se guarda para el lazo rapido, que no puede
        # permitirse recalcularla (17 ms medidos) diez veces por segundo.
        #
        # SE TOMA LA FIJADA, no una lectura propia, y son dos arreglos en uno:
        #
        #   1. Antes se llamaba a find_reference AQUI ademas de dentro de
        #      referencia.de(), o sea DOS VECES POR FRAME. 17 ms tirados.
        #   2. Y lo importante: las dos no daban lo mismo. analyze_layout usa la
        #      referencia FIJADA (mediana de las primeras lecturas buenas) y esto
        #      usaba la CRUDA de este frame, asi que el lazo rapido hasheaba y
        #      OCR-eaba cajas distintas de las que el lento juzgaba. Los dos
        #      lazos tienen que mirar lo mismo o el nombre que lee uno no es del
        #      asiento que cuenta el otro.
        #
        # Mientras no haya suficientes lecturas buenas, `fijada` es None y el
        # lazo rapido no mira nada: es lo correcto, porque sin referencia fiable
        # las zonas estan desplazadas.
        fijada = self.referencia.fijada if self.referencia is not None else None
        self._ref = (tuple(fijada) + (False,)) if fijada is not None else None

        # resumen de la mano anterior. Se parsean las lineas de chat que
        # analyze_layout YA ha OCR-eado: antes esto hacia una segunda pasada de
        # OCR sobre la misma zona, con otro subproceso y otro arranque de
        # tesseract, y costaba 571 ms de un ciclo de 3,9 s. Un fallo aqui no debe
        # tumbar el analisis principal.
        # Solo se vuelve a parsear cuando este frame ha mirado el chat; el resto
        # conserva el ultimo resumen. Un frame sin lectura NO significa "no hay
        # mano anterior", significa "no se ha vuelto a mirar", y son cosas
        # distintas: tratarlas igual dejaria el panel en blanco entre manos.
        if leer_chat:
            try:
                nuevo = hr.parse_hand_result(state.get("chat_lines"))
            except Exception:  # noqa: BLE001
                nuevo = None
            if nuevo:
                self._ultimo_resultado = nuevo
        resultado = self._ultimo_resultado

        # ANTES de decidir: cuanto lleva puesto cada asiento, deducido de su
        # bajada de stack. El numero de mano del chat es la señal de frontera mas
        # fiable que hay, de ahi que el chat se parsee primero.
        try:
            info = self.tracker.update(state, (resultado or {}).get("hand_number"))
            hand_tracker.aplicar(state, info)
            if info["mano"] != self._mano_vista:
                self._mano_vista = info["mano"]
                self.action_log.nueva_mano()
                # SE PIDE EL CHAT PARA EL FRAME SIGUIENTE, no para este. La
                # frontera se detecta AQUI, cuando analyze_layout ya ha corrido,
                # asi que este frame ya no puede leerlo. Y da igual: la linea
                # "X gana el bote" tarda en aparecer, o sea que leerla un frame
                # despues es incluso mejor que leerla en el mismo.
                self._leer_chat = True
                # RE-CENSO. Entre manos cambia quien esta sentado: en Zoom el
                # cliente te cambia de mesa, asi que el ocupante de un asiento
                # puede ser OTRA PERSONA con la capsula igual de oscura. El
                # vigilante rapido solo mira lo que cambia de un frame al
                # siguiente, y eso no lo ve; hay que pedirle expresamente que
                # vuelva a leer los seis. Ver SeatWatch.re_censar (y por que
                # olvidar() haria justo lo contrario).
                self.watch.re_censar()
            self.action_log.observar_estado(state, t=time.time())
            state["acciones"] = self.action_log.acciones()
            state["vigilancia"] = self.vigilancia.a_dict()
        except Exception:  # noqa: BLE001
            pass

        recommendation = engine.decide(state)
        hand = hstr.evaluate_hand(state.get("hero_cards"), state.get("board"))
        equity = self._equity_de(state)

        return Analisis(state=state, recommendation=recommendation, hand=hand,
                        equity=equity, hand_result=resultado,
                        duracion_analisis_s=round(time.perf_counter() - t0, 3))

    def _como_ruta_y_array(self, frame):
        """analyze_layout quiere una RUTA y find_reference quiere un ARRAY, asi
        que hace falta tener los dos. Con una ruta de entrada -el replay- no se
        vuelve a codificar el PNG."""
        if isinstance(frame, (str, os.PathLike)):
            bgr = cv2.imread(str(frame))
            if bgr is None:
                raise ValueError(f"no se pudo leer la imagen: {frame}")
            return str(frame), bgr
        cv2.imwrite(self.tmp_frame, frame)
        return self.tmp_frame, frame

    def _equity_de(self, state):
        """Equity postflop del frame, o None. Una sola implementacion, la del
        motor; un fallo aqui no puede tumbar el analisis."""
        try:
            return engine.postflop_equity(state, seed=self.seed_equity)
        except Exception:  # noqa: BLE001
            return None

    # ----------------------------------------------------------------- vigilancia
    def vigilar(self, crop):
        """Paso rapido: mira si alguna capsula de nameplate ha cambiado y, solo
        entonces, la OCR-ea para quedarse con el verbo de la accion.

        Vive aqui y no en la GUI porque escribe en action_log, que es memoria de
        la mano: partirlo dejaria dos duenyos del mismo estado.

        Usa la referencia del tapete del ULTIMO ANALISIS COMPLETO en vez de
        recalcularla: find_reference cuesta 29 ms, que a 10 Hz serian 29% de un
        nucleo por mirar algo que no se mueve."""
        ref = self._ref
        if ref is None:
            return
        try:
            cambiados = self.watch.cambios(crop, ref)
        except Exception:  # noqa: BLE001
            return
        if not cambiados:
            return
        ahora = time.monotonic()
        if ahora - self._ultimo_ocr < VIGILANCIA_OCR_MIN_S:
            self.vigilancia.saltadas += 1
            return                     # ver VIGILANCIA_OCR_MIN_S
        self._ultimo_ocr = ahora
        try:
            batch = OcrBatch()
            idx = {}
            for seat in cambiados:
                x0, y0, x1, y1 = seat_map.zone_to_px(ref, self.seats[seat]["plate"],
                                                     crop.shape)
                idx[seat] = batch.add_tsv_job(crop[y0:y1, x0:x1], scale=3)
            res = batch.run()
            self.vigilancia.capsulas_ocr += len(cambiados)
            for seat, i in idx.items():
                lineas = parse_tsv_lines(res[i])
                nombre, _s, accion = ts._seat_plate_name_stack(lineas)
                if accion:
                    self.action_log.observar(seat, accion, t=time.time())
                # EL NOMBRE SALE GRATIS y hasta ahora se tiraba: esta lectura ya
                # esta hecha y pagada, se hacia solo por el verbo. El rapido mira
                # las capsulas 1,6 veces mas que el lento y justo cuando cambian,
                # que es el instante en que el verbo se va y el nick vuelve.
                #
                # Va al voto de NOMBRE y a ningun otro sitio: ver
                # HandTracker.observar_nombre, donde esta escrito por que tocar el
                # voto de ocupacion desde aqui degeneraria la mayoria en la union
                # (72,5% de acierto contra 89,2%).
                #
                # _seat_plate_name_stack ya devuelve el verbo APARTE, asi que lo
                # que llega como nombre no puede ser un "Igualar" ni un "Pasar".
                if nombre:
                    self.tracker.observar_nombre(seat, nombre)
        except Exception:  # noqa: BLE001
            pass                       # vigilar es una ayuda, nunca tumba el lazo

    def tick(self, crop):
        """Un frame del lazo rapido. Devuelve el MOTIVO por el que conviene hacer
        un analisis completo ahora, o None si no hay ninguno.

        Quien lleva el lazo (gui.py) decide si obedece, pero la POLITICA vive
        aqui, que es donde esta el estado entre frames. Es lo mismo que se hizo
        con la lectura del chat: vision/ mira, core/ decide cuando.

        EL DISPARO POR TURNO es la idea del usuario, y le da la vuelta al diseño:
        en vez de analizar cada N segundos por si acaso, se analiza CUANDO PASA
        ALGO. Y lo que pasa, para una app que recomienda, es que te toque a ti.

        Por que importa tanto: los botones de accion solo estan en pantalla en el
        turno del hero, y de ellos salen `facing` y `to_call`, que es lo que
        distingue "abro el bote" de "defiendo una subida". Medido sobre 1.011
        frames, el hero tiene botones en 216 y la app hoy solo lee `facing` en 89:
        se pierde el 59% de sus propios turnos, y decide a ciegas en ellos. Con el
        disparo por turno, el analisis cae SIEMPRE con los botones delante."""
        self.vigilancia.ticks += 1
        self.vigilar(crop)

        # sin referencia de confianza no se mira nada: la zona de botones caeria
        # desplazada y el detector diria cualquier cosa (ver ReferenciaFijada.de)
        if self._ref is None:
            return None
        try:
            turno = seat_map.hay_botones(crop, self._ref)
        except Exception:  # noqa: BLE001
            return None
        anterior, self._turno = self._turno, turno
        # EL FLANCO, no el estado. Mientras dure el turno los botones siguen ahi,
        # y re-analizar cada 0,1 s seria peor que lo de ahora: lo que interesa es
        # el INSTANTE en que aparecen.
        return "turno" if turno and not anterior else None
