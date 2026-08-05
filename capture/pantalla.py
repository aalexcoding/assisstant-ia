"""
DE DONDE SALEN LOS FRAMES, sea cual sea el sistema.

Hay dos backends y no se parecen en nada por dentro:

  - LINUX/Wayland: xdg-desktop-portal (ScreenCast) + PipeWire + GStreamer. Una
    sesion con el compositor, un fd, un node_id y un pipeline. Ver
    capture/portal_capture.py.
  - macOS: CoreGraphics via mss, que es una llamada sincrona por frame y no
    tiene sesion ninguna. Ver capture/mac_capture.py.

Lo que tienen en comun es lo unico que le importa al resto de la app: se abre
algo, se leen frames BGR de ahi, y al final se cierra. Esta fachada es ese
"algo", y por eso los llamadores (alpha.py, gui.py, el calibrador) ya no
importan un backend concreto.

LA TUPLA DE CINCO SE ACABA AQUI. Antes cada llamador recibia
(portal, session_handle, fd, stream, props) y tenia que cerrar las cuatro
primeras en su propio `finally` -alpha.py y gui.py tenian el mismo bloque de
cuatro try/except copiado-. Eso ademas hacia imposible cambiar de backend: la
forma del portal estaba escrita en cada sitio. Ahora se devuelve UN objeto que
sabe cerrarse solo, y lo que sobra de cada backend se queda dentro de el.

Uso:
    from capture import pantalla
    with pantalla.abrir_stream() as stream:
        frame = stream.read(timeout_s=5.0)      # ndarray BGR, o None

QUE BACKEND se elige sale de sys.platform. POKER_CAPTURA=portal|mac lo fuerza,
que es lo que hace falta para probar el otro camino sin cambiar de maquina.
"""
import os
import sys


class SinBackendDeCaptura(RuntimeError):
    """No hay backend de captura para esta plataforma."""


class PermisoDeCaptura(RuntimeError):
    """El sistema deja capturar, pero devuelve una pantalla en negro.

    Es su forma de decir que falta el permiso; ver capture/mac_capture.py.
    """


def nombre_backend():
    """"portal" o "mac". POKER_CAPTURA manda sobre la plataforma."""
    forzado = os.environ.get("POKER_CAPTURA")
    if forzado:
        if forzado not in ("portal", "mac"):
            raise SinBackendDeCaptura(
                f"POKER_CAPTURA={forzado!r} no es un backend: usa 'portal' o 'mac'")
        return forzado
    if sys.platform == "darwin":
        return "mac"
    if sys.platform.startswith("linux"):
        return "portal"
    raise SinBackendDeCaptura(
        f"no hay backend de captura para {sys.platform!r} (hay para Linux y macOS)")


def _backend():
    """El MODULO del backend. Se importa aqui dentro y no arriba a proposito:
    portal_capture importa gi/GStreamer y mac_capture importa mss, y ninguno de
    los dos existe en la plataforma del otro. Importarlos a nivel de modulo
    convertiria esta fachada en el sitio que rompe al arrancar."""
    if nombre_backend() == "mac":
        from capture import mac_capture
        return mac_capture
    from capture import portal_capture
    return portal_capture


def abrir_stream(log=print, elegir_pantalla=False):
    """Deja listo un stream del que leer frames repetidamente.

    Devuelve un objeto con .read(timeout_s) -> ndarray BGR o None, .close(), y
    que sirve de gestor de contexto. Cerrarlo cierra TODO lo del backend.

    elegir_pantalla: volver a preguntar que pantalla se captura, ignorando la
    guardada. Lo pide el CALIBRADOR, que es justo el momento en que el usuario
    decide donde esta la mesa; el analisis en marcha quiere lo contrario y
    arranca sin preguntar nada.
    """
    return _backend().abrir_stream(log=log, elegir_pantalla=elegir_pantalla)


def un_frame(timeout_s=10.0, log=print, elegir_pantalla=False):
    """Un unico frame BGR, abriendo y cerrando todo alrededor. Para el
    calibrador, que solo necesita una imagen de referencia."""
    with abrir_stream(log=log, elegir_pantalla=elegir_pantalla) as stream:
        frame = stream.read(timeout_s=timeout_s)
    if frame is None:
        raise RuntimeError("no se recibio ningun frame de la pantalla")
    return frame
