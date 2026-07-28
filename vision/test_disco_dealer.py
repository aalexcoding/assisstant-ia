"""
Verificacion de la busqueda del disco del dealer BARRIENDO la mesa
(vision/disco_dealer.py), el modelo que pidio el usuario: plantilla en codigo,
mapear la mesa, y el asiento mas cercano se lleva el boton.

Lo que de verdad protege:

  1. Que se encuentre el disco ESTE DONDE ESTE, no solo en seis puntos fijos.
     Es la razon de existir del modulo: el detector por anclas veia el disco en
     728 de 895 frames y este en 855, y en la mesa naranja bajaba al 49%.
  2. Que NO dependa del color del tapete ni del aspecto del disco. Se han visto
     dos discos (blanco y dorado) y seis tapetes; lo unico constante es la pica
     con la estrella, que es la plantilla.
  3. Que si el disco cae a medio camino entre dos asientos se diga que NO se
     sabe. Asignarlo al azar corre TODAS las posiciones, que es el fallo mas
     caro de esta app.
  4. Que una carta roja o una ficha roja no pasen por disco.

Las imagenes se generan aqui a partir de la plantilla real del repo, asi que el
test no depende de tener las capturas.
"""
import cv2
import numpy as np
import pytest

from vision import disco_dealer as dd
from vision import seat_map

pytestmark = pytest.mark.vision

REF = (200, 180, 1000, 470)          # nucleo del tapete tipico
ALTO, ANCHO = 960, 1400

# seis tapetes medidos en sesiones reales (naranja, verde, verde claro, azul,
# oliva y negro), en BGR aproximado
TAPETES = [(40, 90, 200), (60, 120, 40), (90, 190, 120),
           (150, 90, 40), (80, 140, 150), (35, 35, 35)]


def mesa(fondo=(60, 120, 40)):
    img = np.zeros((ALTO, ANCHO, 3), np.uint8)
    img[:, :] = fondo
    return img


def pinta_disco(img, centro, cuerpo=(235, 235, 235), escala=1.0):
    """Dibuja un disco como el del cliente: un ovalo claro con la pica roja
    encima. La pica sale de la plantilla real del repo."""
    t = dd._plantilla()
    alto = max(6, int(round(dd.ALTO_FRAC * REF[2] * escala)))
    ancho = max(6, int(round(t.shape[1] * alto / t.shape[0])))
    t = cv2.resize(t, (ancho, alto), interpolation=cv2.INTER_AREA)
    cx, cy = centro
    cv2.ellipse(img, (cx, cy), (int(ancho * 0.85), int(alto * 0.80)), 0, 0, 360, cuerpo, -1)
    y0, x0 = cy - alto // 2, cx - ancho // 2
    trozo = img[y0:y0 + alto, x0:x0 + ancho]
    trozo[t > 127] = (40, 40, 220)          # rojo del logo, en BGR
    return img


def ancla(seat):
    fx, fy = seat_map.SEATS[seat]["button"]
    return int(REF[0] + fx * REF[2]), int(REF[1] + fy * REF[3])


def carta_roja(img):
    cv2.rectangle(img, (600, 300), (680, 420), (40, 40, 200), -1)
    return img


# --- 1. el disco se encuentra en cualquier asiento --------------------------

@pytest.mark.parametrize("seat", sorted(seat_map.SEATS))
def test_el_disco_se_detecta_en_cada_asiento(seat):
    assert dd.detectar(pinta_disco(mesa(), ancla(seat)), REF) == seat


# --- 2. da igual el color del tapete y el aspecto del disco -----------------

@pytest.mark.parametrize("tapete", TAPETES)
def test_seis_tapetes_distintos_mismo_resultado(tapete):
    assert dd.detectar(pinta_disco(mesa(tapete), ancla("UR")), REF) == "UR"


def test_el_disco_dorado_se_detecta_igual_que_el_blanco():
    """Cambia el cuerpo, no la pica: la plantilla es lo unico constante."""
    img = pinta_disco(mesa(), ancla("ML"), cuerpo=(90, 200, 235))
    assert dd.detectar(img, REF) == "ML"


# --- 3. a medio camino entre dos asientos NO se adivina ---------------------

@pytest.fixture
def entre_dos_anclas():
    a, b = ancla("UL"), ancla("TOPC")
    return pinta_disco(mesa(), ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))


def test_un_disco_entre_dos_anclas_no_se_asigna(entre_dos_anclas):
    """Asignarlo al azar corre TODAS las posiciones, que es el fallo mas caro de
    esta app. Callarse es lo correcto."""
    assert dd.detectar(entre_dos_anclas, REF) is None


def test_pero_el_disco_si_se_encuentra(entre_dos_anclas):
    """Lo que falta es a quien asignarlo, no la deteccion."""
    hallado = dd.buscar_disco(entre_dos_anclas, REF)
    assert hallado is not None
    assert hallado[2] >= dd.MIN_PICO


# --- 4. no se confunde con otras cosas rojas --------------------------------

def test_una_carta_roja_no_es_un_disco():
    assert dd.detectar(carta_roja(mesa()), REF) is None


def test_una_ficha_roja_redonda_tampoco():
    img = mesa()
    cv2.circle(img, (640, 360), 18, (40, 40, 210), -1)
    cv2.circle(img, (640, 360), 18, (255, 255, 255), 3)
    assert dd.detectar(img, REF) is None


def test_un_tapete_vacio_no_da_boton():
    assert dd.detectar(mesa(), REF) is None


def test_con_una_carta_roja_al_lado_sigue_eligiendo_el_disco():
    img = pinta_disco(carta_roja(mesa()), ancla("MR"))
    assert dd.detectar(img, REF) == "MR"


# --- 5. tolera que el disco no caiga exacto en el ancla ---------------------

@pytest.mark.parametrize("dx, dy", [(14, 0), (-14, 0), (0, 14), (0, -14), (10, 10)])
def test_desplazado_hasta_catorce_pixeles_sigue_siendo_del_mismo_asiento(dx, dy):
    """Es justo el motivo del modulo: el cliente no lo dibuja siempre en el mismo
    sitio."""
    x, y = ancla("HERO")
    assert dd.detectar(pinta_disco(mesa(), (x + dx, y + dy)), REF) == "HERO"


# --- 6. los umbrales estan donde los dejo la medicion -----------------------

def test_min_pico_dentro_de_la_meseta_medida():
    """Barridos contra el invariante "el boton avanza UN asiento por mano" sobre
    3.087 candidatos de 14 sesiones. De 0.60 a 0.75 el resultado es plano; se
    eligio 0.70, en el centro de esa meseta."""
    assert 0.60 <= dd.MIN_PICO <= 0.75


def test_ventaja_min_exige_que_el_ganador_este_claramente_mas_cerca():
    assert 0.5 < dd.VENTAJA_MIN < 1.0


# --- 7. la plantilla del repo -----------------------------------------------

def test_la_plantilla_existe_y_no_esta_vacia():
    t = dd._plantilla()
    assert t.size > 0
    assert (t > 127).any()


def test_la_plantilla_es_binaria():
    """Una mascara, no una foto."""
    assert set(np.unique(dd._plantilla())) <= {0, 255}


def test_la_plantilla_se_carga_una_sola_vez():
    assert dd._plantilla() is dd._plantilla()


def test_la_plantilla_tiene_forma_de_pica():
    """Se ensancha hasta pasada la mitad y luego se estrecha de golpe en el pie.
    No se comprueba "mas arriba que abajo" -es falso, la estrella recorta la
    parte de arriba- sino el perfil, que es lo que la distingue de un circulo."""
    t = dd._plantilla()
    anchos = (t > 127).sum(axis=1)
    fila_ancha = int(np.argmax(anchos))
    assert 0.45 <= fila_ancha / t.shape[0] <= 0.75, "la fila mas ancha, pasada la mitad"
    assert anchos[-1] < 0.5 * anchos[fila_ancha], "el pie es mucho mas estrecho"
    assert (t[2:fila_ancha] <= 127).any(), "la estrella deja hueco dentro del contorno"
