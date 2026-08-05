"""
El recuadro de la mesa: cuando se da por valido y en que unidades se guarda.

EL FALLO QUE CUBRE, y lo sufrio el usuario entero: recalibro, dibujo el recuadro
sobre una pantalla donde la mesa no estaba -habia quedado una ventana encima- y
el calibrador lo guardo tan contento. El sintoma aparecio media hora despues y en
otro sitio: la app repitiendo "no se encuentra la mesa en este frame" partida tras
partida, con 75 de 75 frames sin analizar.

El calibrador tiene delante el unico dato que hace falta para avisar -si en ese
recuadro se ve el ovalo del tapete, que es la misma pregunta que se hace
analyze_layout en cada frame- asi que callarselo es dejar el fallo para dentro de
media hora.

ESTO YA NO NECESITA GTK. Antes vivia dentro de la ventana (SelectorWindow) y por
eso el test solo corria donde hubiera PyGObject y display: en un Mac, la
comprobacion que evita el fallo mas caro del calibrador no se ejecutaba. Ahora es
una funcion suelta que usan los dos calibradores, el de GTK y el de consola.
"""
import json

import cv2
import numpy as np

from calibration import recuadro as rc
from vision import seat_map


def frame_con_mesa():
    """Un tapete verde ovalado sobre fondo oscuro, como el cliente real."""
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(img, (600, 400), (480, 215), 0, 0, 360, (40, 140, 60), -1)
    return img


def frame_sin_mesa():
    """Una ventana cualquiera: ni tapete ni ovalo. Es lo que capturo el usuario
    -su escritorio con otra ventana delante- sin enterarse."""
    return np.full((800, 1200, 3), 30, dtype=np.uint8)


# --- cuando hay mesa ---------------------------------------------------------

def test_un_recuadro_con_mesa_se_da_por_bueno():
    assert rc.hay_mesa(frame_con_mesa(), (60, 140, 1080, 520)) is True


def test_un_recuadro_sin_mesa_se_detecta():
    assert rc.hay_mesa(frame_sin_mesa(), (60, 140, 1080, 520)) is False


def test_un_recuadro_vacio_no_revienta():
    assert rc.hay_mesa(frame_con_mesa(), (10, 10, 0, 0)) is False


def test_la_pregunta_es_LA_MISMA_que_se_hace_el_analisis():
    """Si el calibrador usara otro criterio, podria dar por bueno un recuadro que
    la app luego no sabe leer, que es justo lo que hay que evitar."""
    img = frame_con_mesa()
    recorte = img[140:660, 60:1140]
    assert rc.hay_mesa(img, (60, 140, 1080, 520)) is (not seat_map.find_reference(recorte)[4])


# --- las unidades ------------------------------------------------------------

def test_la_vista_encoge_pero_el_recuadro_se_guarda_en_pixeles_del_frame():
    """La cuenta que no puede fallar: dibujar sobre una vista a la mitad y
    guardar la mitad de las coordenadas daria un recuadro desplazado, la app no
    encontraria la mesa, y el fallo saldria media hora despues jugando."""
    escala = rc.escala_de_vista(3024, 1964)
    assert escala < 1.0
    assert rc.a_coordenadas_de_frame((100, 50, 400, 300), escala) == (
        int(100 / escala), int(50 / escala), int(400 / escala), int(300 / escala))


def test_un_frame_pequeno_no_se_amplia():
    """Con escala 1 las coordenadas son las mismas, sin redondeos de por medio."""
    assert rc.escala_de_vista(800, 600) == 1.0
    assert rc.a_coordenadas_de_frame((10, 20, 30, 40), 1.0) == (10, 20, 30, 40)


def test_guardar_conserva_el_tamano_del_frame_del_que_salio(tmp_path, monkeypatch):
    """Sin el tamaño del frame no hay forma de saber si una calibracion vieja
    vale para la resolucion de hoy: es lo que comprueba gui._crop_region antes
    de recortar."""
    config = tmp_path / "config.local.json"
    monkeypatch.setattr(rc, "CONFIG_PATH", str(config))
    rc.save_region((3024, 1964), (10, 20, 300, 400))
    guardado = json.loads(config.read_text())["capture_region"]
    assert guardado == {"frame_width": 3024, "frame_height": 1964,
                        "x": 10, "y": 20, "width": 300, "height": 400}


def test_guardar_no_borra_lo_que_ya_hubiera_en_el_fichero(tmp_path, monkeypatch):
    config = tmp_path / "config.local.json"
    config.write_text('{"otra_cosa": 1}')
    monkeypatch.setattr(rc, "CONFIG_PATH", str(config))
    rc.save_region((1200, 800), (1, 2, 3, 4))
    assert json.loads(config.read_text())["otra_cosa"] == 1
