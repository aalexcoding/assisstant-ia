"""
Verificacion de la vigilancia rapida de nameplates (vision/seat_watch.py).

Lo que de verdad protege:

  1. Que un cambio REAL se vea (si no, se pierde la accion del rival, que es
     justo lo que la pieza existe para captar) y que el ruido de la animacion del
     tapete NO cuente como cambio (si no, se dispara un OCR en cada frame y la
     idea deja de ser barata).
  2. Que el buffer GUARDE COPIAS y este ACOTADO: el buffer del stream se
     reescribe en la lectura siguiente, y una sesion de 40 minutos a 10 Hz son
     24.000 frames.

Sin depender de capturas: las imagenes se generan aqui.
"""
import numpy as np
import pytest

from vision import seat_map
from vision import seat_watch as sw

pytestmark = pytest.mark.vision

ALTO, ANCHO = 800, 1200
REF = (100, 100, 1000, 500, False)          # (x, y, w, h, fallback) del nucleo


def frame(valor=60):
    return np.full((ALTO, ANCHO, 3), valor, dtype=np.uint8)


def _caja(img, seat):
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, seat_map.SEATS[seat]["plate"], img.shape)
    return max(0, x0), max(0, y0), min(ANCHO, x1), min(ALTO, y1)


def pintar_asiento(img, seat, valor):
    """Escribe en el INTERIOR de la capsula de un asiento (lo que se hashea)."""
    x0, y0, x1, y1 = _caja(img, seat)
    dy, dx = int((y1 - y0) * 0.2), int((x1 - x0) * 0.2)
    img[y0 + dy:y1 - dy, x0 + dx:x1 - dx] = valor
    return img


def pintar_borde(img, seat, valor):
    """Escribe SOLO en el borde de la capsula (lo que se descarta al hashear)."""
    x0, y0, x1, y1 = _caja(img, seat)
    dy = max(1, int((y1 - y0) * 0.03))
    img[y0:y0 + dy, x0:x1] = valor
    return img


@pytest.fixture
def base():
    return pintar_asiento(frame(), "UL", 200)


@pytest.fixture
def watch():
    return sw.SeatWatch()


# --- que cuenta como cambio --------------------------------------------------

def test_la_primera_vez_no_hay_cambios(watch, base):
    """No hay con que comparar, y darlo por cambiado haria OCR-ear los seis
    asientos sin razon."""
    assert watch.cambios(base, REF) == []


def test_el_mismo_frame_otra_vez_tampoco_cambia(watch, base):
    watch.cambios(base, REF)
    assert watch.cambios(base, REF) == []


def test_cambiar_el_interior_de_una_capsula_se_detecta(watch, base):
    watch.cambios(base, REF)
    assert watch.cambios(pintar_asiento(base.copy(), "UL", 120), REF) == ["UL"]


def test_una_vez_visto_deja_de_contar_como_cambio(watch, base):
    watch.cambios(base, REF)
    otro = pintar_asiento(base.copy(), "UL", 120)
    watch.cambios(otro, REF)
    assert watch.cambios(otro, REF) == []


def test_el_ruido_solo_en_el_borde_no_cuenta(watch, base):
    """Ahi es donde se animan el tapete, el avatar y la marca de bounty: contarlo
    dispararia un OCR en cada frame y la vigilancia dejaria de ser barata."""
    watch.cambios(base, REF)
    assert watch.cambios(pintar_borde(base.copy(), "MR", 5), REF) == []


def test_dos_asientos_a_la_vez_dan_los_dos(watch, base):
    watch.cambios(base, REF)
    dos = pintar_asiento(pintar_asiento(base.copy(), "UL", 30), "MR", 30)
    assert sorted(watch.cambios(dos, REF)) == ["MR", "UL"]


def test_olvidar_vuelve_al_estado_inicial(watch, base):
    watch.cambios(base, REF)
    watch.olvidar()
    assert watch.cambios(base, REF) == []


def test_re_censar_devuelve_LOS_SEIS_aunque_no_haya_cambiado_nada(watch, base):
    """Al abrir mano hay que releer los seis nombres aunque la imagen sea
    identica: entre manos puede haber cambiado quien esta sentado -en Zoom el
    cliente te cambia de mesa- y la capsula del que se fue se parece mucho a la
    del que llega."""
    watch.cambios(base, REF)
    watch.re_censar()
    assert sorted(watch.cambios(base, REF)) == sorted(seat_map.SEATS)


def test_re_censar_se_gasta_en_una_sola_mirada(watch, base):
    """Si no se gastara, la vigilancia OCR-earia los seis asientos en cada tick
    hasta el final de la mano, que es lo que este mecanismo existe para evitar."""
    watch.cambios(base, REF)
    watch.re_censar()
    watch.cambios(base, REF)
    assert watch.cambios(base, REF) == []


def test_olvidar_NO_sirve_para_re_censar(watch, base):
    """La trampa que hay que dejar clavada: olvidar() borra las huellas, y como
    la PRIMERA vez que se ve un asiento no cuenta como cambio, la mirada
    siguiente devuelve CERO. Usarlo al abrir mano dejaria la mesa sin releer
    justo cuando mas falta hace: es lo CONTRARIO de re-censar."""
    watch.cambios(base, REF)
    watch.olvidar()
    assert watch.cambios(base, REF) == []
    watch.cambios(base, REF)
    watch.re_censar()
    assert sorted(watch.cambios(base, REF)) == sorted(seat_map.SEATS)


# --- huellas -----------------------------------------------------------------

def test_hay_una_huella_por_asiento_del_mapa(base):
    assert set(sw.huellas(base, REF)) == set(seat_map.SEATS)


def test_las_huellas_son_bytes(base):
    assert all(isinstance(v, bytes) for v in sw.huellas(base, REF).values())


def test_el_mismo_frame_da_las_mismas_huellas(base):
    assert sw.huellas(base, REF) == sw.huellas(base, REF)


# --- el buffer ---------------------------------------------------------------

def test_el_buffer_guarda_una_copia():
    """El buffer del stream se reescribe en la lectura siguiente, asi que sin
    copiar lo guardado dejaria de ser lo que se vio."""
    b = sw.FrameBuffer(maxlen=3)
    f1 = frame(10)
    b.añadir(f1, t=1.0)
    assert b.ultimo()["frame"] is not f1
    f1[:] = 99
    assert int(b.ultimo()["frame"][0, 0, 0]) == 10


def test_el_buffer_esta_acotado_y_descarta_lo_mas_viejo():
    """Una sesion de 40 minutos a 10 Hz son 24.000 frames."""
    b = sw.FrameBuffer(maxlen=3)
    for i, t in enumerate((1.0, 2.0, 3.0, 4.0), start=1):
        b.añadir(frame(10 * i), t=t)
    assert len(b) == 3
    assert [x["t"] for x in b.todos()] == [2.0, 3.0, 4.0]
    assert b.ultimo()["t"] == 4.0


def test_vaciar_deja_el_buffer_a_cero():
    b = sw.FrameBuffer(maxlen=3)
    b.añadir(frame(10), t=1.0)
    b.vaciar()
    assert len(b) == 0
    assert b.ultimo() is None
