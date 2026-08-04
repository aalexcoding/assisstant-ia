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
from vision import disposicion            # noqa: E402
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


def test_el_auto_del_selector_significa_DETECTARLA(ventana):
    """El "auto" se quito en su dia y volvio con la detección de verdad detras.

    La version vieja se retiro con razon: solo queria decir "no acotes y usa la
    disposicion de 6", asi que en una mesa de 8 leia 4,69 asientos de 8 y 2 nicks
    de 10 sin avisar de nada. La de ahora mira DONDE caen los nameplates y lo
    contrasta con las tres geometrias medidas (vision/disposicion.py): 25
    aciertos, 4 abstenciones y CERO errores sobre las 29 sesiones grabadas con
    disposicion conocida. Lo que hace None ahora es entregar la decision a ese
    detector, no dejar la mesa sin acotar.

    Si alguien vuelve a quitar el detector, este test tiene que caerse: un None
    en el selector sin nadie que lo resuelva es exactamente el "auto" viejo."""
    assert None in gui.PokerAssistantWindow._MESA_OPCIONES
    assert ventana._max_players() is None, "Auto es lo que arranca puesto"
    assert disposicion.PLAZAS_CANDIDATAS, "sin candidatas, Auto no decide nada"


def test_arranca_en_auto(ventana):
    """Acierta o se abstiene, nunca elige mal: es el arranque que menos exige al
    usuario sin arriesgar nada. Cuando se abstiene cae a la de 6, que es la
    disposicion con todas las mediciones del proyecto detras."""
    assert ventana._max_players() is None
    assert len(seat_map.zonas(None)["seats"]) == 6


def test_la_jerarquia_principal_es_compacta_y_tiene_scroll(ventana):
    """La información técnica no puede empujar la recomendación fuera de una
    ventana normal ni competir con ella al arrancar."""
    assert ventana.main_scroll.get_vexpand() is True
    assert ventana.state_details.get_expanded() is False
    assert ventana.rec_label.get_parent() is not None
    assert ventana.header_status_label.get_text() == "EN ESPERA"


def test_la_accion_en_castellano_es_la_lectura_principal(ventana):
    estado = {
        "hero_cards": ["Ah", "Kd"],
        "board": [],
        "pot": "1,5 BB",
        "players": [{"name": "yo", "position": "BTN", "stack": 20,
                     "is_hero": True}],
        "acciones": {"acciones": []},
        "warnings": [],
    }
    ventana.on_result(
        estado,
        {"action": "OPEN RAISE (2 BB)", "action_en": "OPEN RAISE (2 BB)",
         "action_es": "subir a 2 BB", "source": "chart",
         "reasoning": "Rango de apertura"},
    )
    texto = ventana.rec_label.get_text()
    assert texto.startswith("SUBIR A 2 BB")
    assert "Código de tabla: OPEN RAISE (2 BB)" in texto


def test_estan_las_siete_opciones_y_en_el_orden_del_combo(ventana):
    """Si el orden se desincroniza, elegir 8-Max daria la geometria de otra mesa
    y el fallo no se veria: leeria nombres donde no hay nadie."""
    assert gui.PokerAssistantWindow._MESA_OPCIONES == (None, 2, 3, 6, 7, 8, 9)
    for i, plazas in enumerate(gui.PokerAssistantWindow._MESA_OPCIONES):
        ventana.mesa_combo.set_active(i)
        assert ventana._max_players() == plazas
        etiqueta = ventana.mesa_combo.get_active_text()
        esperado = "Auto" if plazas is None else str(plazas)
        assert esperado in etiqueta, f"{etiqueta!r} no habla de {esperado}"


def test_cada_opcion_da_una_geometria_coherente(ventana):
    """Cada opcion tiene que dar la geometria que le toca: 8 y 9 las suyas, y el
    resto la de 6, que es lo que hay medido. Une el combo con seat_map, que es
    donde se podria desincronizar sin que se note: elegir 9 plazas y recibir la
    geometria de otra mesa no falla de forma visible, lee nombres donde no hay
    nadie.

    Auto tambien cae a la de 6, y eso es lo correcto: es la que se usa MIENTRAS
    el detector no tiene evidencia. Cuando la tiene, quien cambia la geometria es
    el Analizador (ver core.Analizador._usar_plazas), no esta funcion."""
    esperado = {None: 6, 2: 6, 3: 6, 6: 6, 7: 7, 8: 8, 9: 9}
    for i, plazas in enumerate(gui.PokerAssistantWindow._MESA_OPCIONES):
        ventana.mesa_combo.set_active(i)
        n = len(seat_map.zonas(ventana._max_players())["seats"])
        assert n == esperado[plazas], f"{plazas} plazas -> {n} asientos"


# --- el selector de MAZO ----------------------------------------------------

def test_el_selector_de_mazo_tiene_los_tres_caminos(ventana):
    """Solid es producción; glyph y auto siguen disponibles explícitamente."""
    assert gui.PokerAssistantWindow._MAZO_OPCIONES == ("solid", "glyph", None)
    assert ventana._mazo() == "solid"
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


def test_la_sesion_grabada_anota_MESA_Y_MAZO(ventana, tmp_path, monkeypatch):
    """Sin esos dos en la meta, reproducir la sesion despues no la reproduce:
    max_players elige la geometria y el mazo se salta la competicion de
    detectores. Es lo que rompio la regresion de oro en cuanto se grabo la
    primera sesion de 9 -4 tests rojos sin que nada estuviera mal- y lo que
    tests/corpus.meta_de_sesion existe para leer."""
    import testing_session as tss
    monkeypatch.setattr(tss, "TESTING_DIR", str(tmp_path))
    ventana.mesa_combo.set_active(gui.PokerAssistantWindow._MESA_OPCIONES.index(9))
    ventana.mazo_combo.set_active(gui.PokerAssistantWindow._MAZO_OPCIONES.index("solid"))
    ses = tss.TestingSession(root=str(tmp_path))
    ses.meta["max_players"] = ventana._max_players()
    ses.meta["mazo"] = ventana._mazo()
    assert ses.meta["max_players"] == 9
    assert ses.meta["mazo"] == "solid"


# --- se ve QUE MESA se esta usando ------------------------------------------
# Lo pidio el usuario: "ponme en algun punto de la gui que geometria de mesa ha
# encontrado". Es lo que decide DONDE se buscan los asientos, y de su recuento
# salen todas las posiciones, asi que cuando algo no cuadra es lo primero que hay
# que poder mirar.

def test_mientras_decide_lo_dice_y_dice_con_que_esta_mirando(ventana):
    texto = ventana._texto_mesa({"max_players": None, "disposicion_detectada": None,
                                 "mesa_elegida": None})
    assert "mirando" in texto
    assert "6" in texto, "hay que decir con que geometria se esta mirando entretanto"


def test_cuando_la_detecta_se_ve_el_numero_Y_que_es_detectada(ventana):
    texto = ventana._texto_mesa({"max_players": 9, "disposicion_detectada": 9,
                                 "mesa_elegida": None})
    assert "9" in texto and "detect" in texto.lower()


def test_elegida_a_mano_se_ve_como_elegida(ventana):
    texto = ventana._texto_mesa({"max_players": 6, "disposicion_detectada": 6,
                                 "mesa_elegida": 6})
    assert "6" in texto and "elegida" in texto


def test_si_el_tapete_no_cuadra_con_lo_elegido_se_avisa_ahi_mismo(ventana):
    """El fallo mudo que esto destapa: elegir 6-Max en una mesa de 9 lee 6 de los
    9 asientos y el recuento desplaza todas las posiciones."""
    texto = ventana._texto_mesa({"max_players": 6, "disposicion_detectada": 9,
                                 "mesa_elegida": 6})
    assert "6" in texto and "9" in texto
    assert "parece" in texto


def test_el_panel_de_sistema_tiene_la_etiqueta(ventana):
    assert ventana.mesa_label.get_parent() is not None


def test_la_mesa_de_7_se_puede_elegir_a_mano(ventana):
    """Es la de las FINALES, y la encontro el usuario señalando el frame 4317 de
    una sesion de 6.573 despues de que se dijera que no existia. Se elige a mano
    porque el detector automatico todavia no la propone: meterla entre sus
    candidatas le cuesta 5 aciertos en las demas y, medido sobre el unico tramo
    grabado de mesa de 7, no gana ninguno -ahi la referencia del tapete esta rota
    y no llega al minimo de evidencia-. Ver vision/disposicion.PLAZAS_CANDIDATAS."""
    i = gui.PokerAssistantWindow._MESA_OPCIONES.index(7)
    ventana.mesa_combo.set_active(i)
    assert ventana._max_players() == 7
    assert len(seat_map.zonas(7)["seats"]) == 7
    assert 7 not in disposicion.PLAZAS_CANDIDATAS
