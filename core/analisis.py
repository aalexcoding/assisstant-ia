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
    buffer: sw.FrameBuffer = field(default_factory=sw.FrameBuffer)
    vigilancia: Vigilancia = field(default_factory=Vigilancia)

    _mano_vista: int | None = None
    _ref: tuple | None = None       # referencia del tapete del ultimo analisis
    _ultimo_ocr: float = 0.0

    # ------------------------------------------------------------------ analisis
    def analizar(self, frame):
        """Un ciclo completo. `frame` es un array BGR o la ruta de una imagen.

        Devuelve un Analisis. No lanza salvo que falle analyze_layout: lo demas
        (chat, rastreador, equity) esta acotado, porque cada uno es una capa de
        informacion adicional y perder una no justifica perder el frame."""
        t0 = time.perf_counter()
        ruta, bgr = self._como_ruta_y_array(frame)

        # los asientos estables de la mano en curso se realimentan al
        # reconocimiento: ver table_state.analyze_layout
        state = ts.analyze_layout(ruta, max_players=self.max_players,
                                  asientos_estables=self.tracker.asientos_estables(),
                                  plantilla_boton=self.plantilla_boton,
                                  referencia=self.referencia,
                                  escala_glifo=self.escala_glifo)

        # la referencia del tapete se guarda para el lazo rapido, que no puede
        # permitirse recalcularla (29 ms) diez veces por segundo
        try:
            ref = seat_map.find_reference(bgr)
            self._ref = None if ref[4] else ref
        except Exception:  # noqa: BLE001
            self._ref = None

        # resumen de la mano anterior. Se parsean las lineas de chat que
        # analyze_layout YA ha OCR-eado: antes esto hacia una segunda pasada de
        # OCR sobre la misma zona, con otro subproceso y otro arranque de
        # tesseract, y costaba 571 ms de un ciclo de 3,9 s. Un fallo aqui no debe
        # tumbar el analisis principal.
        try:
            resultado = hr.parse_hand_result(state.get("chat_lines"))
        except Exception:  # noqa: BLE001
            resultado = None

        # ANTES de decidir: cuanto lleva puesto cada asiento, deducido de su
        # bajada de stack. El numero de mano del chat es la señal de frontera mas
        # fiable que hay, de ahi que el chat se parsee primero.
        try:
            info = self.tracker.update(state, (resultado or {}).get("hand_number"))
            hand_tracker.aplicar(state, info)
            if info["mano"] != self._mano_vista:
                self._mano_vista = info["mano"]
                self.action_log.nueva_mano()
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
                x0, y0, x1, y1 = seat_map.zone_to_px(ref, seat_map.SEATS[seat]["plate"],
                                                     crop.shape)
                idx[seat] = batch.add_tsv_job(crop[y0:y1, x0:x1], scale=3)
            res = batch.run()
            self.vigilancia.capsulas_ocr += len(cambiados)
            for seat, i in idx.items():
                lineas = parse_tsv_lines(res[i])
                _n, _s, accion = ts._seat_plate_name_stack(lineas)
                if accion:
                    self.action_log.observar(seat, accion, t=time.time())
        except Exception:  # noqa: BLE001
            pass                       # vigilar es una ayuda, nunca tumba el lazo

    def tick(self, crop):
        """Un frame del lazo rapido: al buffer, y a vigilar."""
        self.vigilancia.ticks += 1
        self.buffer.añadir(crop, t=time.time())
        self.vigilar(crop)
