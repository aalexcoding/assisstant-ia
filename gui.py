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

El ritmo de analisis NO se elige: se mide en caliente y se enseña. --interval
lo fija a la fuerza, solo para reproducir la cadencia de una sesion vieja.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import cv2

from core import VIGILANCIA_PERIODO_S, Analizador
from core.analisis import Ritmo
from decision.rag import postmano
from vision import hand_result as hr
from vision.ocr_client import cerrar_workers
from capture import portal_capture as pc

import testing_session as ts_session

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

CALIBRATION_PATH = os.path.join(BASE_DIR, "calibration", "config.local.json")
SELECT_REGION_MODULE = "calibration.select_region"

# VIGILANCIA_PERIODO_S y el resto de la cadencia viven en core/analisis.py, con
# el codigo que los usa. Aqui solo se importa el periodo, que hace falta para el
# lazo de captura y para anotarlo en la meta de la sesion de testing.

SUIT_SYMBOLS = {"h": "♥", "d": "♦", "c": "♣", "s": "♠"}
SUIT_COLORS = {"h": "#e74c3c", "d": "#3498db", "c": "#2ecc71", "s": "#95a5a6"}

# Una interfaz de juego necesita jerarquía estable: la acción debe destacar,
# los datos de contexto deben poder leerse sin competir con ella y los detalles
# técnicos deben seguir disponibles sin ocupar la pantalla todo el tiempo.
# Se usa una paleta oscura propia para que el aspecto no dependa del tema GTK
# instalado en la distribución.
APP_CSS = """
window.poker-app {
    background-color: #0b1016;
    color: #e6edf3;
}
.topbar {
    background-color: #111820;
    border-bottom: 1px solid #27313d;
    padding: 14px 20px;
}
.brand-title {
    color: #f4f7fa;
    font-size: 21px;
    font-weight: 800;
}
.brand-subtitle {
    color: #8b98a7;
    font-size: 12px;
}
.toolbar {
    background-color: #0f151c;
    border-bottom: 1px solid #27313d;
    padding: 10px 20px;
}
.content {
    padding: 18px;
}
.card {
    background-color: #151c24;
    border: 1px solid #2a3542;
    border-radius: 12px;
    padding: 16px;
}
.primary-card {
    background-color: #14221c;
    border-color: #2d6b4b;
    padding: 20px;
}
.card-title {
    color: #8b98a7;
    font-size: 11px;
    font-weight: 800;
}
.summary-tile {
    background-color: #0f151c;
    border: 1px solid #27313d;
    border-radius: 9px;
    padding: 11px 13px;
}
.muted {
    color: #8b98a7;
}
.status-pill {
    border-radius: 999px;
    padding: 5px 11px;
    font-size: 11px;
    font-weight: 800;
}
.status-idle {
    background-color: #27313d;
    color: #b6c0cb;
}
.status-live {
    background-color: #173e2b;
    color: #6ee7a7;
}
.status-error {
    background-color: #4a2025;
    color: #ff9da7;
}
button.primary-action {
    background-color: #238636;
    color: white;
    border-color: #2ea043;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 700;
}
button.primary-action:hover {
    background-color: #2ea043;
}
button.secondary-action {
    border-radius: 8px;
    padding: 8px 12px;
}
.field-label {
    color: #8b98a7;
    font-size: 11px;
    font-weight: 700;
}
.technical {
    color: #9ba7b4;
    font-size: 12px;
}
expander > title {
    color: #aeb8c4;
    padding-top: 6px;
}
"""


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
        name = GLib.markup_escape_text(str(p["name"] if p.get("name") else "(?)"))
        # EN CURSIVA CUANDO EL NOMBRE ES DE UNA MANO ANTERIOR. El respaldo hace
        # mucho trabajo -rellena el 24% de las filas- pero no todo lo que rellena
        # sigue siendo verdad: medido sobre 859 mano-asiento sostenidos por el
        # respaldo, 106 resultaron ser OTRA PERSONA (Conexi6n -> anaes,
        # Mig070883 -> bated; no son variantes de OCR del mismo nick). El dato
        # viajaba en el state desde hacia tiempo y el HUD lo ignoraba, o sea que
        # pintaba con la misma confianza lo leido ahora y lo recordado de antes.
        # No se puede distinguir cual de los dos es: lo que si se puede es dejar
        # de afirmarlo, que es lo que hace la cursiva.
        if p.get("name_de_mano_anterior"):
            name = f"<i>{name}</i>"
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
        fila = (f"{name}{GLib.markup_escape_text(pos)}: "
                f"{GLib.markup_escape_text(str(stack))}{mark}{puesto}{accion}")
        # SENTADO PERO FUERA DE LA MANO SE PINTA APAGADO. Es la nota del usuario
        # sobre el frame 254: en el HUD un jugador retirado se veia igual que uno
        # que sigue jugando, y contra cuantos vas es de lo primero que se mira.
        # El cliente los distingue con toda claridad -al que no juega le oscurece
        # la tarjeta y le quita el reverso de las cartas- y la app ya lo lee
        # (table_state.estado_asiento: SENTADO frente a EN_MANO_*), solo que el
        # HUD no lo pintaba.
        #
        # Se apaga la fila ENTERA y no solo el nombre: lo que se quiere de un
        # vistazo es "estos tres cuentan y estos dos no", y un detalle pequeño en
        # un lado no se lee de un vistazo. Los frames viejos no traen `in_hand` y
        # se pintan normales, que es lo que hacia antes.
        if p.get("in_hand") is False:
            fila = f'<span foreground="#7f8c8d">{fila}</span>'
        lines.append(fila)
    return "\n".join(lines)


class AnalysisWorker(threading.Thread):
    """Hilo de analisis: abre el stream, lee frames, recorta, analiza y
    manda cada resultado a la ventana via GLib.idle_add. No toca widgets."""

    def __init__(self, win, interval, sesion=None, max_players=None, mazo="solid"):
        super().__init__(daemon=True)
        self.win = win
        # EL LATIDO SE MIDE. `interval` ya no es el periodo sino la salida de
        # emergencia de --interval: si viene, manda sobre lo medido, para poder
        # reproducir la cadencia de una sesion vieja. Ver core.analisis.Ritmo.
        self.ritmo = Ritmo(fijo=interval)
        # EL ANALISIS, con toda su memoria entre frames (referencia del tapete,
        # plantilla del boton, escala del glifo, rastreador, registro de
        # acciones). Se crea uno por ejecucion: parar y volver a iniciar empieza
        # de cero, que es lo correcto porque mientras estaba parado pudo pasar
        # cualquier cosa en la mesa.
        #
        # max_players (3-Max, 6-Max...) sirve de red: las posiciones salen del
        # RECUENTO de asientos ocupados, asi que un asiento fantasma las desplaza
        # todas.
        self.analizador = Analizador(max_players=max_players, mazo=mazo)
        # TestingSession o None. Lo pone el hilo principal antes de arrancar y no
        # se toca despues: la grabacion se decide al iniciar el analisis, no a
        # mitad, para que una sesion grabada sea de principio a fin.
        self.sesion = sesion
        self._stop = threading.Event()

    @property
    def max_players(self):
        return self.analizador.max_players

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

    def _analyze_and_publish(self, crop):
        """Un ciclo de analisis completo sobre un recorte ya validado.

        El ANALISIS lo hace core.Analizador; aqui solo queda publicarlo en la
        ventana. Esa division es a proposito: el mismo ciclo lo corren alpha.py,
        replay.py y la suite, y si viviera dentro de este metodo cada uno tendria
        que reconstruir la secuencia por su cuenta."""
        res = self.analizador.analizar(crop)
        self.ritmo.anota(res.duracion_analisis_s)
        GLib.idle_add(self.win.on_ritmo, self.ritmo.etiqueta())
        state, recommendation = res.state, res.recommendation
        GLib.idle_add(self.win.on_result, state, recommendation, res.hand)
        GLib.idle_add(self.win.on_hand_result, res.hand_result)
        GLib.idle_add(self.win.on_equity, res.equity)

        datos = res.a_dict()

        # modo testing: la dupla frame + todo lo calculado, para revisarlo luego
        n = None
        sesion = self.sesion
        if sesion is not None:
            # LA MESA DETECTADA SE APUNTA EN LA METADATA. Si no, una sesion
            # grabada con el selector en "Auto" se guarda con max_players=None y
            # deja de servir de verdad de terreno: la regresion de oro no la puede
            # reproducir con su geometria y el test de precision del detector la
            # descarta. Se escribe una sola vez, cuando el detector se fija.
            if (sesion.meta.get("max_players") is None
                    and state.get("disposicion_detectada")):
                sesion.meta["max_players"] = state["disposicion_detectada"]
                sesion.meta["max_players_detectado"] = True
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
            self.analizador.cerrar()
            GLib.idle_add(self.win.on_error, "No hay recuadro calibrado. Pulsa 'Recalibrar recuadro'.")
            GLib.idle_add(self.win.on_stopped)
            return

        try:
            self._log("Abriendo stream (elige la pantalla en el dialogo del portal)...")
            portal, session_handle, fd, stream, _props = pc.open_frame_stream(log=self._log)
        except Exception as e:  # noqa: BLE001 - queremos reportar cualquier fallo del portal en la UI
            self.analizador.cerrar()
            GLib.idle_add(self.win.on_error, f"No se pudo abrir el stream: {e}")
            GLib.idle_add(self.win.on_stopped)
            return

        GLib.idle_add(self.win.on_status, "Stream activo.")
        try:
            # EL LAZO RAPIDO ES EL PRIMARIO. Se captura cada VIGILANCIA_PERIODO_S
            # y de cada frame solo se hacen cosas baratas (~1,3 ms): mirar si
            # alguna capsula de nameplate ha cambiado, y si el cliente esta
            # mostrando los botones de accion. Asi el cartel de accion de un
            # rival, que dura menos de 1,5 s, no se pierde entre dos analisis.
            #
            # EL ANALISIS COMPLETO SE DISPARA POR SUCESOS, no por reloj. La idea
            # es del usuario: lo que importa para recomendar es que TE TOQUE A
            # TI, y eso se ve por los botones. Analizar cada N segundos "por si
            # acaso" gastaba ciclos en frames donde no habia nada que decidir y,
            # peor, casi nunca caia en el turno del hero: medido sobre 1.011
            # frames, tenia botones en 216 y la app solo leia `facing` en 89.
            #
            # El intervalo se queda como LATIDO de fondo, no como ritmo: cubre
            # todo lo que el lazo rapido no ve (que crezca el board, que acabe la
            # mano) y garantiza que el HUD no se congele si el detector de turno
            # se equivoca. Se cuenta DESDE QUE TERMINA el analisis, no desde que
            # empieza: contandolo desde el principio, un ciclo mas largo que el
            # intervalo se lo comia entero y el lazo rapido no corria NUNCA
            # (medido: 1,36 capturas rapidas por analisis en vez de las ~5).
            proximo_latido = 0.0
            while not self._stop.is_set():
                tick = time.monotonic()
                frame = stream.read(timeout_s=5.0)
                if frame is not None:
                    crop, err = self._crop_region(frame)
                    if err:
                        GLib.idle_add(self.win.on_error, err)
                    else:
                        motivo = self.analizador.tick(crop)
                        if motivo or time.monotonic() >= proximo_latido:
                            try:
                                self._analyze_and_publish(crop)
                            except Exception as e:  # noqa: BLE001
                                # el fallo de UN frame (OCR caido, timeout, imagen
                                # corrupta) no debe matar el hilo y dejar la UI
                                # muda: se reporta y se sigue con el siguiente.
                                GLib.idle_add(self.win.on_error,
                                              f"Fallo analizando el frame: {e}")
                            proximo_latido = time.monotonic() + self.ritmo.periodo_s
                # el periodo de VIGILANCIA es un periodo, no una pausa: se espera
                # solo lo que falte. Si el analisis se ha comido el tick entero,
                # no se espera nada y se vuelve a capturar de inmediato.
                resto = VIGILANCIA_PERIODO_S - (time.monotonic() - tick)
                if resto > 0:
                    self._stop.wait(resto)
        finally:
            self.analizador.cerrar()
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
        super().__init__(application=app, title="Poker Assistant — Mesa en directo")
        self.set_default_size(900, 820)
        self.set_size_request(440, 360)
        self.add_css_class("poker-app")
        self._install_css()
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
        self._ultimo_contexto_postflop = {}

        # Primero se construyen los bloques porque algunos (HUD, estado) se
        # enlazan desde la cabecera y la barra de controles.
        estado = self._build_state_frame()
        mano = self._build_hand_frame()
        equity = self._build_equity_frame()
        gto_panel = self._build_gto_frame()
        reco = self._build_recommendation_frame()
        anterior = self._build_prev_hand_frame()
        nota = self._build_note_frame()
        controles = self._build_controls()
        avisos = self._build_status_frame()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(root)
        root.append(self._build_header())
        root.append(controles)

        self.main_scroll = Gtk.ScrolledWindow()
        self.main_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.main_scroll.set_vexpand(True)
        self.main_scroll.set_propagate_natural_height(False)

        contenido = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        contenido.add_css_class("content")
        contenido.append(reco)
        # Justo debajo de la recomendacion: postflop es el unico momento en que
        # aquella se queda en blanco, asi que este panel ocupa su sitio en vez de
        # aparecer al final de un scroll.
        contenido.append(gto_panel)
        contenido.append(estado)

        # Mano formada y equity son dos lecturas relacionadas y secundarias.
        # Compartir renglón deja claro que describen la mano; no compiten con la
        # recomendación, que ocupa sola todo el ancho.
        self.insights_row = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        mano.set_hexpand(True)
        equity.set_hexpand(True)
        self.insights_row.append(mano)
        self.insights_row.append(equity)
        contenido.append(self.insights_row)

        contenido.append(anterior)
        contenido.append(nota)
        contenido.append(avisos)
        self.main_scroll.set_child(contenido)
        root.append(self.main_scroll)

        self.hud = False
        self._paneles_secundarios = (estado, anterior, nota, avisos)

        self._refresh_region_label()
        self.connect("close-request", self._on_close)

    @staticmethod
    def _install_css():
        provider = Gtk.CssProvider()
        provider.load_from_data(APP_CSS, -1)
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    @staticmethod
    def _panel(title, primary=False):
        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        panel.add_css_class("card")
        if primary:
            panel.add_css_class("primary-card")
        heading = Gtk.Label(label=title.upper())
        heading.set_halign(Gtk.Align.START)
        heading.set_xalign(0.0)
        heading.add_css_class("card-title")
        panel.append(heading)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        panel.append(body)
        return panel, body

    def _build_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        header.add_css_class("topbar")

        brand = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        brand.set_hexpand(True)
        title = Gtk.Label(label="Poker Assistant")
        title.set_halign(Gtk.Align.START)
        title.add_css_class("brand-title")
        self.header_subtitle = Gtk.Label(
            label="Decisiones claras · lectura de mesa en tiempo real")
        self.header_subtitle.set_halign(Gtk.Align.START)
        self.header_subtitle.add_css_class("brand-subtitle")
        brand.append(title)
        brand.append(self.header_subtitle)

        self.header_status_label = Gtk.Label(label="EN ESPERA")
        self.header_status_label.add_css_class("status-pill")
        self.header_status_label.add_css_class("status-idle")
        self.header_status_label.set_valign(Gtk.Align.CENTER)

        header.append(brand)
        header.append(self.header_status_label)
        return header

    def _set_run_state(self, text, css_class):
        for old in ("status-idle", "status-live", "status-error"):
            self.header_status_label.remove_css_class(old)
        self.header_status_label.add_css_class(css_class)
        self.header_status_label.set_text(text)

    def _build_state_frame(self):
        panel, box = self._panel("Mesa en directo")

        resumen = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.hero_label = self._markup_label(
            '<span size="small" foreground="#8b98a7">TUS CARTAS</span>\n'
            '<span size="x-large"><i>-</i></span>')
        self.board_label = self._markup_label(
            '<span size="small" foreground="#8b98a7">BOARD</span>\n'
            '<span size="x-large"><i>-</i></span>')
        self.pot_label = self._markup_label(
            '<span size="small" foreground="#8b98a7">BOTE</span>\n'
            '<span size="large"><i>-</i></span>')
        for widget in (self.hero_label, self.board_label, self.pot_label):
            widget.add_css_class("summary-tile")
            widget.set_hexpand(True)
            widget.set_halign(Gtk.Align.FILL)
            widget.set_valign(Gtk.Align.FILL)
            resumen.append(widget)

        self.state_details = Gtk.Expander(label="Jugadores y acciones observadas")
        self.state_details.set_expanded(False)
        detail_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        detail_box.set_margin_top(8)
        self.players_label = self._markup_label("<i>sin datos</i>")
        self.players_label.add_css_class("technical")
        # lo que se ha VISTO hacer en esta mano. Nunca es la lista completa: el
        # verbo dura menos que el periodo de muestreo (ver action_log).
        self.acciones_label = self._markup_label("")
        self.acciones_label.set_wrap(True)
        self.acciones_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.acciones_label.add_css_class("technical")
        detail_box.append(self.players_label)
        detail_box.append(self.acciones_label)
        self.state_details.set_child(detail_box)

        box.append(resumen)
        box.append(self.state_details)
        return panel

    def _build_hand_frame(self):
        panel, box = self._panel("Mano formada y proyectos")

        self.made_label = Gtk.Label()
        self.made_label.set_use_markup(True)
        self.made_label.set_halign(Gtk.Align.START)
        self.made_label.set_xalign(0.0)
        self.made_label.set_markup('<span size="large" weight="bold">-</span>')

        self.draws_label = self._markup_label("<i>-</i>")
        self.draws_label.set_wrap(True)
        self.draws_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        panel.set_tooltip_text(
            "Los porcentajes de proyectos indican la probabilidad de completarlos, "
            "no la probabilidad de ganar. La probabilidad de ganar aparece en Equity.")

        box.append(self.made_label)
        box.append(self.draws_label)
        self.hand_frame = panel
        panel.set_visible(False)
        return panel

    def _build_equity_frame(self):
        panel, box = self._panel("Equity estimada")

        self.eq_main_label = Gtk.Label()
        self.eq_main_label.set_use_markup(True)
        self.eq_main_label.set_halign(Gtk.Align.START)
        self.eq_main_label.set_xalign(0.0)

        self.eq_rivals_label = self._markup_label("")
        self.eq_effect_label = self._markup_label("")
        self.eq_odds_label = self._markup_label("")
        panel.set_tooltip_text(
            "Equity de all-in: supone que se ven todas las cartas sin más apuestas. "
            "Si hay una apuesta, el precio del call se muestra aparte; comparar "
            "ambas cifras sigue sin ser una recomendación de acción.")

        for w in (self.eq_rivals_label, self.eq_effect_label, self.eq_odds_label):
            w.set_wrap(True)
            w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.eq_main_label)
        box.append(self.eq_rivals_label)
        box.append(self.eq_effect_label)
        box.append(self.eq_odds_label)
        self.equity_frame = panel
        panel.set_visible(False)
        return panel

    def _build_gto_frame(self):
        """Guia postflop (decision/postflop_gto.py).

        Panel propio y no una linea mas en el de la recomendacion, porque su
        procedencia es OTRA: la recomendacion sale de rangos digitalizados y
        esto de heuristicas publicas aplicadas aqui. Mezclarlas en el mismo
        bloque haria que las dos parecieran tener el mismo respaldo."""
        panel, box = self._panel("Guía postflop (GTO)")

        self.gto_action_label = Gtk.Label()
        self.gto_action_label.set_use_markup(True)
        self.gto_action_label.set_halign(Gtk.Align.START)
        self.gto_action_label.set_xalign(0.0)

        self.gto_board_label = self._markup_label("")
        self.gto_math_label = self._markup_label("")
        self.gto_reason_label = self._markup_label("")
        panel.set_tooltip_text(
            "Heurísticas GTO públicas (GTO Wizard) aplicadas a este spot: alpha "
            "y MDF son exactos porque salen del bote y la apuesta; la frecuencia "
            "de c-bet es una banda derivada de una ordenación cualitativa, no una "
            "frecuencia de solver. No hay rango postflop digitalizado.")

        for w in (self.gto_board_label, self.gto_math_label, self.gto_reason_label):
            w.set_wrap(True)
            w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.gto_action_label)
        box.append(self.gto_board_label)
        box.append(self.gto_math_label)
        box.append(self.gto_reason_label)
        self.gto_frame = panel
        panel.set_visible(False)
        return panel

    def on_gto(self, guia):
        """Pinta la guia postflop. La accion va en AZUL, el color que esta app
        reserva para lo que viene de una guia publica y no de las tablas del
        usuario (ver on_result)."""
        if not guia:
            self.gto_frame.set_visible(False)
            return False
        self.gto_frame.set_visible(True)
        esc = GLib.markup_escape_text

        accion = guia.get("action_es") or guia.get("action_en") or guia.get("action")
        if accion:
            self.gto_action_label.set_markup(
                f'<span size="x-large" weight="bold" foreground="#38bdf8">'
                f'{esc(str(accion).upper())}</span>')
        else:
            self.gto_action_label.set_markup(
                '<span size="large" weight="bold" foreground="#8b98a7">'
                'SIN ACCIÓN PROPUESTA</span>')

        textura = guia.get("textura_texto") or ""
        posicion = {"IP": "en posición", "OOP": "fuera de posición"}.get(
            guia.get("posicion"), "posición desconocida")
        rivales = guia.get("rivales_vivos")
        self.gto_board_label.set_markup(
            f'<span size="small">Board: <b>{esc(textura)}</b> · {esc(posicion)}'
            f' · {rivales} rival{"es" if rivales != 1 else ""}</span>')

        self.gto_math_label.set_markup(self._gto_math_markup(guia))

        texto = guia.get("reasoning") or guia.get("motivo") or ""
        confianza = guia.get("confidence")
        bloque = esc(texto)
        if confianza:
            bloque += f'\n<i>Confianza — {esc(confianza)}</i>'
        self.gto_reason_label.set_markup(f'<span size="small">{bloque}</span>')
        return False

    @staticmethod
    def _gto_math_markup(guia):
        """La linea de cifras, distinta segun la rama. Vacia si no hay ninguna:
        preferible a un renglon de guiones que parezca un dato."""
        precio = guia.get("precio")
        if precio:
            texto = (
                f'Apuesta del rival <b>{precio["tamano_rival_pct"]:.0f}%</b> del bote '
                f'· necesitaba <b>{100 * precio["alpha_rival"]:.0f}%</b> de foldeos '
                f'(alpha) · defiendes como rango el <b>{100 * precio["mdf"]:.0f}%</b> '
                f'(MDF) · equilibrio '
                f'<b>{precio["ratio_valor_farol_equilibrado"]:g}:1</b> valor:farol'
                f'\nPrecio: pagas <b>{precio["pagar_bb"]:g} BB</b> y necesitas '
                f'<b>{100 * precio["equity_requerida"]:.0f}%</b>')
            if precio.get("margen_pp") is not None:
                texto += f' · margen <b>{precio["margen_pp"]:+.0f} puntos</b>'
            return f'<span size="small">{texto}</span>'

        cbet = guia.get("cbet")
        if cbet:
            tamano = (f' (<b>{cbet["tamano_bb"]:g} BB</b>)'
                      if cbet.get("tamano_bb") is not None else "")
            texto = f'Tamaño <b>{cbet["tamano_pct_del_bote"]}%</b> del bote{tamano}'
            # En turn y river no hay banda: la heuristica importada es de flop y
            # postflop_gto la omite en vez de extrapolarla. El renglon tiene que
            # sobrevivir a ese None, no pintar "None" ni quedarse en blanco.
            if cbet.get("banda_frecuencia"):
                texto += (
                    f' · frecuencia '
                    f'<b>{GLib.markup_escape_text(cbet["banda_frecuencia"])}</b> '
                    f'({GLib.markup_escape_text(cbet["banda_glosa"] or "")})')
            else:
                texto += (
                    ' · <i>sin banda de frecuencia: la heurística es de flop</i>')
            if cbet.get("ratio_valor_farol") is not None:
                texto += (
                    f'\nA ese tamaño: necesita <b>{100 * cbet["alpha"]:.0f}%</b> de '
                    f'foldeos · mezcla <b>{cbet["ratio_valor_farol"]:g}:1</b> '
                    f'valor:farol')
            return f'<span size="small">{texto}</span>'
        return ""

    def on_ritmo(self, texto):
        """Lo que esta tardando de verdad, en la ventana. Sustituye al selector de
        intervalo: el usuario deja de elegir un numero que no describia nada y
        pasa a VER el que hay. Ver core.analisis.Ritmo."""
        self.ritmo_label.set_text(texto)
        return False

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

        odds = eq.get("pot_odds")
        if odds:
            requerido = 100 * odds["required_equity"]
            texto = (
                f'Precio del call: pagar <b>{odds["call_bb"]:g} BB</b> para un bote '
                f'final de <b>{odds["final_pot_bb"]:g} BB</b> · necesita '
                f'<b>{requerido:.0f}%</b> de equity')
            if odds.get("current_spr") is not None:
                texto += (
                    f' · SPR actual <b>{odds["current_spr"]:g}</b> '
                    f'({odds["effective_stack_bb"]:g} BB efectivos)')
            if odds.get("raw_margin_pp") is not None:
                margen = odds["raw_margin_pp"]
                texto += (
                    f'\nEquity bruta frente al precio: '
                    f'<b>{margen:+.0f} puntos</b>')
            texto += (
                '\n<span foreground="#f39c12"><i>Orientativo: la equity supone '
                'check-down y no ajusta el rango rival a esta apuesta; no equivale '
                'a CALL/FOLD.</i></span>')
            self.eq_odds_label.set_markup(
                f'<span size="small">{texto}</span>')
            self.eq_odds_label.set_visible(True)
        else:
            self.eq_odds_label.set_markup("")
            self.eq_odds_label.set_visible(False)
        return False

    def _build_recommendation_frame(self):
        panel, box = self._panel("Decisión recomendada", primary=True)

        self.rec_label = Gtk.Label()
        self.rec_label.set_use_markup(True)
        self.rec_label.set_markup('<span size="xx-large" weight="bold">-</span>')
        self.rec_label.set_halign(Gtk.Align.START)

        self.reasoning_label = self._markup_label('<i>pulsa "Iniciar analisis" para empezar</i>')
        self.reasoning_label.set_wrap(True)
        self.reasoning_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.reasoning_label.add_css_class("muted")

        box.append(self.rec_label)
        box.append(self.reasoning_label)
        return panel

    def _build_prev_hand_frame(self):
        panel, box = self._panel("Última mano")

        self.prev_main_label = self._markup_label("<i>sin manos terminadas todavia</i>")
        self.prev_showdown_label = self._markup_label("")
        self.prev_hero_label = self._markup_label("")
        # hueco preparado para el coaching (Fase 4.3): NO se implementa aqui, va
        # el RAG postflop + historial de acciones, una pieza mayor aparte.
        self.prev_coach_label = self._markup_label("")
        for optional in (self.prev_showdown_label, self.prev_hero_label,
                         self.prev_coach_label):
            optional.set_visible(False)

        for w in (self.prev_main_label, self.prev_showdown_label,
                  self.prev_hero_label, self.prev_coach_label):
            w.set_wrap(True)
            w.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            box.append(w)
        return panel

    def _build_note_frame(self):
        """Marcar una situacion rara y anotarla, para revisarla despues con el
        frame y todo lo calculado delante.

        Va en DOS PASOS a proposito, y ahi esta todo el diseño: el usuario ve la
        rareza y LUEGO escribe. Con el ciclo en ~1,2 s, para cuando termina la
        frase han pasado varios frames y el panel ya muestra otro; una nota
        asociada al frame del momento de guardar apuntaria al frame equivocado.
        Asi que "Marcar situacion" fija de inmediato el frame que se esta viendo
        y el texto se aplica a ese, se tarde lo que se tarde en escribirlo."""
        panel, box = self._panel("Anotar una situación")

        fila = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.mark_button = Gtk.Button(label="Marcar ahora")
        self.mark_button.add_css_class("secondary-action")
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

        self.nota_button = Gtk.Button(label="Guardar")
        self.nota_button.add_css_class("secondary-action")
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
        return panel

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
                    interval=self.default_interval, prefix="notas")
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
        # En 420 px los selectores y el calibrador consumirían más altura que la
        # propia recomendación. El modo compacto conserva solo iniciar/detener y
        # el interruptor para volver; la configuración reaparece intacta al salir.
        self.settings_row.set_visible(not self.hud)
        self.calibrate_button.set_visible(not self.hud)
        self.ritmo_label.set_visible(not self.hud)
        self.header_subtitle.set_visible(not self.hud)
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
            self.set_default_size(460, 360)
        else:
            self.set_default_size(900, 820)

    def _build_controls(self):
        columna = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        columna.add_css_class("toolbar")
        acciones = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ajustes = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Modo HUD: se esconde todo menos lo que se mira en plena mano.
        self.hud_check = Gtk.CheckButton(label="HUD compacto")
        self.hud_check.set_tooltip_text(
            "Deja solo la recomendacion, la equity y la mano actual, y pone la "
            "ventana encima. Para tenerla al lado de la mesa mientras juegas.")
        self.hud_check.connect("toggled", self._on_hud)

        self.start_button = Gtk.Button(label="Iniciar análisis")
        self.start_button.add_css_class("primary-action")
        self.start_button.connect("clicked", self._on_toggle)

        self.calibrate_button = Gtk.Button(label="Calibrar captura")
        self.calibrate_button.add_css_class("secondary-action")
        self.calibrate_button.connect("clicked", self._on_calibrate)

        # Tamaño de mesa. Hace DOS cosas, y las dos importan: acota cuantos
        # asientos puede haber -las posiciones salen del RECUENTO de ocupados,
        # asi que un asiento fantasma las desplaza TODAS- y elige la GEOMETRIA,
        # o sea DONDE estan (ver seat_map.zonas).
        #
        # "AUTO" HA VUELTO, y esta vez detecta de verdad. Se quito en su dia con
        # razon: entonces solo queria decir "no acotes y usa la disposicion de 6",
        # asi que en una mesa de 8 leia 4,69 asientos de 8 y 2 nicks de 10 sin
        # avisar de nada. Ahora mira DONDE caen los nameplates del tapete y lo
        # contrasta con las tres geometrias medidas (vision/disposicion.py): sobre
        # las 29 sesiones grabadas con disposicion conocida acierta 20, se
        # abstiene en 9 y NO se equivoca en ninguna. Cuando se abstiene se queda
        # con la de 6 y lo dice en los avisos, que es lo que la version vieja no
        # hacia.
        mesa_label = Gtk.Label(label="MESA")
        mesa_label.add_css_class("field-label")
        self.mesa_combo = Gtk.ComboBoxText()
        for etiqueta in ("Auto (la lee del tapete)", "2 (heads-up)", "3-Max",
                         "6-Max", "8-Max", "9 plazas"):
            self.mesa_combo.append_text(etiqueta)
        self.mesa_combo.set_active(self._MESA_OPCIONES.index(None))
        self.mesa_combo.set_tooltip_text(
            "Cuantas plazas tiene la mesa. Ademas de acotar el recuento, decide "
            "DONDE se buscan los asientos. Hay geometria medida para 6, 8 y 9; 2 y "
            "3 usan la de 6, que es la que habia.\n\n"
            "Auto la deduce de donde caen los nameplates y se abstiene si no lo "
            "tiene claro (entonces usa la de 6 y avisa). Elegirla a mano sigue "
            "mandando: si la eliges, Auto no toca nada, pero te avisa si lo que ve "
            "no cuadra con lo que has elegido.")

        # EL RITMO SE VE, NO SE ELIGE. Antes habia aqui un spin de 0,25 a 10 s
        # cuyo numero no describia nada: 8 de sus 40 valores son fisicamente
        # imposibles -el ciclo tarda 0,72 s de mediana- y el periodo real nunca
        # fue el elegido, porque se cuenta desde que TERMINA el analisis (pidiendo
        # 1,0 s la app analizaba cada 1,6-1,9 s). Ver core.analisis.Ritmo.
        self.ritmo_label = Gtk.Label(label="Ritmo: sin analizar")
        self.ritmo_label.set_tooltip_text(
            "Lo que esta tardando de verdad, medido sobre los ultimos analisis. "
            "El analisis se dispara cuando pasa algo (te toca a ti, cambia la "
            "mesa); el latido es solo el suelo, para que el HUD no se congele. "
            "Se puede fijar con --interval para reproducir una sesion vieja.")

        # MAZO. Lo pidio el usuario: "añade una opcion en la GUI para que yo te
        # diga que mazo estoy usando, asi vas directo al tema". Y el dato le da la
        # razon: cuando los dos detectores compiten se equivocan, y no de forma
        # visible. En la sesion del 29-07 a las 20:12 elegian "fondo de color" en
        # cartas del otro mazo, el calco de plantillas solo acertaba 24 de 177 y
        # el 8 salia al 1,3% de las lecturas cuando le toca el 7,7%.
        #
        # Se conserva "Auto" para diagnóstico y cambios de mazo, pero la ruta
        # normal arranca directamente en el mazo que se usa ahora: evita ejecutar
        # dos detectores y que una hipótesis ajena gane por cajas espurias.
        mazo_label = Gtk.Label(label="BARAJA")
        mazo_label.add_css_class("field-label")
        self.mazo_combo = Gtk.ComboBoxText()
        for etiqueta in ("Fondo de color", "Cara blanca", "Mazo: auto"):
            self.mazo_combo.append_text(etiqueta)
        self.mazo_combo.set_active(0)
        self.mazo_combo.set_tooltip_text(
            "Que baraja tienes puesta en el cliente. 'Cara blanca' es la de fondo "
            "blanco con el numero en el color del palo; 'Fondo de color' la de "
            "fondo pintado con el numero en blanco, que es la opción principal. "
            "Con auto se prueban las dos y gana la que encuentre más cartas.")

        # Modo testing: graba cada frame junto con todo lo que se calculo de el,
        # emparejados por nombre, en testing/sesion-<fecha>/. Es un CheckButton y
        # no un boton aparte a proposito: la grabacion acompaña al analisis (se
        # decide antes de darle a "Iniciar"), no es un proceso independiente que
        # se pueda encender y apagar a mitad y dejar una sesion a trozos.
        self.testing_check = Gtk.CheckButton(label="Grabar diagnóstico")
        self.testing_check.set_tooltip_text(
            "Guarda cada captura y sus resultados en testing/sesion-<fecha>/, "
            "en duplas 0001.png + 0001.json, para revisar despues por que la app "
            "dijo lo que dijo. Se activa al iniciar el analisis.")

        acciones.append(self.start_button)
        acciones.append(self.hud_check)
        acciones.append(self.calibrate_button)

        # El ritmo es estado, no configuración. Se alinea a la derecha de las
        # acciones principales y deja de mezclarse con los selectores.
        self.ritmo_label.set_halign(Gtk.Align.START)
        self.ritmo_label.set_hexpand(True)
        self.ritmo_label.set_halign(Gtk.Align.END)
        self.ritmo_label.add_css_class("muted")
        acciones.append(self.ritmo_label)

        ajustes.append(mesa_label)
        ajustes.append(self.mesa_combo)
        ajustes.append(mazo_label)
        ajustes.append(self.mazo_combo)
        ajustes.append(self.testing_check)

        columna.append(acciones)
        columna.append(ajustes)
        self.settings_row = ajustes
        return columna

    def _build_status_frame(self):
        panel, box = self._panel("Sistema y diagnóstico")

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
        return panel

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
            self.start_button.set_label("Deteniendo…")
            self.start_button.set_sensitive(False)
            self._set_run_state("DETENIENDO", "status-idle")
            if self.worker:
                self.worker.stop()
        else:
            self.running = True
            self.start_button.set_label("Detener análisis")
            self.calibrate_button.set_sensitive(False)
            self.testing_check.set_sensitive(False)
            self.mesa_combo.set_sensitive(False)
            self.mazo_combo.set_sensitive(False)
            self.status_label.set_markup("Iniciando...")
            self._set_run_state("INICIANDO", "status-live")
            intervalo = self.default_interval

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
                    # el tamaño de mesa fijado va en los metadatos: al revisar la
                    # sesion despues, saber si estaba en auto o en 3-Max explica
                    # la mitad de lo que se vea (ver revisar_sesion.py)
                    self.sesion.meta["max_players"] = self._max_players()
                    # EL MAZO TAMBIEN VA A LA META, por el mismo motivo que las
                    # plazas: sin el, reproducir la sesion despues no la reproduce
                    # -deja que compitan los dos detectores donde el usuario habia
                    # fijado uno- y la regresion de oro compara dos apps distintas.
                    self.sesion.meta["mazo"] = self._mazo()
                    self.sesion.meta["vigilancia_periodo_s"] = VIGILANCIA_PERIODO_S
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
                                         max_players=self._max_players(),
                                         mazo=self._mazo())
            self.worker.start()

    # MISMO ORDEN QUE EL COMBO. Ademas de acotar cuantos asientos puede haber,
    # esto elige la GEOMETRIA: seat_map tiene tabla medida para 6, 8 y 9, y para
    # el resto usa la de 6 (ver seat_map.zonas). En una mesa de 8 con la tabla de
    # 6 no es que falten dos asientos: los laterales caen en el hueco entre los
    # de verdad y se pierden DOS jugadores por lado.
    #
    # None = "Auto": la disposicion la decide vision/disposicion.py mirando el
    # tapete. Va la PRIMERA porque es lo que uno quiere por defecto: acierta o se
    # abstiene, nunca elige mal. Ver el combo.
    _MESA_OPCIONES = (None, 2, 3, 6, 8, 9)

    # mismo orden que el combo de mazo; None = diagnóstico con ambos detectores
    _MAZO_OPCIONES = ("solid", "glyph", None)

    def _mazo(self):
        i = self.mazo_combo.get_active()
        return self._MAZO_OPCIONES[i] if 0 <= i < len(self._MAZO_OPCIONES) else "solid"

    def _max_players(self):
        """Las plazas elegidas, o None si se deja en "Auto" (que es el arranque).

        None NO significa "no acotes": significa "la lee del tapete". Quien la lee
        es vision/disposicion.py, y mientras no tenga evidencia suficiente se
        sigue usando la de 6 y se avisa en los mensajes. Si GTK devolviera -1
        (nada seleccionado, que no deberia pasar) tambien sale None, que es el
        modo mas conservador de los dos."""
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
                subprocess.run([sys.executable, "-m", SELECT_REGION_MODULE], cwd=BASE_DIR)
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
        self._set_run_state("ERROR", "status-error")
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
        self.start_button.set_label("Iniciar análisis")
        self.start_button.set_sensitive(True)
        self.calibrate_button.set_sensitive(True)
        self.testing_check.set_sensitive(True)
        self.mesa_combo.set_sensitive(True)
        self.mazo_combo.set_sensitive(True)
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
        self._set_run_state("EN ESPERA", "status-idle")
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
        self._set_run_state("ANALIZANDO", "status-live")
        # cachea el nombre del hero (ultimo no-nulo del asiento is_hero): su
        # nameplate a veces muestra la accion ("Igualar"/"Pasar") en vez del
        # nombre, asi que solo se actualiza cuando hay nombre.
        for p in state.get("players") or []:
            if p.get("is_hero") and p.get("name"):
                self._hero_name = p["name"]
                break

        self.hero_label.set_markup(
            '<span size="small" foreground="#8b98a7">TUS CARTAS</span>\n'
            f'<span size="x-large">{cards_markup(state.get("hero_cards"))}</span>')
        self.board_label.set_markup(
            '<span size="small" foreground="#8b98a7">BOARD</span>\n'
            f'<span size="x-large">{cards_markup(state.get("board")) if state.get("board") else "<i>Preflop</i>"}</span>')
        pot = state.get("pot")
        pot_text = GLib.markup_escape_text(str(pot)) if pot is not None else "<i>-</i>"
        self.pot_label.set_markup(
            '<span size="small" foreground="#8b98a7">BOTE</span>\n'
            f'<span size="large" weight="bold">{pot_text}</span>')
        if state.get("board"):
            self._ultimo_board = list(state["board"])
            self._ultimo_contexto_postflop = postmano.contexto_desde_estado(
                state, hand)
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
        # state["gto"] ya viene con equity: analizar() corre decide() Y
        # postflop_equity antes de publicar, y la segunda pisa la guia que dejo
        # la primera (ver engine.guia_postflop).
        self.on_gto(state.get("gto"))

        if recommendation:
            # La interfaz está en castellano: la acción legible va primero y el
            # código inglés de la tabla queda como referencia secundaria.
            esc = GLib.markup_escape_text
            en = recommendation.get("action_en") or str(recommendation["action"]).upper()
            es = recommendation.get("action_es")
            # Una accion DERIVADA (Fase E) es indistinguible a simple vista de una
            # que sale de sus tablas -"CHECK" es "CHECK"-, asi que se distingue por
            # color y con una linea propia que nombra la celda donante. El verde se
            # reserva para las capturas originales; una guía pública separada va
            # en azul para que su procedencia tampoco quede oculta.
            source = recommendation.get("source")
            derivada = source == "derived"
            suplementaria = source == "supplemental_chart"
            color = ("#f39c12" if derivada else
                     "#38bdf8" if suplementaria else
                     "#2ecc71")
            principal = str(es or en).upper()
            markup = (
                f'<span size="xx-large" weight="bold" foreground="{color}">'
                f'{esc(principal)}</span>')
            if es and en:
                markup += (
                    f'\n<span size="small" foreground="#8b98a7">'
                    f'Código de tabla: {esc(en)}</span>')
            if derivada:
                markup += (f'\n<span size="small" foreground="#f39c12">inferido de '
                           f'{esc(str(recommendation.get("donor") or "otra celda tuya"))}'
                           f' — confianza {esc(str(recommendation.get("confidence") or "?"))}'
                           f'</span>')
            elif suplementaria:
                markup += (
                    f'\n<span size="small" foreground="#38bdf8">'
                    f'guía pública complementaria: '
                    f'{esc(str(recommendation.get("source_name") or "rango suplementario"))}'
                    f'</span>')
            self.rec_label.set_markup(markup)
            reasoning = recommendation.get("reasoning") or ""
            self.reasoning_label.set_markup(GLib.markup_escape_text(reasoning))
        else:
            self.rec_label.set_markup(
                '<span size="x-large" weight="bold" foreground="#8b98a7">'
                'SIN ACCIÓN DISPONIBLE</span>')
            reason = self._no_reco_reason(state)
            self.reasoning_label.set_markup(
                f'<span foreground="#f39c12"><i>{GLib.markup_escape_text(reason)}</i></span>')

        warnings = state.get("warnings") or []
        self.warnings_label.set_markup(
            ("<b>Avisos</b>\n" + GLib.markup_escape_text("\n• ".join(
                ["• " + warnings[0], *warnings[1:]]))) if warnings else
            '<span foreground="#6ee7a7">Sin avisos activos.</span>')
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
        # y despues, con el selector en "Auto", el rato en que todavia no se sabe
        # que mesa es. Ahi el motor NO recomienda a proposito (ver
        # core.Analizador.analizar): se estaria mirando con la disposicion de 6
        # sin saber si es la que toca, y las posiciones salen del recuento de
        # asientos. Se dice aqui y no como aviso suelto porque es LA razon de que
        # el panel este en blanco, y dura unos segundos al arrancar.
        # se exige que el campo EXISTA -lo pone siempre el pipeline real- para no
        # confundir "en Auto y sin decidir" con "este estado no habla de mesas"
        if ("disposicion_detectada" in state
                and state.get("max_players") is None
                and state["disposicion_detectada"] is None):
            return ("Mirando que mesa es (los nameplates dicen donde estan las plazas). "
                    "Hasta saberlo no se recomienda: con la disposicion equivocada las "
                    "posiciones salen mal y la recomendacion seria convincente y falsa. "
                    "Si tienes prisa, elige el tamaño en el selector 'Mesa'.")
        # y lo segundo, porque es un ajuste que el usuario arregla en dos segundos
        # y sin el no hay NI UNA recomendacion: haber fijado un tamaño de mesa que
        # no es el de la mesa en la que se esta sentado. Sin nombrarlo aqui, el
        # sintoma es "no dice nada" y no hay forma de adivinar la causa.
        for w in state.get("warnings") or []:
            if "asientos ocupados en una mesa de" in w:
                return (w + ". Cambia el selector 'Mesa' de la barra de abajo al tamaño "
                        "real, o ponlo en 'auto'.")
        cards = state.get("hero_cards") or []
        players = state.get("players") or []
        if not players and not cards:
            return ("No se detecta una mesa de poker (¿estas en el lobby o fuera de una mano?). "
                    "La app solo recomienda con una mesa activa en pantalla.")
        if state.get("board"):
            base = ("Postflop: no hay rango postflop digitalizado, asi que este panel "
                    "-que es el de tus tablas- no propone accion.")
            guia = state.get("gto") or {}
            if guia.get("action"):
                return (base + " La propuesta postflop va en el panel 'Guia postflop "
                        "(GTO)': sale de heuristicas publicas aplicadas al bote y a la "
                        "textura del board, no de una celda tuya.")
            if guia.get("motivo"):
                return f"{base} La guia postflop tampoco propone accion: {guia['motivo']}."
            return (base + " Lo que si hay es la equity estimada — pero es una "
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
        self.prev_showdown_label.set_visible(bool(opps))

        outcome = hr.hero_outcome(result, self._hero_name)
        if outcome["status"] == "won":
            body = ("Ganaste esta mano con: " + esc(outcome["hero_hand"])
                    if outcome["hero_hand"] else "Ganaste esta mano")
            self.prev_hero_label.set_markup(f'<span foreground="#2ecc71" weight="bold">{body}</span>')
            self.prev_hero_label.set_visible(True)
        elif outcome["status"] == "split":
            body = ("Empataste el bote con: " + esc(outcome["hero_hand"])
                    if outcome["hero_hand"] else "Empataste el bote")
            self.prev_hero_label.set_markup(f'<span foreground="#3498db" weight="bold">{body}</span>')
            self.prev_hero_label.set_visible(True)
        elif outcome["status"] == "lost":
            body = ("Perdiste con: " + esc(outcome["hero_hand"])
                    if outcome["hero_hand"] else "Perdiste esta mano")
            self.prev_hero_label.set_markup(f'<span foreground="#e74c3c" weight="bold">{body}</span>')
            self.prev_hero_label.set_visible(True)
        else:
            # sin evidencia de si el hero jugo la mano: no se afirma nada
            self.prev_hero_label.set_markup("")
            self.prev_hero_label.set_visible(False)

        # ESTUDIO POST-MANO (Fase 4.4). Se lanza en un hilo porque la primera
        # consulta carga el modelo de embeddings y tarda segundos; la mano ya ha
        # terminado, asi que la latencia no importa.
        self.prev_coach_label.set_markup(
            '<span size="small" foreground="#95a5a6"><i>buscando videos sobre '
            'situaciones parecidas...</i></span>')
        self.prev_coach_label.set_visible(True)
        # SE VACIA AL CONSUMIRLO. Es el board de la mano que acaba de terminar y
        # solo sirve para este estudio; si se queda puesto, la siguiente mano que
        # termine sin haber llegado a leer board -todos se retiran preflop, que es
        # lo normal- estudiaria el board de la mano ANTERIOR y lo presentaria como
        # suyo. Al abrir mano no se vacia nada: el board de la mano que se cierra
        # hace falta justo aqui, despues de la frontera.
        board, self._ultimo_board = list(self._ultimo_board), []
        contexto, self._ultimo_contexto_postflop = (
            dict(self._ultimo_contexto_postflop), {})
        ganadora = result.get("winning_hand")
        showdown = bool(result.get("showdown"))
        threading.Thread(target=self._buscar_estudio,
                         args=(board, ganadora, showdown, contexto),
                         daemon=True).start()
        return False

    def _buscar_estudio(self, board, ganadora, showdown, contexto=None):
        try:
            r = postmano.estudiar(board=board, mano_ganadora=ganadora,
                                  hero_en_showdown=showdown,
                                  contexto=contexto)
        except Exception:  # noqa: BLE001 - estudiar nunca puede tumbar la UI
            r = None
        GLib.idle_add(self.on_estudio, r)

    def on_estudio(self, r):
        """Pinta fichas condicionadas y referencias semánticas de estudio.

        Ninguna entra en el motor live. Las fichas tienen condiciones
        verificables; los vídeos siguen presentándose solo como situaciones
        parecidas y enlazadas a su fuente.
        """
        fichas = (r or {}).get("fichas") or []
        refs = (r or {}).get("referencias") or []
        problema = (r or {}).get("problema")
        if not fichas and not refs and problema:
            self.prev_coach_label.set_markup(
                '<span size="small" foreground="#f39c12"><b>Estudio no disponible:</b> '
                f'{GLib.markup_escape_text(problema)}</span>')
            return False
        if not fichas and not refs:
            self.prev_coach_label.set_markup(
                '<span size="small" foreground="#95a5a6"><i>Sin videos que se parezcan '
                'lo bastante a esta mano.</i></span>')
            return False
        esc = GLib.markup_escape_text
        lineas = []
        if fichas:
            lineas.append(
                '<span size="small" foreground="#95a5a6"><b>Claves para '
                'revisar este spot</b> · estudio postmano, no orden live:</span>')
        for ficha in fichas:
            source = ficha.get("source") or {}
            source_name = source.get("name") or "fuente"
            source_url = source.get("url")
            video_path = source.get("video_path")
            source_link = esc(source_name)
            href = source_url
            if not href and video_path:
                try:
                    href = Path(video_path).as_uri()
                except ValueError:
                    href = None
            if href:
                source_link = f'<a href="{esc(href)}">{source_link}</a>'
            timestamp = source.get("timestamp_s")
            if timestamp is not None:
                source_link += f' · {esc(postmano.minuto(timestamp))}'
            lineas.append(
                f'<span size="small">&#8226; <b>{esc(ficha.get("title") or "")}</b>'
                f' · {source_link}</span>')
            lineas.append(
                f'<span size="small" foreground="#c4ccd4">  '
                f'{esc(ficha.get("principle") or "")}</span>')
            consider = ficha.get("consider") or []
            if consider:
                lineas.append(
                    f'<span size="small" foreground="#8b98a7">  Revisar: '
                    f'{esc(" · ".join(consider[:2]))}</span>')
            limits = ficha.get("limits") or []
            if limits:
                lineas.append(
                    f'<span size="small" foreground="#7f8c8d"><i>  Límite: '
                    f'{esc(limits[0])}</i></span>')
        if refs:
            if lineas:
                lineas.append("")
            lineas.append(
                '<span size="small" foreground="#95a5a6">Vídeos con situaciones '
                '<i>parecidas</i> (no analizan esta mano):</span>')
        for x in refs:
            nombre = x.get("title") or (x["video"] or "").replace("_", " ")
            if len(nombre) > 70:
                nombre = nombre[:70] + "..."
            ruta = x.get("video_path")
            titulo = esc(nombre)
            if ruta:
                try:
                    titulo = f'<a href="{esc(Path(ruta).as_uri())}">{titulo}</a>'
                except ValueError:
                    pass
            extracto = " ".join((x.get("texto") or "").split())
            if len(extracto) > 180:
                extracto = extracto[:177].rsplit(" ", 1)[0] + "..."
            lineas.append(
                f'<span size="small">&#8226; {titulo} '
                f'<b>{esc(postmano.minuto(x["inicio_s"]))}</b>'
                f' · similitud {100 * x["score"]:.0f}%</span>')
            if extracto:
                lineas.append(
                    f'<span size="small" foreground="#8b98a7">  {esc(extracto)}</span>')
        if problema:
            lineas.append(
                '<span size="small" foreground="#f39c12"><i>Referencias '
                f'semánticas no disponibles: {esc(problema)}</i></span>')
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
    # POR DEFECTO NO HAY INTERVALO: el latido se mide en caliente y se enseña en
    # la ventana (ver core.analisis.Ritmo). Esta opcion es la salida de
    # emergencia, para reproducir la cadencia de una sesion vieja; no esta en la
    # ventana a proposito, porque volver a ponerla ahi seria volver a pedirle al
    # usuario un numero que no puede saber.
    parser.add_argument("--interval", type=float, default=None,
                        help="fija el latido en segundos en vez de medirlo "
                             "(para reproducir una sesion grabada con otra cadencia)")
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
