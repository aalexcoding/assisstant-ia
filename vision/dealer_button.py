"""
Localizacion del boton del dealer (disco rojo con una pica blanca, pegado al
asiento que reparte esa mano) y, a partir de el, asignacion de la posicion
relativa (BTN/SB/BB/CO/HJ/MP.../EP...) de cada jugador detectado por
find_players() en color_card_detector.py/text_extract.py.

El color del boton se calibro contra 57 capturas reales de
vision/samples_pokerstars/ (ver /tmp del analisis, no versionado): el mismo
rojo saturado aparece tambien en el icono "?" de notas de cada jugador, en
el "!" de aviso de time bank, en el logo de PokerStars (marca de agua fija
en una esquina) y en el borde de la mesa que ya localiza table_region.py, asi
que el color solo no basta. La señal que sí separa limpiamente el boton del
resto en las 57 muestras es el brillo (V de HSV): el boton se renderiza mas
claro/brillante (V~243, consistente en todas las muestras donde aparece) que
esos otros elementos (V~200-220), ademas de un matiz mas puro (mas cerca de
rojo exacto, H~0/179) que el rojo ligeramente mas magenta de los iconos "?"/
"!" (H~175) y una solidez de contorno (area/bounding-box) tipica de un disco
con un hueco de pica blanca en el centro (~0.5), distinta de placas de rail
(mucho mas alargadas y huecas) o de las burbujas "?"/"!" completas.

Con ese filtro se encuentra el boton en 54 de las 57 muestras (en las 3
restantes la mesa esta cerrada o el frame es de un all-in donde no aparece);
en ninguna aparecen dos candidatos a la vez, asi que no hizo falta discriminar
entre "boton real" y un duplicado.

Para asignar posiciones se usa el mismo criterio que ya emplea
color_card_detector.classify_boxes() para decidir el hero (fraccion de
posicion dentro de la mesa): aqui se ordenan los asientos angularmente
alrededor del centroide de los propios asientos detectados (mas estable que
el bounding-box de table_region.py, que trae padding asimetrico) y se
verifico contra el propio dataset que ese orden angular ascendente
(atan2 en coordenadas de imagen, sin invertir eje Y) coincide exactamente
con el orden real de reparto: siguiendo el boton fotograma a fotograma en
las 57 muestras (que son una secuencia temporal), el boton fue pasando de
asiento en asiento en ese mismo orden angular a lo largo de varias manos
completas (una vuelta entera a la mesa).

find_players() solo devuelve un jugador cuando puede emparejar una linea de
nombre CON una linea de numero (el stack); cuando el nameplate esta
mostrando un estado en vez del stack ("All-in") o en vez del nombre ("No
ir", sit-out...) ese emparejamiento falla y el asiento desaparece de la
lista aunque siga ocupado. Si eso pasa justo en el asiento que hay entre
dos jugadores si detectados, el orden angular de los detectados se
"comprime" (parece que estan un asiento mas cerca el uno del otro de lo que
estan en realidad) y las posiciones salen mal para TODOS los jugadores mas
alla del hueco, no solo para el que falta. find_occupied_seat_markers()
busca una señal de "aqui hay un asiento ocupado" independiente del nombre y
el stack: la burbuja roja "?" de notas que el cliente pinta junto a cada
nameplate, tanto si el nombre/stack se pudo leer como si no (verificado
contra las 57 muestras: sigue apareciendo con jugadores en "All-in" o "No
ir"). assign_positions() usa esos marcadores para rellenar los asientos
ocupados que find_players() no pudo leer (sin inventar quien es, solo que
"ahi hay alguien") antes de calcular el orden angular, y descarta esos
huecos del resultado final.
"""
import math

import cv2
import numpy as np

RED_HUE_DIST_MAX = 3
RED_MIN_V = 225
BUTTON_MIN_AREA = 150
BUTTON_MAX_AREA = 450
BUTTON_AR_MIN, BUTTON_AR_MAX = 0.8, 1.4
BUTTON_SOLIDITY_MIN, BUTTON_SOLIDITY_MAX = 0.40, 0.68

# si el asiento detectado (o hueco, ver mas abajo) mas cercano al boton esta
# mas lejos que esto (fraccion de la diagonal de imagen), no nos fiamos del
# emparejamiento: es sintoma de que el jugador que realmente tiene el boton
# no se detecto ese frame y el mas cercano encontrado es en realidad otro
# asiento lejano.
MAX_BUTTON_SEAT_DIST_FRAC = 0.20

# la burbuja "?"/"!" de notas de cada asiento comparte casi el mismo rojo
# que el boton, pero con un matiz ligeramente mas magenta (mas lejos del
# rojo puro): H a distancia ~4.94-4.97 del rojo exacto en las 57 muestras,
# de forma consistente y sin solapar con el boton (H a ~0-1.5) ni con el
# unico falso positivo real encontrado -un icono fijo de aviso de "juego
# responsable" en la esquina, no ligado a ningun asiento- que quedo
# consistentemente en H a ~4.87, con hueco claro (>0.07) respecto a las
# burbujas reales. BADGE_HUE_DIST_LO se calibro justo por encima de ese
# valor para excluirlo sin perder ninguna burbuja real de las 57 muestras.
BADGE_HUE_DIST_LO = 4.90
BADGE_HUE_DIST_HI = 5.30
BADGE_MIN_AREA = 100
BADGE_MAX_AREA = 350
BADGE_AR_MIN, BADGE_AR_MAX = 0.7, 1.6
BADGE_SOLIDITY_MIN, BADGE_SOLIDITY_MAX = 0.55, 0.95

# si una burbuja de notas esta mas cerca que esto (fraccion de la diagonal)
# de un jugador ya emparejado por nombre+stack, se asume que es SU propia
# burbuja (no un asiento nuevo): en las 57 muestras la distancia entre un
# jugador y su propia burbuja nunca paso de ~135px (diagonal ~1475px,
# ~0.09), con el siguiente asiento mas cercano siempre a 250px o mas
# (~0.17); 0.15 deja margen de sobra a ambos lados.
GHOST_SEAT_MATCH_FRAC = 0.15

# posiciones por asiento (empezando en el BTN y siguiendo el orden real de
# reparto) segun el numero de jugadores activos. Se construye igual que la
# convencion ya usada en decision/preflop/zerospoker_layout.py (CANON9 =
# BB,SB,BTN,CO,HJ,MP2,MP1,EP2,EP1 para 9-max), quitando asientos segun la
# mesa se hace mas corta: BTN, SB y BB son fijos; de los 6 restantes
# (EP1,EP2,MP1,MP2,HJ,CO, en ese orden alrededor de la mesa) se van quitando
# primero los mas "de en medio" (MP2, luego EP2, luego MP1), y el ultimo en
# desaparecer es CO (pegado al BTN). Coincide con el 6-max/9-max estandar
# (6-max = UTG,HJ,CO,BTN,SB,BB; 9-max = UTG,UTG+1,MP1,MP2,HJ,CO,BTN,SB,BB).
# UNA SOLA definicion, la de seat_map. Aqui habia una copia escrita a mano, y dos
# copias que pueden discrepar de como se llama cada asiento es exactamente la
# trampa que este proyecto ya ha pisado varias veces: la copia de aqui se quedo
# con el mapeo viejo (EP1 al primero en hablar en 6-max) mientras la otra se
# corregia. Ver seat_map._posiciones para la regla y el bug que arregla.
from seat_map import SEATING_BY_N          # noqa: F401  (se reexporta a proposito)


def _red_mask(bgr, region):
    """(rx0, ry0, h, s, v, mask) del rojo saturado (boton, burbujas "?"/"!",
    logo, borde de mesa...) dentro de region, en coordenadas del recorte."""
    if region is not None:
        rx0, ry0, rx1, ry1 = region
    else:
        rx0, ry0, rx1, ry1 = 0, 0, bgr.shape[1], bgr.shape[0]
    crop = bgr[ry0:ry1, rx0:rx1]
    if crop.size == 0:
        return rx0, ry0, None, None, None, None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(np.int32), hsv[:, :, 1].astype(np.int32), hsv[:, :, 2].astype(np.int32)
    mask = (((h < 10) | (h > 170)) & (s > 120) & (v > 150)).astype(np.uint8) * 255
    return rx0, ry0, h, s, v, mask


def find_dealer_button(bgr, region=None):
    """Devuelve {"x","y","w","h"} (coordenadas absolutas) del boton del
    dealer, o None si no aparece con confianza (tapado, fuera de frame, o
    ningun contorno encaja con el color/forma calibrados)."""
    rx0, ry0, h, s, v, mask = _red_mask(bgr, region)
    if mask is None:
        return None
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best, best_v = None, -1
    for c in contours:
        area = cv2.contourArea(c)
        if not (BUTTON_MIN_AREA <= area <= BUTTON_MAX_AREA):
            continue
        x, y, w, hh = cv2.boundingRect(c)
        ar = w / hh if hh else 0
        if not (BUTTON_AR_MIN <= ar <= BUTTON_AR_MAX):
            continue
        solidity = area / (w * hh)
        if not (BUTTON_SOLIDITY_MIN <= solidity <= BUTTON_SOLIDITY_MAX):
            continue
        submask = mask[y:y + hh, x:x + w] > 0
        if not submask.any():
            continue
        sub_h = h[y:y + hh, x:x + w][submask]
        sub_v = v[y:y + hh, x:x + w][submask]
        hue_dist0 = float(np.minimum(sub_h, 180 - sub_h).mean())
        mean_v = float(sub_v.mean())
        if hue_dist0 > RED_HUE_DIST_MAX or mean_v < RED_MIN_V:
            continue
        # si (no visto en las 57 muestras, pero por si acaso) hay mas de un
        # candidato que pasa el filtro, nos quedamos con el mas brillante:
        # el boton real, no una variante desvanecida de otro elemento de UI.
        if mean_v > best_v:
            best_v = mean_v
            best = {"x": rx0 + x, "y": ry0 + y, "w": w, "h": hh}
    return best


def find_occupied_seat_markers(bgr, region=None):
    """Devuelve una lista de {"x","y"} (centros, coordenadas absolutas) de
    burbujas "?"/"!" de notas encontradas en el frame: una por cada asiento
    ocupado, se haya podido leer o no el nombre/stack de ese jugador. Ver
    docstring del modulo."""
    rx0, ry0, h, s, v, mask = _red_mask(bgr, region)
    if mask is None:
        return []
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    markers = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (BADGE_MIN_AREA <= area <= BADGE_MAX_AREA):
            continue
        x, y, w, hh = cv2.boundingRect(c)
        ar = w / hh if hh else 0
        if not (BADGE_AR_MIN <= ar <= BADGE_AR_MAX):
            continue
        solidity = area / (w * hh)
        if not (BADGE_SOLIDITY_MIN <= solidity <= BADGE_SOLIDITY_MAX):
            continue
        submask = mask[y:y + hh, x:x + w] > 0
        if not submask.any():
            continue
        sub_h = h[y:y + hh, x:x + w][submask]
        hue_dist0 = float(np.minimum(sub_h, 180 - sub_h).mean())
        if not (BADGE_HUE_DIST_LO <= hue_dist0 <= BADGE_HUE_DIST_HI):
            continue
        markers.append({"x": rx0 + x + w / 2, "y": ry0 + y + hh / 2})
    return markers


def _seats_with_gaps(players, seat_markers, image_diagonal):
    """players + los marcadores de seat_markers que no esten ya cerca de
    algun jugador conocido (esos son "el mismo asiento", no uno nuevo). Los
    huecos añadidos llevan _ghost=True y sin nombre/stack: representan un
    asiento ocupado pero sin OCR fiable, solo para no comprimir el orden
    angular del resto."""
    max_d = image_diagonal * GHOST_SEAT_MATCH_FRAC
    seats = list(players)
    for m in seat_markers:
        near_known = any(((m["x"] - p["x"]) ** 2 + (m["y"] - p["y"]) ** 2) ** 0.5 <= max_d for p in players)
        if not near_known:
            seats.append({"x": m["x"], "y": m["y"], "_ghost": True})
    return seats


def assign_positions(players, dealer_box, image_diagonal, seat_markers=()):
    """Dada la lista de jugadores (dicts con x,y, de find_players()), la
    caja del boton y los marcadores de asiento ocupado de
    find_occupied_seat_markers() (huecos incluidos), determina que asiento
    es el BTN (el mas cercano al boton) y devuelve una copia de players con
    "position" anadido a cada jugador segun su orden angular alrededor del
    centro de la mesa -contando los huecos, para no comprimir el resto-.
    Devuelve None si el boton no esta lo bastante cerca de ningun asiento
    conocido (real o hueco), o si el total de asientos no permite una
    asignacion fiable (menos de 2, o mas de 9: probablemente ruido de
    deteccion, no una mesa real)."""
    if dealer_box is None or not players:
        return None

    seats = _seats_with_gaps(players, seat_markers, image_diagonal)
    if len(seats) < 2 or len(seats) > 9:
        return None

    bx = dealer_box["x"] + dealer_box["w"] / 2
    by = dealer_box["y"] + dealer_box["h"] / 2
    closest = min(seats, key=lambda p: (p["x"] - bx) ** 2 + (p["y"] - by) ** 2)
    d = ((closest["x"] - bx) ** 2 + (closest["y"] - by) ** 2) ** 0.5
    if d > image_diagonal * MAX_BUTTON_SEAT_DIST_FRAC:
        return None

    cx = sum(p["x"] for p in seats) / len(seats)
    cy = sum(p["y"] for p in seats) / len(seats)
    ordered = sorted(seats, key=lambda p: math.atan2(p["y"] - cy, p["x"] - cx))
    btn_i = next(i for i, p in enumerate(ordered) if p is closest)
    rotated = ordered[btn_i:] + ordered[:btn_i]

    names = SEATING_BY_N[len(rotated)]
    return [{**p, "position": name} for p, name in zip(rotated, names) if not p.get("_ghost")]
