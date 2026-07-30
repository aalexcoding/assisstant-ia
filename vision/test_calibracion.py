"""
Verificacion de la calibracion por contenido (vision/calibracion.py).

Lo que hay que blindar es el CRITERIO, porque es la parte que se puede relajar sin
darse cuenta y entonces el instrumento deja de encontrar nada: hacen falta LAS DOS
señales -tocar el borde Y ser mas estrecha que las hermanas-, y por separado
ninguna vale.

La prueba de que el criterio funciona no esta aqui sino en el campo: con los
valores de zona de ANTES de los arreglos del 30-07, la herramienta señala
exactamente los recortes que se habian encontrado a mano, y con los de despues no
señala nada en cuatro sesiones.
"""
import pytest

from vision import calibracion as cal

pytestmark = pytest.mark.vision

ZONA = (100, 200, 600, 400)      # x0, y0, x1, y1


def caja(x, w, y=210, h=120):
    return (x, y, w, h)


# --- que bordes toca --------------------------------------------------------

def test_una_caja_centrada_no_toca_nada():
    assert not any(cal.bordes_tocados(caja(300, 80), ZONA).values())


def test_se_detecta_cada_borde():
    assert cal.bordes_tocados(caja(100, 80), ZONA)["izq"]
    assert cal.bordes_tocados(caja(520, 80), ZONA)["der"]
    assert cal.bordes_tocados(caja(300, 80, y=200), ZONA)["arr"]
    assert cal.bordes_tocados(caja(300, 80, y=480, h=120), ZONA)["aba"]


def test_la_holgura_absorbe_un_pixel():
    """El detector devuelve enteros y el borde de la zona tambien, asi que una
    caja a un pixel del borde no es distinta de una que llega justo."""
    assert cal.bordes_tocados(caja(101, 80), ZONA)["izq"]
    assert not cal.bordes_tocados(caja(110, 80), ZONA)["izq"]


# --- el criterio: LAS DOS señales -------------------------------------------

def test_tocar_el_borde_SIN_ser_estrecha_no_es_recorte():
    """Es el falso positivo que hay que evitar: medido sobre el corpus, el 127% de
    las cartas de board tocaban el borde superior y casi ninguna estaba cortada."""
    cajas = [caja(100, 82), caja(190, 82), caja(280, 82)]
    assert not cal.recorte_de_zona(cajas, ZONA)["recorta"]


def test_ser_estrecha_Y_tocar_el_borde_SI_es_recorte():
    """El caso real: en el frame de la nota del usuario la primera carta media 67
    px contra los 82-83 de las otras dos, pegada al borde izquierdo."""
    cajas = [caja(100, 67), caja(190, 82), caja(280, 83)]
    v = cal.recorte_de_zona(cajas, ZONA)
    assert v["recorta"]
    assert v["lados"] == {"izq": 1}
    assert v["estrechas"] == 1


def test_una_caja_estrecha_EN_MEDIO_no_es_recorte():
    """Si no toca ningun borde, que sea estrecha es cosa suya: una ficha, un icono,
    una carta a medio repartir. La zona no la esta cortando."""
    cajas = [caja(150, 40), caja(250, 82), caja(340, 82)]
    assert not cal.recorte_de_zona(cajas, ZONA)["recorta"]


def test_con_menos_de_dos_cajas_no_hay_veredicto():
    """Sin hermanas no hay con que comparar el ancho. Se dice, en vez de
    inventarse un veredicto: es el caso del hero, que tiene dos cartas y a veces
    se le lee una."""
    v = cal.recorte_de_zona([caja(100, 40)], ZONA)
    assert not v["recorta"] and "nada que comparar" in v["motivo"]


# --- la correccion sugerida --------------------------------------------------

REF = (50, 100, 900, 450, False)


def test_la_correccion_va_en_la_direccion_de_AGRANDAR():
    """Agrandar puede meter ruido, y eso se ve en el recuento de cajas. Dejar la
    carta mordida cambia el rango que se lee, y eso no se ve: una carta de 67 px
    se leia 'A' donde habia un '4'."""
    v = cal.recorte_de_zona([caja(100, 67), caja(190, 82), caja(280, 83)], ZONA)
    c = cal.correccion_sugerida(v, (0.22, 0.24, 0.78, 0.60), REF)
    assert c["izq"] < 0, "el borde izquierdo tiene que ir hacia la izquierda"


def test_la_correccion_es_del_tamaño_de_lo_que_falta():
    """16 px que le faltan a la carta sobre un nucleo de 900 son 0,0178."""
    v = cal.recorte_de_zona([caja(100, 67), caja(190, 83), caja(280, 83)], ZONA)
    c = cal.correccion_sugerida(v, (0.22, 0.24, 0.78, 0.60), REF)
    assert abs(abs(c["izq"]) - 16 / 900) < 0.002


def test_sin_recorte_no_se_sugiere_nada():
    v = cal.recorte_de_zona([caja(200, 82), caja(300, 82)], ZONA)
    assert cal.correccion_sugerida(v, (0.22, 0.24, 0.78, 0.60), REF) == {}


# --- la escala por carta ----------------------------------------------------

def test_la_escala_sale_del_acuerdo_entre_cartas():
    """Medido: el ancho de carta tiene 0,7-8,4 px de desviacion contra 12-164 del
    ancho del nucleo, asi que es la medida mas estable que hay para la escala."""
    assert cal.escala_de_carta([caja(100, 82), caja(200, 83), caja(300, 82)]) == 82


def test_una_carta_MORDIDA_no_marca_la_escala():
    """Es el fallo que arruinaria la idea: tomar como escala justo la caja que esta
    cortada. Se exige acuerdo entre dos dentro del 15%."""
    assert cal.escala_de_carta([caja(100, 41), caja(200, 82), caja(300, 83)]) == 82


def test_sin_acuerdo_no_hay_escala():
    assert cal.escala_de_carta([caja(100, 40), caja(200, 82)]) is None
    assert cal.escala_de_carta([caja(100, 82)]) is None
