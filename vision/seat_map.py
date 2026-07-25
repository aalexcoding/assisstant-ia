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
import re

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
# siempre el de abajo-centro. Mesa de 6 plazas (torneo "6-Max").
#
# Plate y button RE-MEDIDOS sobre samples_layout2/ (111 frames de la misma
# sesion en vivo, calibracion mas ajustada que samples_layout/): las anclas
# de boton se verificaron una a una contra frames reales donde el boton estaba
# en ese asiento (disco blanco con pica roja, aislado sobre el tapete), no
# extrapoladas ni por espejo como en el mapa anterior. Las de MR/UR eran las
# unicas validadas en el primer dataset (0.838/0.752 y 0.904/0.283); ahora el
# boton pasa por los seis asientos y las seis quedan medidas. HERO era una pura
# estimacion (0.66,0.90) y estaba mal: el disco del dealer del hero aparece
# arriba-IZQUIERDA de sus cartas, en ~(0.368,0.872), no a su derecha.
SEATS = {
    "TOPC": {"plate": (0.36, -0.16, 0.69, 0.06), "button": (0.563, 0.142)},
    "UL":   {"plate": (-0.13, -0.02, 0.23, 0.22), "button": (0.104, 0.320)},
    "UR":   {"plate": (0.79, -0.02, 1.14, 0.22), "button": (0.901, 0.308)},
    "ML":   {"plate": (-0.13, 0.60, 0.21, 0.85), "button": (0.090, 0.570)},
    "MR":   {"plate": (0.81, 0.60, 1.14, 0.85), "button": (0.833, 0.803)},
    "HERO": {"plate": (0.37, 0.89, 0.74, 1.13), "button": (0.368, 0.872)},
}
HERO_SEAT = "HERO"

# Nameplate del hero anclado a la posicion de sus CARTAS, no a una fraccion
# fija del ovalo. El nameplate del hero vive en el borde inferior de la
# ventana -la zona mas sensible al encuadre/tamaño-, asi que una fraccion fija
# del ovalo que cuadra en un encuadre se desplaza en otro (y de hecho la que
# habia cortaba el stack por abajo: 0/111 lecturas). En cambio la capsula
# nombre+stack cae SIEMPRE justo debajo de las dos cartas del hero (que
# color_card_detector detecta de forma fiable), asi que se expresa como
# fracciones del bbox de esas cartas. El avatar y la marca de bounty solapan
# la parte IZQUIERDA de la capsula, por eso la zona arranca a la derecha del
# borde izquierdo de las cartas; nombre y stack quedan en la mitad central/
# derecha. Margenes generosos (sobra tapete alrededor del texto) para que el
# stack no se corte aunque el encuadre varie unos pixeles: el OCR tolera texto
# rodeado de fondo mucho mejor que texto cortado por el borde.
# Fracciones (x0,y0,x1,y1): x respecto al borde izq. de las cartas y su ancho;
# y respecto al borde inferior de las cartas y su alto.
HERO_PLATE_FROM_CARDS = (0.13, 0.02, 1.32, 1.60)

# zonas fijas de los elementos de mesa (fracciones del nucleo del tapete)
HERO_CARDS_ZONE = (0.40, 0.83, 0.62, 1.04)
BOARD_ZONE = (0.26, 0.28, 0.78, 0.54)
# el texto "Bote: N" se muestra mas abajo en preflop (sin cartas de board que
# lo empujen hacia arriba) que en postflop; la zona cubre ambas alturas.
POT_ZONE = (0.34, 0.11, 0.66, 0.38)
# cubre las 4 lineas de mensajes visibles del chat: el aviso "Los limites
# suben: Ciegas .../..." va subiendo por el log segun llegan mensajes nuevos,
# asi que hay que abarcar todas las filas para pillarlo este donde este.
#
# x0 = -0.20 y no -0.155: con -0.155 la zona empezaba ~36px a la DERECHA del
# borde del panel de chat y se comia los 3 primeros caracteres de cada linea.
# Medido sobre samples_layout2/: "Repartidor:" se leia "artidor:" en 30/30 de las
# capturas probadas, y peor, las lineas envueltas perdian el principio de la mano
# ganadora ("doble pareja, damas y sietes" -> "le pareja, damas y sietes",
# "pareja de treses" -> "eja de treses"), que es justo el texto que muestra el
# panel "Mano anterior". Con -0.20 se lee completo en 30/30. Ensanchar por la
# DERECHA (x1 de 0.47 a 0.62) no cambiaba nada: el texto se salia por la
# izquierda, no por la derecha.
CHAT_ZONE = (-0.20, 1.29, 0.47, 1.62)
ACTION_ZONE = (0.73, 1.40, 1.18, 1.62)

# ancla de boton: media-zona (fraccion del nucleo) alrededor del punto ancla
BUTTON_HALF_W = 0.070
BUTTON_HALF_H = 0.120

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


def hero_plate_from_cards(hero_boxes, shape):
    """Zona (x0,y0,x1,y1 px) del nameplate del hero anclada al bbox de sus
    cartas ya detectadas (HERO_PLATE_FROM_CARDS). Devuelve None si no hay
    cartas del hero ese frame (entre manos): sin cartas no hay decision que
    tomar, asi que el hueco no importa."""
    if not hero_boxes:
        return None
    bx0 = min(b["x"] for b in hero_boxes)
    bx1 = max(b["x"] + b["w"] for b in hero_boxes)
    by1 = max(b["y"] + b["h"] for b in hero_boxes)
    cw = (bx1 - bx0) or 1
    ch = (by1 - min(b["y"] for b in hero_boxes)) or 1
    fx0, fy0, fx1, fy1 = HERO_PLATE_FROM_CARDS
    x0 = max(0, int(bx0 + fx0 * cw))
    y0 = max(0, int(by1 + fy0 * ch))
    x1 = min(shape[1], int(bx0 + fx1 * cw))
    y1 = min(shape[0], int(by1 + fy1 * ch))
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


# El disco del dealer es BLANCO-dominante con una pequeña pica roja al centro.
# Medido sobre samples_layout2/: fraccion de pixeles blancos ~0.42-0.44 y de
# rojos ~0.27-0.29 (asi que blanco > rojo, con margen ~0.15), area ~600-640.
# Las fichas de apuesta ("5"/"25"/"100") y las marcas de recompensa ("⊕0,31€",
# el crosshair de bounty presente en cada asiento) tambien son blanco+rojo pero
# ROJO-dominantes (blanco ~0.25-0.28 < rojo ~0.38-0.42), y los blancos puros de
# la UI no tienen rojo; exigir blanco>rojo y rojo>=0.12 separa el boton de todos
# ellos sin depender del color del tapete.
BUTTON_AREA_MIN = 380
BUTTON_AREA_MAX = 820
BUTTON_RED_MIN = 0.12
BUTTON_WHITE_MARGIN = 0.04  # blanco debe superar al rojo por este margen


def detect_button_seat(bgr, ref):
    """Devuelve el nombre del asiento que tiene el boton del dealer, o None.
    Enfoque por ancla-por-asiento: dentro de la zona-ancla de cada asiento
    busca el disco del boton (blanco+pica roja) como un blob compacto circular,
    aislado sobre el tapete (no toca los bordes de la zona -eso descarta dorsos
    de carta, avatares y fichas pegados a estructuras mayores-), blanco-dominante
    y con rojo al centro (descarta fichas de apuesta y marcas de recompensa, que
    son rojo-dominantes)."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(np.int32), hsv[:, :, 1].astype(np.int32), hsv[:, :, 2].astype(np.int32)
    white = (s < 80) & (v > 175)
    red = ((h < 10) | (h > 168)) & (s > 90) & (v > 110)
    obj = ((white | red).astype(np.uint8)) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, k, iterations=1)

    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    best, best_margin = None, -1
    for name, cfg in SEATS.items():
        fx, fy = cfg["button"]
        cx, cy = rx + fx * rw, ry + fy * rh
        x0 = max(0, int(cx - BUTTON_HALF_W * rw))
        y0 = max(0, int(cy - BUTTON_HALF_H * rh))
        x1 = min(bgr.shape[1], int(cx + BUTTON_HALF_W * rw))
        y1 = min(bgr.shape[0], int(cy + BUTTON_HALF_H * rh))
        sub = obj[y0:y1, x0:x1]
        wsub = white[y0:y1, x0:x1]
        rsub = red[y0:y1, x0:x1]
        if sub.size == 0:
            continue
        hh, ww = sub.shape
        contours, _ = cv2.findContours(sub, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < BUTTON_AREA_MIN or area > BUTTON_AREA_MAX:
                continue
            x, y, w, h_ = cv2.boundingRect(c)
            ar = w / h_ if h_ else 0
            if not (0.7 <= ar <= 1.4):
                continue
            if area / (w * h_) < 0.65:
                continue
            if x <= 1 or y <= 1 or x + w >= ww - 1 or y + h_ >= hh - 1:
                continue
            wf = wsub[y:y + h_, x:x + w].mean()
            rf = rsub[y:y + h_, x:x + w].mean()
            if rf < BUTTON_RED_MIN or wf < rf + BUTTON_WHITE_MARGIN:
                continue
            margin = wf - rf
            if margin > best_margin:
                best_margin = margin
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


# --- importe apostado por asiento (para inferir quien subio) ---
# En preflop, cada jugador que ha metido fichas tiene su importe dibujado
# delante del asiento, hacia el centro del tapete (la ciega su ciega, un raiser
# un importe mayor). Cada zona es una fraccion (x0,y0,x1,y1) del nucleo del
# tapete, situada entre el nameplate del asiento y el centro -donde cae el
# numero-, con margen generoso para no cortarlo. Medidas sobre samples_layout2/
# (chips "50"/"90"/"100"/"45" verificados uno a uno). El numero del importe cae
# siempre en el lado del stack de fichas que mira al centro; se leen todos los
# enteros de la zona y se toma el mayor (el total apostado siempre iguala o
# supera a la denominacion impresa en cada ficha, e ignora la marca de bounty
# "0,31 €", que no es un entero). La zona del HERO arranca por debajo del borde
# del ovalo para no tragarse las fichas de ante/bote del centro.
SEAT_BET_ZONES = {
    "TOPC": (0.48, -0.02, 0.72, 0.14),
    "UL":   (0.12, 0.16, 0.36, 0.34),
    "UR":   (0.62, 0.12, 0.88, 0.30),
    "ML":   (0.10, 0.58, 0.30, 0.76),
    "MR":   (0.70, 0.58, 0.86, 0.76),
    "HERO": (0.30, 0.68, 0.58, 0.87),
}

# El cliente muestra los importes en dos unidades segun la config del usuario:
#   - FICHAS: enteros con separador de miles ("5.892", "1.900").
#   - BIG BLINDS: coma decimal + sufijo BB ("123,4 BB", "3,75 BB", "89 BB").
# En modo BB el valor leido YA ES la profundidad/apuesta en bb (no hace falta
# dividir por la ciega). Se auto-detecta el modo por la presencia del sufijo BB.

# modo FICHAS: tira de digitos (con separador de miles opcional). Se extrae de
# cada token en vez de exigir que el token entero cuadre, para tolerar glifos
# pegados del OCR sobre el tapete/fichas ("B50" -> 50).
_BET_DIGITS_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+|\d{1,6}")

# modo BB: numero seguido del sufijo BB.
#
# El separador decimal del cliente en castellano es la COMA, pero el OCR la lee a
# veces como PUNTO, asi que se aceptan los dos. Y el lookbehind + el \b no son
# cosmeticos: son lo que evita dos fallos MUDOS que estuvieron vivos y que dan una
# profundidad plausible pero falsa (el peor fallo posible en esta app):
#   '57.2 BB'   -> antes 2       (57bb leidos como 2bb -> tabla de 4bb -> ALL IN)
#   '1234,5 BB' -> antes 234,5   (el tope de 3 digitos truncaba el primero)
# Un numero con separador de MILES ("1.900 BB", "12.500 BB") NO casa a proposito:
# en modo BB no existe -es OCR corrupto de un importe en fichas- y aceptarlo
# volveria a introducir el error de 1000x.
_BB_AMOUNT_RE = re.compile(r"(?<![\d.,])(\d{1,4}(?:[.,]\d{1,2})?)\s*BB\b", re.IGNORECASE)


def parse_bet_amount(lines):
    """Modo FICHAS: importe apostado (int) o None. Toma el mayor entero de la
    zona: el total apostado siempre iguala o supera la denominacion impresa en
    las fichas del stack, e ignora la marca de bounty ("0,31 €", no es entero)."""
    best = None
    for ln in lines:
        for m in _BET_DIGITS_RE.finditer(ln["text"]):
            val = int(m.group(0).replace(".", "").replace(",", ""))
            if val > 0 and (best is None or val > best):
                best = val
    return best


def parse_amount_bb(lines):
    """Modo BB: valor (float) que lleva el sufijo BB ("123,4 BB" -> 123.4,
    "3,75 BB" -> 3.75). Ignora las denominaciones impresas en las fichas
    (enteros sin sufijo) y la marca de bounty. None si no hay ningun "N BB"."""
    text = " ".join(ln["text"] for ln in lines)
    m = _BB_AMOUNT_RE.search(text)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def has_bb_marker(lines):
    """True si en las lineas OCR aparece el sufijo de unidad BB (stacks/apuestas
    mostrados en big blinds, p.ej. "Media: 89 BB" en la esquina o "44,5 BB" en
    un nameplate)."""
    for ln in lines:
        for w in ln["text"].split():
            if w.strip(".,;:'\"|()").upper() == "BB":
                return True
    return bool(_BB_AMOUNT_RE.search(" ".join(ln["text"] for ln in lines)))


# La apuesta del asiento BB no puede tomarse como prueba de una subida: la BB ya
# tiene la ciega puesta y, en un torneo con BB-ante (practicamente todos los
# modernos), tambien el ante, asi que su importe SUPERA la ciega grande sin que
# nadie haya subido. Se acepta como "solo ciega + ante" hasta este multiplo de la
# ciega grande (2.0 = ciega + un ante de 1bb, el BB-ante mas grande habitual).
# Por encima de ahi la BB si ha subido de verdad -> codigo "bb_raised".
#
# Sin esto, con BB-ante el flujo era: bet_BB = 1+ante > bb -> ("BB","single") ->
# se busca threebet_call[stack][hero]["BB"], que NO EXISTE para ningun hero (los
# vs_position posibles son solo {BTN,CO,EP1,EP2,HJ,MP1,MP2,SB}: la BB habla
# ULTIMA preflop, asi que nunca es el agresor al que uno defiende) -> abstencion
# en TODAS las manos. Dejo rastro en el log real de una sesion:
# "sin rango de defensa para CO vs BB a 14.1bb (threebet_call)".
BB_POSTED_MAX_MULT = 2.0


def detect_raiser(players, bb):
    """Con el importe apostado por asiento ya leido (player["bet"]), decide si
    hay UNA sola subida preflop y quien la hizo. Devuelve (vs_position, code):
      - "single": un unico rival (no-hero) con apuesta > bb -> vs_position = su
        posicion; es una subida unica que el hero enfrenta.
      - "no_raise": nadie por encima de la bb -> vs_position None (bote sin
        abrir, solo ciegas/limps); el hero abre.
      - "multiway": >=2 rivales por encima de la bb -> None (bote multiway o
        3bet ya presente); no se adivina.
      - "hero_raised": el propio hero por encima de la bb -> None (ya subio y
        enfrenta una resubida, fuera del modelo threebet_call).
      - "bb_raised": la BB ha subido de verdad (mas que ciega+ante) -> None. La
        BB habla ultima preflop, asi que no hay rango de defensa contra ella en
        las tablas; enfrentarla es un spot distinto (el hero ya limpeo).
      - "raiser_no_pos": subida unica pero el raiser sin posicion -> None.
      - "no_bb": sin ciega grande para juzgar -> None.
    Conservador por diseño: ante cualquier duda devuelve None (mejor no
    recomendar defensa que recomendarla contra una posicion equivocada)."""
    if not bb:
        return None, "no_bb"
    above = [p for p in players
             if isinstance(p.get("bet"), (int, float)) and p["bet"] > bb]
    if any(p.get("is_hero") for p in above):
        return None, "hero_raised"
    opp = [p for p in above if not p.get("is_hero")]
    # el asiento BB solo cuenta como agresor si se pasa de ciega+ante (ver
    # BB_POSTED_MAX_MULT); si no, su importe es dinero obligatorio, no una subida
    bb_seat = [p for p in opp if p.get("position") == "BB"]
    if bb_seat and any(p["bet"] > bb * BB_POSTED_MAX_MULT for p in bb_seat):
        return None, "bb_raised"
    opp = [p for p in opp if p.get("position") != "BB"]
    if not opp:
        return None, "no_raise"
    if len(opp) > 1:
        return None, "multiway"
    pos = opp[0].get("position")
    if pos is None:
        return None, "raiser_no_pos"
    return pos, "single"


# --- ocupacion (nameplate presente) ---
# La ocupacion NO se decide aqui por pixeles: se probo la fraccion de pixeles
# oscuros de la capsula del nameplate y NO separa vacio de ocupado sobre
# samples_layout2/ (un asiento vacio muestra las sillas granate sobre fondo
# casi-negro, tan oscuras como la capsula; ambos dan ~0.5-0.8). Tampoco separa
# ninguna metrica de brillo/gris/color simple (medido). La señal fiable es el
# TEXTO del nameplate (nombre/stack/verbo de accion), que solo tienen los
# asientos ocupados; esa decision vive en table_state._plate_occupied(), donde
# ya estan las lineas OCR por asiento.


# Nota: se exploro exponer un campo opcional in_hand por asiento a partir del
# dorso rojo de las cartas repartidas (el reverso de PokerStars es rojo
# oscuro), pero un muestreo radial simple no localiza los dorsos de forma
# fiable (caen a offsets distintos segun el asiento, y el hero va boca arriba),
# asi que no se incluye para no exponer una señal casi siempre falsa. Haria
# falta una zona de dorso propia por asiento y mas medicion.
