"""
Verificacion del segundo camino de lectura de cartas (vision/rango_directo.py):
deslizar las plantillas de rango sobre la zona, sin buscar la carta.

Lo que de verdad protege:

  1. Que el PALO salga de la derecha del numero. Es el cambio entero. Antes se
     partia la franja de cartas por la mitad y se cogia el color dominante de
     cada lado; como las dos cartas del hero se solapan, el color de la de la
     izquierda ganaba en los dos lados y salian 50 contradicciones de 89
     lecturas, todas del tipo 'Kh 5s' leido 'Kh 5h'.
  2. Que una carta TAPADA POR ABAJO se siga leyendo. Es la razon de existir del
     modulo: las cartas del hero salen cortadas por su propio nameplate, la
     cadena normal no puede segmentarlas y las pierde enteras.
  3. Que el umbral no deje colar rangos que no estan. Con MIN_PICO por debajo de
     0.66 aparecian TRES cartas en la mano del hero, que es imposible.
  4. Que EscalaGlifo fije el tamaño y deje de buscarlo. Barrer 21 escalas en
     cada frame cuesta 21 veces lo que cuesta leer.

Las imagenes se generan aqui, con las plantillas reales del atlas y los colores
de cuerpo de carta de color_card_detector, asi que el test no depende de tener
las capturas.
"""
import cv2
import numpy as np
import pytest

from vision import rango_directo as rd

pytestmark = pytest.mark.vision


def _bgr(h, s, v):
    return tuple(int(x) for x in cv2.cvtColor(
        np.array([[[h, s, v]]], np.uint8), cv2.COLOR_HSV2BGR)[0, 0])


# un color de cuerpo dentro del perfil de cada palo (ver SUIT_HSV_PROFILES)
CUERPO = {
    "heart": _bgr(5, 180, 230),
    "club": _bgr(80, 220, 170),
    "diamond": _bgr(110, 100, 190),
    "spade": _bgr(20, 20, 140),
}
ALTO = 36
ANCHO_CARTA, ALTO_CARTA = 96, 132
RANGOS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


def _plantilla(rango, alto=ALTO):
    for r, t in rd._atlas():
        if r == rango:
            e = alto / t.shape[0]
            return cv2.resize(t, (max(4, int(t.shape[1] * e)), alto),
                              interpolation=cv2.INTER_AREA)
    raise AssertionError("rango sin plantilla en el atlas: " + rango)


def _carta(rango, palo, alto=ALTO):
    """Una carta como las del cliente: cuerpo del color del palo, numero blanco
    arriba a la izquierda."""
    img = np.zeros((ALTO_CARTA, ANCHO_CARTA, 3), np.uint8)
    img[:, :] = CUERPO[palo]
    t = _plantilla(rango, alto)
    trozo = img[8:8 + t.shape[0], 8:8 + t.shape[1]]
    trozo[t > 127] = (255, 255, 255)
    return img


def zona(cartas, fondo=(30, 90, 40), solape=0):
    """Franja con las cartas una al lado de otra, opcionalmente solapadas como
    salen en la mano del hero."""
    paso = ANCHO_CARTA - solape
    z = np.zeros((ALTO_CARTA + 40, paso * (len(cartas) - 1) + ANCHO_CARTA + 40, 3), np.uint8)
    z[:, :] = fondo
    for i, (rango, palo) in enumerate(cartas):
        x = 20 + i * paso
        z[20:20 + ALTO_CARTA, x:x + ANCHO_CARTA] = _carta(rango, palo)
    return z


def leidas(z, alto=ALTO):
    out = []
    for _x, r, p, _pico in rd.leer_zona(z, alto):
        if (r, p) not in out:
            out.append((r, p))
    return out


# --- 1. dos cartas sueltas, rango y palo ------------------------------------

def test_dos_cartas_sueltas_se_leen_con_su_rango_y_su_palo():
    l = leidas(zona([("K", "heart"), ("5", "spade")]))
    assert len(l) == 2
    assert [r for r, _p in l] == ["K", "5"], "en orden de izquierda a derecha"
    assert [p for _r, p in l] == ["heart", "spade"]


# --- 2. cartas SOLAPADAS: el palo no se contagia del vecino -----------------
# El fallo real: 'Kh 5s' se leia 'Kh 5h' porque el rojo de la carta de la
# izquierda dominaba las dos mitades de la franja.

def test_solapadas_siguen_siendo_dos_cartas_y_cada_una_con_su_palo():
    d = dict(leidas(zona([("K", "heart"), ("5", "spade")], solape=28)))
    assert len(d) == 2
    assert d.get("5") == "spade", "la segunda NO hereda el palo de la primera"
    assert d.get("K") == "heart", "la primera conserva el suyo"


@pytest.mark.parametrize("izq, der", [
    ("heart", "spade"), ("spade", "heart"), ("club", "diamond"), ("diamond", "club"),
])
def test_solapadas_en_las_cuatro_combinaciones(izq, der):
    d = dict(leidas(zona([("Q", izq), ("9", der)], solape=28)))
    assert d.get("Q") == izq
    assert d.get("9") == der


def test_el_color_se_mira_a_la_derecha_del_numero_no_alrededor():
    """Se mancha el hueco a la IZQUIERDA del numero con el color de otro palo. Si
    la lectura mirase alrededor, cambiaria; mirando a la derecha, no."""
    z = zona([("8", "club")])
    z[20:20 + ALTO_CARTA, 4:20] = CUERPO["heart"]
    assert dict(leidas(z)).get("8") == "club"


# --- 3. carta TAPADA POR ABAJO (el nameplate del hero) ----------------------

def test_una_carta_tapada_por_abajo_se_sigue_leyendo():
    """Es la razon de existir del modulo: la cadena normal no puede segmentarlas
    y las pierde enteras."""
    z = zona([("A", "diamond"), ("7", "club")])
    z[20 + ALTO_CARTA // 2:, :] = (45, 45, 45)      # el plate gris oscuro encima
    l = leidas(z)
    assert len(l) == 2
    assert [r for r, _p in l] == ["A", "7"]
    assert [p for _r, p in l] == ["diamond", "club"]


# --- 4. no se inventa lo que no hay -----------------------------------------

def test_un_tapete_vacio_no_da_ninguna_carta():
    z = np.zeros((172, 300, 3), np.uint8)
    z[:, :] = (30, 90, 40)
    assert leidas(z) == []


def test_dos_cartas_nunca_dan_mas_de_dos():
    """El hero solo tiene dos."""
    assert len(leidas(zona([("K", "heart"), ("5", "spade")]))) <= 2


# --- 5. los trece rangos ----------------------------------------------------

@pytest.mark.parametrize("rango", RANGOS)
def test_cada_rango_se_lee_solo_y_bien(rango):
    assert list(dict(leidas(zona([(rango, "club")])))) == [rango]


# --- 6. el umbral esta por encima del acantilado ----------------------------

def test_min_pico_por_encima_de_donde_se_rompe_el_invariante():
    """Medido sobre 300 frames: por debajo de 0.66 aparecen frames con TRES
    cartas en la mano del hero (36 a 0.64, 147 a 0.50)."""
    assert rd.MIN_PICO >= 0.66


def test_min_pico_no_tan_alto_que_deje_de_leer():
    assert rd.MIN_PICO <= 0.72


# --- 7. EscalaGlifo se fija y deja de buscar --------------------------------

@pytest.fixture
def z_dos_cartas():
    return zona([("K", "heart"), ("5", "spade")])


def test_la_escala_no_se_fija_con_una_sola_muestra(z_dos_cartas):
    esc = rd.EscalaGlifo()
    assert esc.de(z_dos_cartas) is None
    assert esc.fijada is None


def test_la_escala_se_fija_tras_las_muestras_necesarias(z_dos_cartas):
    esc = rd.EscalaGlifo()
    for _ in range(rd.EscalaGlifo.MUESTRAS_PARA_FIJAR):
        esc.de(z_dos_cartas)
    assert esc.fijada is not None
    assert abs(esc.fijada - ALTO) <= 4, "la escala encontrada es la que se dibujo"


def test_una_vez_fijada_no_vuelve_a_buscar(z_dos_cartas, monkeypatch):
    """Barrer 21 escalas en cada frame cuesta 21 veces lo que cuesta leer."""
    esc = rd.EscalaGlifo()
    for _ in range(rd.EscalaGlifo.MUESTRAS_PARA_FIJAR):
        esc.de(z_dos_cartas)
    llamadas = []
    original = rd.buscar_escala
    monkeypatch.setattr(rd, "buscar_escala",
                        lambda *a, **k: (llamadas.append(1), original(*a, **k))[1])
    esc.de(z_dos_cartas)
    assert not llamadas


def test_buscar_escala_devuelve_none_en_una_zona_sin_cartas():
    assert rd.buscar_escala(np.full((172, 300, 3), 40, np.uint8)) is None


# --- 8. una carta APAGADA no se lee -----------------------------------------
# Es lo unico peligroso de este segundo camino. Apagada significa que el hero ya
# se retiro de la mano; recomendar sobre ella seria aconsejar una mano
# abandonada. Y como este camino no encuentra cajas de carta, table_state no
# puede calcular su 'dimmed' -en 10 de 300 frames medidos entraria sin cajas y
# 'dimmed' saldria False por omision-.
#
# La garantia no es un umbral aparte sino la propia mascara: exige tinta con
# V > WHITE_MIN_VALUE (170) y una cara apagada cae a V=77 (medido en
# glyph_card_detector). Se comprueba aqui para que nadie afloje ese valor sin
# darse cuenta de que lo que sujeta es esto.

def test_una_carta_viva_se_lee(z_dos_cartas):
    assert len(leidas(z_dos_cartas)) == 2


@pytest.fixture
def apagada(z_dos_cartas):
    return (z_dos_cartas.astype(np.float32) * (77.0 / 255.0)).astype(np.uint8)


def test_una_carta_apagada_no_se_lee(apagada):
    assert leidas(apagada) == []


def test_en_una_zona_apagada_tampoco_se_encuentra_escala(apagada):
    assert rd.buscar_escala(apagada) is None


# --- 9. el atlas ------------------------------------------------------------

def test_el_atlas_trae_los_trece_rangos():
    assert len(rd._atlas()) == 13


def test_el_atlas_se_carga_una_sola_vez():
    assert rd._atlas() is rd._atlas()


def test_las_plantillas_vienen_recortadas_a_su_tinta():
    assert all(t.shape[0] > 0 and t.shape[1] > 0 and (t > 127).any()
               for _r, t in rd._atlas())
