"""
El calibrador avisa cuando en el recuadro NO se ve una mesa.

EL FALLO QUE CUBRE, y lo sufrio el usuario entero: recalibro, dibujo el recuadro
sobre una pantalla donde la mesa no estaba -habia quedado una ventana encima- y
el calibrador lo guardo tan contento. El sintoma aparecio media hora despues y en
otro sitio: la app repitiendo "no se encuentra la mesa en este frame" partida tras
partida, con 75 de 75 frames sin analizar.

El calibrador tiene delante el unico dato que hace falta para avisar -si en ese
recuadro se ve el ovalo del tapete, que es la misma pregunta que se hace
analyze_layout en cada frame- asi que callarselo es dejar el fallo para dentro de
media hora.

NO IMPIDE GUARDARLO: el segundo Enter guarda igual. El usuario puede tener un
motivo (una mesa de un tema que el detector no ve todavia, por ejemplo) y quien
manda es el.
"""
import numpy as np
import pytest

pytest.importorskip("gi", reason="hace falta PyGObject")

from calibration import select_region as sr           # noqa: E402
from vision import seat_map                           # noqa: E402

pytestmark = pytest.mark.gtk


def frame_con_mesa():
    """Un tapete verde ovalado sobre fondo oscuro, como el cliente real."""
    import cv2
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(img, (600, 400), (480, 215), 0, 0, 360, (40, 140, 60), -1)
    return img


def frame_sin_mesa():
    """Una ventana cualquiera: ni tapete ni ovalo. Es lo que capturo el usuario
    -su escritorio con otra ventana delante- sin enterarse."""
    return np.full((800, 1200, 3), 30, dtype=np.uint8)


class VentanaFalsa:
    """Solo la parte de SelectorWindow que decide, sin GTK de por medio."""

    def __init__(self, frame):
        self.frame = frame

    _hay_mesa = sr.SelectorWindow._hay_mesa


def test_un_recuadro_con_mesa_se_da_por_bueno():
    v = VentanaFalsa(frame_con_mesa())
    assert v._hay_mesa((60, 140, 1080, 520)) is True


def test_un_recuadro_sin_mesa_se_detecta():
    v = VentanaFalsa(frame_sin_mesa())
    assert v._hay_mesa((60, 140, 1080, 520)) is False


def test_un_recuadro_vacio_no_revienta():
    v = VentanaFalsa(frame_con_mesa())
    assert v._hay_mesa((10, 10, 0, 0)) is False


def test_la_pregunta_es_LA_MISMA_que_se_hace_el_analisis():
    """Si el calibrador usara otro criterio, podria dar por bueno un recuadro que
    la app luego no sabe leer, que es justo lo que hay que evitar."""
    img = frame_con_mesa()
    v = VentanaFalsa(img)
    recorte = img[140:660, 60:1140]
    assert v._hay_mesa((60, 140, 1080, 520)) is (not seat_map.find_reference(recorte)[4])
