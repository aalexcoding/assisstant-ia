"""
El calibrador de consola, sin ventana de opencv delante.

Lo unico suyo que hay que probar es el LAZO: cuantas veces pregunta, cuando
avisa y cuando se rinde y guarda. Dibujar el rectangulo lo hace cv2.selectROI y
no es nuestro; se inyecta.

Lo importante es que se comporte IGUAL que el de GTK ante un recuadro sin mesa:
avisar la primera vez y guardar si el usuario insiste. Dos calibradores que
avisan distinto son peores que uno solo, porque el usuario aprende el
comportamiento de uno y se lleva la sorpresa con el otro.
"""
import numpy as np

from calibration import select_region_cv as src
from calibration.test_recuadro import frame_con_mesa, frame_sin_mesa


class Usuario:
    """Devuelve los recuadros que se le digan, uno por pregunta."""

    def __init__(self, *rects):
        self.rects = list(rects)
        self.veces = 0

    def __call__(self, vista):
        self.veces += 1
        self.vista = vista
        return self.rects.pop(0) if self.rects else None


def test_un_recuadro_con_mesa_se_acepta_a_la_primera():
    usuario = Usuario((60, 140, 1080, 520))
    rect = src.calibrar(frame_con_mesa(), usuario, log=lambda _m: None)
    assert rect == (60, 140, 1080, 520)
    assert usuario.veces == 1


def test_uno_sin_mesa_avisa_y_vuelve_a_preguntar():
    avisos = []
    usuario = Usuario((10, 10, 100, 100), (60, 140, 1080, 520))
    rect = src.calibrar(frame_con_mesa(), usuario, log=avisos.append)
    assert rect == (60, 140, 1080, 520)
    assert usuario.veces == 2
    assert len(avisos) == 1 and "NO se ve una mesa" in avisos[0]


def test_si_el_usuario_insiste_se_guarda_igual():
    """Manda el: puede tener un motivo (un tema de mesa que el detector no
    conoce todavia). Lo que no puede pasar es que se guarde en SILENCIO."""
    avisos = []
    usuario = Usuario((10, 10, 100, 100), (20, 20, 200, 200))
    rect = src.calibrar(frame_sin_mesa(), usuario, log=avisos.append)
    assert rect == (20, 20, 200, 200)
    assert len(avisos) == 1


def test_salir_sin_dibujar_no_devuelve_recuadro():
    """ESC en cv2.selectROI. No se guarda nada: mejor quedarse con la
    calibracion anterior que machacarla con un recuadro vacio."""
    assert src.calibrar(frame_con_mesa(), Usuario(None), log=lambda _m: None) is None


def test_la_vista_se_encoge_y_el_recuadro_vuelve_a_pixeles_del_frame():
    """Se dibuja sobre una vista reducida (un frame Retina no cabe en pantalla)
    y lo que se devuelve tiene que estar en coordenadas del frame original."""
    # negro entero: no hay mesa, asi que hace falta insistir (el mismo recuadro
    # dos veces) para llegar al guardado. Lo que se mira aqui son las unidades.
    grande = np.zeros((1964, 3024, 3), np.uint8)
    usuario = Usuario((100, 50, 400, 300), (100, 50, 400, 300))
    rect = src.calibrar(grande, usuario, log=lambda _m: None)
    assert usuario.vista.shape[1] <= 1500
    assert rect[0] > 100 and rect[2] > 400          # deshecha la reduccion
    assert rect[0] == int(100 / (1500 / 3024))
