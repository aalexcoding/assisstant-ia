"""
Backend de captura de macOS: CoreGraphics a traves de mss.

Es el equivalente de capture/portal_capture.py para Mac, y por dentro no se
parece en nada: aqui no hay sesion con el compositor, ni fd, ni pipeline, ni
token que restaurar. Cada frame es una llamada sincrona que devuelve la
pantalla entera. Lo que se conserva es el contrato de la fachada
(capture/pantalla.py): abrir, leer BGR, cerrar.

RESOLUCION NATIVA POR DEFECTO. mss pide siempre la imagen "nominal" -o sea en
PUNTOS, no en pixeles-, asi que en una pantalla Retina devuelve la mitad de lo
que hay. Para OCR de nameplates eso es tirar la mitad de la senyal, y el backend
de Linux entrega el framebuffer tal cual, asi que aqui se hace lo mismo. Medido
en un MacBook Pro de 14" (3024x1964 nativos, 1512x982 en puntos):

    logica   1512x982    p50  9,8 ms   p95 10,7 ms
    nativa   3024x1964   p50 21,6 ms   p95 24,3 ms

El lazo rapido de la app captura cada 0,1 s (VIGILANCIA_PERIODO_S), asi que
incluso la nativa sobra: 24 ms de 100. Si en una maquina concreta no sobrara,
POKER_CAPTURA_ESCALA=logica vuelve a la mitad de pixeles.

EL PERMISO ES LO PRIMERO QUE FALLA. Sin "Grabacion de pantalla" concedido a
quien lanza python (Terminal, VS Code, iTerm...), macOS no da error: devuelve
una imagen NEGRA y se queda tan tranquilo. Un frame negro entra en el pipeline,
seat_map no encuentra el tapete y el sintoma aparece tres capas mas abajo como
"no se encuentra la mesa en este frame". Por eso el primer frame se mira y, si
esta uniformemente negro, se dice lo que pasa con esas palabras.

UN STREAM ES DE UN HILO. El objeto de mss no es thread-safe: se crea y se lee
desde el mismo hilo, que es lo que ya hace la app (el hilo de analisis abre su
stream y lee de el; ver gui.AnalysisWorker).

Uso: .venv/bin/python -m capture.mac_capture [--frames N] [--elegir-pantalla]
"""
import argparse
import json
import os
import time

import numpy as np

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.local.json")

# clave donde se recuerda que pantalla se eligio. Convive en el mismo fichero
# que el screencast_restore_token del backend de Linux: es el mismo dato ("de
# donde capturo"), contado en el idioma de cada sistema.
CLAVE_MONITOR = "mac_monitor_index"


def _leer_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def _guardar_config(**claves):
    """Escribe claves CONSERVANDO el resto: el fichero lo comparten los dos
    backends y machacarlo borraria el restore_token del portal."""
    data = _leer_config()
    data.update(claves)
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def escala_nativa():
    """True si se captura en pixeles reales (por defecto), False si en puntos."""
    return os.environ.get("POKER_CAPTURA_ESCALA", "nativa") != "logica"


def _aplicar_escala(nativa, log=print):
    """Quita (o pone) el flag de resolucion nominal de mss.

    mss lo tiene como constante de modulo y lo lee en cada grab, asi que esta es
    la unica forma de pedirle pixeles de verdad sin reimplementar su backend. Si
    una version futura de mss dejara de tener esas constantes, se sigue
    capturando -en puntos, que es su comportamiento- y se avisa, en vez de
    tumbar la sesion por un detalle de calidad."""
    try:
        import mss.darwin as md
        base = md.kCGWindowImageBoundsIgnoreFraming | md.kCGWindowImageShouldBeOpaque
        md.IMAGE_OPTIONS = base if nativa else base | md.kCGWindowImageNominalResolution
        return True
    except (ImportError, AttributeError):  # noqa: BLE001
        log("aviso: esta version de mss no deja pedir resolucion nativa; "
            "se captura en puntos (la mitad de pixeles en una pantalla Retina)")
        return False


def elegir_monitor(monitores, guardado=None, elegir=False, preguntar=None, log=print):
    """Indice del monitor a capturar dentro de la lista de mss.

    El 0 de mss es la union de todas las pantallas y no se ofrece: capturar el
    escritorio entero de dos monitores da un frame gigante donde la mesa ocupa
    un cuarto, que es justo lo que la calibracion intenta evitar.

    - Con UNA pantalla no se pregunta nunca: no hay nada que decidir.
    - `elegir` (el calibrador) pregunta aunque hubiera una guardada.
    - Una guardada que ya no existe (se desconecto el monitor) no es un error:
      se cae a la primera y se avisa.
    """
    reales = list(range(1, len(monitores)))
    if not reales:
        raise RuntimeError("mss no encuentra ninguna pantalla")

    if len(reales) == 1:
        return reales[0]

    if not elegir and guardado in reales:
        return guardado
    if not elegir and guardado is not None:
        log(f"la pantalla guardada ({guardado}) ya no esta; se usa la {reales[0]}")
        return reales[0]

    for i in reales:
        m = monitores[i]
        log(f"  [{i}] {m['width']}x{m['height']} en ({m['left']},{m['top']})")
    if preguntar is None:
        log(f"no hay consola para preguntar: se usa la pantalla {reales[0]}")
        return reales[0]
    respuesta = preguntar("Que pantalla tiene la mesa? [numero] ").strip()
    try:
        elegida = int(respuesta)
    except ValueError:
        elegida = -1
    if elegida not in reales:
        log(f"'{respuesta}' no es una de las pantallas; se usa la {reales[0]}")
        return reales[0]
    return elegida


def _preguntar_por_consola():
    """input() solo si hay una consola de verdad detras. Desde la GUI no la hay,
    y ahi un input() no pregunta: cuelga el hilo para siempre."""
    try:
        import sys
        if sys.stdin is not None and sys.stdin.isatty():
            return input
    except Exception:  # noqa: BLE001
        pass
    return None


def _esta_en_negro(frame):
    """Frame uniformemente negro. Es como macOS dice "no tienes permiso"."""
    return frame is not None and frame.size > 0 and not frame.any()


MENSAJE_PERMISO = (
    "macOS devuelve la pantalla en NEGRO: falta el permiso de grabacion de "
    "pantalla.\n"
    "  Ajustes del Sistema > Privacidad y seguridad > Grabacion de pantalla\n"
    "  y activa la app desde la que lanzas python (Terminal, iTerm, VS Code...).\n"
    "  Despues hay que CERRARLA Y VOLVER A ABRIRLA: el permiso se lee al arrancar.\n"
    "(Si la pantalla estaba apagada o el salvapantallas puesto, es lo mismo que "
    "se ve.)"
)


class StreamMac:
    """Frames BGR de una pantalla. Mismo contrato que FrameStream del portal."""

    def __init__(self, sct, monitor, log=print):
        self._sct = sct
        self._monitor = monitor
        self._log = log
        self._primera = True

    def read(self, timeout_s=5.0):
        """Un frame BGR (ndarray) o None si mss no pudo capturar.

        timeout_s se acepta por compatibilidad con el backend del portal y no se
        usa: aqui no hay espera, la captura es sincrona y vuelve o falla."""
        del timeout_s
        if self._sct is None:
            return None
        try:
            crudo = self._sct.grab(self._monitor)
        except Exception as e:  # noqa: BLE001
            self._log(f"fallo al capturar la pantalla: {e}")
            return None
        # mss entrega BGRA; el resto de la app trabaja en BGR.
        frame = np.asarray(crudo)[:, :, :3]
        if self._primera:
            self._primera = False
            if _esta_en_negro(frame):
                from capture.pantalla import PermisoDeCaptura
                raise PermisoDeCaptura(MENSAJE_PERMISO)
        return frame

    def close(self):
        sct, self._sct = self._sct, None
        if sct is not None:
            try:
                sct.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_excepcion):
        self.close()
        return False


def abrir_stream(log=print, elegir_pantalla=False, sct=None):
    """Abre la captura de una pantalla. Ver capture/pantalla.abrir_stream.

    sct: se inyecta en los tests. En produccion lo crea mss.
    """
    if sct is None:
        import mss
        _aplicar_escala(escala_nativa(), log=log)
        sct = mss.MSS()

    guardado = _leer_config().get(CLAVE_MONITOR)
    indice = elegir_monitor(sct.monitors, guardado=guardado, elegir=elegir_pantalla,
                            preguntar=_preguntar_por_consola() if elegir_pantalla else None,
                            log=log)
    if indice != guardado:
        _guardar_config(**{CLAVE_MONITOR: indice})
    monitor = sct.monitors[indice]
    log(f"Capturando la pantalla {indice} ({monitor['width']}x{monitor['height']} "
        f"en puntos, escala {'nativa' if escala_nativa() else 'logica'}).")
    return StreamMac(sct, monitor, log=log)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--elegir-pantalla", action="store_true",
                        help="ignora la pantalla guardada y vuelve a preguntar cual")
    parser.add_argument("--volcar", default="captura_mac.png",
                        help="donde dejar el ultimo frame, para mirarlo a ojo")
    args = parser.parse_args()

    with abrir_stream(elegir_pantalla=args.elegir_pantalla) as stream:
        stream.read()                      # la primera paga el arranque
        tiempos, frame = [], None
        for _ in range(args.frames):
            t0 = time.perf_counter()
            frame = stream.read()
            tiempos.append((time.perf_counter() - t0) * 1000)

    if frame is None or not tiempos:
        print("no se pudo capturar ni un frame")
        return 1

    tiempos.sort()
    p50 = tiempos[len(tiempos) // 2]
    p95 = tiempos[max(0, int(len(tiempos) * 0.95) - 1)]
    print(f"\nResolucion capturada: {frame.shape[1]}x{frame.shape[0]}")
    print(f"Latencia por frame: p50 {p50:.1f} ms | p95 {p95:.1f} ms | max {tiempos[-1]:.1f} ms")
    print(f"Techo: {1000 / p50:.0f} fps (el lazo rapido pide 10)")
    print(f"Media de pixel: {frame.mean():.1f}")

    import cv2
    cv2.imwrite(args.volcar, frame)
    print(f"Ultimo frame en {args.volcar}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
