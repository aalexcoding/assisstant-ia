"""
Fase 1: sesion de captura de pantalla via xdg-desktop-portal (ScreenCast) + PipeWire.

La primera vez que se ejecuta, el compositor (KDE en este caso) abre un dialogo
real pidiendo elegir que pantalla compartir y confirmar. Si la sesion pide
persist_mode, el portal devuelve un restore_token que se guarda en
config.local.json (no versionado) para que las siguientes ejecuciones no
vuelvan a pedir permiso.

CALIBRAR ES LA EXCEPCION y pasa `elegir_pantalla=True`: ahi el dialogo TIENE que
salir, porque elegir donde esta la mesa es justo lo que el usuario va a hacer.
Ver open_screencast_session.

Uso: .venv/bin/python capture/portal_capture.py [--frames N] [--timeout-s S]
                                                [--elegir-pantalla]
"""
import argparse
import json
import os
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gio, GLib, Gst

Gst.init(None)

BUS_NAME = "org.freedesktop.portal.Desktop"
OBJECT_PATH = "/org/freedesktop/portal/desktop"
SCREENCAST_IFACE = "org.freedesktop.portal.ScreenCast"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.local.json")

SOURCE_TYPE_MONITOR = 1
CURSOR_MODE_HIDDEN = 1
PERSIST_UNTIL_REVOKED = 2

_token_counter = 0


def _next_token():
    global _token_counter
    _token_counter += 1
    return f"claude_poker_{os.getpid()}_{_token_counter}"


def _load_restore_token():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f).get("screencast_restore_token")
    return None


def _save_restore_token(token):
    data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    data["screencast_restore_token"] = token
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


class Portal:
    def __init__(self):
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender_segment = self.connection.get_unique_name()[1:].replace(".", "_")

    def _request_call(self, method, positional_args, options):
        """
        Llama a un metodo del portal que devuelve un Request (o) y bloquea
        hasta que llega la señal Response en ese Request. El path del Request
        se calcula por adelantado (segun especifica xdg-desktop-portal) y nos
        suscribimos ANTES de invocar el metodo, para no perder la señal si
        llega muy rapido (CreateSession/SelectSources no muestran dialogo).
        """
        token = _next_token()
        options = dict(options)
        options["handle_token"] = GLib.Variant("s", token)
        expected_path = f"/org/freedesktop/portal/desktop/request/{self.sender_segment}/{token}"

        loop = GLib.MainLoop()
        outcome = {}

        def on_response(_conn, _sender, _path, _iface, _signal, params):
            code, results = params.unpack()
            outcome["code"] = code
            outcome["results"] = results
            loop.quit()

        sub_id = self.connection.signal_subscribe(
            BUS_NAME, REQUEST_IFACE, "Response", expected_path, None,
            Gio.DBusSignalFlags.NONE, on_response,
        )

        args = positional_args + (options,)
        reply = self.connection.call_sync(
            BUS_NAME, OBJECT_PATH, SCREENCAST_IFACE, method,
            GLib.Variant(self._signature(method), args),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, -1, None,
        )
        actual_path = reply.unpack()[0]
        if actual_path != expected_path:
            self.connection.signal_unsubscribe(sub_id)
            sub_id = self.connection.signal_subscribe(
                BUS_NAME, REQUEST_IFACE, "Response", actual_path, None,
                Gio.DBusSignalFlags.NONE, on_response,
            )

        loop.run()
        self.connection.signal_unsubscribe(sub_id)
        if outcome["code"] != 0:
            raise RuntimeError(f"{method} cancelado o fallido (response code={outcome['code']})")
        return outcome["results"]

    @staticmethod
    def _signature(method):
        return {
            "CreateSession": "(a{sv})",
            "SelectSources": "(oa{sv})",
            "Start": "(osa{sv})",
        }[method]

    def create_session(self):
        results = self._request_call("CreateSession", (), {
            "session_handle_token": GLib.Variant("s", _next_token()),
        })
        return results["session_handle"]

    def select_sources(self, session_handle, restore_token):
        options = {
            "types": GLib.Variant("u", SOURCE_TYPE_MONITOR),
            "cursor_mode": GLib.Variant("u", CURSOR_MODE_HIDDEN),
            "persist_mode": GLib.Variant("u", PERSIST_UNTIL_REVOKED),
        }
        if restore_token:
            options["restore_token"] = GLib.Variant("s", restore_token)
        self._request_call("SelectSources", (session_handle,), options)

    def start(self, session_handle):
        return self._request_call("Start", (session_handle, ""), {})

    def open_pipewire_remote(self, session_handle):
        options = GLib.Variant("a{sv}", {})
        reply, fd_list = self.connection.call_with_unix_fd_list_sync(
            BUS_NAME, OBJECT_PATH, SCREENCAST_IFACE, "OpenPipeWireRemote",
            GLib.Variant("(oa{sv})", (session_handle, {})),
            GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, -1, None, None,
        )
        (fd_index,) = reply.unpack()
        return fd_list.get(fd_index)

    def close_session(self, session_handle):
        self.connection.call_sync(
            BUS_NAME, session_handle, SESSION_IFACE, "Close",
            None, None, Gio.DBusCallFlags.NONE, -1, None,
        )


class FrameStream:
    """Pipeline de GStreamer que se queda abierto y del que se puede leer
    un frame (numpy BGR) cada vez que haga falta, sin recrear la sesion."""

    def __init__(self, fd, node_id):
        self.pipeline = Gst.parse_launch(
            f"pipewiresrc fd={fd} path={node_id} ! videoconvert "
            f"! video/x-raw,format=BGR ! appsink name=sink max-buffers=1 drop=true sync=false"
        )
        self.sink = self.pipeline.get_by_name("sink")
        self.pipeline.set_state(Gst.State.PLAYING)

    def read(self, timeout_s=5.0):
        sample = self.sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
        if sample is None:
            return None
        caps = sample.get_caps().get_structure(0)
        width, height = caps.get_value("width"), caps.get_value("height")
        buf = sample.get_buffer()
        ok, mapinfo = buf.map(Gst.MapFlags.READ)
        if not ok:
            return None
        import numpy as np
        frame = np.ndarray((height, width, 3), buffer=mapinfo.data, dtype=np.uint8).copy()
        buf.unmap(mapinfo)
        return frame

    def close(self):
        self.pipeline.set_state(Gst.State.NULL)


def grab_frames(fd, node_id, n_frames, timeout_s):
    stream = FrameStream(fd, node_id)
    frames, timestamps = [], []
    try:
        for _ in range(n_frames):
            frame = stream.read(timeout_s)
            if frame is None:
                break
            timestamps.append(time.monotonic())
            frames.append(frame)
    finally:
        stream.close()
    return frames, timestamps


def open_screencast_session(log=print, elegir_pantalla=False):
    """
    Hace todo el intercambio con el portal (sesion, seleccion de fuente,
    start, pipewire remote) y devuelve (portal, session_handle, fd, node_id,
    stream_props). El llamador es responsable de cerrar la sesion
    (portal.close_session(session_handle)) y el fd (os.close(fd)) cuando
    termine.

    elegir_pantalla: NO mandar el restore_token guardado, con lo que el portal
    vuelve a abrir su dialogo de "que pantalla quieres compartir". Es lo que
    quiere la CALIBRACION -ahi el usuario esta decidiendo justamente eso, y con
    varias pantallas la guardada puede no ser la de la mesa-, mientras que el
    lazo de analisis quiere lo contrario: arrancar sin preguntar nada.

    La eleccion nueva NO se pierde: el token que devuelve Start se guarda igual
    que siempre, asi que despues de calibrar el analisis arranca solo, y sobre la
    pantalla recien elegida.
    """
    portal = Portal()
    restore_token = None if elegir_pantalla else _load_restore_token()

    log("Creando sesion de ScreenCast...")
    session_handle = portal.create_session()

    log("Seleccionando fuente (puede abrir un dialogo para elegir pantalla)...")
    portal.select_sources(session_handle, restore_token)

    log("Iniciando captura (confirma el dialogo si aparece)...")
    start_results = portal.start(session_handle)

    new_token = start_results.get("restore_token")
    if new_token:
        _save_restore_token(new_token)
        log("restore_token guardado.")

    streams = start_results["streams"]
    node_id, stream_props = streams[0]
    fd = portal.open_pipewire_remote(session_handle)
    return portal, session_handle, fd, node_id, stream_props


def open_frame_stream(log=print, elegir_pantalla=False):
    """
    Como open_screencast_session pero ademas deja el pipeline de GStreamer
    listo para leer frames repetidamente con FrameStream.read(). Devuelve
    (portal, session_handle, fd, stream, stream_props); el llamador cierra
    con stream.close(), os.close(fd) y portal.close_session(session_handle).
    """
    portal, session_handle, fd, node_id, stream_props = open_screencast_session(
        log=log, elegir_pantalla=elegir_pantalla)
    stream = FrameStream(fd, node_id)
    return portal, session_handle, fd, stream, stream_props


class StreamPortal:
    """El stream del portal con TODO lo suyo dentro: el pipeline, el fd y la
    sesion con el compositor.

    Existe para que capture/pantalla.py pueda tratar a este backend y al de
    macOS igual. Lo que hace close() es exactamente el bloque de cuatro
    try/except que estaba copiado en alpha.py y en gui.py: cerrar el pipeline,
    cerrar el fd y cerrar la sesion, y que un fallo en uno no impida los otros.
    """

    def __init__(self, portal, session_handle, fd, stream):
        self._portal = portal
        self._session_handle = session_handle
        self._fd = fd
        self._stream = stream

    def read(self, timeout_s=5.0):
        if self._stream is None:
            return None
        return self._stream.read(timeout_s=timeout_s)

    def close(self):
        stream, self._stream = self._stream, None
        if stream is None:
            return
        for cerrar in (lambda: stream.close(),
                       lambda: os.close(self._fd),
                       lambda: self._portal.close_session(self._session_handle)):
            try:
                cerrar()
            except Exception:  # noqa: BLE001 - cerrar lo que se pueda; el resto da igual
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_excepcion):
        self.close()
        return False


def abrir_stream(log=print, elegir_pantalla=False):
    """Ver capture/pantalla.abrir_stream. Es la puerta de este backend."""
    portal, session_handle, fd, stream, _props = open_frame_stream(
        log=log, elegir_pantalla=elegir_pantalla)
    return StreamPortal(portal, session_handle, fd, stream)


def get_one_frame(timeout_s=10.0, log=print, elegir_pantalla=False):
    """Abre una sesion, captura un unico frame (numpy BGR) y cierra todo."""
    portal, session_handle, fd, node_id, _props = open_screencast_session(
        log=log, elegir_pantalla=elegir_pantalla)
    try:
        frames, _timestamps = grab_frames(fd, node_id, 1, timeout_s)
    finally:
        os.close(fd)
        portal.close_session(session_handle)
    if not frames:
        raise RuntimeError("no se recibio ningun frame del stream de PipeWire")
    return frames[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=10)
    parser.add_argument("--timeout-s", type=float, default=10.0)
    parser.add_argument("--elegir-pantalla", action="store_true",
                        help="ignora la pantalla guardada y vuelve a preguntar cual")
    args = parser.parse_args()

    portal, session_handle, fd, node_id, stream_props = open_screencast_session(
        elegir_pantalla=args.elegir_pantalla)
    print(f"Stream de PipeWire obtenido: node_id={node_id}, props={stream_props}")

    print(f"Capturando hasta {args.frames} frames (timeout {args.timeout_s}s por frame)...")
    frames, timestamps = grab_frames(fd, node_id, args.frames, args.timeout_s)
    os.close(fd)
    portal.close_session(session_handle)

    if len(frames) < 2:
        print(f"Solo se recibieron {len(frames)} frames, no hay suficientes para medir latencia.")
        return

    deltas = [t1 - t0 for t0, t1 in zip(timestamps, timestamps[1:])]
    avg_dt = sum(deltas) / len(deltas)
    print(f"\nFrames recibidos: {len(frames)}")
    print(f"Resolucion: {frames[0].shape[1]}x{frames[0].shape[0]}")
    print(f"Intervalo medio entre frames: {avg_dt*1000:.1f} ms (~{1/avg_dt:.1f} fps)")
    print(f"Duracion total: {timestamps[-1]-timestamps[0]:.2f}s")


if __name__ == "__main__":
    main()
