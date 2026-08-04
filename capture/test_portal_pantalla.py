"""
Que pantalla se comparte: cuando se pregunta y cuando no.

LA REGLA, que es del usuario: "cada vez que voy a calibrar captura, que me pida
la pantalla de donde quiero capturar". Calibrar es el momento en que decide
donde esta la mesa, asi que ahi el dialogo del portal TIENE que salir aunque
haya una pantalla guardada de la vez anterior. El resto de la app quiere lo
contrario: arrancar el analisis sin preguntar nada.

El mecanismo es el `restore_token` de xdg-desktop-portal: mandarlo hace que el
compositor reutilice la eleccion en silencio, y no mandarlo hace que abra su
dialogo. Aqui se prueba ESA decision -que token se manda- con el portal
sustituido por un doble, que es lo unico que se puede probar sin un compositor
delante.
"""
import pytest

from capture import portal_capture as pc


class PortalFalso:
    """Registra que restore_token se le paso a SelectSources."""

    def __init__(self):
        self.recibido = "sin llamar"

    def create_session(self):
        return "/sesion"

    def select_sources(self, session_handle, restore_token):
        self.recibido = restore_token

    def start(self, _session_handle):
        return {"streams": [(42, {})], "restore_token": "token-nuevo"}

    def open_pipewire_remote(self, _session_handle):
        return 7


@pytest.fixture
def portal(monkeypatch):
    doble = PortalFalso()
    guardados = []
    monkeypatch.setattr(pc, "Portal", lambda: doble)
    monkeypatch.setattr(pc, "_load_restore_token", lambda: "token-guardado")
    monkeypatch.setattr(pc, "_save_restore_token", guardados.append)
    doble.guardados = guardados
    return doble


def test_al_calibrar_se_vuelve_a_preguntar_la_pantalla(portal):
    """Sin restore_token, el portal abre su dialogo de eleccion."""
    pc.open_screencast_session(log=lambda *_a: None, elegir_pantalla=True)
    assert portal.recibido is None


def test_el_analisis_arranca_con_la_pantalla_ya_elegida(portal):
    """Preguntar en cada arranque del lazo seria un dialogo por sesion de juego."""
    pc.open_screencast_session(log=lambda *_a: None)
    assert portal.recibido == "token-guardado"


def test_la_pantalla_recien_elegida_se_guarda(portal):
    """Si no, calibrar en el segundo monitor obligaria a volver a elegirlo al
    arrancar el analisis."""
    pc.open_screencast_session(log=lambda *_a: None, elegir_pantalla=True)
    assert portal.guardados == ["token-nuevo"]
