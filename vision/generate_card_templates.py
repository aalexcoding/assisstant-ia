"""
Genera las 4 plantillas de palo (vision/card_templates/{suit}.png) recortando
el icono pequeno del palo (el que va junto al rango en la esquina superior
izquierda de la carta) a partir de ejemplos reales en vision/samples/. Se
ejecuta una sola vez; las plantillas generadas quedan versionadas y
reutilizables por suit_classifier.py sin volver a tocar las muestras.

No se buscaron 52 plantillas de carta completa (serian fragiles a cualquier
variacion de fuente/tamano): solo la forma del palo, que se combina con la
clasificacion de color (vision/suit_classifier.py) para resolver las 4
posibilidades.
"""
import os

import cv2
import numpy as np

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")
OUT_DIR = os.path.join(os.path.dirname(__file__), "card_templates")
TEMPLATE_SIZE = 28

# (imagen de muestra, caja de la carta x,y,w,h, indice del componente del
# icono de palo dentro de la esquina) obtenidos inspeccionando visualmente
# cartas reales del dataset (ver informe de vision para el detalle).
SOURCES = {
    "club": ("sample_1784849878991.png", (173, 381, 78, 60)),
    "spade": ("sample_1784849763801.png", (535, 388, 78, 110)),
    "diamond": ("sample_1784849763801.png", (618, 388, 78, 109)),
    "heart": ("sample_1784849878991.png", (296, 556, 78, 61)),
}


def _pip_components(card_bgr, w, h):
    corner = card_bgr[0:int(h * 0.55), 0:int(w * 0.75)]
    hsv = cv2.cvtColor(corner, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    colored = ((s > 40) | (v < 120)).astype(np.uint8) * 255
    n, labels, stats, _ = cv2.connectedComponentsWithStats(colored)
    comps = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < 8:
            continue
        x, y, cw, ch = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], \
            stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        comps.append((x, y, cw, ch, area))
    return comps, colored


def _find_index_pip(comps):
    """El icono de indice (el que acompana al rango, no el cuerpo de la
    carta) aparece siempre en una franja x~[25,50], y~[15,45] de la esquina
    recortada, con tamano pequeno y compacto."""
    best = None
    for (x, y, w, h, area) in comps:
        if 22 <= x <= 50 and 12 <= y <= 45 and 8 <= w <= 22 and 8 <= h <= 22:
            if best is None or area > best[4]:
                best = (x, y, w, h, area)
    return best


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for suit, (filename, box) in SOURCES.items():
        im = cv2.imread(os.path.join(SAMPLES_DIR, filename))
        x, y, w, h = box
        card = im[y:y + h, x:x + w]
        comps, mask = _pip_components(card, w, h)
        pip = _find_index_pip(comps)
        if pip is None:
            raise RuntimeError(f"no se encontro el icono de indice para {suit}")
        px, py, pw, ph, _ = pip
        pad = 2
        crop = mask[max(0, py - pad):py + ph + pad, max(0, px - pad):px + pw + pad]
        crop = cv2.resize(crop, (TEMPLATE_SIZE, TEMPLATE_SIZE), interpolation=cv2.INTER_AREA)
        _, crop = cv2.threshold(crop, 100, 255, cv2.THRESH_BINARY)
        out_path = os.path.join(OUT_DIR, f"{suit}.png")
        cv2.imwrite(out_path, crop)
        print(f"{suit}: {out_path}")


if __name__ == "__main__":
    main()
