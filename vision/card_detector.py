"""
Deteccion de cartas como region (parte 1 del enfoque recomendado): las cartas
de PokerStars son rectangulos blancos/redondeados con el rango+palo pintados
en la esquina superior izquierda. Se detectan por contorno (mascara de blanco
casi puro + forma rectangular de proporcion de carta), no por plantillas de
carta completa ni coordenadas fijas.

Las cartas de mano (hero u otro jugador que las muestra en el showdown) se
dibujan pegadas entre si (sin hueco), por lo que su contorno blanco aparece
fusionado en un solo bloque ancho-y-bajo (bajo porque el nameplate suele tapar
la mitad inferior). Las cartas comunitarias si tienen hueco entre ellas y
aparecen como contornos separados. Por eso, ademas de detectar cartas
"sueltas" (candidatas a board), se detectan bloques anchos-y-fusionados y se
dividen en dos mitades (candidatas a par de mano).

La clasificacion hero/board/other no usa fracciones fijas de posicion como
señal principal (poco fiable cerca de los bordes de la region detectada):
usa la señal estructural fuerte de "fusionadas vs separadas", y solo dentro
de los grupos fusionados (que siempre son pares de 2 cartas de mano de algun
jugador) usa la posicion para decidir cual es la del hero (el asiento inferior
-centro es una convencion fija del cliente de PokerStars, no una coordenada
de esta captura en concreto).
"""
import cv2
import numpy as np

WHITE_MAX_SATURATION = 55
WHITE_MIN_VALUE = 150
MIN_CARD_AREA = 700

SINGLE_ASPECT = (1.15, 1.9)
SINGLE_MIN_W, SINGLE_MIN_H = 25, 35
SINGLE_MIN_SOLIDITY = 0.85

PAIR_ASPECT_MAX = 0.9
PAIR_MIN_W, PAIR_MIN_H = 90, 50
PAIR_MAX_W, PAIR_MAX_H = 260, 200
PAIR_MIN_SOLIDITY = 0.7


def _white_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    return ((s < WHITE_MAX_SATURATION) & (v > WHITE_MIN_VALUE)).astype(np.uint8) * 255


def find_card_boxes(bgr, region=None):
    """Devuelve lista de dicts {x,y,w,h,group} con coordenadas absolutas en
    la imagen original. Las dos mitades de un bloque fusionado comparten el
    mismo group_id y group_kind='pair'; las cartas sueltas van solas con
    group_kind='single'."""
    if region is not None:
        rx0, ry0, rx1, ry1 = region
    else:
        rx0, ry0, rx1, ry1 = 0, 0, bgr.shape[1], bgr.shape[0]
    crop = bgr[ry0:ry1, rx0:rx1]
    mask = _white_mask(crop)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    group_id = 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < MIN_CARD_AREA:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w == 0 or h == 0:
            continue
        ar = h / w
        solidity = area / (w * h)

        if SINGLE_ASPECT[0] < ar < SINGLE_ASPECT[1] and solidity > SINGLE_MIN_SOLIDITY \
                and w > SINGLE_MIN_W and h > SINGLE_MIN_H:
            boxes.append({"x": rx0 + x, "y": ry0 + y, "w": w, "h": h,
                          "group_id": group_id, "group_kind": "single"})
            group_id += 1
            continue

        if ar < PAIR_ASPECT_MAX and PAIR_MIN_W < w < PAIR_MAX_W and PAIR_MIN_H < h < PAIR_MAX_H \
                and solidity > PAIR_MIN_SOLIDITY:
            half_w = w // 2
            boxes.append({"x": rx0 + x, "y": ry0 + y, "w": half_w, "h": h,
                          "group_id": group_id, "group_kind": "pair"})
            boxes.append({"x": rx0 + x + half_w, "y": ry0 + y, "w": w - half_w, "h": h,
                          "group_id": group_id, "group_kind": "pair"})
            group_id += 1

    return boxes


def classify_boxes(boxes, table_region, image_shape):
    """Devuelve (hero_boxes, board_boxes, other_boxes). Los grupos 'pair'
    fusionados son siempre 2 cartas de mano de algun jugador (nunca board);
    de esos grupos, el mas cercano al asiento inferior-centro es el hero.
    Los grupos 'single' sueltos son candidatas a board."""
    if table_region is not None:
        rx0, ry0, rx1, ry1 = table_region
    else:
        rx0, ry0, rx1, ry1 = 0, 0, image_shape[1], image_shape[0]
    rw, rh = (rx1 - rx0) or 1, (ry1 - ry0) or 1

    groups = {}
    singles = []
    for b in boxes:
        if b["group_kind"] == "pair":
            groups.setdefault(b["group_id"], []).append(b)
        else:
            singles.append(b)

    def group_score(group):
        cx = sum(b["x"] + b["w"] / 2 for b in group) / len(group)
        cy = sum(b["y"] + b["h"] / 2 for b in group) / len(group)
        fx = (cx - rx0) / rw
        fy = (cy - ry0) / rh
        return fx, fy

    hero_boxes, other_boxes = [], []
    if groups:
        best_id, best_fy = None, -1
        for gid, group in groups.items():
            fx, fy = group_score(group)
            if abs(fx - 0.5) < 0.3 and fy > best_fy:
                best_fy = fy
                best_id = gid
        for gid, group in groups.items():
            if gid == best_id:
                hero_boxes.extend(group)
            else:
                other_boxes.extend(group)

    board_boxes = list(singles)
    return hero_boxes, board_boxes, other_boxes
