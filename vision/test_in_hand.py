"""
Verificacion de la deteccion de "quien sigue en la mano" por dorso de carta
(seat_map.card_back_fractions / detect_in_hand_seats).

No hay ground truth etiquetado de quien se retiro, asi que la validacion se
apoya en tres propiedades que TIENEN que cumplirse si la señal es real, mas un
puñado de frames comprobados a ojo:

  1. BIMODALIDAD CON MARGEN. Si la metrica separa de verdad, no debe haber
     observaciones en la banda intermedia. Cero de 705 es una afirmacion fuerte;
     una sola en la banda ya seria motivo para revisar los umbrales.
  2. MONOTONIA DENTRO DE UNA MANO. El conjunto de jugadores vivos solo puede
     ENCOGERSE segun avanza una mano. Las fronteras entre manos se detectan por
     discontinuidad del board, no por tiempo.
  3. SUBCONJUNTO. Quien tiene cartas esta sentado, asi que in_hand ⊆ ocupados.

Es lento (procesa 141 capturas, ~1 min) porque recorre imagenes, aunque no use
OCR: solo pixeles.

DEPENDE DE CAPTURAS NO VERSIONADAS (vision/samples_layout*/). Cuando faltan, los
tests hacen SKIP con motivo. Antes esto imprimia "nada que verificar" y salia con
codigo 0, o sea que en cualquier maquina que no fuera la del autor el fichero
pasaba en verde sin comprobar absolutamente nada.
"""
import glob
import json
import os

import cv2
import numpy as np
import pytest

from vision import seat_map

pytestmark = [pytest.mark.vision, pytest.mark.lento]

VISION = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(VISION, "results_samples_layout2.json")
BANDA = (0.02, 0.10)          # la banda prohibida entre las dos poblaciones


def medir(carpeta):
    """[(nombre_fichero, {asiento: fraccion}), ...] en orden de captura."""
    out = []
    for f in sorted(glob.glob(os.path.join(VISION, carpeta, "*.png"))):
        bgr = cv2.imread(f)
        if bgr is None:
            continue
        ref = seat_map.find_reference(bgr)
        out.append((os.path.basename(f), seat_map.card_back_fractions(bgr, ref)))
    return out


@pytest.fixture(scope="module")
def medidas():
    """Las fracciones de dorso de las dos carpetas de capturas. De modulo porque
    procesar 141 imagenes cuesta ~1 min y todos los tests miran lo mismo."""
    datos = {c: medir(c) for c in ("samples_layout2", "samples_layout")}
    if sum(len(v) for v in datos.values()) == 0:
        pytest.skip("no hay capturas en vision/samples_layout*/ (no versionadas)")
    return datos


@pytest.fixture(scope="module")
def snapshot():
    if not os.path.exists(SNAP):
        pytest.skip(f"falta {os.path.basename(SNAP)} (no versionado)")
    with open(SNAP) as fh:
        return {r["image"]: r for r in json.load(fh)}


# --- 1. bimodalidad con margen ----------------------------------------------

@pytest.mark.parametrize("carpeta", ["samples_layout2", "samples_layout"])
def test_nada_cae_en_la_banda_prohibida(medidas, carpeta):
    """Si la metrica separa de verdad, no debe haber NI UNA observacion entre las
    dos poblaciones. Una sola ya seria motivo para revisar los umbrales."""
    filas = medidas[carpeta]
    if not filas:
        pytest.skip(f"no hay capturas en vision/{carpeta}/")
    vals = np.array([v for _, fr in filas for v in fr.values()])
    medio = vals[(vals >= BANDA[0]) & (vals <= BANDA[1])]
    assert len(medio) == 0, \
        f"{len(medio)} de {len(vals)} observaciones en [{BANDA[0]}, {BANDA[1]}]"


@pytest.mark.parametrize("carpeta", ["samples_layout2", "samples_layout"])
def test_el_margen_entre_poblaciones_es_de_al_menos_cinco_veces(medidas, carpeta):
    filas = medidas[carpeta]
    if not filas:
        pytest.skip(f"no hay capturas en vision/{carpeta}/")
    vals = np.array([v for _, fr in filas for v in fr.values()])
    bajos, altos = vals[vals < BANDA[0]], vals[vals > BANDA[1]]
    if not len(bajos) or not len(altos):
        pytest.skip("las capturas no cubren las dos poblaciones")
    assert altos.min() > bajos.max() * 5, \
        f"sin cartas max {bajos.max():.4f}, con cartas min {altos.min():.4f}"


# --- 2. monotonia dentro de una mano ----------------------------------------

def test_el_conjunto_de_vivos_nunca_crece_dentro_de_una_mano(medidas, snapshot):
    """Las manos se separan por discontinuidad del board: si el board deja de ser
    prefijo del anterior (o se vacia y vuelve), empezo una mano nueva. El board se
    lee del snapshot ya calculado, para no tener que correr el OCR aqui."""
    violaciones = []
    previo_set, previo_board, previo_img = None, None, None
    for img, fr in medidas["samples_layout2"]:
        board = tuple(snapshot.get(img, {}).get("board") or [])
        vivos = {n for n, v in fr.items() if v >= seat_map.CARD_BACK_MIN_AREA_FRAC}
        # Frontera entre manos: el board deja de crecer como prefijo del anterior,
        # O el frame anterior no tenia a NADIE con cartas -si nadie sostiene
        # cartas la mano ya termino, asi que lo siguiente es un reparto nuevo-.
        # Sin esta segunda condicion el criterio del board no basta: entre dos
        # manos el board esta vacio en los dos frames y parecerian la misma.
        misma_mano = (previo_board is not None
                      and bool(previo_set)
                      and (board[:len(previo_board)] == previo_board
                           or previo_board[:len(board)] == board)
                      and len(board) >= len(previo_board))
        if misma_mano and previo_set is not None and not vivos <= previo_set:
            violaciones.append((previo_img, sorted(previo_set), img, sorted(vivos)))
        previo_set, previo_board, previo_img = vivos, board, img
    assert not violaciones, violaciones[:3]


# --- 3. invariante de subconjunto -------------------------------------------

def test_nunca_hay_mas_rivales_con_cartas_que_asientos_ocupados(medidas, snapshot):
    """Quien tiene cartas esta sentado."""
    malos = []
    for img, fr in medidas["samples_layout2"]:
        r = snapshot.get(img)
        if not r:
            continue
        n_vivos = sum(1 for v in fr.values() if v >= seat_map.CARD_BACK_MIN_AREA_FRAC)
        # los vivos son rivales; el hero va aparte, de ahi el +1
        if n_vivos + 1 > len(r["players"]):
            malos.append((img, n_vivos, len(r["players"])))
    assert not malos, malos[:3]


# --- 4. frames comprobados a ojo --------------------------------------------

@pytest.mark.parametrize("imagen, esperado", [
    # david sagunt (UL) y Amsterdam974 (UR) tienen dos cartas granate cada uno;
    # rubydog77 (ML) no, y Parfisal58 (MR) esta "Ausente".
    ("sample_1784909873584.png", {"UL", "UR"}),
])
def test_frames_verificados_a_ojo(medidas, imagen, esperado):
    por_nombre = dict(medidas["samples_layout2"])
    if imagen not in por_nombre:
        pytest.skip(f"{imagen} no esta en las capturas locales")
    obtenido = {n for n, v in por_nombre[imagen].items()
                if v >= seat_map.CARD_BACK_MIN_AREA_FRAC}
    assert obtenido == esperado
