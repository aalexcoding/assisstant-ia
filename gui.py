"""
Fase 5: panel de control GTK4. Envuelve el mismo flujo que alpha.py (captura
via portal_capture, recorte al recuadro de calibration/config.local.json,
table_state.analyze_layout -> GameState, engine.decide -> recomendacion) pero
en una ventana no bloqueante: la UI corre en el hilo principal (GLib main
loop) y el analisis (captura + OCR, ~1-2s por frame) corre en un hilo aparte
que actualiza los widgets via GLib.idle_add (GTK no es thread-safe).

Todos los importes se leen en BIG BLINDS: hay que configurar PokerStars para
mostrarlos asi. Si no lo esta, no se leen y la app se abstiene en vez de
adivinar (ver el bloque "LA APP ES BB-ONLY" de vision/table_state.py). Por eso
ya no hay panel de ciegas: con los stacks en bb, el nivel no hace falta.
"Recalibrar recuadro" lanza calibration/select_region.py como subproceso y
recarga el recuadro al volver.

Uso: .venv/bin/python gui.py [--interval SEGUNDOS] [--self-test]
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "capture"))
sys.path.insert(0, os.path.join(BASE_DIR, "vision"))
sys.path.insert(0, os.path.join(BASE_DIR, "decision"))
sys.path.insert(0, os.path.join(BASE_DIR, "decision", "preflop"))
sys.path.insert(0, os.path.join(BASE_DIR, "decision", "rag"))

import cv2

import engine
import hand_result as hr
import hand_strength as hstr
import action_log as alog
import hand_tracker
import postmano
from ocr_client import OcrBatch, cerrar_workers
from text_extract import parse_tsv_lines
import portal_capture as pc
import seat_map
import seat_watch as sw
import table_state as ts

import testing_session as ts_session

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk, Pango

CALIBRATION_PATH = os.path.join(BASE_DIR, "calibration", "config.local.json")
SELECT_REGION_PATH = os.path.join(BASE_DIR, "calibration", "select_region.py")
TMP_FRAME_PATH = "/tmp/poker_gui_frame.png"

# Cada cuanto se captura para VIGILAR (no para analizar). Ver seat_watch.py: el
# cartel de accion de un rival dura menos de 1,5 s, asi que a un periodo parecido
# al del analisis se pierden acciones.
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

SUIT_SYMBOLS = {"h": "♥", "d": "♦", "c": "♣", "s": "♠"}
SUIT_COLORS = {"h": "#e74c3c", "d": "#3498db", "c": "#2ecc71", "s": "#95a5a6"}


def load_region():
    with open(CALIBRATION_PATH) as f:
        region = json.load(f)["capture_region"]
    return region["x"], region["y"], region["width"], region["height"]


def _card_span(code):
    if not code or len(code) < 2:
        return GLib.markup_escape_text(str(code))
    rank, suit = code[:-1], code[-1].lower()
    color = SUIT_COLORS.get(suit, "#cccccc")
    symbol = SUIT_SYMBOLS.get(suit, suit)
    return f'<span foreground="{color}" weight="bold">{GLib.markup_escape_text(rank)}{symbol}</span>'


def cards_markup(codes):
    if not codes:
        return "<i>-</i>"
    return "  ".join(_card_span(c) for c in codes)


def players_markup(players):
    if not players:
        return "<i>sin jugadores detectados</i>"
    lines = []
    for p in players:
        # el nick puede venir REPUESTO por el rastreador: el cliente lo tapa con
        # el verbo de la accion justo cuando ese jugador actua (ver
        # table_state.es_verbo_de_accion). Lo que hizo se muestra aparte.
        name = p["name"] if p.get("name") else "(?)"
        pos = f" [{p['position']}]" if p.get("position") else ""
        # con unidad: los importes son big blinds, y verlo evita confundir un
        # stack de 44,5 BB con 44,5 fichas de un vistazo
        stack = f"{p['stack']:g} BB" if p.get("stack") is not None else "?"
        mark = "  <b>(TU)</b>" if p.get("is_hero") else ""
        # lo que lleva puesto en la mano, deducido de como le ha bajado el stack
        # entre frames (ver decision/hand_tracker.py). Es una COTA INFERIOR, de
        # ahi el "≥": si la mano ya habia empezado cuando se le vio por primera
        # vez, se pierde lo que puso antes. Se marca en verde cuando el importe
        # dibujado en la mesa dice lo mismo, que es la corroboracion.
        puesto = ""
        com = p.get("committed")
        if isinstance(com, (int, float)) and com > 0:
            color = "#2ecc71" if p.get("committed_acuerdo") == "coinciden" else "#95a5a6"
            puesto = f'  <span foreground="{color}">(≥{com:g} BB puestos)</span>'
        accion = ""
        if p.get("action"):
            accion = (f'  <span foreground="#f39c12">'
                      f'{GLib.markup_escape_text(str(p["action"]))}</span>')
        lines.append(f"{GLib.markup_escape_text(str(name))}{GLib.markup_escape_text(pos)}: "
                     f"{GLib.markup_escape_text(str(stack))}{mark}{puesto}{accion}")
    return "\n".join(lines)


class AnalysisWorker(threading.Thread):
    """Hilo de analisis: abre el stream, lee frames, recorta, analiza y
    manda cada resultado a la ventana via GLib.idle_add. No toca widgets."""

    def __init__(self, win, interval, sesion=None, max_players=None):
        super().__init__(daemon=True)
        self.win = win
        self.interval = interval
        # cuantos jugadores caben en la mesa (3-Max, 6-Max...), o None para
        # deducirlo. Sirve de red: las posiciones salen del RECUENTO de asientos
        # ocupados, asi que un asiento fantasma las desplaza todas.
        self.max_players = max_players
        # TestingSession o None. Lo pone el hilo principal antes de arrancar y no
        # se toca despues: la grabacion se decide al iniciar el analisis, no a
        # mitad, para que una sesion grabada sea de principio a fin.
        self.sesion = sesion
        # Estado ENTRE frames: cuanto lleva puesto cada asiento en la mano en
        # curso, deducido de como le baja el stack. Se crea uno por ejecucion
        # (parar y volver a iniciar empieza de cero, que es lo correcto: puede
        # haber pasado cualquier cosa mientras estaba parado).
        self.tracker = hand_tracker.HandTracker()
        # Historial de acciones de la mano, reconstruido de los verbos que el
        # cliente pone en el nameplate. Se cuelga de las fronteras que ya detecta
        # el rastreador para no tener dos criterios distintos de "mano nueva".
        self.action_log = alog.ActionLog()
        self._mano_vista = None
        # Vigilancia rapida: ver seat_watch.py. El cartel de accion de un rival
        # dura menos de 1,5 s, o sea menos que el ciclo de analisis, asi que sin
        # esto se pierden acciones. Se mira cada VIGILANCIA_PERIODO_S si alguna
        # capsula de nameplate ha cambiado (0,8 ms) y solo entonces se paga un
        # OCR, y solo el de esa capsula.
        self.watch = sw.SeatWatch()
        self.buffer = sw.FrameBuffer()
        self._ref = None            # referencia del tapete del ultimo analisis
        self.vistas = 0             # capsulas OCR-eadas por el vigilante
        self.ticks = 0              # capturas rapidas hechas
        self.saltadas = 0           # veces que el tope de seguridad freno un OCR
        self._ultimo_ocr = 0.0
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _log(self, msg):
        GLib.idle_add(self.win.on_status, msg)

    def _crop_region(self, frame):
        """Recorta el frame al recuadro calibrado. Devuelve (crop, error).

        Valida que el recuadro CABE en el frame capturado: si la calibracion es
        de otra resolucion o de otro monitor, numpy no falla -devuelve un recorte
        vacio o truncado- y era cv2.imwrite el que lanzaba, ya dentro del hilo de
        analisis, matandolo sin mas rastro que un "Parado." en la UI. Asi el
        usuario ve el motivo real y que la solucion es recalibrar."""
        try:
            x, y, w, h = load_region()
        except (FileNotFoundError, ValueError, KeyError):
            return None, "No se pudo leer el recuadro de calibracion. Pulsa 'Recalibrar recuadro'."
        fh, fw = frame.shape[:2]
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > fw or y + h > fh:
            return None, (f"El recuadro calibrado (x={x} y={y} {w}x{h}) no cabe en la pantalla "
                          f"capturada ({fw}x{fh}): ¿cambio la resolucion o el monitor? "
                          f"Pulsa 'Recalibrar recuadro'.")
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0:
            return None, (f"El recuadro calibrado quedo vacio ({w}x{h}). "
                          f"Pulsa 'Recalibrar recuadro'.")
        return crop, None

    def _vigilar(self, crop):
        """Paso rapido: mira si alguna capsula de nameplate ha cambiado y, solo
        entonces, la OCR-ea para quedarse con el verbo de la accion.

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
            self.saltadas += 1
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
            self.vistas += len(cambiados)
            for seat, i in idx.items():
                lineas = parse_tsv_lines(res[i])
                _n, _s, accion = ts._seat_plate_name_stack(lineas)
                if accion:
                    self.action_log.observar(seat, accion, t=time.time())
        except Exception:  # noqa: BLE001
            pass                       # vigilar es una ayuda, nunca tumba el lazo

    def _equity_de(self, state):
        """Equity postflop del frame, o None. Una sola implementacion, la del
        motor; un fallo aqui no puede tumbar el analisis."""
        try:
            return engine.postflop_equity(state)
        except Exception:  # noqa: BLE001
            return None

    def _analyze_and_publish(self, crop):
        """Un ciclo de analisis completo sobre un recorte ya validado."""
        t0 = time.perf_counter()
        cv2.imwrite(TMP_FRAME_PATH, crop)
        state = ts.analyze_layout(TMP_FRAME_PATH, max_players=self.max_players)
        # la referencia del tapete se guarda para el lazo rapido, que no puede
        # permitirse recalcularla (29 ms) diez veces por segundo
        try:
            ref = seat_map.find_reference(crop)
            self._ref = None if ref[4] else ref
        except Exception:  # noqa: BLE001
            self._ref = None
        # resumen de la mano anterior. Se parsean las lineas de chat que
        # analyze_layout YA ha OCR-eado: antes esto hacia una segunda pasada de
        # OCR sobre la misma zona, con otro subproceso y otro arranque de
        # tesseract, y costaba 571 ms de un ciclo de 3,9 s. Un fallo aqui no debe
        # tumbar el analisis principal.
        try:
            result = hr.parse_hand_result(state.get("chat_lines"))
        except Exception:  # noqa: BLE001
            result = None
        # ANTES de decidir: cuanto lleva puesto cada asiento, deducido de su
        # bajada de stack. El numero de mano del chat es la señal de frontera mas
        # fiable que hay, de ahi que el chat se parsee primero.
        try:
            info = self.tracker.update(state, (result or {}).get("hand_number"))
            hand_tracker.aplicar(state, info)
            if info["mano"] != self._mano_vista:
                self._mano_vista = info["mano"]
                self.action_log.nueva_mano()
            self.action_log.observar_estado(state, t=time.time())
            state["acciones"] = self.action_log.acciones()
            state["vigilancia"] = {"ticks": self.ticks, "capsulas_ocr": self.vistas,
                                   "saltadas": self.saltadas,
                                   "periodo_s": VIGILANCIA_PERIODO_S}
        except Exception:  # noqa: BLE001
            pass
        recommendation = engine.decide(state)
        hand = hstr.evaluate_hand(state.get("hero_cards"), state.get("board"))
        GLib.idle_add(self.win.on_result, state, recommendation, hand)
        GLib.idle_add(self.win.on_hand_result, result)

        eq = self._equity_de(state)
        GLib.idle_add(self.win.on_equity, eq)

        datos = {"duracion_analisis_s": round(time.perf_counter() - t0, 3),
                 "state": state, "recommendation": recommendation,
                 "hand": hand, "equity": eq, "hand_result": result}

        # modo testing: la dupla frame + todo lo calculado, para revisarlo luego
        n = None
        sesion = self.sesion
        if sesion is not None:
            n = sesion.guardar(crop, datos, lambda ruta: cv2.imwrite(ruta, crop))
            if n is not None:
                GLib.idle_add(self.win.on_testing_progress, n, sesion.errores)

        # el ultimo frame queda a mano para "Marcar situacion". Se COPIA: crop es
        # una vista del buffer del stream, que se reescribe en la lectura
        # siguiente, asi que sin copia lo que se marcase ya no seria lo que se
        # vio. Son ~3,6 MB de memcpy, medio milisegundo de un ciclo de 1,2 s.
        GLib.idle_add(self.win.on_frame_ready, crop.copy(), datos, n, sesion)

    def run(self):
        try:
            load_region()
        except (FileNotFoundError, ValueError, KeyError):
            GLib.idle_add(self.win.on_error, "No hay recuadro calibrado. Pulsa 'Recalibrar recuadro'.")
            GLib.idle_add(self.win.on_stopped)
            return

        try:
            self._log("Abriendo stream (elige la pantalla en el dialogo del portal)...")
            portal, session_handle, fd, stream, _props = pc.open_frame_stream(log=self._log)
        except Exception as e:  # noqa: BLE001 - queremos reportar cualquier fallo del portal en la UI
            GLib.idle_add(self.win.on_error, f"No se pudo abrir el stream: {e}")
            GLib.idle_add(self.win.on_stopped)
            return

        GLib.idle_add(self.win.on_status, "Stream activo.")
        try:
            # EL LAZO RAPIDO ES EL PRIMARIO. Se captura cada VIGILANCIA_PERIODO_S
            # y de cada frame solo se comprueba si alguna capsula de nameplate ha
            # cambiado (0,8 ms); el analisis completo (~1 s) se lanza cuando toca
            # segun el intervalo elegido. Asi el cartel de accion de un rival, que
            # dura menos de 1,5 s, no se pierde entre dos analisis.
            proximo_analisis = 0.0
            while not self._stop.is_set():
                tick = time.monotonic()
                frame = stream.read(timeout_s=5.0)
                if frame is not None:
                    crop, err = self._crop_region(frame)
                    if err:
                        GLib.idle_add(self.win.on_error, err)
                    else:
                        self.ticks += 1
                        self.buffer.añadir(crop, t=time.time())
                        self._vigilar(crop)
                        if time.monotonic() >= proximo_analisis:
                            proximo_analisis = time.monotonic() + self.interval
                            try:
                                self._analyze_and_publish(crop)
                            except Exception as e:  # noqa: BLE001
                                # el fallo de UN frame (OCR caido, timeout, imagen
                                # corrupta) no debe matar el hilo y dejar la UI
                                # muda: se reporta y se sigue con el siguiente.
                                GLib.idle_add(self.win.on_error,
                                              f"Fallo analizando el frame: {e}")
                # el periodo de VIGILANCIA es un periodo, no una pausa: se espera
                # solo lo que falte. Si el analisis se ha comido el tick entero,
                # no se espera nada y se vuelve a capturar de inmediato.
                resto = VIGILANCIA_PERIODO_S - (time.monotonic() - tick)
                if resto > 0:
                    self._stop.wait(resto)
        finally:
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                os.close(fd)
            except Exception:  # noqa: BLE001
                pass
            try:
                portal.close_session(session_handle)
            except Exception:  # noqa: BLE001
                pass
            GLib.idle_add(self.win.on_stopped)


class PokerAssistantWindow(Gtk.ApplicationWindow):
    def __init__(self, app, interval):
        super().__init__(application=app, title="Poker Assistant IA - Panel de control")
        self.set_default_size(520, 700)
        self.worker = None
        self.running = False
        self.sesion = None          # TestingSession mientras se graba
        self.sesion_notas = None    # sesion creada al vuelo si se marca sin grabar
        self._ultimo = None         # ultimo frame analizado, por si se marca
        self._marcado = None        # el frame que fijo "Marcar situacion"
        self.default_interval = interval
        # estado cross-frame del resumen de mano anterior: nombre del hero
        # cacheado (ultimo no-nulo del asiento is_hero; su nameplate a veces
        # muestra la accion en vez del nombre) y firma de la ultima mano ya
        # mostrada (numero de mano, o resumen si no se leyo), para no reescribir
        # el panel en cada frame de la misma mano (evita el parpadeo).
        self._hero_name = None
        self._prev_hand_sig = None
        # ultimo board visto de la mano en curso, para el estudio post-mano: al
        # terminar la mano el board ya no esta en pantalla
        self._ultimo_board = []

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(16)
        root.set_margin_end(16)
        self.set_child(root)

        # Los paneles que el modo HUD esconde. La recomendacion, la equity y la
        # mano actual se quedan: son lo unico que se mira en plena mano.
        estado = self._build_state_frame()
        mano = self._build_hand_frame()
        equity = self._build_equity_frame()
        reco = self._build_recommendation_frame()
        anterior = self._build_prev_hand_frame()
        nota = self._build_note_frame()
        controles = self._build_controls()
        avisos = self._build_status_frame()

        for w in (estado, mano, equity, reco, anterior, nota, controles, avisos):
            root.append(w)
        self.hud = False
        self._paneles_secundarios = (estado, anterior, nota, avisos)

        self._refresh_region_label()
        self.connect("close-request", self._on_close)

    def _build_state_frame(self):
        frame = Gtk.Frame(label="Estado detectado")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        self.hero_label = self._markup_label("Tus cartas: <i>-</i>")
        self.board_label = self._markup_label("Board: <i>-</i>")
        self.pot_label = self._markup_label("Bote: <i>-</i>")
        players_title = self._markup_label("<b>Jugadores</b>")
        self.players_label = self._markup_label("<i>sin datos</i>")
        # lo que se ha VISTO hacer en esta mano. Nunca es la lista completa: el
        # verbo dura menos que el periodo de muestreo (ver action_log).
        self.acciones_label = self._markup_label("")
        self.acciones_label.set_wrap(True)
        self.acciones_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        for w in (self.hero_label, self.board_label, self.pot_label, players_title,
                  self.players_label, self.acciones_label):
            box.append(w)
        frame.set_child(box)
        return frame

    def _build_hand_frame(self):
        frame = Gtk.Frame(label="Mano actual")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        self.made_label = Gtk.Label()
        self.made_label.set_use_markup(True)
        self.made_label.set_halign(Gtk.Align.START)
        self.made_label.set_xalign(0.0)
        self.made_label.set_markup('<span size="large" weight="bold">-</span>')

        self.draws_label = self._markup_label("<i>-</i>")
        self.draws_label.set_wrap(True)
        self.draws_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        note = self._markup_label(
            '<span size="small" foreground="#95a5a6"><i>Probabilidad de COMPLETAR el '
            'proyecto (calculo exacto; entre corchetes la regla del 2 y 4), '
            'NO de ganar la mano: esa es la de abajo, en "Equity estimada". Se puede '
            'ligar el color y perder contra uno mayor, o no ligarlo y ganar igual.</i></span>')
        note.set_wrap(True)
        note.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.made_label)
        box.append(self.draws_label)
        box.append(note)
        frame.set_child(box)
        self.hand_frame = frame
        frame.set_visible(False)
        return frame

    def _build_equity_frame(self):
        frame = Gtk.Frame(label="Equity estimada")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for lado in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{lado}")(8)

        self.eq_main_label = Gtk.Label()
        self.eq_main_label.set_use_markup(True)
        self.eq_main_label.set_halign(Gtk.Align.START)
        self.eq_main_label.set_xalign(0.0)

        self.eq_rivals_label = self._markup_label("")
        self.eq_effect_label = self._markup_label("")
        eq_note = self._markup_label(
            '<span size="small" foreground="#95a5a6"><i>Equity "de all-in": supone que se '
            'ven todas las cartas sin mas apuestas. NO es una recomendacion, no mira el bote. '
            'Supone que cada rival tiene el rango con el que ENTRO al bote — ya han pasado el '
            'flop, asi que su rango real es mas fuerte y este numero es un TECHO. La '
            'probabilidad de COMPLETAR un proyecto esta arriba, en "Mano actual": es otra cosa.'
            '</i></span>')

        for w in (self.eq_rivals_label, self.eq_effect_label, eq_note):
            w.set_wrap(True)
            w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.eq_main_label)
        box.append(self.eq_rivals_label)
        box.append(self.eq_effect_label)
        box.append(eq_note)
        frame.set_child(box)
        self.equity_frame = frame
        frame.set_visible(False)
        return frame

    def on_equity(self, eq):
        """Pinta la equity. Nunca mas digitos de los que soporta std_error_pp: el
        error de una Monte Carlo de 10.000 iteraciones ronda 0,4 pp, asi que dar
        decimales seria fingir una precision que no hay."""
        if not eq:
            self.equity_frame.set_visible(False)
            return False
        self.equity_frame.set_visible(True)
        esc = GLib.markup_escape_text
        w, t, l = (100 * eq["win_probability"], 100 * eq["tie_probability"],
                   100 * eq["loss_probability"])
        # el separador de miles se cambia SOLO en el numero, no en toda la cadena:
        # un replace global convertia tambien la coma de "pp, " en un punto
        sims = f'{eq["iterations_valid"]:,}'.replace(",", ".")
        self.eq_main_label.set_markup(
            f'<span size="large" weight="bold" foreground="#2ecc71">Ganar {w:.0f}%</span>'
            f'  <span size="large">·  Empatar {t:.0f}%  ·  Perder {l:.0f}%</span>\n'
            f'<span size="small" foreground="#95a5a6">±{eq["std_error_pp"]:.1f} pp, '
            f'{sims} simulaciones — {esc(eq["street"])}</span>')

        pos = eq["positional_adjustment"]
        metas = pos.get("opponent_ranges") or []
        detalle = ", ".join(
            f'{m.get("position") or "?"} {100 * (m.get("pct_of_all") or 0):.0f}%' for m in metas)
        self.eq_rivals_label.set_markup(
            f'Rivales activos: <b>{pos["opponents"]}</b>'
            + (f' — rangos de tu tabla: {esc(detalle)}' if detalle else ""))

        efecto = pos.get("range_effect_pp")
        vs_rnd = pos.get("win_probability_vs_random")
        if efecto is not None and vs_rnd is not None:
            self.eq_effect_label.set_markup(
                f'<span size="small">Con rivales de mano cualquiera seria '
                f'{100 * vs_rnd:.0f}%: <b>{abs(efecto):.0f} puntos</b> de la diferencia '
                f'vienen de que tienen un rango.</span>')
        else:
            self.eq_effect_label.set_markup("")
        return False

    def _build_recommendation_frame(self):
        frame = Gtk.Frame(label="Recomendacion")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        self.rec_label = Gtk.Label()
        self.rec_label.set_use_markup(True)
        self.rec_label.set_markup('<span size="xx-large" weight="bold">-</span>')
        self.rec_label.set_halign(Gtk.Align.START)

        self.reasoning_label = self._markup_label('<i>pulsa "Iniciar analisis" para empezar</i>')
        self.reasoning_label.set_wrap(True)
        self.reasoning_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.rec_label)
        box.append(self.reasoning_label)
        frame.set_child(box)
        return frame

    def _build_prev_hand_frame(self):
        frame = Gtk.Frame(label="Mano anterior")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        self.prev_main_label = self._markup_label("<i>sin manos terminadas todavia</i>")
        self.prev_showdown_label = self._markup_label("")
        self.prev_hero_label = self._markup_label("")
        # hueco preparado para el coaching (Fase 4.3): NO se implementa aqui, va
        # el RAG postflop + historial de acciones, una pieza mayor aparte.
        self.prev_coach_label = self._markup_label("")

        for w in (self.prev_main_label, self.prev_showdown_label,
                  self.prev_hero_label, self.prev_coach_label):
            w.set_wrap(True)
            w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            box.append(w)
        frame.set_child(box)
        return frame

    def _build_note_frame(self):
        """Marcar una situacion rara y anotarla, para revisarla despues con el
        frame y todo lo calculado delante.

        Va en DOS PASOS a proposito, y ahi esta todo el diseño: el usuario ve la
        rareza y LUEGO escribe. Con el ciclo en ~1,2 s, para cuando termina la
        frase han pasado varios frames y el panel ya muestra otro; una nota
        asociada al frame del momento de guardar apuntaria al frame equivocado.
        Asi que "Marcar situacion" fija de inmediato el frame que se esta viendo
        y el texto se aplica a ese, se tarde lo que se tarde en escribirlo."""
        frame = Gtk.Frame(label="Marcar una situacion para revisarla despues")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for lado in ("top", "bottom", "start", "end"):
            getattr(box, f"set_margin_{lado}")(8)

        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.mark_button = Gtk.Button(label="Marcar situacion")
        self.mark_button.set_tooltip_text(
            "Fija AHORA el frame que estas viendo. Escribe la nota despues sin prisa: "
            "se guardara junto a ESE frame, no al que se este analizando cuando "
            "termines de escribir.")
        self.mark_button.set_sensitive(False)
        self.mark_button.connect("clicked", self._on_marcar)

        self.nota_entry = Gtk.Entry()
        self.nota_entry.set_hexpand(True)
        self.nota_entry.set_placeholder_text("que te ha parecido raro (Enter para guardar)")
        self.nota_entry.connect("activate", self._on_guardar_nota)

        self.nota_button = Gtk.Button(label="Guardar nota")
        self.nota_button.connect("clicked", self._on_guardar_nota)

        fila.append(self.mark_button)
        fila.append(self.nota_entry)
        fila.append(self.nota_button)

        self.nota_estado = self._markup_label(
            '<span size="small" foreground="#95a5a6"><i>nada marcado todavia</i></span>')
        self.nota_estado.set_wrap(True)
        self.nota_estado.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(fila)
        box.append(self.nota_estado)
        frame.set_child(box)
        return frame

    def _nota_aviso(self, texto, color="#95a5a6", size="small"):
        self.nota_estado.set_markup(
            f'<span size="{size}" foreground="{color}">'
            f'{GLib.markup_escape_text(texto)}</span>')

    @staticmethod
    def _resumen_marcado(datos):
        """Una linea con lo que habia en pantalla en el frame marcado, para que
        se vea de inmediato que se marco lo que se creia marcar."""
        st = (datos or {}).get("state") or {}
        trozos = []
        if st.get("hero_cards"):
            trozos.append(" ".join(str(c) for c in st["hero_cards"]))
        if st.get("board"):
            trozos.append("board " + " ".join(str(c) for c in st["board"]))
        if st.get("hero_position"):
            trozos.append(str(st["hero_position"]))
        rec = (datos or {}).get("recommendation") or {}
        accion = rec.get("action_en") or rec.get("action")
        trozos.append(str(accion) if accion else "sin recomendacion")
        return " · ".join(trozos)

    def _sesion_para_notas(self):
        """Donde guardar un frame marcado: devuelve (sesion, error).

        Si se esta grabando, en esa sesion. Si NO, en una carpeta
        testing/notas-<fecha> que se crea al vuelo la primera vez. Marcar una
        anomalia es justo cuando mas falta hace tenerla guardada, asi que no
        puede depender de haberse acordado de activar el modo testing antes."""
        if self.sesion is not None:
            return self.sesion, None
        if self.sesion_notas is None:
            try:
                self.sesion_notas = ts_session.TestingSession(
                    interval=self.interval_spin.get_value(), prefix="notas")
            except OSError as e:
                return None, str(e)
        return self.sesion_notas, None

    def _on_marcar(self, _btn=None):
        ultimo = self._ultimo
        if ultimo is None:
            self._nota_aviso("Aun no se ha analizado ningun frame que marcar: "
                             "pulsa 'Iniciar analisis'.", "#e67e22")
            return False
        sesion, n = ultimo["sesion"], ultimo["n"]
        if sesion is None or n is None:
            # sin modo testing -o si el guardado de ese frame fallo- el frame no
            # esta en disco, asi que se guarda ahora, al marcarlo.
            sesion, err = self._sesion_para_notas()
            if sesion is None:
                self._nota_aviso(f"No se pudo crear la carpeta para la nota: {err}", "#e74c3c")
                return False
            crop = ultimo["crop"]
            n = sesion.guardar(crop, ultimo["datos"], lambda ruta: cv2.imwrite(ruta, crop))
            if n is None:
                self._nota_aviso("No se pudo guardar el frame marcado (¿disco lleno?).", "#e74c3c")
                return False
        self._marcado = {"sesion": sesion, "n": n, "hora": ultimo["hora"],
                         "datos": ultimo["datos"]}
        self._pintar_marcado()
        self.nota_entry.grab_focus()
        return True

    def _pintar_marcado(self):
        m = self._marcado
        destino = os.path.relpath(os.path.join(m["sesion"].dir, f'{m["n"]:04d}.png'), BASE_DIR)
        self.nota_estado.set_markup(
            f'<span foreground="#3498db">Marcado el frame <b>{m["n"]:04d}</b> '
            f'({GLib.markup_escape_text(m["hora"])}) — '
            f'{GLib.markup_escape_text(self._resumen_marcado(m["datos"]))}</span>\n'
            f'<span size="small" foreground="#95a5a6">{GLib.markup_escape_text(destino)} '
            f'— escribe la nota sin prisa, se guardara en ESE frame.</span>')

    def _on_guardar_nota(self, _w=None):
        texto = self.nota_entry.get_text().strip()
        if not texto:
            self._nota_aviso("Escribe la nota antes de guardarla.", "#e67e22")
            return False
        aviso = ""
        if self._marcado is None:
            # nadie marco: se marca AHORA y se dice claramente que la nota va al
            # frame actual, que puede no ser el de la anomalia. Negarse no
            # ayudaria -marcar ahora fijaria el mismo frame- y perderia el texto.
            if not self._on_marcar():
                return False
            aviso = (" OJO: no habias pulsado 'Marcar situacion', asi que la nota va al frame "
                     "de AHORA, que puede no ser el de lo que viste.")
        m = self._marcado
        ok = m["sesion"].anotar(m["n"], texto)
        if ok:
            self.nota_entry.set_text("")
            destino = os.path.relpath(m["sesion"].dir, BASE_DIR)
            self._nota_aviso(f'Nota guardada en el frame {m["n"]:04d} de {destino}.{aviso}',
                             "#2ecc71" if not aviso else "#e67e22")
            self._marcado = None
        else:
            self._nota_aviso(f'No se pudo escribir la nota en el frame {m["n"]:04d}.', "#e74c3c")
        return False

    def on_frame_ready(self, crop, datos, n, sesion):
        """Deja a mano el ultimo frame analizado por si el usuario lo marca. Solo
        el ultimo: marcar es "esto de ahora", no un historial."""
        self._ultimo = {"crop": crop, "datos": datos, "n": n, "sesion": sesion,
                        "hora": time.strftime("%H:%M:%S")}
        self.mark_button.set_sensitive(True)
        return False

    def _on_hud(self, boton):
        """Modo HUD: deja solo lo que se mira en plena mano -la orden, la equity y
        la mano actual- y esconde lo demas.

        No es una ventana aparte: es la MISMA, con paneles ocultos y siempre
        encima. Una ventana nueva significaria duplicar el cableado de cada
        widget y tener dos sitios donde arreglar cada cosa; y en Wayland no se
        puede posicionar una ventana desde la aplicacion, asi que "anclarla bajo
        el recuadro" no depende de nosotros de todos modos: la coloca el usuario
        una vez y se queda encima."""
        self.hud = boton.get_active()
        for panel in self._paneles_secundarios:
            panel.set_visible(not self.hud)
        self.set_title("Poker Assistant IA" + (" — HUD" if self.hud
                                               else " - Panel de control"))
        try:
            # always-on-top: en X11 lo aplica el gestor de ventanas; en Wayland
            # muchos compositores lo ignoran, asi que no se puede prometer.
            surface = self.get_surface()
            if surface is not None and hasattr(surface, "set_keep_above"):
                surface.set_keep_above(self.hud)
        except Exception:  # noqa: BLE001
            pass
        if self.hud:
            self.set_default_size(420, 320)

    def _build_controls(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Modo HUD: se esconde todo menos lo que se mira en plena mano.
        self.hud_check = Gtk.CheckButton(label="HUD")
        self.hud_check.set_tooltip_text(
            "Deja solo la recomendacion, la equity y la mano actual, y pone la "
            "ventana encima. Para tenerla al lado de la mesa mientras juegas.")
        self.hud_check.connect("toggled", self._on_hud)

        self.start_button = Gtk.Button(label="Iniciar analisis")
        self.start_button.connect("clicked", self._on_toggle)

        self.calibrate_button = Gtk.Button(label="Recalibrar recuadro")
        self.calibrate_button.connect("clicked", self._on_calibrate)

        # Tamaño de mesa. Las posiciones se derivan del RECUENTO de asientos
        # ocupados, asi que un asiento fantasma (texto que el OCR saca del propio
        # tapete) las desplaza TODAS y el rango elegido es el de otra posicion.
        # Decir cuantos caben convierte eso en una contradiccion demostrable.
        mesa_label = Gtk.Label(label="Mesa")
        self.mesa_combo = Gtk.ComboBoxText()
        for etiqueta in ("auto", "2 (heads-up)", "3-Max", "6-Max", "9 plazas"):
            self.mesa_combo.append_text(etiqueta)
        self.mesa_combo.set_active(0)
        self.mesa_combo.set_tooltip_text(
            "Cuantos jugadores caben en la mesa. Con 'auto' se deduce de lo que se ve; "
            "si lo fijas, detectar mas asientos de los que caben se trata como un error "
            "y se descarta la lectura mas debil en vez de desplazar las posiciones.")

        interval_label = Gtk.Label(label="Intervalo (s)")
        self.interval_spin = Gtk.SpinButton.new_with_range(0.25, 10.0, 0.25)
        self.interval_spin.set_digits(2)
        self.interval_spin.set_value(self.default_interval)

        # Modo testing: graba cada frame junto con todo lo que se calculo de el,
        # emparejados por nombre, en testing/sesion-<fecha>/. Es un CheckButton y
        # no un boton aparte a proposito: la grabacion acompaña al analisis (se
        # decide antes de darle a "Iniciar"), no es un proceso independiente que
        # se pueda encender y apagar a mitad y dejar una sesion a trozos.
        self.testing_check = Gtk.CheckButton(label="Grabar sesion de testing")
        self.testing_check.set_tooltip_text(
            "Guarda cada captura y sus resultados en testing/sesion-<fecha>/, "
            "en duplas 0001.png + 0001.json, para revisar despues por que la app "
            "dijo lo que dijo. Se activa al iniciar el analisis.")

        box.append(self.start_button)
        box.append(self.hud_check)
        box.append(self.calibrate_button)
        box.append(mesa_label)
        box.append(self.mesa_combo)
        box.append(interval_label)
        box.append(self.interval_spin)
        box.append(self.testing_check)
        return box

    def _build_status_frame(self):
        frame = Gtk.Frame(label="Estado / avisos")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        self.region_label = self._markup_label("Recuadro: <i>-</i>")
        self.status_label = self._markup_label("Parado.")
        self.testing_label = self._markup_label("")
        self.testing_label.set_wrap(True)
        self.warnings_label = self._markup_label("")
        self.warnings_label.set_wrap(True)
        self.warnings_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.region_label)
        box.append(self.status_label)
        box.append(self.testing_label)
        box.append(self.warnings_label)
        frame.set_child(box)
        return frame

    @staticmethod
    def _markup_label(markup):
        label = Gtk.Label()
        label.set_use_markup(True)
        label.set_markup(markup)
        label.set_halign(Gtk.Align.START)
        label.set_xalign(0.0)
        return label

    def _refresh_region_label(self):
        try:
            x, y, w, h = load_region()
            self.region_label.set_markup(f"Recuadro: x={x} y={y} {w}x{h}")
        except (FileNotFoundError, ValueError, KeyError):
            self.region_label.set_markup('Recuadro: <span foreground="#e67e22">sin calibrar</span>')

    def _on_toggle(self, _btn):
        if self.running:
            self.start_button.set_label("Parando...")
            self.start_button.set_sensitive(False)
            if self.worker:
                self.worker.stop()
        else:
            self.running = True
            self.start_button.set_label("Parar analisis")
            self.calibrate_button.set_sensitive(False)
            self.interval_spin.set_sensitive(False)
            self.testing_check.set_sensitive(False)
            self.mesa_combo.set_sensitive(False)
            self.status_label.set_markup("Iniciando...")
            intervalo = self.interval_spin.get_value()

            self.sesion = None
            if self.testing_check.get_active():
                try:
                    region = None
                    try:
                        x, y, w, h = load_region()
                        region = {"x": x, "y": y, "width": w, "height": h}
                    except (FileNotFoundError, ValueError, KeyError):
                        pass
                    self.sesion = ts_session.TestingSession(interval=intervalo, region=region)
                    self.testing_label.set_markup(
                        f'<span foreground="#3498db">Grabando en '
                        f'{GLib.markup_escape_text(os.path.relpath(self.sesion.dir, BASE_DIR))}'
                        f' — 0 frames</span>')
                except OSError as e:
                    # no poder grabar no debe impedir analizar
                    self.testing_label.set_markup(
                        f'<span foreground="#e74c3c">No se pudo crear la carpeta de '
                        f'testing: {GLib.markup_escape_text(str(e))}</span>')

            self.worker = AnalysisWorker(self, intervalo, sesion=self.sesion,
                                         max_players=self._max_players())
            self.worker.start()

    _MESA_OPCIONES = (None, 2, 3, 6, 9)      # mismo orden que el combo

    def _max_players(self):
        i = self.mesa_combo.get_active()
        return self._MESA_OPCIONES[i] if 0 <= i < len(self._MESA_OPCIONES) else None

    def _on_calibrate(self, _btn):
        if self.running:
            return
        self.calibrate_button.set_sensitive(False)
        self.start_button.set_sensitive(False)
        self.status_label.set_markup("Abriendo calibrador (elige la pantalla, dibuja el recuadro, Enter)...")

        def work():
            try:
                subprocess.run([sys.executable, SELECT_REGION_PATH])
            finally:
                GLib.idle_add(self._after_calibrate)

        threading.Thread(target=work, daemon=True).start()

    def _after_calibrate(self):
        self._refresh_region_label()
        self.calibrate_button.set_sensitive(True)
        self.start_button.set_sensitive(True)
        self.status_label.set_markup("Recuadro recargado.")
        return False

    def on_status(self, msg):
        self.status_label.set_markup(GLib.markup_escape_text(msg))
        return False

    def on_error(self, msg):
        self.status_label.set_markup(f'<span foreground="#e74c3c">{GLib.markup_escape_text(msg)}</span>')
        return False

    def on_testing_progress(self, n, errores):
        aviso = f"  ({errores} sin guardar)" if errores else ""
        self.testing_label.set_markup(
            f'<span foreground="#3498db">Grabando en '
            f'{GLib.markup_escape_text(os.path.relpath(self.sesion.dir, BASE_DIR))} — '
            f'{n} frames{GLib.markup_escape_text(aviso)}</span>')
        return False

    def on_stopped(self):
        self.running = False
        self.worker = None
        self.start_button.set_label("Iniciar analisis")
        self.start_button.set_sensitive(True)
        self.calibrate_button.set_sensitive(True)
        self.interval_spin.set_sensitive(True)
        self.testing_check.set_sensitive(True)
        self.mesa_combo.set_sensitive(True)
        if self.sesion is not None:
            carpeta = self.sesion.cerrar()
            n, errores = self.sesion.n, self.sesion.errores
            self.sesion = None
            self.testing_label.set_markup(
                f'<span foreground="#2ecc71">Sesion guardada: {n} frames en '
                f'{GLib.markup_escape_text(os.path.relpath(carpeta, BASE_DIR))}'
                f'{GLib.markup_escape_text(f"  ({errores} sin guardar)" if errores else "")}'
                f'</span>')
        if not self.status_label.get_text().startswith("No se pudo"):
            self.status_label.set_markup("Parado.")
        return False

    @staticmethod
    def _draw_line(d):
        name = GLib.markup_escape_text(d["name"])
        outs = d["outs"]
        if d.get("pct_river") is not None:
            pct = (f"~{d['pct_river']}% al river, ~{d['pct_next']}% a la siguiente "
                   f"[regla 2/4: {d['pct_next_rule']}%/{d['pct_river_rule']}%]")
        else:
            pct = f"~{d['pct_next']}% al river [regla del 2: {d['pct_next_rule']}%]"
        body = f"{name}: {outs} outs, {pct}"
        if d.get("combined"):
            return f'<span foreground="#2ecc71" weight="bold">&#8226; {body}</span>'
        if d.get("speculative"):
            return f'<span foreground="#95a5a6"><i>&#8226; {body}</i></span>'
        return f"&#8226; {body}"

    def _update_hand(self, hand):
        if not hand:
            self.hand_frame.set_visible(False)
            return
        self.hand_frame.set_visible(True)
        made = f'<span size="large" weight="bold">{GLib.markup_escape_text(hand["made_name"])}</span>'
        explain = hand.get("made_explain")
        if explain:
            made += (f'\n<span size="small" color="#888888">'
                     f'({GLib.markup_escape_text(explain)})</span>')
        self.made_label.set_markup(made)
        draws = hand.get("draws") or []
        if draws:
            self.draws_label.set_markup("\n".join(self._draw_line(d) for d in draws))
        elif hand.get("street") == "river":
            self.draws_label.set_markup("<i>Sin proyectos (river: no quedan cartas por venir).</i>")
        elif hand.get("street") == "preflop":
            self.draws_label.set_markup("<i>Proyectos: se calculan a partir del flop.</i>")
        else:
            self.draws_label.set_markup("<i>Sin proyectos.</i>")
        return False

    def on_result(self, state, recommendation, hand=None):
        # cachea el nombre del hero (ultimo no-nulo del asiento is_hero): su
        # nameplate a veces muestra la accion ("Igualar"/"Pasar") en vez del
        # nombre, asi que solo se actualiza cuando hay nombre.
        for p in state.get("players") or []:
            if p.get("is_hero") and p.get("name"):
                self._hero_name = p["name"]
                break

        self.hero_label.set_markup("Tus cartas: " + cards_markup(state.get("hero_cards")))
        self.board_label.set_markup("Board: " + (cards_markup(state.get("board"))
                                                 if state.get("board") else "<i>(preflop)</i>"))
        pot = state.get("pot")
        self.pot_label.set_markup(f"Bote: {GLib.markup_escape_text(str(pot))}" if pot is not None
                                  else "Bote: <i>-</i>")
        if state.get("board"):
            self._ultimo_board = list(state["board"])
        self.players_label.set_markup(players_markup(state.get("players")))
        acc = (state.get("acciones") or {}).get("acciones") or []
        if acc:
            _ES = {"check": "pasa", "call": "paga", "bet": "apuesta", "raise": "sube",
                   "fold": "no va", "allin": "all-in", "post": "pone ciega"}
            texto = " · ".join(f'{a["position"] or a["seat"]} {_ES.get(a["accion"], a["accion"])}'
                               for a in acc)
            self.acciones_label.set_markup(
                f'<span size="small">Visto en esta mano: '
                f'{GLib.markup_escape_text(texto)}</span>'
                f'<span size="small" foreground="#95a5a6">  (puede faltar alguna)</span>')
        else:
            self.acciones_label.set_markup("")
        self._update_hand(hand)

        if recommendation:
            # orden bilingue: ingles grande, castellano debajo mas pequeño. El
            # ingles ya viene normalizado por la capa de traduccion; el .upper()
            # solo actua en el respaldo, por si llega una etiqueta sin traducir.
            esc = GLib.markup_escape_text
            en = recommendation.get("action_en") or str(recommendation["action"]).upper()
            es = recommendation.get("action_es")
            # Una accion DERIVADA (Fase E) es indistinguible a simple vista de una
            # que sale de sus tablas -"CHECK" es "CHECK"-, asi que se distingue por
            # color y con una linea propia que nombra la celda donante. El verde se
            # reserva para lo que si esta digitalizado.
            derivada = recommendation.get("source") == "derived"
            color = "#f39c12" if derivada else "#2ecc71"
            markup = f'<span size="xx-large" weight="bold" foreground="{color}">{esc(en)}</span>'
            if es:
                markup += f'\n<span size="large" foreground="#bdc3c7">{esc(es)}</span>'
            if derivada:
                markup += (f'\n<span size="small" foreground="#f39c12">inferido de '
                           f'{esc(str(recommendation.get("donor") or "otra celda tuya"))}'
                           f' — confianza {esc(str(recommendation.get("confidence") or "?"))}'
                           f'</span>')
            self.rec_label.set_markup(markup)
            reasoning = recommendation.get("reasoning") or ""
            self.reasoning_label.set_markup(GLib.markup_escape_text(reasoning))
        else:
            self.rec_label.set_markup('<span size="xx-large" weight="bold" foreground="#7f8c8d">-</span>')
            reason = self._no_reco_reason(state)
            self.reasoning_label.set_markup(
                f'<span foreground="#f39c12"><i>{GLib.markup_escape_text(reason)}</i></span>')

        warnings = state.get("warnings") or []
        self.warnings_label.set_markup(
            ("Avisos: " + GLib.markup_escape_text("; ".join(warnings))) if warnings else "")
        return False

    @staticmethod
    def _no_reco_reason(state):
        """Motivo en lenguaje claro de por que no hay recomendacion, segun la
        fase detectada -mas util que el ultimo aviso tecnico."""
        # lo primero, porque invalida todo lo demas: sin la referencia del tapete
        # ninguna zona esta donde toca, asi que analyze_layout ni siquiera analiza
        for w in state.get("warnings") or []:
            if "no se encuentra la mesa" in w:
                return w
        cards = state.get("hero_cards") or []
        players = state.get("players") or []
        if not players and not cards:
            return ("No se detecta una mesa de poker (¿estas en el lobby o fuera de una mano?). "
                    "La app solo recomienda con una mesa activa en pantalla.")
        if state.get("board"):
            return ("Postflop: no hay rango postflop digitalizado, asi que no se recomienda "
                    "una ACCION. Lo que si hay es la equity estimada de arriba — pero es una "
                    "probabilidad, no una decision: un 20% puede ser un call correcto con el "
                    "precio adecuado y un 60% un fold con malas implied odds.")
        if len(cards) != 2:
            return ("No se ven tus 2 cartas (entre manos, aun sin repartir, o no estas en esta mano). "
                    "La recomendacion aparece cuando tienes tus cartas boca arriba en preflop.")
        if not state.get("hero_position"):
            return ("No se detecta tu posicion (el boton de dealer no se ve o esta tapado). "
                    "Sin posicion no se puede elegir el rango.")
        # el caso mas comun de abstencion con todo lo demas listo: no se leyo el
        # stack. Como parse_amount_bb EXIGE el sufijo "BB", eso casi siempre
        # significa que el cliente no esta en modo big blinds; se le dice, porque
        # es lo unico que el usuario puede arreglar.
        hero = next((p for p in players if p.get("is_hero")), None)
        if hero is not None and hero.get("stack") is None:
            return ("No se lee tu stack en BB. La app trabaja SOLO con importes en big "
                    "blinds: en PokerStars, ajustes de mesa -> mostrar los importes en "
                    "BIG BLINDS. Mientras no sea asi se abstiene en vez de adivinar, "
                    "porque leer un importe en la unidad equivocada daria una "
                    "recomendacion convincente y falsa.")
        warnings = state.get("warnings") or []
        return warnings[-1] if warnings else "Sin recomendacion en este spot."

    @staticmethod
    def _result_sig(result):
        return "|".join(str(result.get(k) or "") for k in ("winner", "amount", "winning_hand"))

    def on_hand_result(self, result):
        # solo actualiza el panel cuando la mano terminada es NUEVA (numero de
        # mano distinto del ya mostrado; si no hay numero legible, se usa el
        # resumen como firma). Asi el panel refleja la ultima mano y no parpadea.
        if not result:
            return False
        sig = result.get("hand_number") or self._result_sig(result)
        if not sig or sig == self._prev_hand_sig:
            return False
        self._prev_hand_sig = sig
        self._render_prev_hand(result)
        return False

    def _render_prev_hand(self, result):
        esc = GLib.markup_escape_text
        winner = result.get("winner")
        if winner and result.get("split"):
            reparto = " y ".join(esc(w) for w in (result.get("winners") or [winner]))
            line = f"Anterior mano: <b>Bote dividido</b> entre {reparto}"
            if result.get("winning_hand"):
                line += f" — Mano: {esc(result['winning_hand'])}"
            if result.get("amount"):
                line += f"  (bote {esc(result['amount'])})"
        elif winner:
            line = f"Anterior mano: Gano <b>{esc(winner)}</b>"
            if result.get("winning_hand"):
                line += f" — Mano: {esc(result['winning_hand'])}"
            if result.get("amount"):
                line += f"  (bote {esc(result['amount'])})"
        else:
            line = "Anterior mano: <i>resultado no legible</i>"
        self.prev_main_label.set_markup(line)

        ganadores = result.get("winners") or ([winner] if winner else [])
        opps = [f"{esc(s['player'])} ({esc(s['hand'])})"
                for s in result.get("showdown", [])
                if not any(hr._names_match(s.get("player", ""), g) for g in ganadores)]
        self.prev_showdown_label.set_markup(
            "mano a mano con: " + ", ".join(opps) if opps else "")

        outcome = hr.hero_outcome(result, self._hero_name)
        if outcome["status"] == "won":
            body = ("Ganaste esta mano con: " + esc(outcome["hero_hand"])
                    if outcome["hero_hand"] else "Ganaste esta mano")
            self.prev_hero_label.set_markup(f'<span foreground="#2ecc71" weight="bold">{body}</span>')
        elif outcome["status"] == "split":
            body = ("Empataste el bote con: " + esc(outcome["hero_hand"])
                    if outcome["hero_hand"] else "Empataste el bote")
            self.prev_hero_label.set_markup(f'<span foreground="#3498db" weight="bold">{body}</span>')
        elif outcome["status"] == "lost":
            body = ("Perdiste con: " + esc(outcome["hero_hand"])
                    if outcome["hero_hand"] else "Perdiste esta mano")
            self.prev_hero_label.set_markup(f'<span foreground="#e74c3c" weight="bold">{body}</span>')
        else:
            # sin evidencia de si el hero jugo la mano: no se afirma nada
            self.prev_hero_label.set_markup("")

        # ESTUDIO POST-MANO (Fase 4.4). Se lanza en un hilo porque la primera
        # consulta carga el modelo de embeddings y tarda segundos; la mano ya ha
        # terminado, asi que la latencia no importa.
        self.prev_coach_label.set_markup(
            '<span size="small" foreground="#95a5a6"><i>buscando videos sobre '
            'situaciones parecidas...</i></span>')
        board = list(self._ultimo_board)
        ganadora = result.get("winning_hand")
        showdown = bool(result.get("showdown"))
        threading.Thread(target=self._buscar_estudio, args=(board, ganadora, showdown),
                         daemon=True).start()
        return False

    def _buscar_estudio(self, board, ganadora, showdown):
        try:
            r = postmano.estudiar(board=board, mano_ganadora=ganadora,
                                  hero_en_showdown=showdown)
        except Exception:  # noqa: BLE001 - estudiar nunca puede tumbar la UI
            r = None
        GLib.idle_add(self.on_estudio, r)

    def on_estudio(self, r):
        """Pinta las referencias de estudio. NO es consejo sobre la mano que se
        acaba de jugar -es prosa recuperada por parecido semantico- y el texto lo
        dice: se ofrece el video y el minuto para poder comprobarlo."""
        refs = (r or {}).get("referencias") or []
        if not refs:
            self.prev_coach_label.set_markup(
                '<span size="small" foreground="#95a5a6"><i>Sin videos que se parezcan '
                'lo bastante a esta mano.</i></span>')
            return False
        esc = GLib.markup_escape_text
        lineas = ['<span size="small" foreground="#95a5a6">Para repasar, videos que hablan '
                  'de situaciones <i>parecidas</i> (no de esta mano):</span>']
        for x in refs:
            nombre = (x["video"] or "").replace("_", " ")
            if len(nombre) > 70:
                nombre = nombre[:70] + "..."
            lineas.append(f'<span size="small">&#8226; {esc(nombre)} '
                          f'<b>{esc(postmano.minuto(x["inicio_s"]))}</b></span>')
        self.prev_coach_label.set_markup("\n".join(lineas))
        return False

    def _on_close(self, *_a):
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=6.0)
        # los workers de OCR viven entre lotes, asi que hay que cerrarlos: si no,
        # quedan procesos python sueltos al cerrar la ventana
        try:
            cerrar_workers()
        except Exception:  # noqa: BLE001
            pass
        if self.sesion_notas is not None:
            self.sesion_notas.cerrar()
            self.sesion_notas = None
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=3.0, help="segundos entre analisis")
    parser.add_argument("--self-test", action="store_true",
                        help="construye la ventana y sale (verifica que los widgets se crean)")
    args = parser.parse_args()

    # NON_UNIQUE en el self-test: con el id compartido, si ya hay una ventana
    # abierta GTK conecta la segunda instancia a la primera por D-Bus, "activate"
    # se dispara en la OTRA y esta sale con codigo 0 sin imprimir nada. O sea que
    # el smoke test APROBABA en silencio justo cuando no podia comprobar nada.
    # Un test que no puede fallar no sirve.
    flags = Gio.ApplicationFlags.NON_UNIQUE if args.self_test else Gio.ApplicationFlags.DEFAULT_FLAGS
    app = Gtk.Application(application_id="org.pokerassistant.gui", flags=flags)

    construida = {"ok": False}

    def on_activate(app):
        win = PokerAssistantWindow(app, args.interval)
        construida["ok"] = True
        if args.self_test:
            print("self-test OK: ventana y widgets construidos")
            app.quit()
        else:
            win.present()

    app.connect("activate", on_activate)
    codigo = app.run(None)
    if args.self_test and not construida["ok"]:
        print("self-test FALLO: la ventana no llego a construirse", file=sys.stderr)
        return 1
    return codigo


if __name__ == "__main__":
    raise SystemExit(main())
