"""
El backend de captura de macOS, sin macOS delante.

Lo que se prueba aqui son las DOS decisiones que toma este backend y que no
dependen de CoreGraphics: que pantalla se captura, y que hacer cuando la imagen
llega en negro. La captura en si es una llamada de mss y no hay nada nuestro que
comprobar en ella; el objeto de mss se inyecta.

EL FRAME NEGRO ES EL CASO IMPORTANTE. macOS no da error cuando falta el permiso
de grabacion de pantalla: devuelve una pantalla negra. Ese frame entra en el
pipeline, seat_map no encuentra el tapete, y el usuario acaba leyendo "no se
encuentra la mesa en este frame" a tres capas de distancia del problema real,
que era un interruptor en Ajustes del Sistema.
"""
import numpy as np
import pytest

from capture import mac_capture as mc
from capture.pantalla import PermisoDeCaptura


class SctFalso:
    """Lo minimo de mss: una lista de monitores y un grab() que devuelve BGRA."""

    def __init__(self, monitores, frames=None, fallar=False):
        self.monitors = monitores
        self._frames = list(frames or [])
        self._fallar = fallar
        self.cerrado = 0
        self.pedidos = []

    def grab(self, monitor):
        self.pedidos.append(monitor)
        if self._fallar:
            raise RuntimeError("CoreGraphics dijo que no")
        if self._frames:
            return self._frames.pop(0)
        return np.full((4, 6, 4), 200, np.uint8)

    def close(self):
        self.cerrado += 1


def monitores(n):
    """Como los da mss: el [0] es la union de todas, luego una por pantalla."""
    union = {"left": 0, "top": 0, "width": 3000, "height": 1000}
    pantallas = [{"left": 1500 * i, "top": 0, "width": 1500, "height": 1000}
                 for i in range(n)]
    return [union] + pantallas


# --- que pantalla se captura -------------------------------------------------

def test_con_una_sola_pantalla_no_se_pregunta_nunca():
    """Ni siquiera calibrando: no hay nada que decidir. Preguntar aqui seria
    pedirle al usuario que elija entre una cosa."""
    preguntas = []
    i = mc.elegir_monitor(monitores(1), guardado=None, elegir=True,
                          preguntar=lambda t: preguntas.append(t) or "1", log=lambda _m: None)
    assert i == 1
    assert preguntas == []


def test_la_union_de_pantallas_no_se_ofrece():
    """El monitor 0 de mss es el escritorio entero. Capturarlo con dos pantallas
    da un frame gigante donde la mesa ocupa un cuarto."""
    ofrecidas = []
    mc.elegir_monitor(monitores(2), guardado=None, elegir=True,
                      preguntar=lambda _t: "1", log=ofrecidas.append)
    assert not any(linea.startswith("  [0]") for linea in ofrecidas)


def test_la_guardada_se_respeta_sin_preguntar():
    """El analisis arranca sin molestar: es la contrapartida de que el
    calibrador si pregunte."""
    preguntas = []
    i = mc.elegir_monitor(monitores(3), guardado=2, elegir=False,
                          preguntar=lambda t: preguntas.append(t) or "1")
    assert i == 2
    assert preguntas == []


def test_calibrar_pregunta_aunque_haya_guardada():
    i = mc.elegir_monitor(monitores(3), guardado=2, elegir=True,
                          preguntar=lambda _t: "3", log=lambda _m: None)
    assert i == 3


def test_una_guardada_que_ya_no_existe_no_es_un_error():
    """Se desconecto el monitor. Caer a la primera y decirlo es mejor que
    reventar al arrancar el analisis."""
    avisos = []
    i = mc.elegir_monitor(monitores(2), guardado=7, elegir=False, log=avisos.append)
    assert i == 1
    assert any("ya no esta" in a for a in avisos)


@pytest.mark.parametrize("respuesta", ["", "9", "la de la derecha", "0"])
def test_una_respuesta_que_no_es_una_pantalla_cae_en_la_primera(respuesta):
    """Incluido el "0": la union no es una opcion."""
    i = mc.elegir_monitor(monitores(2), guardado=None, elegir=True,
                          preguntar=lambda _t: respuesta, log=lambda _m: None)
    assert i == 1


def test_sin_consola_no_se_cuelga_preguntando():
    """Desde la GUI no hay stdin: un input() ahi no pregunta, cuelga el hilo."""
    avisos = []
    i = mc.elegir_monitor(monitores(2), guardado=None, elegir=True,
                          preguntar=None, log=avisos.append)
    assert i == 1
    assert any("no hay consola" in a for a in avisos)


def test_sin_ninguna_pantalla_se_dice():
    with pytest.raises(RuntimeError, match="ninguna pantalla"):
        mc.elegir_monitor(monitores(0), log=lambda _m: None)


# --- leer frames -------------------------------------------------------------

def test_read_devuelve_bgr_de_tres_canales():
    """mss entrega BGRA y el resto de la app trabaja en BGR: el canal alfa se
    cae aqui y no tres modulos mas abajo."""
    stream = mc.StreamMac(SctFalso(monitores(1)), monitores(1)[1], log=lambda _m: None)
    frame = stream.read()
    assert frame.shape == (4, 6, 3)


def test_el_primer_frame_negro_dice_que_falta_el_permiso():
    negro = np.zeros((4, 6, 4), np.uint8)
    stream = mc.StreamMac(SctFalso(monitores(1), frames=[negro]), monitores(1)[1],
                          log=lambda _m: None)
    with pytest.raises(PermisoDeCaptura) as e:
        stream.read()
    assert "Grabacion de pantalla" in str(e.value)


def test_un_negro_a_mitad_de_sesion_no_es_falta_de_permiso():
    """La pantalla se puede apagar o entrar el salvapantallas con el analisis en
    marcha. Eso es un frame malo -que el pipeline ya sabe descartar-, no una
    sesion que haya que tumbar: si el permiso faltara, el primero ya habria
    salido negro."""
    negro = np.zeros((4, 6, 4), np.uint8)
    bueno = np.full((4, 6, 4), 200, np.uint8)
    stream = mc.StreamMac(SctFalso(monitores(1), frames=[bueno, negro]),
                          monitores(1)[1], log=lambda _m: None)
    stream.read()
    assert not stream.read().any()


def test_un_fallo_de_captura_devuelve_none_y_no_propaga():
    """Un frame perdido es un frame perdido: el lazo de analisis ya lo trata.
    Propagar mataria el hilo entero por una captura."""
    avisos = []
    stream = mc.StreamMac(SctFalso(monitores(1), fallar=True), monitores(1)[1],
                          log=avisos.append)
    assert stream.read() is None
    assert any("fallo al capturar" in a for a in avisos)


def test_close_cierra_mss_y_se_puede_repetir():
    sct = SctFalso(monitores(1))
    stream = mc.StreamMac(sct, monitores(1)[1], log=lambda _m: None)
    stream.close()
    stream.close()
    assert sct.cerrado == 1
    assert stream.read() is None


def test_sirve_de_gestor_de_contexto():
    sct = SctFalso(monitores(1))
    with mc.StreamMac(sct, monitores(1)[1], log=lambda _m: None) as stream:
        assert stream.read() is not None
    assert sct.cerrado == 1


# --- la pantalla elegida se recuerda ----------------------------------------

def test_abrir_stream_recuerda_la_pantalla_sin_borrar_lo_del_portal(tmp_path, monkeypatch):
    """El fichero de config lo comparten los dos backends: guardar la pantalla
    de Mac no puede llevarse por delante el restore_token del portal."""
    config = tmp_path / "config.local.json"
    config.write_text('{"screencast_restore_token": "no-me-toques"}')
    monkeypatch.setattr(mc, "CONFIG_PATH", str(config))

    sct = SctFalso(monitores(3))
    stream = mc.abrir_stream(log=lambda _m: None, elegir_pantalla=False, sct=sct)
    stream.close()

    import json
    guardado = json.loads(config.read_text())
    assert guardado["screencast_restore_token"] == "no-me-toques"
    assert guardado[mc.CLAVE_MONITOR] == 1


def test_una_config_corrupta_no_impide_capturar(tmp_path, monkeypatch):
    """El fichero es local y no versionado: se puede quedar a medio escribir.
    Perder la pantalla guardada cuesta una pregunta; no arrancar cuesta la
    sesion."""
    config = tmp_path / "config.local.json"
    config.write_text("{esto no es json")
    monkeypatch.setattr(mc, "CONFIG_PATH", str(config))
    assert mc._leer_config() == {}
    stream = mc.abrir_stream(log=lambda _m: None, sct=SctFalso(monitores(1)))
    assert stream.read() is not None
