"""
Clasificacion del palo de una carta ya localizada (parte 3 del enfoque
recomendado): color primero, forma despues, en vez de 52 plantillas
completas o OCR del simbolo.

Los mazos de PokerStars pueden ser a 2 colores (negro/rojo, el estandar) o a
4 colores (el que se ve en vision/samples/: picas negras, corazones rojos,
treboles verdes, diamantes azules). Se detecta el color dominante del icono
de indice (junto al rango) y se reduce a 1 o 2 palos candidatos; si quedan 2
candidatos con el mismo color (negro -> pica/trebol, rojo -> corazon/
diamante, como en un mazo estandar de 2 colores), se desempata por forma
contra las plantillas pequeñas generadas en generate_card_templates.py.
"""
import os

import cv2
import numpy as np

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "card_templates")
TEMPLATE_SIZE = 28

_COLOR_SUITS = {
    "black": ["spade", "club"],
    "red": ["heart", "diamond"],
    "green": ["club"],
    "blue": ["diamond"],
}


def _load_templates():
    templates = {}
    for suit in ("spade", "heart", "club", "diamond"):
        path = os.path.join(TEMPLATES_DIR, f"{suit}.png")
        templates[suit] = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    return templates


_TEMPLATES = _load_templates()


def _colored_mask(bgr_corner):
    hsv = cv2.cvtColor(bgr_corner, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    return ((s > 40) | (v < 120)).astype(np.uint8) * 255, hsv


def _glyph_pixels(bgr_corner):
    """Pixeles de la mascara de color que pertenecen a un componente
    conexo significativo (rango o icono de palo), no ruido suelto de
    antialiasing del fondo (tapete verde/morado) que se cuela con el
    mismo umbral de saturacion/valor. Cuando la esquina redondeada de la
    carta queda muy pegada al glifo (sin margen blanco de por medio), el
    fondo y el glifo se funden en un unico componente conexo enorme; se
    descarta por tamaño (un rango o icono de palo real es compacto, nunca
    ocupa la esquina entera)."""
    mask, hsv = _colored_mask(bgr_corner)
    ch, cw = mask.shape
    max_w = max(15, int(cw * 0.75))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep = np.zeros_like(mask, dtype=bool)
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        w = stats[i, cv2.CC_STAT_WIDTH]
        if area >= 8 and w <= max_w:
            keep |= (labels == i)
    return hsv, keep


def _dominant_color_bucket(bgr_corner):
    hsv, keep = _glyph_pixels(bgr_corner)
    ys, xs = np.nonzero(keep)
    if len(xs) < 5:
        return None
    hue = hsv[:, :, 0][ys, xs].astype(np.int32)
    sat = hsv[:, :, 1][ys, xs]

    # el negro (picas) se distingue por saturacion baja, no por brillo: la
    # compresion de video oscurece cualquier color por igual (un rojo
    # oscuro sigue siendo rojo), asi que usar "brillo bajo" como señal de
    # negro clasifica mal glifos rojos/verdes/azules oscurecidos.
    is_black = sat < 60
    is_red = ~is_black & ((hue < 15) | (hue > 165))
    is_green = ~is_black & ~is_red & (hue >= 40) & (hue <= 85)
    is_blue = ~is_black & ~is_red & ~is_green & (hue >= 95) & (hue <= 135)

    votes = {"black": int(is_black.sum()), "red": int(is_red.sum()),
             "green": int(is_green.sum()), "blue": int(is_blue.sum())}
    best = max(votes, key=votes.get)
    if votes[best] == 0:
        return None
    return best


def _find_index_pip_box(bgr_corner):
    """El icono de indice (junto al rango) aparece siempre en una franja
    relativa de la esquina, no en un rango de pixeles absolutos: las
    cartas del hero llegan mas bajas (nameplate tapando la mitad inferior)
    que las del board, asi que hay que buscar en fraccion de la esquina,
    no en pixeles fijos calibrados contra un tamaño de carta concreto."""
    mask, _ = _colored_mask(bgr_corner)
    ch, cw = mask.shape
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    best = None
    for i in range(1, n):
        x, y, w, h, area = (stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP],
                             stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT],
                             stats[i, cv2.CC_STAT_AREA])
        if area < 8:
            continue
        if not (0.30 * cw <= x <= 0.90 * cw and 0.15 * ch <= y <= 0.80 * ch):
            continue
        if not (0.10 * cw <= w <= 0.40 * cw and 0.10 * ch <= h <= 0.40 * ch):
            continue
        if best is None or area > best[4]:
            best = (x, y, w, h, area)
    if best is None:
        return None
    x, y, w, h, _ = best
    pad = 2
    y0, y1 = max(0, y - pad), y + h + pad
    x0, x1 = max(0, x - pad), x + w + pad
    return mask[y0:y1, x0:x1]


def _notch_depth(mask):
    """Mide si el icono tiene una muesca (hueco) en el centro de su borde
    superior, como el corazon (dos bultos) o el trebol (tres lobulos),
    frente a un pico liso en el centro, como el diamante o la pica. Es mas
    fiable que la correlacion de plantilla en iconos tan pequeños."""
    hh, ww = mask.shape

    def top_row(col_lo, col_hi):
        ys, _ = np.nonzero(mask[:, col_lo:col_hi])
        return int(ys.min()) if len(ys) else hh

    center = top_row(int(ww * 0.40), int(ww * 0.60))
    left = top_row(int(ww * 0.05), int(ww * 0.30))
    right = top_row(int(ww * 0.70), int(ww * 0.95))
    return center - min(left, right)


def classify_suit(card_bgr, w, h):
    """card_bgr: recorte BGR de la carta completa (o de su mitad, si viene
    de un par fusionado). Devuelve (suit, confidence) o (None, 0.0)."""
    corner = card_bgr[0:int(h * 0.55), 0:int(w * 0.75)]
    if corner.size == 0:
        return None, 0.0

    bucket = _dominant_color_bucket(corner)
    if bucket is None:
        candidates = ["spade", "heart", "club", "diamond"]
    else:
        candidates = _COLOR_SUITS[bucket]

    if len(candidates) == 1:
        return candidates[0], 0.9

    pip = _find_index_pip_box(corner)
    if pip is None or pip.size == 0:
        return candidates[0], 0.3

    if bucket == "red":
        # corazon vs diamante: el corazon tiene una muesca central arriba,
        # el diamante un pico liso. Mas fiable a esta resolucion que la
        # correlacion de plantilla (ver informe de vision).
        has_notch = _notch_depth(pip) >= -1
        return ("heart", 0.75) if has_notch else ("diamond", 0.75)

    if pip.shape[0] < 12 or pip.shape[1] < 10:
        # icono demasiado pequeño (carta del hero truncada por el
        # nameplate) para que la correlacion de forma sea fiable; picas
        # es, con diferencia, el caso mas frecuente en negro.
        return candidates[0], 0.3

    query = cv2.resize(pip, (TEMPLATE_SIZE, TEMPLATE_SIZE), interpolation=cv2.INTER_AREA)
    _, query = cv2.threshold(query, 100, 255, cv2.THRESH_BINARY)

    best_suit, best_score = None, -2.0
    for suit in candidates:
        tmpl = _TEMPLATES[suit]
        score = cv2.matchTemplate(query, tmpl, cv2.TM_CCOEFF_NORMED)[0][0]
        if score > best_score:
            best_score, best_suit = score, suit
    return best_suit, max(0.0, (best_score + 1) / 2)
