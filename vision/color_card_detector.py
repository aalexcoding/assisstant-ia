"""
Deteccion de cartas para el mazo de 4 colores (fondo de color solido +
rango en blanco) del cliente real de PokerStars (vision/samples_pokerstars/),
en vez del mazo blanco con texto de color de vision/samples/ (card_detector.py).

Verificado contra 57 capturas reales: cada palo tiene un color de fondo
propio y estable (corazon salmon, trebol turquesa, diamante azul, pica
gris), asi que el palo se resuelve directamente segun a que mascara de
color pertenece el contorno — no hace falta plantilla de forma como en
suit_classifier.py.

Las cartas no aparecen fusionadas como en el mazo blanco (ahi el hueco entre
las 2 cartas de una mano era ~0px, aqui siempre hay hueco visible entre
cartas, incluidas las de una misma mano), asi que la señal estructural para
distinguir "board" de "un par de mano" no puede ser fusion de contorno: en
Texas Hold'em el board nunca tiene 1 o 2 cartas (solo 0/3/4/5), mientras que
una mano siempre son exactamente 2, asi que agrupar los contornos sueltos
por fila (misma altura, hueco pequeño) y mirar el tamaño del grupo basta:
grupos de 3-5 son board, grupos de 2 son una mano de algun jugador.

Ademas del mazo blanco, aqui hay 2 estilos de render distintos con
tamaño/proporcion propios: las cartas de board y las de una mano cuando el
cliente la muestra "en grande" (icono de palo arriba, rango grande abajo,
alto/ancho ~1.4) y las cartas reveladas en un all-in ("en pequeño", rango
arriba/icono abajo, alto/ancho ~0.8). Ambos estilos se detectan igual (color
+ forma redondeada); solo importa para separar candidatas validas de ruido
de UI (fichas, watermarks, botones), que quedan fuera del rango de aspecto
0.6-2.0 valido para una carta.
"""
import cv2
import numpy as np

# (hue_lo, hue_hi, sat_lo, sat_hi, val_lo, val_hi) en HSV de OpenCV (H:0-179).
# Calibrado contra sample_1784855343738/393862/429002.png (los 4 palos
# confirmados con ejemplos reales, no solo corazon/trebol como en el board
# revisado a mano).
SUIT_HSV_RANGES = {
    "heart": (0, 12, 140, 230, 200, 255),
    "club": (70, 95, 200, 255, 120, 220),
    "diamond": (100, 120, 70, 140, 150, 230),
    "spade": (10, 30, 5, 40, 110, 170),
}

MIN_AREA = 800
MIN_W, MIN_H = 40, 35
AR_MIN, AR_MAX = 0.6, 2.0
ROW_Y_TOL = 20
ROW_X_GAP_FACTOR = 2.5


def find_card_boxes(bgr, region=None):
    """Devuelve lista de dicts {x,y,w,h,suit} en coordenadas absolutas.
    A diferencia de card_detector.find_card_boxes, el palo ya viene resuelto
    aqui (una mascara de color por palo), no hace falta suit_classifier."""
    if region is not None:
        rx0, ry0, rx1, ry1 = region
    else:
        rx0, ry0, rx1, ry1 = 0, 0, bgr.shape[1], bgr.shape[0]
    crop = bgr[ry0:ry1, rx0:rx1]
    if crop.size == 0:
        return []
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(np.int32), hsv[:, :, 1].astype(np.int32), hsv[:, :, 2].astype(np.int32)

    boxes = []
    for suit, (hlo, hhi, slo, shi, vlo, vhi) in SUIT_HSV_RANGES.items():
        mask = (((h >= hlo) & (h <= hhi)) & ((s >= slo) & (s <= shi)) &
                ((v >= vlo) & (v <= vhi))).astype(np.uint8) * 255
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < MIN_AREA:
                continue
            x, y, w, hh = cv2.boundingRect(c)
            if w < MIN_W or hh < MIN_H:
                continue
            ar = hh / w if w else 0
            if not (AR_MIN <= ar <= AR_MAX):
                continue
            boxes.append({"x": rx0 + x, "y": ry0 + y, "w": w, "h": hh, "suit": suit})
    return boxes


def _group_rows(boxes):
    """Agrupa cajas sueltas por fila (misma altura aproximada) y, dentro de
    cada fila, corta por hueco grande (dos asientos distintos que caen a la
    misma altura no deben fusionarse en un solo grupo)."""
    remaining = sorted(boxes, key=lambda b: b["y"])
    rows = []
    used = [False] * len(remaining)
    for i, b in enumerate(remaining):
        if used[i]:
            continue
        row = [b]
        used[i] = True
        for j, b2 in enumerate(remaining):
            if used[j]:
                continue
            if abs(b2["y"] - b["y"]) < ROW_Y_TOL:
                row.append(b2)
                used[j] = True
        row.sort(key=lambda bb: bb["x"])
        group = [row[0]]
        for prev, cur in zip(row, row[1:]):
            gap = cur["x"] - (prev["x"] + prev["w"])
            if gap > ROW_X_GAP_FACTOR * prev["w"]:
                rows.append(group)
                group = [cur]
            else:
                group.append(cur)
        rows.append(group)
    return rows


def classify_boxes(boxes, table_region, image_shape):
    """Devuelve (hero_boxes, board_boxes, other_boxes), igual contrato que
    card_detector.classify_boxes. Un grupo de 3-5 cartas en la misma fila es
    siempre board (el board nunca tiene 1-2 cartas); un grupo de exactamente
    2 es la mano de algun jugador, y de esos grupos el mas cercano al
    asiento inferior-centro es el hero (misma convencion que en el mazo
    blanco)."""
    if table_region is not None:
        rx0, ry0, rx1, ry1 = table_region
    else:
        rx0, ry0, rx1, ry1 = 0, 0, image_shape[1], image_shape[0]
    rw, rh = (rx1 - rx0) or 1, (ry1 - ry0) or 1

    rows = _group_rows(boxes)
    board_boxes, other_boxes, pair_groups = [], [], []
    for row in rows:
        if len(row) >= 3:
            board_boxes.extend(row[:5])
        elif len(row) == 2:
            pair_groups.append(row)
        else:
            other_boxes.extend(row)

    def group_score(group):
        cx = sum(b["x"] + b["w"] / 2 for b in group) / len(group)
        cy = sum(b["y"] + b["h"] / 2 for b in group) / len(group)
        return (cx - rx0) / rw, (cy - ry0) / rh

    hero_boxes = []
    if pair_groups:
        best_i, best_fy = None, -1
        for i, group in enumerate(pair_groups):
            fx, fy = group_score(group)
            if abs(fx - 0.5) < 0.3 and fy > best_fy:
                best_fy = fy
                best_i = i
        for i, group in enumerate(pair_groups):
            if i == best_i:
                hero_boxes.extend(group)
            else:
                other_boxes.extend(group)

    board_boxes.sort(key=lambda b: b["x"])
    return hero_boxes, board_boxes, other_boxes
