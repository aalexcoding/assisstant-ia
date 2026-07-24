"""
Fase 5: panel de control GTK4. Envuelve el mismo flujo que alpha.py (captura
via portal_capture, recorte al recuadro de calibration/config.local.json,
table_state.analyze_layout -> GameState, engine.decide -> recomendacion) pero
en una ventana no bloqueante: la UI corre en el hilo principal (GLib main
loop) y el analisis (captura + OCR, ~1-2s por frame) corre en un hilo aparte
que actualiza los widgets via GLib.idle_add (GTK no es thread-safe).

El campo de ciegas escribe blinds.local.json en la raiz con el mismo formato
que ./set-blinds, asi que engine.decide lo recoge en cada analisis sin
reiniciar. "Recalibrar recuadro" lanza calibration/select_region.py como
subproceso y recarga el recuadro al volver.

Uso: .venv/bin/python gui.py [--interval SEGUNDOS] [--self-test]
"""
import argparse
import json
import os
import subprocess
import sys
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, "capture"))
sys.path.insert(0, os.path.join(BASE_DIR, "vision"))
sys.path.insert(0, os.path.join(BASE_DIR, "decision"))
sys.path.insert(0, os.path.join(BASE_DIR, "decision", "preflop"))

import cv2

import engine
import hand_strength as hstr
import portal_capture as pc
import table_state as ts

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango

CALIBRATION_PATH = os.path.join(BASE_DIR, "calibration", "config.local.json")
SELECT_REGION_PATH = os.path.join(BASE_DIR, "calibration", "select_region.py")
BLINDS_PATH = os.path.join(BASE_DIR, "blinds.local.json")
TMP_FRAME_PATH = "/tmp/poker_gui_frame.png"

SUIT_SYMBOLS = {"h": "♥", "d": "♦", "c": "♣", "s": "♠"}
SUIT_COLORS = {"h": "#e74c3c", "d": "#3498db", "c": "#2ecc71", "s": "#95a5a6"}


def load_region():
    with open(CALIBRATION_PATH) as f:
        region = json.load(f)["capture_region"]
    return region["x"], region["y"], region["width"], region["height"]


def read_blinds():
    try:
        with open(BLINDS_PATH) as f:
            data = json.load(f)
        return {"sb": data.get("sb", 0), "bb": data.get("bb"), "ante": data.get("ante", 0)}
    except (FileNotFoundError, ValueError):
        return None


def write_blinds(sb, bb, ante):
    with open(BLINDS_PATH, "w") as f:
        json.dump({"sb": int(sb), "bb": int(bb), "ante": int(ante)}, f)
        f.write("\n")


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
        name = p["name"] if p.get("name") else "(?)"
        pos = f" [{p['position']}]" if p.get("position") else ""
        stack = p["stack"] if p.get("stack") is not None else "?"
        mark = "  <b>(TU)</b>" if p.get("is_hero") else ""
        lines.append(f"{GLib.markup_escape_text(str(name))}{GLib.markup_escape_text(pos)}: "
                     f"{GLib.markup_escape_text(str(stack))}{mark}")
    return "\n".join(lines)


class AnalysisWorker(threading.Thread):
    """Hilo de analisis: abre el stream, lee frames, recorta, analiza y
    manda cada resultado a la ventana via GLib.idle_add. No toca widgets."""

    def __init__(self, win, interval):
        super().__init__(daemon=True)
        self.win = win
        self.interval = interval
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def _log(self, msg):
        GLib.idle_add(self.win.on_status, msg)

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
            while not self._stop.is_set():
                frame = stream.read(timeout_s=5.0)
                if frame is not None:
                    try:
                        x, y, w, h = load_region()
                    except (FileNotFoundError, ValueError, KeyError):
                        GLib.idle_add(self.win.on_status, "No se pudo leer el recuadro de calibracion.")
                        self._stop.wait(self.interval)
                        continue
                    crop = frame[y:y + h, x:x + w]
                    cv2.imwrite(TMP_FRAME_PATH, crop)
                    state = ts.analyze_layout(TMP_FRAME_PATH)
                    recommendation = engine.decide(state)
                    hand = hstr.evaluate_hand(state.get("hero_cards"), state.get("board"))
                    GLib.idle_add(self.win.on_result, state, recommendation, hand)
                self._stop.wait(self.interval)
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
        self.set_default_size(520, 640)
        self.worker = None
        self.running = False
        self.default_interval = interval

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(16)
        root.set_margin_bottom(16)
        root.set_margin_start(16)
        root.set_margin_end(16)
        self.set_child(root)

        root.append(self._build_state_frame())
        root.append(self._build_hand_frame())
        root.append(self._build_recommendation_frame())
        root.append(self._build_blinds_frame())
        root.append(self._build_controls())
        root.append(self._build_status_frame())

        self._load_blinds_into_entries()
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

        for w in (self.hero_label, self.board_label, self.pot_label, players_title, self.players_label):
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
            'no de ganar la mano.</i></span>')
        note.set_wrap(True)
        note.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.made_label)
        box.append(self.draws_label)
        box.append(note)
        frame.set_child(box)
        self.hand_frame = frame
        frame.set_visible(False)
        return frame

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

    def _build_blinds_frame(self):
        frame = Gtk.Frame(label="Ciegas (manda sobre lo detectado; escribe blinds.local.json)")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)

        self.entry_sb = self._blind_entry("SB")
        self.entry_bb = self._blind_entry("BB")
        self.entry_ante = self._blind_entry("ante")
        save = Gtk.Button(label="Guardar ciegas")
        save.connect("clicked", self._on_save_blinds)

        box.append(Gtk.Label(label="SB"))
        box.append(self.entry_sb)
        box.append(Gtk.Label(label="BB"))
        box.append(self.entry_bb)
        box.append(Gtk.Label(label="ante"))
        box.append(self.entry_ante)
        box.append(save)
        frame.set_child(box)
        return frame

    def _build_controls(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        self.start_button = Gtk.Button(label="Iniciar analisis")
        self.start_button.connect("clicked", self._on_toggle)

        self.calibrate_button = Gtk.Button(label="Recalibrar recuadro")
        self.calibrate_button.connect("clicked", self._on_calibrate)

        interval_label = Gtk.Label(label="Intervalo (s)")
        self.interval_spin = Gtk.SpinButton.new_with_range(0.25, 10.0, 0.25)
        self.interval_spin.set_digits(2)
        self.interval_spin.set_value(self.default_interval)

        box.append(self.start_button)
        box.append(self.calibrate_button)
        box.append(interval_label)
        box.append(self.interval_spin)
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
        self.warnings_label = self._markup_label("")
        self.warnings_label.set_wrap(True)
        self.warnings_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

        box.append(self.region_label)
        box.append(self.status_label)
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

    @staticmethod
    def _blind_entry(placeholder):
        entry = Gtk.Entry()
        entry.set_max_width_chars(6)
        entry.set_width_chars(6)
        entry.set_placeholder_text(placeholder)
        entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        return entry

    def _load_blinds_into_entries(self):
        b = read_blinds()
        if b:
            self.entry_sb.set_text(str(b.get("sb") or 0))
            if b.get("bb"):
                self.entry_bb.set_text(str(b["bb"]))
            self.entry_ante.set_text(str(b.get("ante") or 0))

    def _refresh_region_label(self):
        try:
            x, y, w, h = load_region()
            self.region_label.set_markup(f"Recuadro: x={x} y={y} {w}x{h}")
        except (FileNotFoundError, ValueError, KeyError):
            self.region_label.set_markup('Recuadro: <span foreground="#e67e22">sin calibrar</span>')

    def _on_save_blinds(self, _btn):
        def parse(entry, default=0):
            txt = entry.get_text().strip()
            if not txt:
                return default
            return int(txt)
        try:
            sb = parse(self.entry_sb, 0)
            bb = parse(self.entry_bb, 0)
            ante = parse(self.entry_ante, 0)
        except ValueError:
            self.status_label.set_markup('<span foreground="#e74c3c">Ciegas invalidas (usa numeros enteros).</span>')
            return
        if bb <= 0:
            self.status_label.set_markup('<span foreground="#e74c3c">La ciega grande (BB) debe ser mayor que 0.</span>')
            return
        write_blinds(sb, bb, ante)
        self.status_label.set_markup(f"Ciegas fijadas: SB={sb} BB={bb} ante={ante}")

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
            self.status_label.set_markup("Iniciando...")
            self.worker = AnalysisWorker(self, self.interval_spin.get_value())
            self.worker.start()

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

    def on_stopped(self):
        self.running = False
        self.worker = None
        self.start_button.set_label("Iniciar analisis")
        self.start_button.set_sensitive(True)
        self.calibrate_button.set_sensitive(True)
        self.interval_spin.set_sensitive(True)
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
        self.made_label.set_markup(
            f'<span size="large" weight="bold">{GLib.markup_escape_text(hand["made_name"])}</span>')
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
        self.hero_label.set_markup("Tus cartas: " + cards_markup(state.get("hero_cards")))
        self.board_label.set_markup("Board: " + (cards_markup(state.get("board"))
                                                 if state.get("board") else "<i>(preflop)</i>"))
        pot = state.get("pot")
        self.pot_label.set_markup(f"Bote: {GLib.markup_escape_text(str(pot))}" if pot is not None
                                  else "Bote: <i>-</i>")
        self.players_label.set_markup(players_markup(state.get("players")))
        self._update_hand(hand)

        if recommendation:
            action = str(recommendation["action"]).upper()
            self.rec_label.set_markup(
                f'<span size="xx-large" weight="bold" foreground="#2ecc71">{GLib.markup_escape_text(action)}</span>')
            reasoning = recommendation.get("reasoning") or ""
            self.reasoning_label.set_markup(GLib.markup_escape_text(reasoning))
        else:
            self.rec_label.set_markup('<span size="xx-large" weight="bold" foreground="#7f8c8d">-</span>')
            warnings = state.get("warnings") or []
            reason = warnings[-1] if warnings else "Sin recomendacion."
            self.reasoning_label.set_markup(
                f'<span foreground="#f39c12"><i>{GLib.markup_escape_text(reason)}</i></span>')

        warnings = state.get("warnings") or []
        self.warnings_label.set_markup(
            ("Avisos: " + GLib.markup_escape_text("; ".join(warnings))) if warnings else "")
        return False

    def _on_close(self, *_a):
        if self.worker:
            self.worker.stop()
            self.worker.join(timeout=6.0)
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=3.0, help="segundos entre analisis")
    parser.add_argument("--self-test", action="store_true",
                        help="construye la ventana y sale (verifica que los widgets se crean)")
    args = parser.parse_args()

    app = Gtk.Application(application_id="org.pokerassistant.gui")

    def on_activate(app):
        win = PokerAssistantWindow(app, args.interval)
        if args.self_test:
            print("self-test OK: ventana y widgets construidos")
            app.quit()
        else:
            win.present()

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    main()
