"""
Verificacion de la funcion de NOTAS de la GUI: marcar una situacion rara mientras
se juega y anotarla para revisarla despues.

Lo unico que hay que blindar aqui es el motivo por el que la funcion va en DOS
PASOS: el usuario ve la rareza y LUEGO escribe, y con el ciclo en ~1,2 s para
cuando termina la frase ya han pasado varios frames. Si la nota se pegara al
frame del momento de GUARDAR, apuntaria al frame equivocado y la funcion no
serviria para nada. Asi que el test simula justo eso: marcar en el frame 1,
dejar pasar cuatro frames, y escribir la nota al final.

La ventana se levanta sin presentarla, con la aplicacion REGISTRADA pero sin
lazo principal: GTK4 exige una aplicacion registrada para crear una
ApplicationWindow, pero no exige que este corriendo.
"""
import json
import os

import numpy as np
import pytest

gi = pytest.importorskip("gi", reason="hace falta PyGObject")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk        # noqa: E402

import gui                                # noqa: E402
import testing_session as tss             # noqa: E402

pytestmark = pytest.mark.gtk


def leer(directorio, n):
    with open(os.path.join(directorio, f"{n:04d}.json")) as fh:
        return json.load(fh)


def png(ruta):
    with open(ruta, "wb") as f:
        f.write(b"png")


def frame_falso(n):
    """Lo que el hilo de analisis manda a on_frame_ready."""
    return (np.zeros((8, 8, 3), dtype=np.uint8),
            {"state": {"hero_cards": ["Ah", "Kd"], "hero_position": "CO"},
             "recommendation": {"action": "FOLD", "action_en": "FOLD"}},
            n)


@pytest.fixture(scope="module")
def app():
    """UNA sola aplicacion por proceso: registrar dos veces el mismo
    application_id revienta con "An object is already exported". Se registra sin
    correr el lazo principal, que es lo unico que GTK4 exige para poder crear una
    ApplicationWindow."""
    a = Gtk.Application(application_id="org.pokerassistant.test_notas",
                        flags=Gio.ApplicationFlags.NON_UNIQUE)
    a.register()
    return a


@pytest.fixture
def ventana(app, tmp_path, monkeypatch):
    """Una ventana limpia por test. TESTING_DIR se desvia al tmp para que las
    carpetas de notas creadas al vuelo no ensucien el testing/ del repo."""
    monkeypatch.setattr(tss, "TESTING_DIR", str(tmp_path))
    win = gui.PokerAssistantWindow(app, 1.2)
    yield win
    win.destroy()


@pytest.fixture
def sesion(tmp_path):
    return tss.TestingSession(root=str(tmp_path))


def analizar(win, ses, n):
    """Simula un ciclo completo del hilo de analisis publicando en la ventana."""
    crop, datos, _ = frame_falso(n)
    if ses is not None:
        ses.guardar(crop, datos, png)
    win.on_frame_ready(crop, datos, n if ses is not None else None, ses)


# --- sin nada analizado: decirlo, no fallar en silencio ---------------------

def test_sin_frames_analizados_el_boton_de_marcar_esta_apagado(ventana):
    assert not ventana.mark_button.get_sensitive()


def test_marcar_sin_frames_no_hace_nada_pero_avisa(ventana):
    assert ventana._on_marcar() is False
    assert ventana._marcado is None
    assert "Iniciar analisis" in ventana.nota_estado.get_text()


# --- marcar durante una sesion de testing ----------------------------------

def test_con_un_frame_analizado_el_boton_se_enciende(ventana, sesion):
    ventana.sesion = sesion
    analizar(ventana, sesion, 1)
    assert ventana.mark_button.get_sensitive()


def test_marcar_fija_el_frame_que_se_estaba_viendo_y_lo_dice(ventana, sesion):
    ventana.sesion = sesion
    analizar(ventana, sesion, 1)
    ventana._on_marcar()
    assert ventana._marcado is not None
    assert ventana._marcado["n"] == 1
    assert "0001" in ventana.nota_estado.get_text(), \
        "la UI dice CUAL, que es lo que hace la funcion usable"


# --- EL CASO QUE JUSTIFICA TODO: pasan frames mientras se escribe ----------

@pytest.fixture
def marcada_y_cuatro_frames_despues(ventana, sesion):
    """Se marca el frame 1 y luego llegan cuatro frames mas, como cuando el
    usuario esta escribiendo."""
    ventana.sesion = sesion
    analizar(ventana, sesion, 1)
    ventana._on_marcar()
    for n in (2, 3, 4, 5):
        analizar(ventana, sesion, n)
    return ventana, sesion


def test_el_marcado_no_se_mueve_aunque_sigan_llegando_frames(marcada_y_cuatro_frames_despues):
    win, _ses = marcada_y_cuatro_frames_despues
    assert win._marcado["n"] == 1


def test_la_nota_se_guarda_en_el_frame_marcado(marcada_y_cuatro_frames_despues):
    """Y NO en el que se estaba analizando al terminar de escribir: si fuera asi,
    la funcion no serviria para nada."""
    win, ses = marcada_y_cuatro_frames_despues
    win.nota_entry.set_text("recomienda FOLD con AK y no lo entiendo")
    win._on_guardar_nota()
    assert leer(ses.dir, 1).get("nota") == "recomienda FOLD con AK y no lo entiendo"
    assert leer(ses.dir, 5).get("nota") is None


def test_tras_guardar_el_campo_se_vacia_y_la_marca_se_suelta(marcada_y_cuatro_frames_despues):
    """Para no colgar dos notas del mismo frame sin querer."""
    win, _ses = marcada_y_cuatro_frames_despues
    win.nota_entry.set_text("algo")
    win._on_guardar_nota()
    assert win.nota_entry.get_text() == ""
    assert win._marcado is None


# --- guardar sin haber marcado: no se pierde el texto, pero se avisa -------

def test_sin_marca_previa_la_nota_va_al_frame_de_ahora_y_se_avisa(ventana, sesion):
    ventana.sesion = sesion
    for n in (1, 2, 3):
        analizar(ventana, sesion, n)
    ventana.nota_entry.set_text("esto tambien canta")
    ventana._on_guardar_nota()
    assert leer(sesion.dir, 3).get("nota")
    assert "OJO" in ventana.nota_estado.get_text(), \
        "puede no ser el frame de la anomalia y hay que decirlo"


def test_una_nota_vacia_no_crea_nada(ventana, sesion):
    ventana.sesion = sesion
    analizar(ventana, sesion, 1)
    ventana.nota_entry.set_text("   ")
    ventana._on_guardar_nota()
    assert "Escribe la nota" in ventana.nota_estado.get_text()


# --- SIN modo testing: es justo cuando mas falta hace guardar el frame -----

@pytest.fixture
def sin_grabar(ventana):
    """El modo testing apagado y una nota escrita: la carpeta se crea al vuelo."""
    ventana.sesion = None
    crop, datos, _ = frame_falso(9)
    ventana.on_frame_ready(crop, datos, None, None)     # n=None: no se guardo nada
    ventana.nota_entry.set_text("aqui la posicion sale mal")
    ventana._on_guardar_nota()
    return ventana


def test_con_el_modo_testing_apagado_se_crea_una_carpeta_de_notas(sin_grabar):
    assert sin_grabar.sesion_notas is not None
    assert os.path.basename(sin_grabar.sesion_notas.dir).startswith("notas-")


def test_se_guarda_el_frame_marcado_con_todo_lo_calculado_de_el(sin_grabar):
    d = leer(sin_grabar.sesion_notas.dir, 1)
    assert d["state"]["hero_position"] == "CO"
    assert d["recommendation"]["action"] == "FOLD"
    assert d.get("nota") == "aqui la posicion sale mal"


def test_y_su_png_al_lado_para_poder_mirar_la_imagen(sin_grabar):
    assert os.path.exists(os.path.join(sin_grabar.sesion_notas.dir, "0001.png"))


def test_las_notas_de_la_misma_ejecucion_van_a_la_misma_carpeta(sin_grabar):
    """No una carpeta por nota."""
    carpeta = sin_grabar.sesion_notas.dir
    crop, datos, _ = frame_falso(10)
    sin_grabar.on_frame_ready(crop, datos, None, None)
    sin_grabar.nota_entry.set_text("y otra mas")
    sin_grabar._on_guardar_nota()
    assert sin_grabar.sesion_notas.dir == carpeta
    assert leer(carpeta, 2).get("nota") == "y otra mas"
    assert len(tss.resumen(carpeta)["notas"]) == 2


# --- MODO HUD: la misma ventana, con lo secundario escondido ---------------
# Se mira en plena mano, asi que lo que NO puede pasar es que esconda la
# recomendacion o la equity, que son justo para lo que se enciende.

def test_el_modo_hud_esconde_los_paneles_secundarios(ventana):
    ventana.hud_check.set_active(True)
    assert all(not p.get_visible() for p in ventana._paneles_secundarios)
    assert ventana.rec_label.get_parent() is not None, \
        "pero NUNCA la recomendacion: es para lo que se enciende"
    assert "HUD" in ventana.get_title()


def test_al_apagar_el_modo_hud_vuelve_todo(ventana):
    antes = [p.get_visible() for p in ventana._paneles_secundarios]
    ventana.hud_check.set_active(True)
    ventana.hud_check.set_active(False)
    assert [p.get_visible() for p in ventana._paneles_secundarios] == antes
    assert "HUD" not in ventana.get_title()
