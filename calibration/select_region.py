"""
Fase 0: selector de recuadro de calibracion.

Captura un frame de referencia (reutilizando capture/pantalla.py) y lo
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
from capture import pantalla
# Donde se guarda el recuadro y cuando es valido NO vive aqui: lo comparten
# esta ventana y el calibrador de consola (select_region_cv.py). Ver
# calibration/recuadro.py.
from calibration.recuadro import (AVISO_SIN_MESA, CONFIG_PATH,
                                  a_coordenadas_de_frame, escala_de_vista,
                                  hay_mesa, save_region)

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk


class SelectorWindow(Gtk.ApplicationWindow):
    def __init__(self, app, frame):
        super().__init__(application=app, title="Dibuja el recuadro de la mesa (Enter para guardar, Esc para salir)")
        self.frame_h, self.frame_w = frame.shape[0], frame.shape[1]
        self.scale = escala_de_vista(self.frame_w, self.frame_h)
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
            rect = a_coordenadas_de_frame(self.rect_display, self.scale)
            if not self._hay_mesa(rect) and not self.forzar:
                # NO SE GUARDA A LA PRIMERA UN RECUADRO SIN MESA. Es el fallo que
                # el usuario se comio: recalibro, dibujo el recuadro donde no
                # estaba la mesa, y no se entero hasta que la app llevaba un rato
                # diciendo "no se encuentra la mesa en este frame" partida tras
                # partida. El calibrador tiene delante el unico dato que hace
                # falta para avisar -si en ese recuadro se ve un ovalo de tapete-
                # y callarselo es dejar el fallo para dentro de media hora.
                self.set_title(AVISO_SIN_MESA +
                               " Dibuja otro, o pulsa Enter otra vez para guardarlo igual.")
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
        """Ver hay_mesa(), que es la que usan los dos calibradores."""
        return hay_mesa(self.frame, rect)

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
    # que se elija aqui (ver capture/pantalla.py y cada backend).
    print("Capturando frame de referencia (elige la pantalla en el dialogo)...")
    frame = pantalla.un_frame(elegir_pantalla=True)

    app = Gtk.Application(application_id="org.pokerassistant.calibration")

    def on_activate(app):
        win = SelectorWindow(app, frame)
        win.present()

    app.connect("activate", on_activate)
    app.run(None)


if __name__ == "__main__":
    main()
