"""
Localiza el area aproximada de la mesa (ovalo + borde rojo) dentro del frame,
para usarla como region de busqueda y descartar el "cromo" ajeno (barra de
YouTube, panel lateral, chat) sin depender de coordenadas fijas: se detecta
por el borde rojo de la mesa, que es un elemento fijo del skin estandar de
PokerStars (a diferencia del tapete, cuyo color varia).

El borde suele aparecer partido en varios arcos (los nameplates de los
jugadores, las cartas del hero y el HUD del stream lo tapan en partes), asi
que no se puede asumir un unico contorno cerrado: se toma la caja envolvente
de todos los fragmentos de borde detectados y se amplia con margen generoso,
calibrado contra las muestras reales para incluir nameplates que sobresalen
por encima/por debajo del ovalo y los botones de accion.
"""
import cv2
import numpy as np

RED_HUE_LOW = 10
RED_HUE_HIGH = 170
RED_MIN_SATURATION = 80
RED_MIN_VALUE = 60

PAD_TOP = 0.45
PAD_BOTTOM = 0.65
PAD_SIDES = 0.20


def find_table_region(bgr):
    h_img, w_img = bgr.shape[:2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (((h < RED_HUE_LOW) | (h > RED_HUE_HIGH)) & (s > RED_MIN_SATURATION) & (v > RED_MIN_VALUE))
    mask = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    fragments = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 300:
            continue
        x, y, w, hh = cv2.boundingRect(c)
        solidity = area / (w * hh) if w * hh else 0
        if solidity < 0.5 and w > 40 and hh > 15:
            fragments.append((x, y, w, hh))
    if not fragments:
        return None

    xs = [f[0] for f in fragments] + [f[0] + f[2] for f in fragments]
    ys = [f[1] for f in fragments] + [f[1] + f[3] for f in fragments]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    bw, bh = x1 - x0, y1 - y0

    x0 -= int(bw * PAD_SIDES)
    x1 += int(bw * PAD_SIDES)
    y0 -= int(bh * PAD_TOP)
    y1 += int(bh * PAD_BOTTOM)

    return max(0, x0), max(0, y0), min(w_img, x1), min(h_img, y1)
