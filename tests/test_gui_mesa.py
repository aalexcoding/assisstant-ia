"""
Que el selector de MESA diga la verdad sobre lo que hace.

Hace DOS cosas y las dos importan: acota cuantos asientos puede haber -las
posiciones salen del RECUENTO de ocupados, asi que un asiento fantasma las
desplaza TODAS- y elige la GEOMETRIA, o sea donde se buscan.

Ya no ofrece "auto". Lo pidio el usuario y tenia razon: no detectaba nada. Solo
queria decir "no acotes y usa la disposicion de 6", asi que en una mesa de 8
leia 4,69 asientos de 8 y 2 nicks de 10 sin avisar de nada. Una opcion que dice
deducir algo y no lo deduce es peor que no tenerla: invita a dejarla puesta.
"""
import pytest

gi = pytest.importorskip("gi", reason="hace falta PyGObject")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk        # noqa: E402

import gui                                # noqa: E402
from vision import seat_map               # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(scope="module")
def app():
    a = Gtk.Application(application_id="org.pokerassistant.test_mesa",
                        flags=Gio.ApplicationFlags.NON_UNIQUE)
    a.register()
    return a


@pytest.fixture
def ventana(app):
    win = gui.PokerAssistantWindow(app, None)
    yield win
    win.destroy()


def test_el_selector_de_mesa_NO_ofrece_auto(ventana):
    """Lo pidio el usuario y tenia razon: 'auto' no detectaba nada. Solo queria
    decir "no acotes y usa la disposicion de 6", asi que en una mesa de 8 leia
    4,69 asientos de 8 y 2 nicks de 10 sin avisar. Una opcion que dice deducir
    algo y no lo deduce invita a dejarla puesta."""
    assert None not in gui.PokerAssistantWindow._MESA_OPCIONES
    assert ventana._max_players() is not None


def test_arranca_en_6_max(ventana):
    """La disposicion con todas las mediciones del proyecto detras."""
    assert ventana._max_players() == 6


def test_estan_las_cinco_mesas_y_en_el_orden_del_combo(ventana):
    """Si el orden se desincroniza, elegir 8-Max daria la geometria de otra mesa
    y el fallo no se veria: leeria nombres donde no hay nadie."""
    assert gui.PokerAssistantWindow._MESA_OPCIONES == (2, 3, 6, 8, 9)
    for i, plazas in enumerate(gui.PokerAssistantWindow._MESA_OPCIONES):
        ventana.mesa_combo.set_active(i)
        assert ventana._max_players() == plazas
        etiqueta = ventana.mesa_combo.get_active_text()
        assert str(plazas) in etiqueta, f"{etiqueta!r} no habla de {plazas} plazas"


def test_cada_opcion_da_una_geometria_coherente(ventana):
    """Cada opcion tiene que dar la geometria que le toca: 8 y 9 las suyas, y el
    resto la de 6, que es lo que hay medido. Une el combo con seat_map, que es
    donde se podria desincronizar sin que se note: elegir 9 plazas y recibir la
    geometria de otra mesa no falla de forma visible, lee nombres donde no hay
    nadie."""
    esperado = {2: 6, 3: 6, 6: 6, 8: 8, 9: 9}
    for i, plazas in enumerate(gui.PokerAssistantWindow._MESA_OPCIONES):
        ventana.mesa_combo.set_active(i)
        n = len(seat_map.zonas(ventana._max_players())["seats"])
        assert n == esperado[plazas], f"{plazas} plazas -> {n} asientos"


# --- el selector de MAZO ----------------------------------------------------

def test_el_selector_de_mazo_tiene_los_tres_caminos(ventana):
    """Lo pidio el usuario: "añade una opcion en la GUI para que yo te diga que
    mazo estoy usando". Auto sigue existiendo -y arranca- porque aqui la
    deteccion SI funciona: gana el que encuentra mas cartas, esta medido, y
    ademas cubre cambiar de mazo a mitad de sesion."""
    assert gui.PokerAssistantWindow._MAZO_OPCIONES == (None, "glyph", "solid")
    assert ventana._mazo() is None
    for i, mazo in enumerate(gui.PokerAssistantWindow._MAZO_OPCIONES):
        ventana.mazo_combo.set_active(i)
        assert ventana._mazo() == mazo


def test_el_mazo_elegido_llega_al_detector():
    """Fijarlo tiene que SALTARSE la competicion, no solo anotarse."""
    import numpy as np
    from vision import table_state as ts
    zona = (10, 10, 300, 200)
    img = np.zeros((300, 400, 3), np.uint8)
    llamados = []
    class Falso:
        def __init__(self, nombre): self.nombre = nombre
        def find_card_boxes(self, *a, **k):
            llamados.append(self.nombre); return []
    import unittest.mock as mock
    with mock.patch.object(ts, "glyph_card_detector", Falso("glyph")), \
         mock.patch.object(ts, "color_card_detector", Falso("solid")):
        llamados.clear(); ts._cajas_de_carta(img, zona, mazo="glyph")
        assert llamados == ["glyph"], llamados
        llamados.clear(); ts._cajas_de_carta(img, zona, mazo="solid")
        assert llamados == ["solid"], llamados
        llamados.clear(); ts._cajas_de_carta(img, zona)
        assert sorted(llamados) == ["glyph", "solid"], "sin fijar, compiten los dos"
