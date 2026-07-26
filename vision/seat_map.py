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
#
# HERO_CARDS_ZONE se ensancho el 26-07-2026 al cambiar de mazo. Extension real
# de las cartas medida en fracciones del nucleo, sobre los frames con reference
# bueno de las dos sesiones de ese dia:
#
#     mazo de fondo solido   x 0.401..0.600   y 0.908..1.065   (n=97)
#     mazo de cara blanca    x 0.344..0.601   y 0.877..1.159   (n=93)
#
# La zona anterior (0.40, 0.83, 0.62, 1.04) cortaba por abajo a LOS DOS mazos, y
# por la izquierda al nuevo. Ensancharla es neutral para el viejo -215 frames
# con las 2 cartas antes y despues, identicos- y sube el nuevo de 0 a 171.
HERO_CARDS_ZONE = (0.34, 0.86, 0.64, 1.10)

# El borde INFERIOR del board (0.60) no es un margen de cortesia: es un fallo que
# mordio de verdad. Estaba en 0.54 y las cartas se CORTABAN por abajo, con lo que
# el glifo perdia su parte de abajo y el OCR leia otro rango: medido en una
# partida real, un board 9c Qc 4h salia como ['9c','9c','4h'] -la Q sin su cola
# se lee como 9- y la equity se calculaba con una carta FALSA, o se descartaba
# por duplicada (15 frames en una sesion). Las cajas terminaban exactamente en
# y+h = borde de la zona, que es la firma de un recorte, no de una deteccion.
#
# Calibrado sobre 227 cartas de dos sesiones con encuadres distintos: las cartas
# acaban entre las fracciones 0.385 y 0.578 del nucleo, con mediana 0.537, y
# miden 119 px de alto (las que se cortaban median 105). Con 0.60 caben todas con
# margen. Ampliando incluso hasta 0.68 NO aparecen cartas fantasma -las fichas del
# bote no pasan el detector-, asi que el margen es gratis.
BOARD_ZONE = (0.26, 0.28, 0.78, 0.60)
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

# Etiquetas de posicion de una mesa de 9, que es como estan digitalizados los
# rangos del usuario (decision/preflop/zerospoker_layout.CANON9), en orden de
# habla preflop: el primero abre y la BB cierra.
CANON9 = ("EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB")


def _posiciones(n):
    """Etiquetas para una mesa de n jugadores, empezando en el BOTON y siguiendo
    el orden de reparto (horario), que es lo que espera table_state.

    LA EQUIVALENCIA ES POR CUANTOS JUGADORES QUEDAN DETRAS, no por el nombre del
    asiento. Es lo que determina la anchura de un rango de apertura: importa
    cuanta gente puede despertarse despues de ti, no como se llame tu silla.

    El primero en hablar de una mesa de n tiene n-1 jugadores detras, asi que le
    corresponde la etiqueta de 9-max con esos mismos n-1 detras.

    EL BUG QUE ARREGLA. La tabla estaba escrita a mano y a partir de 6 jugadores
    asignaba EP1 al primero en hablar, siempre. Pero EP1 de una mesa de 9 tiene
    OCHO jugadores detras, y el primero de una de 6 solo tiene CINCO: le
    corresponde MP2. Consecuencia, medida sobre ranges.json a 20bb: se servia un
    rango del 17,0% de las manos donde tocaba uno del 25,0%, o sea un tercio mas
    tight de lo debido, y en TODAS las manos abiertas desde esa posicion. Falla
    en silencio porque las posiciones se emparejan por cadena de texto.

    Las filas de 3, 4, 5 y 9 jugadores ya eran correctas y siguen dando lo mismo;
    cambian 6, 7 y 8. Y heads-up pasa de BTN a SB, que tambien es lo correcto: en
    heads-up el boton ES la ciega pequeña, habla primero y tiene un solo rival
    detras, exactamente como la SB de una mesa de 9 -que ademas es la unica fila
    con LIMP digitalizado, la forma que pide ese spot-."""
    habla = [CANON9[len(CANON9) - 1 - (n - 1 - j)] for j in range(n)]
    corte = max(0, n - 3)          # el boton va tres antes del final (BTN SB BB)
    return habla[corte:] + habla[:corte]


SEATING_BY_N = {n: _posiciones(n) for n in range(2, 10)}


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
# El area del disco se expresa como FRACCION del area del nucleo del tapete, no
# en pixeles: es el mismo principio que el resto del modulo -"todo se expresa
# como fracciones de una referencia que se escala sola con la ventana"- y este
# umbral era la unica cosa que se habia quedado en pixeles absolutos.
#
# Costo caro: con el recuadro recalibrado a 1315x908 (el nucleo pasa de 798x370 a
# 967x455, factor de AREA 1.47) el disco pasaba a medir ~886 px, por encima del
# antiguo maximo de 820, y el boton dejaba de detectarse EN TODOS LOS FRAMES. Sin
# boton no hay posiciones, y sin posiciones el motor no recomienda nada: una
# sesion entera de 224 frames con cero recomendaciones por un umbral que no
# escalaba. Medido sobre las dos resoluciones:
#     area ABSOLUTA   antiguo 627-634   nuevo 882-894   (41% de diferencia)
#     area FRACCION   antiguo 0.00203-0.00216   nuevo 0.00195-0.00217  (la misma)
# Los margenes conservan la generosidad de los valores originales (~0.6x y ~1.3x
# alrededor del disco observado).
BUTTON_AREA_FRAC_MIN = 0.00125
BUTTON_AREA_FRAC_MAX = 0.00275
# El disco lleva SIEMPRE los dos colores -un fondo claro y una pica roja-, pero
# NO siempre en la misma proporcion: el tema de mesa decide cual domina. Medido
# sobre los dos temas vistos:
#
#     tema con trama de puntos   disco BLANCO con pica roja pequeña   blanco 0.50  rojo 0.15
#     tema de fieltro liso       disco CREMA con pica roja grande     blanco 0.23  rojo 0.61
#
# La regla de antes exigia que el blanco superase al rojo, asi que en el segundo
# tema NO encontraba el boton en NINGUN frame, y sin boton no hay posiciones y sin
# posiciones el motor no recomienda: 44 frames seguidos con las cartas bien
# leidas y cero recomendaciones. Lo que de verdad separa al boton de una ficha o
# de un icono de la interfaz es que estan los DOS colores a la vez en un blob
# compacto, no cual de ellos gana, asi que se exige un minimo de cada uno y se
# elige por el mas equilibrado (el que mas tiene del color que le falta).
BUTTON_RED_MIN = 0.12
BUTTON_WHITE_MIN = 0.12


def detect_button_seat(bgr, ref):
    """Devuelve el nombre del asiento que tiene el boton del dealer, o None.
    Enfoque por ancla-por-asiento: dentro de la zona-ancla de cada asiento
    busca el disco del boton (blanco+pica roja) como un blob compacto circular,
    aislado sobre el tapete (no toca los bordes de la zona -eso descarta dorsos
    de carta, avatares y fichas pegados a estructuras mayores-) y con los DOS
    colores presentes, en cualquier proporcion: el tema de mesa decide si domina
    el claro o el rojo (ver BUTTON_RED_MIN). Exigir los dos es lo que descarta
    fichas de apuesta y marcas de recompensa, que son de un solo color."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(np.int32), hsv[:, :, 1].astype(np.int32), hsv[:, :, 2].astype(np.int32)
    white = (s < 80) & (v > 175)
    red = ((h < 10) | (h > 168)) & (s > 90) & (v > 110)
    obj = ((white | red).astype(np.uint8)) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    obj = cv2.morphologyEx(obj, cv2.MORPH_CLOSE, k, iterations=1)

    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    area_nucleo = max(1, rw * rh)   # el area del disco se juzga relativa a esto
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
            if not (BUTTON_AREA_FRAC_MIN <= area / area_nucleo <= BUTTON_AREA_FRAC_MAX):
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
            if rf < BUTTON_RED_MIN or wf < BUTTON_WHITE_MIN:
                continue
            margin = min(wf, rf)
            if margin > best_margin:
                best_margin = margin
                best = name
            break
    return best


# --- el boton SIN MIRAR COLOR: gana el hueco donde hay algo ---
#
# La idea es del usuario y es mejor que cualquier calibracion de color: en el
# hueco del boton hay ALGO que tapa el tapete, y en los otros cinco no hay nada.
# Con eso el tono del disco deja de importar, que es lo que ha roto esta pieza
# dos veces (el tema de mesa cambia el dibujo del boton).
#
# El unico color que se usa es el DEL PROPIO TAPETE, leido del frame en dos
# parches dentro del ovalo, asi que no hay nada calibrado que un tema pueda
# invalidar.
#
# Se exige que el objeto NO TOQUE el borde del hueco (eso descarta el rail, los
# nameplates y cualquier estructura que entre por un lado) y que el ganador
# DOBLE al segundo: si dos huecos tienen algo parecido no se sabe cual es y se
# devuelve None, que es la respuesta honesta.
#
# Medido sobre 614 frames de tres sesiones con tres temas distintos:
#
#                       por color   sin color   union    desacuerdos
#     tema con puntos       95%        90%        95%         0
#     tema liso             32%        36%        49%         0
#     mesa de 4             49%        51%        76%         0
#
# CERO desacuerdos en las 438 veces que los dos responden, asi que la union es
# segura: no hay que decidir cual gana porque nunca se contradicen.
#
# Los limites de area salen de una barrida: con el rango estrecho del detector
# por color la cobertura se queda en el 13%, y aflojando el margen por debajo de
# 1.6 empiezan a aparecer desacuerdos. 0.0008-0.005 con margen 1.6 es el punto
# donde la cobertura es maxima con acuerdo perfecto.
BOTON_FORMA_AREA_MIN = 0.0008
BOTON_FORMA_AREA_MAX = 0.005
BOTON_FORMA_MARGEN = 1.6
TAPETE_H_TOL = 12
TAPETE_S_TOL = 80


def _color_del_tapete(hsv, ref):
    """Tono y saturacion del fieltro, leidos del propio frame: dos parches
    dentro del ovalo, a los lados, lejos del board y de las fichas del bote."""
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    ps = []
    for fx0, fx1 in ((0.06, 0.20), (0.80, 0.94)):
        sub = hsv[ry + int(0.30 * rh):ry + int(0.65 * rh),
                  rx + int(fx0 * rw):rx + int(fx1 * rw)]
        if sub.size:
            ps.append(sub.reshape(-1, 3))
    if not ps:
        return None
    a = np.vstack(ps)
    return int(np.median(a[:, 0])), int(np.median(a[:, 1]))


def button_shape_scores(bgr, ref):
    """{asiento: area del mayor objeto AISLADO en su hueco / area del hueco}.
    Publico para poder auditar por que gano un hueco y no otro."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    felt = _color_del_tapete(hsv, ref)
    if felt is None:
        return {name: 0.0 for name in SEATS}
    h = hsv[:, :, 0].astype(np.int32)
    s = hsv[:, :, 1].astype(np.int32)
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    area_nucleo = max(1, rw * rh)
    out = {}
    for name, cfg in SEATS.items():
        fx, fy = cfg["button"]
        cx, cy = rx + fx * rw, ry + fy * rh
        x0 = max(0, int(cx - BUTTON_HALF_W * rw))
        y0 = max(0, int(cy - BUTTON_HALF_H * rh))
        x1 = min(bgr.shape[1], int(cx + BUTTON_HALF_W * rw))
        y1 = min(bgr.shape[0], int(cy + BUTTON_HALF_H * rh))
        zh, zs = h[y0:y1, x0:x1], s[y0:y1, x0:x1]
        if zh.size == 0:
            out[name] = 0.0
            continue
        d = np.minimum(np.abs(zh - felt[0]), 180 - np.abs(zh - felt[0]))
        m = (~((d <= TAPETE_H_TOL) & (np.abs(zs - felt[1]) <= TAPETE_S_TOL))).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        n, _lab, st, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
        hh, ww = m.shape
        mejor = 0
        for i in range(1, n):
            x, y, w, hb, a = st[i]
            if x <= 1 or y <= 1 or x + w >= ww - 1 or y + hb >= hh - 1:
                continue
            if not (BOTON_FORMA_AREA_MIN <= a / area_nucleo <= BOTON_FORMA_AREA_MAX):
                continue
            mejor = max(mejor, int(a))
        out[name] = mejor / max(1, zh.size)
    return out


def detect_button_seat_por_forma(bgr, ref):
    """El asiento cuyo hueco de boton tiene algo, cuando los demas no tienen
    nada. None si empatan o si no hay nada en ninguno."""
    orden = sorted(button_shape_scores(bgr, ref).items(), key=lambda kv: -kv[1])
    if not orden or orden[0][1] <= 0:
        return None
    if len(orden) > 1 and orden[1][1] > 0 and orden[0][1] < BOTON_FORMA_MARGEN * orden[1][1]:
        return None
    return orden[0][0]


def detect_button_seat_union(bgr, ref, plantilla=None):
    """El boton por las tres vias, en orden de precision: color, forma y
    plantilla aprendida. Ninguna contradice a otra -0 desacuerdos en 438 y en
    1.027 comparaciones- asi que encadenarlas solo puede añadir cobertura.

    `plantilla` es un PlantillaBoton que el llamador mantiene entre frames; si no
    se pasa, se usan solo las dos primeras vias. Ademas se le da de comer cada
    respuesta segura, que es como aprende."""
    seat = detect_button_seat(bgr, ref) or detect_button_seat_por_forma(bgr, ref)
    if plantilla is None:
        return seat
    if seat is not None:
        plantilla.aprender(bgr, ref, seat)
        return seat
    return plantilla.buscar(bgr, ref)


# --- la plantilla del disco, aprendida de la propia mesa ---
#
# Idea del usuario: guardar el disco UNA VEZ en la sesion y luego buscarlo tal
# cual, en vez de re-analizarlo cada frame. Es la via que mas cobertura añade y
# la unica que no depende de segmentar bien: una correlacion no necesita que el
# contorno salga entero, y el fallo mas comun del tema de fieltro liso es
# justamente que el aro dorado del disco parte el contorno (40 de sus 80 fallos).
#
# Se aprende SOLA de los frames que las otras dos vias ya resuelven, asi que no
# hay nada que calibrar ni que configurar, y se re-aprende en cada sesion: una
# plantilla guardada en disco se quedaria vieja el dia que cambie el tema, que es
# justo el fallo del que se viene huyendo.
#
# Medido sobre 1.339 frames de tres sesiones con tres temas:
#
#                    color   +forma   +plantilla
#     tema con puntos  94%     95%       95%
#     tema liso        34%     48%       71%
#     mesa de 4-max    53%     79%       80%
#
# Y sobre 1.027 frames donde las otras vias saben la respuesta, la plantilla
# acierta 1.027 y falla 0. Ese cero es lo que la hace segura de encadenar.
#
# SE PROBO Y SE DESCARTO una via intermedia: aprender solo la FIRMA DE COLOR del
# disco (histograma de tono) y usarla para elegir entre candidatos con la
# geometria aflojada. La firma se aprende perfectamente -0.99 de coherencia, y
# describe bien los dos temas: "claro 64% + rojo 35%" el uno, "dorado 39% + rojo
# 26% + claro 18%" el otro- pero al aflojar la geometria entran objetos que no
# son el disco y el parecido de color los elige igual: 14 de 34 respuestas nuevas
# contradecian al asiento seguro de al lado. Cambiar "no lo se" por un asiento
# equivocado es el peor cambio posible en esta app.
PLANTILLA_LADO = 40           # tamaño canonico en que se guarda
PLANTILLA_RADIO_FRAC = 0.030  # medio lado del recorte, en fracciones del nucleo
PLANTILLA_MIN_DISCOS = 8      # con menos no se usa: la mediana no vale de nada
PLANTILLA_MAX_DISCOS = 60
PLANTILLA_MIN_SCORE = 0.55
PLANTILLA_MARGEN = 0.10


def _hueco_px(bgr, ref, seat):
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    fx, fy = SEATS[seat]["button"]
    cx, cy = rx + fx * rw, ry + fy * rh
    return (max(0, int(cx - BUTTON_HALF_W * rw)),
            max(0, int(cy - BUTTON_HALF_H * rh)),
            min(bgr.shape[1], int(cx + BUTTON_HALF_W * rw)),
            min(bgr.shape[0], int(cy + BUTTON_HALF_H * rh)))


class PlantillaBoton:
    """El disco del dealer recortado de la propia mesa, para buscarlo por
    correlacion cuando el color y la forma no lo encuentran.

    Vive fuera de vision/ (lo guarda quien lleva la sesion) porque es estado
    ENTRE frames, igual que asientos_estables."""

    def __init__(self):
        self._discos = []
        self._tpl = None

    def __len__(self):
        return len(self._discos)

    @property
    def lista(self):
        return self._tpl is not None

    def aprender(self, bgr, ref, seat):
        """Guarda el disco de un frame en que ya se sabe donde esta."""
        if seat is None or len(self._discos) >= PLANTILLA_MAX_DISCOS:
            return
        d = self._recortar(bgr, ref, seat)
        if d is None:
            return
        self._discos.append(d)
        if len(self._discos) >= PLANTILLA_MIN_DISCOS:
            # la MEDIANA y no la media: un recorte con una ficha encima no debe
            # arrastrar la plantilla
            self._tpl = np.median(np.array(self._discos), axis=0).astype(np.uint8)

    def _recortar(self, bgr, ref, seat):
        puntos = button_shape_scores(bgr, ref)
        if puntos.get(seat, 0) <= 0:
            return None
        x0, y0, x1, y1 = _hueco_px(bgr, ref, seat)
        r = int(PLANTILLA_RADIO_FRAC * ref[2])
        if r < 4:
            return None
        cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
        a, b, c, d = cy - r, cy + r, cx - r, cx + r
        if a < 0 or c < 0 or b > bgr.shape[0] or d > bgr.shape[1]:
            return None
        return cv2.resize(bgr[a:b, c:d], (PLANTILLA_LADO, PLANTILLA_LADO),
                          interpolation=cv2.INTER_AREA)

    def buscar(self, bgr, ref):
        """Asiento cuyo hueco se parece mas a la plantilla, o None si ninguno
        llega al minimo o si dos empatan."""
        if self._tpl is None:
            return None
        esc = (2 * int(PLANTILLA_RADIO_FRAC * ref[2])) / PLANTILLA_LADO
        if esc <= 0:
            return None
        tpl = cv2.resize(self._tpl, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
        out = []
        for seat in SEATS:
            x0, y0, x1, y1 = _hueco_px(bgr, ref, seat)
            sub = bgr[y0:y1, x0:x1]
            if sub.shape[0] < tpl.shape[0] or sub.shape[1] < tpl.shape[1]:
                continue
            out.append((float(cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED).max()), seat))
        out.sort(reverse=True)
        if not out or out[0][0] < PLANTILLA_MIN_SCORE:
            return None
        if len(out) > 1 and out[0][0] < out[1][0] + PLANTILLA_MARGEN:
            return None
        return out[0][1]


# --- quien sigue en la mano: dorsos de carta por asiento ---
#
# Esta nota SUSTITUYE a la que habia al final del fichero diciendo que la
# deteccion de dorsos no era viable. Aquel intento fallo por MUESTREO RADIAL
# (buscar los dorsos a un offset fijo desde el centro del asiento), y el
# diagnostico de entonces era correcto: caen a offsets distintos segun el asiento.
# La conclusion que se saco, en cambio, no lo era. Lo que hacia falta es lo que la
# propia nota pedia -"una zona de dorso propia por asiento y mas medicion"- y con
# eso funciona.
#
# Color del dorso, MEDIDO sobre las capturas reales: HSV (178, 131, 127), un
# granate oscuro desaturado. Se separa de todo lo demas con holgura:
#   dorso de carta      H=178  S=131  V=127
#   silla vacia          H=110  S= 31  V= 35   <- desaturada y oscura
#   tapete               H= 68  S=200  V=116   <- verde
#   carta boca arriba    S~190  V~254          <- mucho mas viva
#
# Zonas medidas por busqueda ciega de blobs sobre 141 frames (samples_layout2 +
# samples_layout): 253 blobs, 245 de ellos agrupados en estos cinco asientos con
# una desviacion tipica <= 0.016 en fracciones del nucleo. El blob de un par de
# cartas mide ~0.174 x 0.084, asi que las zonas llevan margen generoso alrededor.
#
# NO hay zona para el HERO: sus cartas van boca arriba y state["hero_cards"] ya
# responde a "¿esta el hero en la mano?". Es justo el caso que la nota antigua
# señalaba como problematico, y desaparece por construccion.
# EL DORSO CAMBIA DE COLOR CON EL TEMA DE MESA, asi que hay un perfil por cada
# uno visto y basta con que encaje UNO. Medidos, los dos planos porque el cliente
# los renderiza vectoriales:
#
#   granate (tema con trama de puntos)   H=178  S=131  V=127
#   naranja (tema de fieltro liso)       H= 19  S=255  V=248
#
# Costo caro: con el tema naranja el dorso no encajaba en NINGUN asiento, asi que
# in_hand salia 0 rivales en los 65 frames de una sesion y la equity no se
# calculaba ni una vez -"no se detecta ningun rival con cartas"-. El usuario lo
# noto como que los porcentajes de ganar/perder habian desaparecido.
#
# Cada perfil es (H_lo, H_hi, S_lo, S_hi, V_lo, V_hi), con H circular cuando
# H_lo > H_hi (el granate cae a caballo del origen del tono).
CARD_BACK_PERFILES = (
    (168, 6, 95, 175, 85, 175),      # granate
    (12, 26, 190, 255, 190, 255),    # naranja
)
CARD_BACK_MIN_AREA_FRAC = 0.10   # area del mayor blob / area de la zona

CARD_BACK_ZONES = {
    "TOPC": (0.39, -0.30, 0.62, -0.14),
    "UL":   (-0.10, -0.10, 0.13, 0.05),
    "UR":   (0.87, -0.10, 1.10, 0.05),
    "ML":   (-0.14, 0.51, 0.10, 0.69),
    "MR":   (0.91, 0.51, 1.15, 0.69),
}


def card_back_fractions(bgr, ref):
    """{asiento: fraccion del area de su zona ocupada por el mayor blob de dorso}.

    Se devuelve la metrica cruda y no solo el si/no para que el test pueda
    afirmar el MARGEN entre las dos poblaciones y para poder depurar en vivo,
    igual que detect_button_seat expone sus constantes medidas."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.int32)
    s = hsv[:, :, 1].astype(np.int32)
    v = hsv[:, :, 2].astype(np.int32)
    mask = np.zeros(h.shape, dtype=bool)
    for hlo, hhi, slo, shi, vlo, vhi in CARD_BACK_PERFILES:
        tono = ((h >= hlo) | (h <= hhi)) if hlo > hhi else ((h >= hlo) & (h <= hhi))
        mask |= tono & (s >= slo) & (s <= shi) & (v >= vlo) & (v <= vhi)
    mask = mask.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                            cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))

    out = {}
    for name, zona in CARD_BACK_ZONES.items():
        x0, y0, x1, y1 = zone_to_px(ref, zona, bgr.shape)
        sub = mask[y0:y1, x0:x1]
        if sub.size == 0:
            out[name] = 0.0
            continue
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(sub, connectivity=8)
        mayor = max((stats[i, cv2.CC_STAT_AREA] for i in range(1, n)), default=0)
        out[name] = float(mayor) / sub.size
    return out


def detect_in_hand_seats(bgr, ref):
    """Asientos rivales con cartas repartidas (dorso visible, del color que sea).

    LIMITACION que hay que tener presente: en un all-in o en el showdown el
    cliente da la vuelta a las cartas, los dorsos desaparecen y el recuento BAJA.
    Eso infla la equity del hero, que es la direccion peligrosa, asi que quien
    consuma esto debe abstenerse cuando el recuento llegue a cero con el hero aun
    con cartas, y calcular solo cuando sea el turno del hero."""
    return {n for n, frac in card_back_fractions(bgr, ref).items()
            if frac >= CARD_BACK_MIN_AREA_FRAC}


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


def parse_to_call_bb(lines):
    """Importe EN BB que pide el boton "Igualar/Pagar", o None si no se lee con
    confianza. Solo tiene sentido en modo BB (el boton muestra el sufijo).

    Para que sirve: es la unica evidencia independiente de que hay una subida que
    enfrentar. Si el boton pide mas de 1bb y NINGUN asiento tiene un importe que
    lo explique (porque el OCR de la mesa fallo), el motor esta a punto de
    recomendar el rango de APERTURA enfrentando una subida -plausible y falso-.
    Con esto se puede abstener en su lugar.

    Se busca primero en la linea del verbo, porque sobre samples_layout2/ el
    importe suele caer en la MISMA linea OCR que el ("_Ú Igualar 90"); pero no
    siempre (["Igualar", "Subir a", "100", "200"]), asi que si ahi no hay, se
    toma el MENOR importe de la zona: igualar es siempre menor que subir-a.
    "Igualar cualquiera" (all-in sin cifra) no lleva importe -> None.

    SIN VALIDAR contra capturas en modo BB: no las hay todavia, asi que no se
    sabe si el cliente pone el sufijo "BB" en los botones como lo pone en los
    stacks. Por eso solo se usa para ABSTENERSE, nunca para construir una
    recomendacion: si devuelve None de mas, no se pierde nada."""
    verbo = []
    todos = []
    for ln in lines:
        low = ln["text"].lower()
        vals = [float(m.group(1).replace(",", ".")) for m in _BB_AMOUNT_RE.finditer(ln["text"])]
        todos.extend(vals)
        if any(w in low for w in FACING_BET_WORDS):
            verbo.extend(vals)
    if verbo:
        return min(verbo)
    if todos:
        return min(todos)
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
#
# LA APP SOLO LEE BIG BLINDS. Habia un parse_bet_amount para el modo fichas que
# tomaba "el mayor entero de la zona"; se retiro con el paso a BB-only y NO debe
# volver como respaldo de parse_amount_bb "para ganar cobertura": un entero
# desnudo sobre el tapete es tambien la DENOMINACION IMPRESA en una ficha (25,
# 100), asi que aceptarlo leeria una ficha como una apuesta de 25bb e inventaria
# un raiser. Exigir el sufijo "BB" es lo que garantiza que, si el cliente no esta
# en modo big blinds, no se lea NADA y la app se abstenga en vez de leer mal.

# numero seguido del sufijo BB.
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


def parse_amount_bb(lines):
    """Modo BB: valor (float) que lleva el sufijo BB ("123,4 BB" -> 123.4,
    "3,75 BB" -> 3.75). Ignora las denominaciones impresas en las fichas
    (enteros sin sufijo) y la marca de bounty. None si no hay ningun "N BB".

    A PRUEBA DE AMBIGUEDAD: si en la zona aparecen DOS importes distintos, se
    devuelve None en vez del primero. Una zona de nameplate puede tragarse el
    importe del asiento vecino o el "Media: N BB" de la esquina si el encuadre
    baila, y quedarse con "el que salga antes" significa elegir la profundidad
    equivocada -y con ella el rango equivocado- sin que nada lo delate. Sin
    stack el motor se abstiene o tira del cache; con un stack falso recomienda
    con conviccion. Medido sobre samples_bb/: las tres zonas con importe dan un
    unico valor, asi que hoy no cuesta cobertura."""
    text = " ".join(ln["text"] for ln in lines)
    valores = {float(m.group(1).replace(",", ".")) for m in _BB_AMOUNT_RE.finditer(text)}
    if len(valores) == 1:
        return valores.pop()
    return None


def has_bb_amount(lines):
    """True si en la zona hay AL MENOS un importe con sufijo BB, sin importar
    cuantos ni cual. Es la pregunta que necesita la deteccion de ocupacion
    ("¿hay alguien sentado?"), distinta de la que responde parse_amount_bb
    ("¿cuanto tiene?"), que devuelve None a proposito si hay ambiguedad.

    Exige NUMERO + sufijo. Hubo un has_bb_marker que aceptaba un token "BB"
    suelto: valia para detectar la UNIDAD (donde el sufijo bastaba), pero como
    señal de ocupacion un "BB" suelto es ruido de OCR de dos caracteres, y un
    asiento vacio que lo produzca contaria como ocupado y desplazaria las
    posiciones de TODOS. Se retiro con la deteccion de unidad."""
    return _BB_AMOUNT_RE.search(" ".join(ln["text"] for ln in lines)) is not None


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


# Nota historica (RESUELTA, ver CARD_BACK_ZONES / detect_in_hand_seats mas
# arriba): se exploro exponer un campo in_hand por asiento a partir del dorso
# rojo de las cartas repartidas y se descarto porque "un muestreo radial simple
# no localiza los dorsos de forma fiable (caen a offsets distintos segun el
# asiento, y el hero va boca arriba)". El diagnostico era correcto y la
# conclusion no: lo que fallaba era el muestreo radial, no la señal. Haciendo lo
# que la propia nota pedia -una zona de dorso propia por asiento y mas medicion-
# la separacion es limpia: sobre 141 frames x 5 asientos = 705 observaciones,
# "sin cartas" llega como mucho a 0.0085 y "con cartas" empieza en 0.1159, con
# CERO observaciones en la banda intermedia. Y el hero no necesita zona: sus
# cartas van boca arriba y hero_cards ya responde por el.
