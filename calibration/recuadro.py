"""
El recuadro de la mesa: donde se guarda y cuando es valido.

Esto no dibuja nada. Es lo que comparten los DOS calibradores -el de GTK
(select_region.py) y el de consola (select_region_cv.py, que es el que hay en
Mac mientras no haya GTK)- porque la parte que importa de calibrar no es la
ventana: es que el recuadro se guarde en el sitio y en las unidades correctas, y
que no se guarde callando uno donde no se ve la mesa.

Si esto viviera dentro de la ventana de GTK, el calibrador de consola tendria
que copiarlo, y entonces los dos avisarian de cosas distintas -o uno dejaria de
avisar- sin que nadie se enterase hasta la siguiente partida.
"""
import json
import os

from vision import seat_map

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.local.json")

# Ninguna pantalla de calibracion pinta el frame a tamaño real: con una captura
# Retina de 3024x1964 no cabria. Es solo para MIRAR; el recuadro se guarda
# siempre en pixeles del frame original (ver a_coordenadas_de_frame).
MAX_DISPLAY_SIZE = 1500

AVISO_SIN_MESA = "En ese recuadro NO se ve una mesa de poker."


def save_region(frame_size, rect):
    """Guarda el recuadro EN PIXELES DEL FRAME ORIGINAL, junto al tamaño del
    frame del que salio: sin eso no hay forma de saber si una calibracion vieja
    vale para la resolucion de hoy (lo comprueba gui._crop_region)."""
    data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            data = json.load(f)
    data["capture_region"] = {
        "frame_width": frame_size[0],
        "frame_height": frame_size[1],
        "x": rect[0],
        "y": rect[1],
        "width": rect[2],
        "height": rect[3],
    }
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def escala_de_vista(frame_w, frame_h):
    """Cuanto hay que encoger el frame para que quepa en pantalla. Nunca amplia."""
    return min(1.0, MAX_DISPLAY_SIZE / max(frame_w, frame_h))


def a_coordenadas_de_frame(rect_vista, escala):
    """Del recuadro que se dibujo SOBRE LA VISTA al del frame original.

    Es la unica cuenta de todo el calibrador y equivocarla no da error: da un
    recuadro desplazado, la app no encuentra la mesa, y el fallo aparece media
    hora despues jugando."""
    x, y, w, h = rect_vista
    return (int(x / escala), int(y / escala), int(w / escala), int(h / escala))


def hay_mesa(frame, rect):
    """¿Se ve el ovalo del tapete dentro de ese recuadro?

    Es exactamente la pregunta que se hace analyze_layout en cada frame (ver
    seat_map.find_reference): si aqui no se encuentra, en la partida tampoco, y
    todas las zonas quedarian desplazadas.

    EL FALLO QUE CUBRE, y lo sufrio el usuario entero: recalibro, dibujo el
    recuadro sobre una pantalla donde la mesa no estaba -habia quedado una
    ventana encima- y el calibrador lo guardo tan contento. El sintoma aparecio
    media hora despues y en otro sitio: la app repitiendo "no se encuentra la
    mesa en este frame" partida tras partida.
    """
    x, y, w, h = rect
    recorte = frame[y:y + h, x:x + w]
    if recorte.size == 0:
        return False
    try:
        return not seat_map.find_reference(recorte)[4]
    except Exception:                     # noqa: BLE001 - avisar nunca puede tumbar el calibrador
        return True
