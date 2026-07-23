"""
Fase 0: selector de recuadro de calibracion.

Captura un frame de referencia (reutilizando capture/portal_capture.py) y lo
muestra en una ventana para que el usuario dibuje con el raton el rectangulo
de la mesa. El resultado (en pixeles del frame original, sin escalar) se
guarda en calibration/config.local.json y es lo que luego usa Fase 1 para
recortar cada frame capturado.

Uso: .venv/bin/python calibration/select_region.py
Controles: arrastrar para dibujar el rectangulo, Enter para guardar, Esc para salir.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "capture"))
import portal_capture as pc

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

        self.drag_start = None
        self.rect_display = None
        self.saved_rect = None

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
            self.saved_rect = (
                int(x / self.scale), int(y / self.scale),
                int(w / self.scale), int(h / self.scale),
            )
            save_region((self.frame_w, self.frame_h), self.saved_rect)
            print(f"Guardado en {CONFIG_PATH}: {self.saved_rect}")
            self.get_application().quit()
        elif keyval == Gdk.KEY_Escape:
            self.get_application().quit()

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
    print("Capturando frame de referencia (confirma el dialogo si aparece)...")
    frame = pc.get_one_frame()

    app = Gtk.Application(application_id="org.pokerassistant.calibration")

    def on_activate(app):
        win = SelectorWindow(app, frame)
        win.present()

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    main()
