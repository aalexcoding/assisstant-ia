"""
Que backend de captura se elige.

Es una decision de una linea y aun asi tiene tres formas de salir mal: elegir el
de Linux en un Mac, no dejar forzar el otro para poder probarlo, y -la peor-
importar los dos al cargar el modulo, con lo que la fachada seria justo el sitio
que revienta al arrancar en cualquiera de las dos plataformas (gi no existe en
Mac, mss no se instala en Linux).
"""
import sys

import pytest

from capture import pantalla


def test_en_mac_el_backend_es_el_de_mac(monkeypatch):
    monkeypatch.delenv("POKER_CAPTURA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert pantalla.nombre_backend() == "mac"


def test_en_linux_el_backend_es_el_del_portal(monkeypatch):
    monkeypatch.delenv("POKER_CAPTURA", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert pantalla.nombre_backend() == "portal"


def test_poker_captura_manda_sobre_la_plataforma(monkeypatch):
    """Sirve para probar el camino del otro sistema sin cambiar de maquina."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("POKER_CAPTURA", "mac")
    assert pantalla.nombre_backend() == "mac"


def test_un_backend_que_no_existe_se_dice_al_arrancar(monkeypatch):
    monkeypatch.setenv("POKER_CAPTURA", "pipewire")
    with pytest.raises(pantalla.SinBackendDeCaptura, match="pipewire"):
        pantalla.nombre_backend()


def test_una_plataforma_sin_backend_lo_dice_con_su_nombre(monkeypatch):
    monkeypatch.delenv("POKER_CAPTURA", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(pantalla.SinBackendDeCaptura, match="win32"):
        pantalla.nombre_backend()


def test_el_backend_de_mac_es_el_modulo_de_mac(monkeypatch):
    monkeypatch.delenv("POKER_CAPTURA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert pantalla._backend().__name__ == "capture.mac_capture"


def test_importar_la_fachada_no_arrastra_gi():
    """LO QUE PROTEGE ESTE TEST: que capture/pantalla.py se pueda importar en
    las dos plataformas. Si algun dia alguien sube el import del portal a la
    cabecera del modulo, en Mac deja de arrancar la app entera -no la captura:
    la app-, porque gi no esta ahi. Se comprueba en un proceso NUEVO porque en
    este la suite ya ha importado medio proyecto.
    """
    import subprocess
    codigo = ("import sys; import capture.pantalla; "
              "sys.exit(1 if 'gi' in sys.modules else 0)")
    raiz = __file__.rsplit("/capture/", 1)[0]
    assert subprocess.run([sys.executable, "-c", codigo], cwd=raiz).returncode == 0


def test_un_frame_cierra_el_stream_aunque_no_venga_frame(monkeypatch):
    """un_frame es de usar y tirar (lo llama el calibrador). Si se queda sin
    cerrar, en Linux deja viva la sesion de ScreenCast con el compositor."""
    cerrados = []

    class StreamFalso:
        def read(self, timeout_s=5.0):
            return None

        def close(self):
            cerrados.append(True)

        def __enter__(self):
            return self

        def __exit__(self, *_e):
            self.close()
            return False

    monkeypatch.setattr(pantalla, "abrir_stream", lambda **_k: StreamFalso())
    with pytest.raises(RuntimeError, match="ningun frame"):
        pantalla.un_frame()
    assert cerrados == [True]
