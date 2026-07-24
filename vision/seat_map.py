"""
Reconocimiento por ZONAS FIJAS (mapa de asientos) para el cliente real de
PokerStars, capturado limpio (sin cromo de navegador). Sustituye al enfoque
dinamico por blobs de analyze_color_deck() -que detecta boton y ciegas
buscando globalmente y falla al generalizar entre torneos- por un mapa de
asientos: los elementos de la mesa estan siempre en las mismas zonas de la
ventana y solo cambian de tamaño con ella, asi que todo se expresa como
FRACCIONES de una referencia que se escala sola con la ventana.

Ancla de referencia (independiente del color del tapete): el tapete puede ser
verde, morado, azul... y el rail rojo o azul, asi que NO se detecta por tono.
Se detecta el ovalo central por CONTRASTE contra el fondo casi-negro: el
tapete (sea del color que sea) es una gran elipse saturada y brillante,
mientras el borde/sillas de alrededor es oscuro y texturado. Se umbraliza
"saturado Y brillante", se aplica una APERTURA morfologica grande (mata las
protuberancias -nameplates, rail, fichas, cartas, cromo lateral- y los
puentes finos hacia el cromo) y se coge el mayor blob central: queda el
nucleo eliptico del tapete, muy estable (verificado contra las 30 capturas de
samples_layout/: desviacion tipica ~0 en x/w). Fallback si no se detecta: la
posicion fraccionaria tipica del tapete dentro del recuadro capturado (equivale
a anclar al crop calibrado, la premisa del propio usuario).

Todas las zonas (asientos, board, bote, cartas del hero, chat, botones de
accion, anclas de boton) son fracciones (x0,y0,x1,y1) de ese bounding box del
nucleo; pueden salirse de [0,1] porque los asientos rodean el ovalo por fuera.
Derivadas empiricamente midiendo sobre samples_layout/ (una sesion real en
vivo, misma calibracion, 6 asientos ocupados en layout simetrico de 6 plazas:
hero abajo-centro, mas superior-centro, 2 superiores laterales y 2 laterales
medios).
"""
import math

import cv2
import numpy as np

# posicion fraccionaria tipica del nucleo del tapete dentro del recuadro
# capturado (medida sobre samples_layout/), usada solo como fallback si la
# deteccion por contraste falla.
FELT_CORE_IN_FRAME = (0.186, 0.164, 0.675, 0.458)

# --- deteccion del ovalo por contraste (independiente del color) ---
CORE_MIN_S = 45
CORE_MIN_V = 60
CORE_OPEN_KERNEL = 41

# --- mapa de asientos (fracciones del nucleo del tapete) ---
# Cada asiento: zona OCR del nameplate (nombre+stack) y ancla de boton (punto
# donde aparece el disco del dealer cuando ese asiento reparte). El hero es
# siempre el de abajo-centro. Layout de 6 plazas medido sobre samples_layout/.
SEATS = {
    "TOPC": {"plate": (0.30, -0.16, 0.62, 0.03), "button": (0.567, 0.144)},
    "UL":   {"plate": (-0.14, -0.03, 0.20, 0.22), "button": (0.096, 0.283)},
    "UR":   {"plate": (0.80, -0.03, 1.16, 0.22), "button": (0.904, 0.283)},
    "ML":   {"plate": (-0.14, 0.57, 0.18, 0.85), "button": (0.162, 0.752)},
    "MR":   {"plate": (0.82, 0.58, 1.17, 0.86), "button": (0.838, 0.752)},
    "HERO": {"plate": (0.37, 0.98, 0.75, 1.19), "button": (0.66, 0.90)},
}
HERO_SEAT = "HERO"

# zonas fijas de los elementos de mesa (fracciones del nucleo del tapete)
HERO_CARDS_ZONE = (0.40, 0.83, 0.62, 1.04)
BOARD_ZONE = (0.26, 0.28, 0.78, 0.54)
# el texto "Bote: N" se muestra mas abajo en preflop (sin cartas de board que
# lo empujen hacia arriba) que en postflop; la zona cubre ambas alturas.
POT_ZONE = (0.34, 0.11, 0.66, 0.38)
# cubre las 4 lineas de mensajes visibles del chat: el aviso "Los limites
# suben: Ciegas .../..." va subiendo por el log segun llegan mensajes nuevos,
# asi que hay que abarcar todas las filas para pillarlo este donde este.
CHAT_ZONE = (-0.155, 1.29, 0.47, 1.62)
ACTION_ZONE = (0.73, 1.40, 1.18, 1.62)

# ancla de boton: media-zona (fraccion del nucleo) alrededor del punto ancla
BUTTON_HALF_W = 0.075
BUTTON_HALF_H = 0.14

# posiciones por numero de asientos ocupados, empezando en BTN y siguiendo el
# orden de reparto (horario). Misma convencion que dealer_button.SEATING_BY_N /
# decision/preflop/zerospoker_layout.CANON9.
SEATING_BY_N = {
    2: ["BTN", "BB"],
    3: ["BTN", "SB", "BB"],
    4: ["BTN", "SB", "BB", "CO"],
    5: ["BTN", "SB", "BB", "HJ", "CO"],
    6: ["BTN", "SB", "BB", "EP1", "HJ", "CO"],
    7: ["BTN", "SB", "BB", "EP1", "MP1", "HJ", "CO"],
    8: ["BTN", "SB", "BB", "EP1", "EP2", "MP1", "HJ", "CO"],
    9: ["BTN", "SB", "BB", "EP1", "EP2", "MP1", "MP2", "HJ", "CO"],
}


def find_reference(bgr):
    """Devuelve (x0, y0, w, h, is_fallback) del nucleo del tapete. Deteccion
    por contraste, independiente del color; si falla, usa la posicion tipica
    del tapete dentro del recuadro (fallback)."""
    h_img, w_img = bgr.shape[:2]
    hsv = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    fg = ((v >= CORE_MIN_V) & (s >= CORE_MIN_S)).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CORE_OPEN_KERNEL, CORE_OPEN_KERNEL))
    core = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k, iterations=1)
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(core, connectivity=8)
    best, best_area = None, -1
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw < 0.3 * w_img or bh < 0.2 * h_img:
            continue
        if area > best_area:
            best_area = area
            best = (int(x), int(y), int(bw), int(bh))
    if best is not None:
        return best[0], best[1], best[2], best[3], False
    fx, fy, fw, fh = FELT_CORE_IN_FRAME
    return int(fx * w_img), int(fy * h_img), int(fw * w_img), int(fh * h_img), True


def zone_to_px(ref, zone, shape):
    """Convierte una zona en fracciones del nucleo a pixeles absolutos
    (x0, y0, x1, y1), recortada al frame."""
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    fx0, fy0, fx1, fy1 = zone
    x0 = max(0, int(rx + fx0 * rw))
    y0 = max(0, int(ry + fy0 * rh))
    x1 = min(shape[1], int(rx + fx1 * rw))
    y1 = min(shape[0], int(ry + fy1 * rh))
    return x0, y0, x1, y1


def seat_center_px(ref, seat_name):
    """Centro (px) de la zona de nameplate de un asiento."""
    fx0, fy0, fx1, fy1 = SEATS[seat_name]["plate"]
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    cx = rx + (fx0 + fx1) / 2 * rw
    cy = ry + (fy0 + fy1) / 2 * rh
    return cx, cy


def dealing_order(seat_names, ref):
    """Ordena asientos en orden de reparto (horario) por angulo alrededor del
    centro de los asientos, igual criterio que dealer_button.assign_positions
    (atan2 ascendente en coordenadas de imagen coincide con el orden real)."""
    centers = {s: seat_center_px(ref, s) for s in seat_names}
    cx = sum(c[0] for c in centers.values()) / len(centers)
    cy = sum(c[1] for c in centers.values()) / len(centers)
    return sorted(seat_names, key=lambda s: math.atan2(centers[s][1] - cy, centers[s][0] - cx))


def detect_button_seat(bgr, ref):
    """Devuelve el nombre del asiento que tiene el boton del dealer, o None.
    Enfoque por ancla-por-asiento: dentro de la zona-ancla de cada asiento
    busca el disco del boton (blanco+pica roja) como un blob compacto
    (blanco union rojo) circular, aislado sobre el tapete (no toca los bordes
    de la zona -eso descarta dorsos de carta, avatares tipo bandera y fichas,
    que estan pegados a estructuras mayores- y contiene rojo en el centro)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(np.int32), hsv[:, :, 1].astype(np.int32), hsv[:, :, 2].astype(np.int32)
    white = (s < 80) & (v > 175)
    red = ((h < 10) | (h > 168)) & (s > 90) & (v > 110)
    obj = ((white | red).astype(np.uint8)) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, k, iterations=1)

    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    best, best_area = None, -1
    for name, cfg in SEATS.items():
        fx, fy = cfg["button"]
        cx, cy = rx + fx * rw, ry + fy * rh
        x0 = max(0, int(cx - BUTTON_HALF_W * rw))
        y0 = max(0, int(cy - BUTTON_HALF_H * rh))
        x1 = min(bgr.shape[1], int(cx + BUTTON_HALF_W * rw))
        y1 = min(bgr.shape[0], int(cy + BUTTON_HALF_H * rh))
        sub = obj[y0:y1, x0:x1]
        rsub = red[y0:y1, x0:x1]
        if sub.size == 0:
            continue
        hh, ww = sub.shape
        contours, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < 250 or area > 1500:
                continue
            x, y, w, h_ = cv2.boundingRect(c)
            ar = w / h_ if h_ else 0
            if not (0.6 <= ar <= 1.7):
                continue
            if area / (w * h_) < 0.62:
                continue
            if x <= 1 or y <= 1 or x + w >= ww - 1 or y + h_ >= hh - 1:
                continue
            if rsub[y:y + h_, x:x + w].mean() < 0.10:
                continue
            if area > best_area:
                best_area = area
                best = name
            break
    return best


# --- facing: que enfrenta el hero, segun los botones de accion ---
# Si el hero puede IGUALAR/PAGAR una cantidad, enfrenta una apuesta ("bet").
# Si sus opciones son PASAR (check) o APOSTAR (bet inicial), no enfrenta nada
# que pagar ("check"). Si no hay botones (no es su turno), None.
FACING_BET_WORDS = ("igualar", "pagar")
FACING_CHECK_WORDS = ("pasar", "apostar")


def parse_facing(action_text):
    low = action_text.lower()
    if any(w in low for w in FACING_BET_WORDS):
        return "bet"
    if any(w in low for w in FACING_CHECK_WORDS):
        return "check"
    return None


# --- ocupacion (nameplate presente) ---
# La ocupacion se decide por la presencia de la CAPSULA del nameplate (la
# placa oscura de nombre+stack), NO por que el OCR lea el texto: cuando un
# jugador acaba de actuar, el cliente sustituye su nombre por el verbo de la
# accion ("Iguala"/"Apuesta"/"No ir") y a veces tambien tapa el stack, asi que
# depender del OCR hace que el asiento "desaparezca" en frames sueltos y
# descuadre las posiciones de toda la mesa. La capsula, en cambio, esta
# siempre mientras el jugador este sentado. Se mide como fraccion de pixeles
# oscuros/poco saturados en la zona del nameplate: en samples_layout/ los 6
# asientos ocupados dan 0.43-0.83 de forma estable en las 30 capturas.
# NOTA: el dataset no tiene asientos vacios, asi que el umbral que separa
# ocupado de vacio no esta validado; se elige por debajo del rango ocupado
# (0.35) asumiendo que un asiento vacio -mayormente tapete brillante- daria una
# fraccion oscura menor. Habria que confirmarlo con capturas de mesas con
# huecos.
OCCUPANCY_DARK_FRAC = 0.35


def seat_occupied(bgr, ref, seat_name):
    x0, y0, x1, y1 = zone_to_px(ref, SEATS[seat_name]["plate"], bgr.shape)
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return False
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    dark = (v < 105) & (s < 95)
    return bool(dark.mean() > OCCUPANCY_DARK_FRAC)


# Nota: se exploro exponer un campo opcional in_hand por asiento a partir del
# dorso rojo de las cartas repartidas (el reverso de PokerStars es rojo
# oscuro), pero un muestreo radial simple no localiza los dorsos de forma
# fiable (caen a offsets distintos segun el asiento, y el hero va boca arriba),
# asi que no se incluye para no exponer una señal casi siempre falsa. Haria
# falta una zona de dorso propia por asiento y mas medicion.
