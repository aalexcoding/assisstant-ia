"""
Que la ventana ENSEÑE el ritmo en vez de PEDIRLO.

El selector de intervalo que habia aqui no describia nada: 8 de sus 40 valores
son fisicamente imposibles -el ciclo tarda 0,72 s de mediana, asi que pedir
0,25 s no acelera, solo hace que el latido venza siempre- y el periodo real nunca
fue el elegido, porque se cuenta desde que TERMINA el analisis (pidiendo 1,0 s la
app analizaba cada 1,6-1,9 s).

La logica del ritmo se prueba en tests/test_core_analisis.py, que es donde vive.
Aqui solo se blinda el cableado: que el widget no vuelva, que la etiqueta exista
y que lo que el hilo publica llegue a ella.
"""
import pytest

gi = pytest.importorskip("gi", reason="hace falta PyGObject")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk        # noqa: E402

import gui                                # noqa: E402

pytestmark = pytest.mark.gtk


@pytest.fixture(scope="module")
def app():
    a = Gtk.Application(application_id="org.pokerassistant.test_ritmo",
                        flags=Gio.ApplicationFlags.NON_UNIQUE)
    a.register()
    return a


@pytest.fixture
def ventana(app):
    win = gui.PokerAssistantWindow(app, None)
    yield win
    win.destroy()


def test_la_ventana_NO_tiene_selector_de_intervalo(ventana):
    """Si vuelve, vuelve a pedirle al usuario un numero que no puede saber."""
    assert not hasattr(ventana, "interval_spin")


def test_la_ventana_tiene_etiqueta_de_ritmo(ventana):
    assert ventana.ritmo_label.get_text().startswith("Ritmo")


def test_lo_que_publica_el_hilo_llega_a_la_etiqueta(ventana):
    """on_ritmo es lo que el hilo de analisis llama por GLib.idle_add tras cada
    ciclo. Devuelve False para no repetirse, como todo idle_add de un solo uso."""
    assert ventana.on_ritmo("Ritmo: 0.59 s/analisis (p95 0.90)") is False
    assert ventana.ritmo_label.get_text() == "Ritmo: 0.59 s/analisis (p95 0.90)"


def test_sin_interval_el_latido_se_mide():
    """Por defecto no hay intervalo fijo: si lo hubiera, el ritmo medido no se
    usaria NUNCA. Es el fallo que tuvo la primera version de este cambio, con
    --interval a 1.0 por defecto."""
    w = gui.AnalysisWorker.__new__(gui.AnalysisWorker)
    from core.analisis import Ritmo, PERIODO_MIN_S
    w.ritmo = Ritmo(fijo=None)
    assert w.ritmo.periodo_s == PERIODO_MIN_S
    w.ritmo.anota(0.8)
    assert w.ritmo.periodo_s > PERIODO_MIN_S, "se mueve con lo medido"
