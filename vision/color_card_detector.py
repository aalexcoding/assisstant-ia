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
# PokerStars tiene VARIOS mazos de fondo solido y el usuario los cambia desde
# las opciones sin que la app se entere, asi que hay una lista de perfiles por
# palo y basta con que encaje UNO. Todos los colores son planos (minimo = maximo
# en las medianas medidas), porque el cliente los renderiza vectoriales.
#
#   mazo "vivo"   (calibrado contra 57 capturas de samples_pokerstars/)
#       corazon salmon, trebol turquesa, diamante azul claro, pica gris claro
#   mazo "apagado" (medido el 27-07-2026 sobre 205 cartas de board de una sesion)
#       corazon H=0 S=142 V=130   trebol H=48 S=139 V=138
#       diamante H=97 S=126 V=128  pica gris H=0 S=0 V=90
#
# Los dos juegos NO se pisan: el corazon apagado tiene V=130 y el vivo exige
# V>=200; el trebol apagado esta en H=48 y el vivo empieza en H=70; la pica
# apagada tiene V=90 y la viva exige V>=110. El unico solape es entre los dos
# diamantes, y ahi los dos dicen "diamante", asi que no hay ambigüedad.
#
# Los margenes son de ~15% alrededor de lo medido, no ajustados al pixel: una
# tolerancia demasiado justa convierte cualquier variacion de render en un fallo.
SUIT_HSV_PROFILES = {
    "heart": [(0, 12, 140, 230, 200, 255),
              (0, 6, 120, 165, 110, 155), (174, 180, 120, 165, 110, 155)],
    "club": [(70, 95, 200, 255, 120, 220),
             (42, 56, 110, 165, 80, 165)],
    "diamond": [(100, 120, 70, 140, 150, 230),
                (90, 104, 60, 150, 110, 215)],
    "spade": [(10, 30, 5, 40, 110, 170),
              (0, 180, 0, 28, 72, 108)],
}

# se conserva el nombre antiguo para quien lo consulte: el primer perfil de cada
# palo es el mazo con el que se calibro el modulo
SUIT_HSV_RANGES = {k: v[0] for k, v in SUIT_HSV_PROFILES.items()}

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
    for suit, perfiles in SUIT_HSV_PROFILES.items():
        m = np.zeros(h.shape, dtype=bool)
        for hlo, hhi, slo, shi, vlo, vhi in perfiles:
            m |= (((h >= hlo) & (h <= hhi)) & ((s >= slo) & (s <= shi)) &
                  ((v >= vlo) & (v <= vhi)))
        mask = m.astype(np.uint8) * 255
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
    return _limpiar(boxes)


# Ancho de carta admisible, en fracciones del ancho MEDIANO de la zona. Las
# cartas de una misma mesa miden todas lo mismo, asi que una caja que se sale de
# ahi no es una carta.
ANCHO_MIN_FRAC = 0.60
ANCHO_MAX_FRAC = 1.60


def _solapan(a, b):
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and
            a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def _limpiar(boxes):
    """Quita cajas imposibles: las que miden mucho mas o mucho menos que una
    carta, y las que se SOLAPAN con otra.

    POR QUE. Las fichas del bote se apoyan encima de las cartas, y cuando el chip
    es rojo y la carta tambien SE FUNDEN en un solo blob. Ese blob sigue pasando
    el filtro de forma -183x140 da 1.31 de proporcion, dentro del 0.6-2.0- asi
    que salia como una carta mas, encima de las buenas: boards de SEIS cartas,
    con la misma carta contada dos veces. Medido en la sesion del 27-07 a las
    04:00, frame 18:

        x=481 w= 57  heart     <- fragmento
        x=481 w=183  heart     <- el MISMO sitio, dos cartas fundidas
        x=547 w= 83  heart     x=641 w=82   x=732 w=83   x=824 w=82

    Dos cartas del board NUNCA se solapan y todas miden lo mismo, asi que las dos
    reglas son estructurales, no umbrales tanteados. Con menos de 3 cajas no se
    aplica el filtro de ancho: no hay mediana fiable y la mano del hero son 2."""
    if not boxes:
        return boxes
    orden = sorted(boxes, key=lambda b: b["x"])
    if len(orden) >= 3:
        anchos = sorted(b["w"] for b in orden)
        med = anchos[len(anchos) // 2]
        orden = [b for b in orden
                 if ANCHO_MIN_FRAC * med <= b["w"] <= ANCHO_MAX_FRAC * med]
    fuera = []
    for b in orden:
        if any(_solapan(b, y) for y in fuera):
            continue
        fuera.append(b)
    return fuera


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
