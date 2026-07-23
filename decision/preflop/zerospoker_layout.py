"""
Constantes de layout y helpers de bajo nivel para digitalizar capturas de ZEROSPOKER.COM.

Todo lo de aquí se dedujo midiendo pixeles reales sobre varias capturas de ambas
categorias (OPEN RAISE y 3BET-CALL, distintos stacks y posiciones), no asumiendo
coordenadas de un unico ejemplo. Ver notas en parse_ranges.py.
"""
import re
from collections import Counter

import cv2
import numpy as np
from PIL import Image

CANON9 = ["BB", "SB", "BTN", "CO", "HJ", "MP2", "MP1", "EP2", "EP1"]
OPEN_RAISE_ROW_LABELS = CANON9[1:]       # SB..EP1 (8) - BB nunca abre
THREEBET_HERO_ROW_LABELS = CANON9[:8]    # BB..EP2 (8) - EP1 nunca enfrenta apertura

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]

INDIVIDUAL_RES = (1920, 1080)

CYAN_ACTIVE = (81, 165, 191)
CYAN_TOL = 20
BTN_INACTIVE = (22, 23, 25)
BTN_INACTIVE_TOL = 3
BTN_MIN_WIDTH = 30

GRID_LEFT = 582
COL_W = 55
ROW_H = 44
GRID_N = 13

LEGEND_X_RANGE = (150, 570)
LEGEND_MIN_AREA = 3000
LEGEND_MIN_WIDTH = 150
LEGEND_BOX_W = 312
LEGEND_BOX_H = 77

LEGEND_LABEL_CHARS = re.compile(r"^[A-Z0-9 %().,\-]*")


def load_rgb(path):
    return np.array(Image.open(path).convert("RGB"))


def mode_color(region):
    """Color dominante (mayoria de pixeles) de una region HxWx3."""
    flat = region.reshape(-1, 3)
    counts = Counter(map(tuple, flat))
    return counts.most_common(1)[0][0], counts, len(flat)


def color_blobs(im, target, tol, min_area=100):
    diff = np.abs(im.astype(int) - np.array(target))
    mask = np.all(diff <= tol, axis=-1).astype(np.uint8) * 255
    n, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area > min_area:
            boxes.append((int(x), int(y), int(w), int(h), int(area)))
    return boxes


def find_position_rows(im):
    """
    Devuelve [hero_blob] o [hero_blob, opp_blob] (bounding boxes del boton cian activo),
    excluyendo el tab de navegacion (columna izquierda) y el panel STACK / opponent-size
    (mas abajo, separados por un salto grande de Y).
    """
    blobs = color_blobs(im, CYAN_ACTIVE, CYAN_TOL, min_area=150)
    candidates = [b for b in blobs if b[0] >= 560]
    candidates.sort(key=lambda b: b[1])
    if not candidates:
        return []
    group = [candidates[0]]
    for b in candidates[1:]:
        if b[1] - group[-1][1] < 150:
            group.append(b)
        else:
            break
    return group[:2]


def row_button_index(im, blob, x_range=(560, 1900)):
    """
    Dado el boton activo (blob) de una fila de posiciones, encuentra todos los
    botones (activos + inactivos) de esa fila y devuelve el indice (0-based,
    de izquierda a derecha) del boton activo dentro de la fila completa.
    """
    x0, y0, w, h, _area = blob
    y_band = (max(0, y0 - 6), y0 + h + 6)
    x0r, x1r = x_range
    sub = im[y_band[0]:y_band[1], x0r:x1r]
    inactive = color_blobs(sub, BTN_INACTIVE, BTN_INACTIVE_TOL, min_area=150)
    active = color_blobs(sub, CYAN_ACTIVE, CYAN_TOL, min_area=150)
    boxes = []
    for (bx, by, bw, bh, ba) in inactive:
        if bw >= BTN_MIN_WIDTH:
            boxes.append((bx + x0r, "inactive"))
    for (bx, by, bw, bh, ba) in active:
        if bw >= BTN_MIN_WIDTH:
            boxes.append((bx + x0r, "active"))
    boxes.sort(key=lambda t: t[0])
    for idx, (_x, tag) in enumerate(boxes):
        if tag == "active":
            return idx, len(boxes)
    return None, len(boxes)


def find_legend_swatches(im):
    """
    Cajas de leyenda: rectangulos grandes de color solido en la columna izquierda,
    debajo de los botones de posicion. La mayoria son colores vivos (rojo/amarillo/
    cian) pero algunos escenarios (ALL IN de shove) usan un gris neutro de baja
    saturacion, asi que no podemos filtrar solo por saturacion HSV: basta con que
    no sean "casi negro" (fondo de pagina / botones inactivos).
    """
    x0, x1 = LEGEND_X_RANGE
    y0, y1 = 350, im.shape[0]
    sub = im[y0:y1, x0:x1]
    mask = (sub.max(axis=-1) > 40).astype(np.uint8) * 255
    n, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area > LEGEND_MIN_AREA and w > LEGEND_MIN_WIDTH:
            boxes.append((int(x) + x0, int(y) + y0, int(w), int(h)))
    boxes.sort(key=lambda b: b[1])
    return boxes


def legend_label_box(box):
    """Recorte (x0,y0,x1,y1,scale) con la linea de texto de la etiqueta de accion."""
    x, y, w, h = box
    return (x, y, x + int(w * 0.72), y + int(h * 0.55), 3)


def legend_meta_box(box):
    """Recorte (x0,y0,x1,y1,scale) con la segunda linea ('7.28% (97 combos)')."""
    x, y, w, h = box
    return (x, y + int(h * 0.5), x + int(w * 0.85), y + h - 4, 3)


def parse_legend_label(raw):
    raw = (raw or "").strip()
    first_line = raw.splitlines()[0] if raw else ""
    m = LEGEND_LABEL_CHARS.match(first_line)
    clean = m.group(0).strip() if m else first_line.strip()
    clean = re.sub(r"^3\s+BET", "3BET", clean)  # OCR a veces separa "3BET" en "3 BET"
    return clean or None


def legend_swatch_color(im, box):
    x, y, w, h = box
    y0 = y + int(h * 0.68)
    y1 = y + h - 4
    x0 = x + 10
    x1 = x + w - 10
    region = im[y0:y1, x0:x1]
    color, _counts, _n = mode_color(region)
    return color


def parse_legend_meta(raw):
    """Segunda linea de la leyenda: '7.28% (97 combos)' -> (pct, combos), best effort."""
    raw = (raw or "").strip()
    pct = None
    combos = None
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", raw)
    if m:
        pct = float(m.group(1))
    m = re.search(r"(\d+)\s*combos", raw, re.IGNORECASE)
    if m:
        combos = int(m.group(1))
    return pct, combos


def hand_at(i, j):
    if i == j:
        return RANKS[i] + RANKS[i]
    if j > i:
        return RANKS[i] + RANKS[j] + "s"
    return RANKS[j] + RANKS[i] + "o"


def cell_rect(grid_top, i, j, inset=4):
    x = GRID_LEFT + j * COL_W + inset
    y = grid_top + i * ROW_H + inset
    w = COL_W - 2 * inset
    h = ROW_H - 2 * inset
    return x, y, w, h


def classify_cell(im, grid_top, i, j):
    x, y, w, h = cell_rect(grid_top, i, j)
    region = im[y:y + h, x:x + w]
    dominant, counts, total = mode_color(region)
    top2 = counts.most_common(2)
    second_frac = 0.0
    if len(top2) == 2:
        second_frac = top2[1][1] / total
    return dominant, second_frac


def nearest_legend_label(color, legend_colors, tol=40):
    best = None
    best_dist = None
    for label, lcolor in legend_colors:
        d = sum((int(a) - int(b)) ** 2 for a, b in zip(color, lcolor)) ** 0.5
        if best_dist is None or d < best_dist:
            best_dist = d
            best = label
    if best is not None and best_dist <= tol:
        return best
    return None
