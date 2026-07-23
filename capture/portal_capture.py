"""
Fase 1: sesion de captura de pantalla via xdg-desktop-portal (ScreenCast) + PipeWire.

La primera vez que se ejecuta, el compositor (KDE en este caso) abre un dialogo
real pidiendo elegir que pantalla compartir y confirmar. Si la sesion pide
persist_mode, el portal devuelve un restore_token que se guarda en
config.local.json (no versionado) para que las siguientes ejecuciones no
vuelvan a pedir permiso.

Uso: .venv/bin/python capture/portal_capture.py [--frames N] [--timeout-s S]
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


def grab_frames(fd, node_id, n_frames, timeout_s):
    pipeline = Gst.parse_launch(
        f"pipewiresrc fd={fd} path={node_id} ! videoconvert "
        f"! video/x-raw,format=BGR ! appsink name=sink max-buffers=1 drop=true sync=false"
    )
    sink = pipeline.get_by_name("sink")
    pipeline.set_state(Gst.State.PLAYING)

    frames = []
    timestamps = []
    try:
        for _ in range(n_frames):
            sample = sink.emit("try-pull-sample", int(timeout_s * Gst.SECOND))
            if sample is None:
                break
            timestamps.append(time.monotonic())
            caps = sample.get_caps().get_structure(0)
            width, height = caps.get_value("width"), caps.get_value("height")
            buf = sample.get_buffer()
            ok, mapinfo = buf.map(Gst.MapFlags.READ)
            if ok:
                import numpy as np
                frame = np.ndarray((height, width, 3), buffer=mapinfo.data, dtype=np.uint8).copy()
                frames.append(frame)
                buf.unmap(mapinfo)
    finally:
        pipeline.set_state(Gst.State.NULL)
    return frames, timestamps


def open_screencast_session(log=print):
    """
    Hace todo el intercambio con el portal (sesion, seleccion de fuente,
    start, pipewire remote) y devuelve (portal, session_handle, fd, node_id,
    stream_props). El llamador es responsable de cerrar la sesion
    (portal.close_session(session_handle)) y el fd (os.close(fd)) cuando
    termine.
    """
    portal = Portal()
    restore_token = _load_restore_token()

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


def get_one_frame(timeout_s=10.0, log=print):
    """Abre una sesion, captura un unico frame (numpy BGR) y cierra todo."""
    portal, session_handle, fd, node_id, _props = open_screencast_session(log=log)
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
    args = parser.parse_args()

    portal, session_handle, fd, node_id, stream_props = open_screencast_session()
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
