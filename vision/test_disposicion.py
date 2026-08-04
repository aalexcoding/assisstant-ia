"""
Que mesa es: la decision de vision/disposicion.py.

Se prueba con mesas SINTETICAS -tapete verde con capsulas grises donde la
disposicion dice que hay asientos-, porque lo que hay que blindar es la REGLA:
que la disposicion buena gane, que gane con margen, que se abstenga cuando no lo
tiene claro y que no cambie de opinion por un frame suelto. Con capturas reales
eso queda escondido detras de si la capsula se detecto o no, que es otra cosa y
se mide aparte (ver test_disposicion_corpus.py, que la contrasta contra las
sesiones grabadas).

LA REGLA QUE MAS IMPORTA es la abstencion. Una disposicion equivocada no falla de
forma visible -lee nombres donde no hay nadie y deja jugadores invisibles-, y eso
desplaza TODAS las posiciones, que salen del recuento de ocupados. Por eso sobre
el corpus el detector acierta 20 de 29, se abstiene en 9 y no se equivoca en
ninguna: el reparto de errores correcto.
"""
import numpy as np
import pytest

from vision import disposicion as disp
from vision import seat_map

pytestmark = pytest.mark.vision

TAPETE = (40, 120, 40)          # BGR verde saturado: es fieltro, no capsula
CAPSULA = (35, 33, 32)          # gris muy oscuro y casi sin color
REF = (200, 150, 1000, 400, False)
FORMA = (900, 1600, 3)


def mesa(plazas, ocupados=None, ruido=()):
    """Un tapete con una capsula en cada asiento de esa disposicion.

    ocupados: cuantos asientos poner (None = todos). Sirve para el caso que el
    usuario describio: "en 6-max a veces hay sentados 3".
    """
    img = np.zeros(FORMA, dtype=np.uint8)
    img[:, :] = TAPETE
    zonas = list(seat_map.zonas(plazas)["seats"].items())
    if ocupados is not None:
        zonas = zonas[:ocupados]
    for _nombre, z in zonas:
        x0, y0, x1, y1 = seat_map.zone_to_px(REF, z["plate"], FORMA)
        # una capsula ocupa casi toda la zona, como en una mesa de verdad
        mx, my = int((x1 - x0) * 0.08), int((y1 - y0) * 0.08)
        img[y0 + my:y1 - my, x0 + mx:x1 - mx] = CAPSULA
    for x0, y0, x1, y1 in ruido:
        img[y0:y1, x0:x1] = CAPSULA
    return img


@pytest.mark.parametrize("plazas", disp.PLAZAS_CANDIDATAS)
def test_una_mesa_llena_se_reconoce(plazas):
    assert disp.decidir(disp.puntuar(mesa(plazas), REF)) == plazas


@pytest.mark.parametrize("plazas, ocupados", [(6, 3), (9, 4), (9, 7), (8, 4)])
def test_una_mesa_a_medias_tambien(plazas, ocupados):
    """El caso que describio el usuario: "en 6-max a veces hay sentados 3, luego
    las mesas finales son de 7, 8 o 9". Lo que se detecta es DONDE estan las
    plazas, no cuantas estan ocupadas: tres jugadores de un 6-max siguen cayendo
    en sitios de 6-max, y una final de 7 es una mesa de 9 con dos huecos."""
    assert disp.decidir(disp.puntuar(mesa(plazas, ocupados), REF)) == plazas


def test_un_tapete_vacio_no_decide_nada():
    """Entre torneos, o con la mesa recien abierta, no hay evidencia de nada."""
    vacia = np.zeros(FORMA, dtype=np.uint8)
    vacia[:, :] = TAPETE
    assert disp.decidir(disp.puntuar(vacia, REF)) is None


def test_dos_asientos_no_bastan_para_decidir():
    """Un heads-up cae en sitios que comparten las tres disposiciones, asi que no
    hay forma de saber que mesa es. Abstenerse es la respuesta correcta: con la
    de 6 puesta por defecto se leen los dos asientos igual."""
    assert disp.decidir(disp.puntuar(mesa(6, 2), REF)) is None


def test_la_de_8_no_gana_en_una_mesa_de_6():
    """Es el par que mas se parece -comparten varios asientos- y el que obligo a
    penalizar las capsulas que una disposicion deja sin explicar."""
    puntos = disp.puntuar(mesa(6), REF)
    assert puntos[6] > puntos[8], puntos
    assert puntos[6] >= disp.MARGEN * max(puntos[8], puntos[9]), puntos


def test_la_de_6_no_gana_en_una_mesa_de_9():
    puntos = disp.puntuar(mesa(9), REF)
    assert puntos[9] > puntos[6], puntos


# --- el pestillo de sesion ---------------------------------------------------

def test_no_decide_con_un_frame_suelto():
    """Entre manos las capsulas se atenuan y una mesa a medias puntua poco en
    todas; hace falta evidencia acumulada."""
    fijador = disp.DisposicionFijada()
    assert fijador.de(mesa(9), REF) is None
    assert fijador.fijada is None


def test_fija_con_los_frames_de_evidencia():
    fijador = disp.DisposicionFijada()
    img = mesa(9)
    for _ in range(disp.FRAMES_PARA_FIJAR):
        salida = fijador.de(img, REF)
    assert salida == 9
    assert fijador.fijada == 9


def test_una_vez_fijada_no_la_mueve_un_frame_raro():
    """Cambiar de disposicion a mitad de mano desplaza TODAS las posiciones, asi
    que hace falta que otra gane de forma SEGUIDA para moverse."""
    fijador = disp.DisposicionFijada()
    for _ in range(disp.FRAMES_PARA_FIJAR):
        fijador.de(mesa(9), REF)
    for _ in range(disp.FRAMES_PARA_REFIJAR - 1):
        assert fijador.de(mesa(6), REF) == 9
    assert fijador.de(mesa(6), REF) == 6, "con la evidencia seguida SI se re-fija"


def test_una_racha_interrumpida_no_cuenta():
    fijador = disp.DisposicionFijada()
    for _ in range(disp.FRAMES_PARA_FIJAR):
        fijador.de(mesa(9), REF)
    for _ in range(disp.FRAMES_PARA_REFIJAR - 1):
        fijador.de(mesa(6), REF)
    fijador.de(mesa(9), REF)                      # vuelve a verse la buena
    for _ in range(disp.FRAMES_PARA_REFIJAR - 1):
        assert fijador.de(mesa(6), REF) == 9, "la racha tiene que empezar de cero"


def test_sin_evidencia_sigue_intentandolo():
    """Si la primera tanda no decide, no se zanja para siempre: la mesa puede
    estar llenandose."""
    fijador = disp.DisposicionFijada()
    vacia = np.zeros(FORMA, dtype=np.uint8)
    vacia[:, :] = TAPETE
    for _ in range(disp.FRAMES_PARA_FIJAR):
        fijador.de(vacia, REF)
    assert fijador.fijada is None
    for _ in range(disp.FRAMES_PARA_FIJAR):
        salida = fijador.de(mesa(8), REF)
    assert salida == 8


# --- la mesa de 7 ------------------------------------------------------------

def test_la_mesa_de_7_no_esta_y_no_se_inventa():
    """No hay tabla de 7 porque no hay un solo frame de una en el corpus (se
    busco: ver el docstring del modulo). Lo que NO se hace es colocar una a ojo:
    una disposicion inventada lee nombres donde no hay nadie."""
    assert 7 not in disp.PLAZAS_CANDIDATAS
    assert len(seat_map.zonas(7)["seats"]) == 6, "cae a la de 6, como siempre"


def test_una_final_de_7_es_una_mesa_de_9_con_dos_huecos():
    """Que es lo que de verdad pasa en un torneo: los asientos no se mueven, se
    vacian. Aqui se comprueba que eso se detecta como 9, que es lo correcto."""
    assert disp.decidir(disp.puntuar(mesa(9, 7), REF)) == 9
