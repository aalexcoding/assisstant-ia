"""
Verificacion de que el ESTUDIO POST-MANO se hace sobre el board de SU mano.

El board no esta en pantalla cuando la mano termina -el cliente ya lo ha
retirado-, asi que la ventana guarda el ultimo que vio mientras la mano corria y
lo usa despues. Ese apaño tiene un filo: si no se tira al gastarlo, se queda
puesto, y la siguiente mano que termine SIN board -todos se retiran preflop, que
es el desenlace mas comun de todos- estudiaria el board de la mano anterior y lo
presentaria como suyo.

La ventana se levanta sin presentarla, con la aplicacion registrada pero sin lazo
principal, igual que en test_gui_notas.
"""
import pytest

gi = pytest.importorskip("gi", reason="hace falta PyGObject")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk        # noqa: E402

import gui                                # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(scope="module")
def app():
    a = Gtk.Application(application_id="org.pokerassistant.test_estudio",
                        flags=Gio.ApplicationFlags.NON_UNIQUE)
    a.register()
    return a


@pytest.fixture
def ventana(app, monkeypatch):
    """El estudio de verdad lanza un hilo que carga el modelo de embeddings y
    consulta el indice. Aqui solo interesa CON QUE BOARD se le llama, asi que se
    sustituye por un buzon."""
    win = gui.PokerAssistantWindow(app, 1.2)
    llamadas = []
    monkeypatch.setattr(
        win, "_buscar_estudio",
        lambda board, ganadora, showdown, contexto=None:
        llamadas.append((board, contexto)))
    win.llamadas = llamadas
    yield win
    win.destroy()


def termina_mano(win, n, board=None):
    if board is not None:
        win.on_result({"board": board, "players": [], "hero_cards": None}, None)
    # `showdown` es la LISTA de manos enseñadas, no un booleano: _render_prev_hand
    # la recorre. El estudio solo mira si esta vacia o no.
    win.on_hand_result({"hand_number": n, "summary": f"mano {n}",
                        "winning_hand": None, "showdown": [], "winners": []})


def test_el_estudio_recibe_el_board_de_la_mano_que_termina(ventana):
    termina_mano(ventana, 1, board=["Ah", "Kd", "2c"])
    assert ventana.llamadas[0][0] == ["Ah", "Kd", "2c"]
    assert ventana.llamadas[0][1]["board"] == ["Ah", "Kd", "2c"]


def test_una_mano_sin_board_no_hereda_el_de_la_anterior(ventana):
    """El caso que rompe: la mano 1 llega a flop, la mano 2 se acaba preflop.
    Sin vaciar, la 2 estudiaria el flop de la 1."""
    termina_mano(ventana, 1, board=["Ah", "Kd", "2c"])
    termina_mano(ventana, 2)
    assert [x[0] for x in ventana.llamadas] == [["Ah", "Kd", "2c"], []]
    assert ventana.llamadas[1][1] == {}


def test_pinta_ficha_trazable_aunque_el_indice_semantico_falle(ventana):
    ventana.on_estudio({
        "fichas": [{
            "title": "Multiway: rangos más fuertes",
            "principle": "Apostar y continuar más estrecho.",
            "consider": ["Evitar range-bet", "Valorar el potencial de nuts"],
            "limits": ["No sustituye rangos específicos."],
            "source": {
                "name": "Guía pública",
                "url": "https://example.test/guia",
            },
        }],
        "referencias": [],
        "problema": "índice no disponible",
    })
    text = ventana.prev_coach_label.get_text()
    assert "Multiway: rangos más fuertes" in text
    assert "Guía pública" in text
    assert "índice no disponible" in text
