"""
El recorte del nameplate anclado a LA CAPSULA (table_state.capsula_px).

POR QUE EXISTE. La zona de un asiento es una fraccion del nucleo del tapete, y en
vivo ese nucleo es el FIJADO de la sesion, no el que se ve en el frame. Medido
sobre 12 sesiones de agosto, el borde de la zona baila 17 px de mediana, 98 de
p95 y hasta 133 respecto al ovalo del frame; la capsula mide ~380x115 px, asi que
un desvio asi le muerde el texto. Y cuando el recorte muerde el texto, casi nunca
se lee: 20 lecturas buenas de 136 medidas, frente a 516 de 629 cuando cabe.

Lo que se afirma aqui es la REGLA de eleccion, con imagenes sinteticas: donde no
hay capsula no se inventa una, la del vecino no vale, y la propia se recorta con
margen aunque la zona este desplazada. La ganancia sobre capturas reales esta
medida en el comentario de capsula_px.
"""
import numpy as np
import pytest

from vision import table_state as ts

pytestmark = pytest.mark.vision

TAPETE = (40, 120, 40)      # BGR: verde, saturado -> no es capsula
CAPSULA = (35, 33, 32)      # gris muy oscuro y casi sin color
ZONA = (300, 200, 680, 315)     # 380x115, como una zona de nameplate real


def mesa(*capsulas):
    """Un tapete con las capsulas que se le pidan, cada una (x0, y0, x1, y1)."""
    img = np.zeros((600, 1200, 3), dtype=np.uint8)
    img[:, :] = TAPETE
    for x0, y0, x1, y1 in capsulas:
        img[y0:y1, x0:x1] = CAPSULA
    return img


def test_sin_capsula_no_se_recorta_nada():
    """Un asiento vacio tiene que seguir leyendose como hasta ahora: quien llama
    usa la zona de siempre cuando esto devuelve None."""
    assert ts.capsula_px(mesa(), ZONA) is None


def test_la_capsula_centrada_se_recorta_con_margen():
    caja = (320, 215, 660, 300)
    x0, y0, x1, y1 = ts.capsula_px(mesa(caja), ZONA)
    m = ts.CAPSULA_MARGEN_PX
    assert (x0, y0, x1, y1) == (caja[0] - m, caja[1] - m, caja[2] + m, caja[3] + m)


def test_una_zona_desplazada_encuentra_su_capsula_igual():
    """El caso que motiva todo esto: la referencia fijada deja la zona 60 px a la
    derecha y la capsula sigue siendo la misma."""
    caja = (320, 215, 660, 300)
    desplazada = (ZONA[0] + 60, ZONA[1] + 10, ZONA[2] + 60, ZONA[3] + 10)
    assert ts.capsula_px(mesa(caja), desplazada) == ts.capsula_px(mesa(caja), ZONA)


def test_la_capsula_del_vecino_no_cuenta():
    """Sin este filtro, un asiento VACIO se quedaba con la mancha oscura mas
    grande de su ventana de busqueda -un trozo de la capsula de al lado- y de ahi
    salian nicks e importes de otro asiento: 4 asientos fantasma de 78 zonas
    vacias antes de exigir que la mancha pise la zona y tenga el centro dentro."""
    vecino = (700, 215, 1040, 300)         # pegado por la derecha, fuera de ZONA
    assert ts.capsula_px(mesa(vecino), ZONA) is None


def test_una_mancha_oscura_pequeña_no_es_una_capsula():
    """El disco del boton, una carta de dorso oscuro o una sombra no tienen el
    tamaño de un nameplate."""
    assert ts.capsula_px(mesa((480, 240, 520, 270)), ZONA) is None


def test_una_mancha_enorme_tampoco():
    """Un panel del cliente abierto encima de la mesa tapa la zona entera; ahi lo
    correcto es no anclar nada y quedarse con la zona."""
    assert ts.capsula_px(mesa((100, 100, 1100, 500)), ZONA) is None


def test_la_capsula_pegada_a_las_fichas_de_la_apuesta_no_vale():
    """Debajo de la capsula estan la marca de bounty y, si ese asiento ha
    apostado, SU MONTON DE FICHAS con el importe al lado. Todo eso es oscuro y
    sin color, asi que a veces sale pegado en una sola mancha; anclarse a ella
    mete la apuesta en el recorte del stack y la lectura pasa a ser ambigua.

    El caso real: frame 1861 de sesion-2026-08-03_221628. marta1525 tiene
    "27,8 BB" escrito clarisimo, la mancha medida daba 1,36 veces el alto de la
    zona -llegaba hasta las fichas de su ciega- y el asiento se quedaba SIN
    stack. Con la mancha rechazada se lee de la zona, y se lee bien."""
    capsula = (320, 190, 660, 290)
    fichas = (400, 290, 500, 345)          # pegadas por abajo: una sola mancha
    alto_zona = ZONA[3] - ZONA[1]
    assert (345 - 190) / alto_zona == pytest.approx(1.35, abs=0.03), \
        "la mancha del caso real medía 1,36 veces el alto de la zona"
    assert ts.capsula_px(mesa(capsula, fichas), ZONA) is None
    # y sin las fichas -el mismo asiento sin apostar- la capsula si vale
    assert ts.capsula_px(mesa(capsula), ZONA) is not None


@pytest.mark.parametrize("zona", [(300, 200, 300, 315), (300, 200, 680, 200)])
def test_una_zona_vacia_no_revienta(zona):
    assert ts.capsula_px(mesa((320, 215, 660, 300)), zona) is None
