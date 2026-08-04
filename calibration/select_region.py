"""
Fase 0: selector de recuadro de calibracion.

Captura un frame de referencia (reutilizando capture/portal_capture.py) y lo
muestra en una ventana para que el usuario dibuje con el raton el rectangulo
de la mesa. El resultado (en pixeles del frame original, sin escalar) se
guarda en calibration/config.local.json y es lo que luego usa Fase 1 para
recortar cada frame capturado.

SIEMPRE PREGUNTA QUE PANTALLA, aunque ya hubiera una guardada: calibrar es el
momento en que el usuario decide donde esta la mesa. El analisis en marcha sigue
sin preguntar nada y usa la que se haya elegido aqui.

Uso: .venv/bin/python calibration/select_region.py
Controles: arrastrar para dibujar el rectangulo, Enter para guardar, Esc para salir.
"""
import json
import os

from capture import portal_capture as pc
from vision import seat_map

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.local.json")
MAX_DISPLAY_SIZE = 1500


def save_region(frame_size, rect):
    data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    data["capture_region"] = {
        "frame_width": frame_size[0],
        "frame_height": frame_size[1],
        "x": rect[0],
        "y": rect[1],
        "width": rect[2],
        "height": rect[3],
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


class SelectorWindow(Gtk.ApplicationWindow):
    def __init__(self, app, frame):
        super().__init__(application=app, title="Dibuja el recuadro de la mesa (Enter para guardar, Esc para salir)")
        self.frame_h, self.frame_w = frame.shape[0], frame.shape[1]
        self.scale = min(1.0, MAX_DISPLAY_SIZE / max(self.frame_w, self.frame_h))
        disp_w, disp_h = int(self.frame_w * self.scale), int(self.frame_h * self.scale)

        rgb = frame[:, :, ::-1].copy()
        self._pixbuf_data = rgb.tobytes()
        self.pixbuf = GdkPixbuf.Pixbuf.new_from_data(
            self._pixbuf_data, GdkPixbuf.Colorspace.RGB, False, 8,
            self.frame_w, self.frame_h, self.frame_w * 3,
        )
        if self.scale != 1.0:
            self.pixbuf = self.pixbuf.scale_simple(disp_w, disp_h, GdkPixbuf.InterpType.BILINEAR)

        self.frame = frame
        self.drag_start = None
        self.rect_display = None
        self.saved_rect = None
        # se pone a True cuando ya se ha avisado de que en el recuadro no hay
        # mesa: el segundo Enter guarda igual, porque el usuario manda
        self.forzar = False

        self.area = Gtk.DrawingArea()
        self.area.set_content_width(disp_w)
        self.area.set_content_height(disp_h)
        self.area.set_draw_func(self._on_draw)
        self.set_child(self.area)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.area.add_controller(drag)

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

    def _on_drag_begin(self, _gesture, x, y):
        self.drag_start = (x, y)
        self.rect_display = (x, y, 0, 0)
        self.area.queue_draw()

    def _on_drag_update(self, _gesture, dx, dy):
        x0, y0 = self.drag_start
        self.rect_display = (x0, y0, dx, dy)
        self.area.queue_draw()

    def _on_drag_end(self, _gesture, dx, dy):
        x0, y0 = self.drag_start
        x, y = min(x0, x0 + dx), min(y0, y0 + dy)
        w, h = abs(dx), abs(dy)
        self.rect_display = (x, y, w, h)
        self.area.queue_draw()

    def _on_key(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Return and self.rect_display and self.rect_display[2] > 5 and self.rect_display[3] > 5:
            x, y, w, h = self.rect_display
            rect = (int(x / self.scale), int(y / self.scale),
                    int(w / self.scale), int(h / self.scale))
            if not self._hay_mesa(rect) and not self.forzar:
                # NO SE GUARDA A LA PRIMERA UN RECUADRO SIN MESA. Es el fallo que
                # el usuario se comio: recalibro, dibujo el recuadro donde no
                # estaba la mesa, y no se entero hasta que la app llevaba un rato
                # diciendo "no se encuentra la mesa en este frame" partida tras
                # partida. El calibrador tiene delante el unico dato que hace
                # falta para avisar -si en ese recuadro se ve un ovalo de tapete-
                # y callarselo es dejar el fallo para dentro de media hora.
                self.set_title("En ese recuadro NO se ve una mesa de poker. "
                               "Dibuja otro, o pulsa Enter otra vez para guardarlo igual.")
                self.forzar = True
                return True
            self.saved_rect = rect
            save_region((self.frame_w, self.frame_h), self.saved_rect)
            print(f"Guardado en {CONFIG_PATH}: {self.saved_rect}")
            self.get_application().quit()
        elif keyval == Gdk.KEY_Escape:
            self.get_application().quit()
        return False

    def _hay_mesa(self, rect):
        """¿Se ve el ovalo del tapete dentro de ese recuadro?

        Es exactamente la pregunta que se hace analyze_layout en cada frame (ver
        seat_map.find_reference): si aqui no se encuentra, en la partida tampoco,
        y todas las zonas quedarian desplazadas."""
        x, y, w, h = rect
        recorte = self.frame[y:y + h, x:x + w]
        if recorte.size == 0:
            return False
        try:
            return not seat_map.find_reference(recorte)[4]
        except Exception:                     # noqa: BLE001 - avisar nunca puede tumbar el calibrador
            return True

    def _on_draw(self, _area, cr, _width, _height):
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
        cr.paint()
        if self.rect_display:
            x, y, w, h = self.rect_display
            cr.set_source_rgba(0.1, 0.9, 0.3, 0.9)
            cr.set_line_width(2)
            cr.rectangle(x, y, w, h)
            cr.stroke()
            cr.set_source_rgba(0.1, 0.9, 0.3, 0.15)
            cr.rectangle(x, y, w, h)
            cr.fill()


def main():
    # SIEMPRE se pregunta QUE PANTALLA. Calibrar es justo el momento de decidirlo
    # -es cuando el usuario dice donde esta la mesa-, y con dos monitores la
    # guardada puede ser la otra: entonces se dibujaba el recuadro sobre una
    # pantalla que no era, y el fallo aparecia despues, en forma de recortes
    # vacios. El resto de la app sigue arrancando sin preguntar, con la pantalla
    # que se elija aqui (ver portal_capture.open_screencast_session).
    print("Capturando frame de referencia (elige la pantalla en el dialogo)...")
    frame = pc.get_one_frame(elegir_pantalla=True)

    app = Gtk.Application(application_id="org.pokerassistant.calibration")

    def on_activate(app):
        win = SelectorWindow(app, frame)
        win.present()

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    main()
