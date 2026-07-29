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

from vision import color_card_detector

# posicion fraccionaria tipica del nucleo del tapete dentro del recuadro
# capturado (medida sobre samples_layout/), usada solo como fallback si la
# deteccion por contraste falla.
FELT_CORE_IN_FRAME = (0.186, 0.164, 0.675, 0.458)

# --- deteccion del ovalo por contraste (independiente del color) ---
#
# HAY VARIOS TIPOS DE MESA Y EL CLIENTE PONE UNO U OTRO SEGUN EL TORNEO. No es
# el tema que elige el usuario: en una sola sesion grabada (215025) aparecen
# TRES mesas distintas segun la mano. Catalogo medido sobre 13 sesiones, con el
# HSV mediano del fieltro y el acierto de esta funcion:
#
#     fieltro (H,S,V)     sesiones                          acierto
#     ( 12,201,220) naranja  021103 022334 023224 034522     76-96%
#     ( 67,200,100) verde    014058 163519 220231            86-100%
#     ( 82,200, 97) verde az 214214 215025                   83-88%
#     (104,160, 72) azul     020044 020432                   88-100%
#     ( 44, 96,145) oliva    003045                          14-20%   <-- roto
#     (  0,  0, 30) NEGRA    215025 (Mystery Bounty)          2-4%    <-- roto
#
# El papel de pared es (43,81,32) en casi todas y gris (0,0,33) en las ultimas.
#
# Las dos rotas lo estan por razones distintas y las dos rompen la premisa de
# esta funcion:
#   - La NEGRA no pasa NINGUNO de los dos umbrales (S=0 < 45, V=30 < 60): para
#     esta funcion la mesa sencillamente no existe.
#   - La OLIVA tiene el mismo tono que el papel de pared (44 contra 43), asi que
#     fieltro y fondo son la misma mancha.
# Ademas el fondo NO es oscuro como dice el parrafo de _nucleo_plausible: en las
# esquinas esta a V=32, pero tiene una banda arriba a V=85 que pasa el umbral y
# suelda el ovalo con el borde de arriba del frame.
#
# CUATRO SUSTITUTOS PROBADOS Y DESCARTADOS, todos medidos sobre las 13 sesiones,
# comparando la caja contra la de aqui (importa que sea LA MISMA: todas las
# zonas son fracciones suyas, asi que moverla desplaza el mapa entero):
#
#     sustituto                        arregla        rompe            desvio
#     tono dominante del fieltro       215025 0->100  014058 100->16   29%
#     recorte por forma de ovalo       215025 0->40   -                p95 54%
#     ancla de color HSV completo      215025 2->72   naranjas 96->0   13%
#     elipse por bordes (Canny)        -              TODO 0%          -
#     "lo que no es el papel de pared" 215025 3->43   casi todo <16%   24%
#
# El de bordes falla porque los nameplates y las cartas parten el contorno del
# ovalo en trozos y no queda ni una elipse entera. El de "no es el fondo" falla
# porque la barra de arriba, el chat y los nameplates tampoco son fondo y se
# funden en una sola mancha pegada al borde.
#
# La textura tampoco separa, aunque lo parezca: se midio la desviacion tipica
# local y los fieltros naranjas salen MAS rugosos que el papel de pared (12.5
# contra 7.3) porque llevan trama de puntos.
#
# O sea que la solucion no es cambiar estos dos numeros: hace falta IDENTIFICAR
# QUE MESA ES y usar la regla que le toque, que es lo que pidio el usuario.
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
SEATS_6MAX = {
    "TOPC": {"plate": (0.36, -0.16, 0.69, 0.06), "button": (0.563, 0.142)},
    "UL":   {"plate": (-0.13, -0.02, 0.23, 0.22), "button": (0.104, 0.320)},
    "UR":   {"plate": (0.79, -0.02, 1.14, 0.22), "button": (0.901, 0.308)},
    "ML":   {"plate": (-0.13, 0.60, 0.21, 0.85), "button": (0.090, 0.570)},
    "MR":   {"plate": (0.81, 0.60, 1.14, 0.85), "button": (0.833, 0.803)},
    "HERO": {"plate": (0.37, 0.89, 0.74, 1.13), "button": (0.368, 0.872)},
}

# MESA DE 8: TRES POR CADA LADO Y DOS ENFRENTADOS, que es como la describe el
# usuario y lo que la medicion reprodujo por su cuenta.
#
# LO QUE FALLABA no era que faltaran dos zonas: es que las que hay caen en el
# sitio equivocado. En 8-max cada lateral tiene DOS asientos a media altura y
# abajo (y = +0,44 y y = +0,94) y el mapa de 6 define UNO en y = +0,72, o sea
# justo en el hueco entre los dos. Por eso ML y MR aterrizaban en tapete vacio y
# se perdian DOS jugadores, no uno. Medido jugando: 4,62 asientos leidos por
# frame habiendo 6-8 ocupados, 19% de frames con las cartas del hero, y pestañas
# del cliente -"Manos", "Frases", "Mesav"- coladas como nicks.
#
# LAS OCHO ZONAS salen de barrer el tapete con una ventana del tamaño de un
# nameplate sobre 349 frames de dos sesiones, y agrupar. Ver docs/MESAS-DE-8-Y-9.md
# para el metodo y lo que no funciono (buscar manchas en la mascara: la capsula
# se funde con las sillas y con la de al lado).
#
# LOS DOS DEL MEDIO SOBRESALEN -ML en -0,05 y MR en +1,07 frente a +0,04 y +0,95
# de sus vecinos- y ese detalle es la mejor señal de que la medicion es real: es
# la panza del ovalo. Unas posiciones inventadas habrian salido en columna.
#
# LAS ANCLAS DEL BOTON estan medidas aparte, acumulando la posicion del disco en
# 670 frames (se ve en el 97%) y agrupando igual. Cada una queda 1,22x-1,98x mas
# cerca de su asiento que del siguiente, que es el margen del que depende que
# disco_dealer no le atribuya el boton al vecino.
SEATS_8MAX = {
    "TOPC": {"plate": (0.33, -0.28, 0.69, -0.04), "button": (0.558, 0.072)},
    "UL":   {"plate": (-0.14, -0.12, 0.22, 0.11), "button": (0.168, 0.188)},
    "UR":   {"plate": (0.77, -0.12, 1.13, 0.12), "button": (0.867, 0.210)},
    "ML":   {"plate": (-0.23, 0.32, 0.13, 0.56), "button": (0.069, 0.291)},
    "MR":   {"plate": (0.89, 0.32, 1.25, 0.56), "button": (0.932, 0.615)},
    "DL":   {"plate": (-0.14, 0.81, 0.22, 1.05), "button": (0.218, 0.804)},
    "DR":   {"plate": (0.77, 0.82, 1.13, 1.06), "button": (0.755, 0.788)},
    "HERO": {"plate": (0.32, 1.01, 0.68, 1.25), "button": (0.358, 0.910)},
}

# MESA DE 9: CUATRO POR CADA LADO Y NADIE EN FRENTE, que es como la describe el
# usuario -"si tenemos como referencia al hero que soy yo abajo, 4 andan a mi
# izquierda y otro 4 a la derecha, nadie en frente"- y lo que la medicion
# reprodujo por su cuenta. No hay TOPC: los dos asientos de arriba estan a los
# LADOS del centro (+0,26 y +0,74), no en el.
#
# Medido sobre la sesion del 29-07 a las 21:35, barriendo el tapete con una
# ventana del tamaño de un nameplate y agrupando: salen NUEVE cumulos, cada uno
# en el 96-100% de los frames, y ninguno falso. Verificado a ojo en
# docs/casos/mesa9_nueve_localizados.png.
#
# LAS POSICIONES SE RE-MIDIERON con 1.291 frames de dos sesiones largas y salen
# iguales que con los 74 primeros, dentro de 0,02 en las nueve. Confirmadas.
#
# LAS ANCLAS DEL BOTON SI CAMBIARON, y por eso hubo que medirlas. La primera
# version las derivaba tirando de cada asiento un 30% hacia el centro, calibrado
# con las 2 unicas anclas que habia entonces. Con el disco visto en 1.157 frames
# aparecen OCHO cumulos, y la derivacion se equivocaba una media de 0,083 del
# nucleo, hasta 0,158 en HERO y 0,144 en MR. No es un error inocente: el disco se
# atribuye al ancla MAS CERCANA, asi que a esa distancia el boton se le puede dar
# al vecino.
#
#     asiento   derivada      medida        error
#     UR        0.913,0.199   0.912,0.219   0.020
#     DL        0.178,0.815   0.218,0.834   0.044
#     TR        0.668,0.045   0.685,0.099   0.057
#     DR        0.829,0.829   0.772,0.802   0.063
#     TL        0.332,0.024   0.259,0.057   0.080
#     UL        0.094,0.199   0.049,0.289   0.101
#     MR        0.913,0.500   0.940,0.641   0.144
#     HERO      0.507,0.962   0.359,0.907   0.158
#
# ML SIGUE DERIVADA: el disco no paso por ese asiento en ninguna de las dos
# sesiones, asi que no hay nada que medir. Queda como la unica de las nueve sin
# comprobar, y se nota porque es la que menos separacion tiene de su vecina
# (0,221 de UL).
#
# La separacion minima entre anclas es 0,159 (HERO y DL). disco_dealer exige que
# la primera sea <= 0,75x la segunda o se abstiene, asi que con esa separacion un
# disco a medio camino no se atribuye a nadie en vez de atribuirse mal, que es el
# reparto de errores correcto.
SEATS_9MAX = {
    "TL":   {"plate": (0.08, -0.30, 0.44, -0.06), "button": (0.259, 0.057)},
    "TR":   {"plate": (0.56, -0.27, 0.92, -0.03), "button": (0.685, 0.099)},
    "UL":   {"plate": (-0.26, -0.05, 0.10, 0.19), "button": (0.049, 0.289)},
    "UR":   {"plate": (0.91, -0.05, 1.27, 0.19), "button": (0.912, 0.219)},
    "ML":   {"plate": (-0.27, 0.39, 0.09, 0.63), "button": (0.087, 0.507)},
    "MR":   {"plate": (0.91, 0.38, 1.27, 0.62), "button": (0.940, 0.641)},
    "DL":   {"plate": (-0.14, 0.83, 0.22, 1.07), "button": (0.218, 0.834)},
    "DR":   {"plate": (0.79, 0.85, 1.15, 1.09), "button": (0.772, 0.802)},
    "HERO": {"plate": (0.33, 1.04, 0.69, 1.28), "button": (0.359, 0.907)},
}

# La de 6 sigue siendo la de por defecto: es la que tiene detras todas las
# mediciones del proyecto, y una mesa de 6 es lo que el usuario juega
# habitualmente. SEATS se conserva como nombre para no reescribir los modulos
# que solo leen la disposicion por defecto (herramientas de diagnostico y tests).
SEATS = SEATS_6MAX

DISPOSICIONES = {6: SEATS_6MAX, 8: SEATS_8MAX}


def disposicion(max_players=None):
    """Mapa de asientos para una mesa de `max_players` plazas.

    Sin decirlo, o con un numero para el que no hay tabla, se usa la de 6. NO se
    adivina: una disposicion equivocada no falla de forma visible, lee nombres de
    donde no hay nadie y deja jugadores invisibles, y eso desplaza TODAS las
    posiciones porque salen del recuento de asientos ocupados. Mas vale leer de
    menos con la tabla conocida que leer de mas con una inventada.

    La mesa de 7 no tiene tabla todavia y cae a la de 6."""
    return DISPOSICIONES.get(max_players, SEATS_6MAX)


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
#
# EL TOTAL SALE DE AQUI Y DE NINGUN OTRO SITIO. Cuando hay un all-in el cliente
# ademas PARTE el bote y dibuja cada trozo con sus fichas DEBAJO del board
# ("29,6 BB" y "137,8 BB" en sesion-2026-07-28_012453/0485, que suman los 167,4
# de esta etiqueta). Esos trozos no se leen: la etiqueta de encima del board ya
# da el total, asi que sumarlos seria trabajo extra para llegar al mismo numero
# con mas formas de equivocarse.
#
# La zona no llega a esa banda y por eso no se contaminan: medidos los trozos de
# bote sobre frames reales, caen en fy 0,59..0,69, y esta zona acaba en 0,38.
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
    if best is not None and _nucleo_plausible(best, h_img, w_img):
        return best[0], best[1], best[2], best[3], False
    # REPARACION, no sustitucion. Solo se intenta cuando el blob mayor NO es
    # plausible, o sea cuando hoy el frame se pierde entero. Los frames que hoy
    # funcionan no pasan por aqui, asi que no pueden cambiar: la garantia es
    # estructural, no estadistica. Ver _recortar_puente.
    if best is not None:
        arreglado = _recortar_puente(core, best)
        if arreglado is not None and _nucleo_plausible(arreglado, h_img, w_img):
            return arreglado[0], arreglado[1], arreglado[2], arreglado[3], False
    fx, fy, fw, fh = FELT_CORE_IN_FRAME
    return int(fx * w_img), int(fy * h_img), int(fw * w_img), int(fh * h_img), True


# El nucleo del tapete es un OVALO ANCHO que nunca llega al borde del frame: el
# cliente siempre tiene barra arriba y panel de chat abajo. Estas dos condiciones
# son lo unico que hace falta para saber que la deteccion se ha ido, y hacen
# falta porque la premisa del metodo -"el fondo es casi negro"- se rompe con los
# temas de FONDO CLARO: uno de fondo olivo (H=44, S=80) deja pasar el 42% del
# frame y el "mayor blob" acaba siendo fondo y tapete pegados.
#
# Costo caro: con ese tema el nucleo salia (192, 0, 980, 629) -y=0, o sea tocando
# el borde de arriba- y TODAS las zonas quedaban desplazadas. Se seguian leyendo
# cartas por casualidad, pero los dorsos caian fuera de sus zonas, asi que no se
# detectaba ningun rival en la mano y la equity no se calculaba nunca. El usuario
# lo vio como "no me salen las probabilidades de ganar".
#
# Medido sobre 687 frames de tres sesiones:
#
#     tema de fondo oscuro (2 sesiones)   proporcion 2.12-2.36   toca el borde  0%
#     tema de fondo claro                 proporcion 1.24-2.12   toca el borde 80%
#
# 2.0 cae en el hueco entre las dos poblaciones. Cuando salta, analyze_layout
# corta el frame con su aviso, que es lo correcto: mejor no decir nada que leer
# el sitio equivocado.
NUCLEO_AR_MIN = 2.0
NUCLEO_MARGEN_BORDE = 3


def _nucleo_plausible(caja, h_img, w_img):
    x, y, w, h = caja
    if h <= 0 or w / h < NUCLEO_AR_MIN:
        return False
    if y <= NUCLEO_MARGEN_BORDE or y + h >= h_img - NUCLEO_MARGEN_BORDE:
        return False
    return True


# Holgura al subir por el ovalo: su borde sale con dientes, asi que se permite
# que una fila sea algo mas ancha que la de debajo sin dar el corte por bueno.
PUENTE_TOL = 1.06
# Ancho minimo, en fraccion del ancho maximo, para seguir considerando que una
# fila es del ovalo. Un ovalo se estrecha hasta CASI CERO en su borde: con este
# valor solo se le recorta el 1% de arriba (para una elipse, el ancho cae al 20%
# cuando ya se esta al 98% del semieje). Un puente, en cambio, sube con ancho
# mas o menos constante y se corta limpio. Hace falta ADEMAS de la regla de "no
# se ensancha", porque un puente de ancho constante nunca la incumple.
PUENTE_ANCHO_MIN_FRAC = 0.20


def _recortar_puente(core, caja):
    """Quita del blob la protuberancia que lo suelda con el borde del frame.

    EL CASO QUE LO MOTIVA. El papel de pared tiene una banda clara arriba que
    pasa el umbral de brillo, y cuando el encuadre deja bastante margen por
    encima de la mesa se une con el ovalo. El resultado es un blob que llega a
    y=0 y con proporcion 1,5 en vez de 2,5, asi que _nucleo_plausible lo rechaza
    -bien rechazado: esa caja desplazaria todas las zonas- y el frame se pierde
    entero. Medido en la sesion 014613: 123 de 123 frames, el 100%.

    COMO SE CORTA. Un ovalo, subiendo desde su fila mas ancha, solo puede
    ESTRECHARSE. Donde deja de cumplirse es donde empieza lo que no es la mesa.
    Se sube desde la fila mas ancha hasta la primera que se ensancha y ahi se
    corta; por abajo no hace falta, porque nada suelda el ovalo hacia abajo.

    SOLO SE LLAMA CUANDO EL BLOB YA ES IMPLAUSIBLE. Esa es la diferencia con los
    seis intentos anteriores de mejorar la deteccion (ver el catalogo de tipos de
    mesa mas arriba y docs 2.0c): todos cambiaban la caja TAMBIEN donde ya
    funcionaba -desvios medianos del 5% al 29%- y eso mueve el mapa de zonas
    entero. Aqui los frames que hoy salen bien ni entran en esta funcion."""
    x, y, w, h = caja
    sub = core[y:y + h, x:x + w] > 0
    if not sub.any():
        return None
    anchos = sub.sum(axis=1)
    y_ancha = int(np.argmax(anchos))
    minimo = PUENTE_ANCHO_MIN_FRAC * anchos[y_ancha]
    arriba = y_ancha
    for i in range(y_ancha - 1, -1, -1):
        if anchos[i] < minimo or anchos[i] > anchos[i + 1] * PUENTE_TOL:
            break
        arriba = i
    if arriba == 0:
        return None                    # no se corto nada: sigue tocando el borde
    filas = sub[arriba:]
    cols = np.flatnonzero(filas.any(axis=0))
    ys = np.flatnonzero(filas.any(axis=1))
    if not len(cols) or not len(ys):
        return None
    return (x + int(cols[0]), y + arriba + int(ys[0]),
            int(cols[-1] - cols[0]) + 1, int(ys[-1] - ys[0]) + 1)


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


def seat_center_px(ref, seat_name, seats=None):
    """Centro (px) de la zona de nameplate de un asiento."""
    fx0, fy0, fx1, fy1 = (seats or SEATS)[seat_name]["plate"]
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    cx = rx + (fx0 + fx1) / 2 * rw
    cy = ry + (fy0 + fy1) / 2 * rh
    return cx, cy


def dealing_order(seat_names, ref, seats=None):
    """Ordena asientos en orden de reparto (horario) por angulo alrededor del
    centro de los asientos, igual criterio que dealer_button.assign_positions
    (atan2 ascendente en coordenadas de imagen coincide con el orden real)."""
    centers = {s: seat_center_px(ref, s, seats) for s in seat_names}
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


def detect_button_seat(bgr, ref, seats=None):
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
    for name, cfg in (seats or SEATS).items():
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


# --- la referencia se FIJA una vez por sesion ---
#
# Idea del usuario: lo que no cambia entre frames se calcula una vez y se da por
# bueno. El tapete no se mueve mientras juegas, asi que recalcular su ovalo en
# cada frame no solo cuesta 29 ms: expone la app a que un frame concreto lo
# detecte mal y TODAS las zonas se corran ese frame.
#
# Y rescata entero el tema de FONDO CLARO. Ahi el ovalo solo se detecta bien en
# el 14% de los frames -en el resto el fondo se le pega y la guarda de forma lo
# rechaza-, pero esas pocas buenas COINCIDEN entre si, asi que basta con fijarla
# una vez. Medido sobre la sesion que lo destapo, 132 frames:
#
#                        por frame   fijada
#     frames analizados      19       132
#     con tus 2 cartas        3        75
#     con rivales en mano    15       114
#     CON EQUITY              0        27
#
# La tolerancia sale de los datos y coincide con la intuicion del usuario de
# dejar un 1-4% de margen: las referencias buenas de una sesion se desvian de la
# fijada un 0-3,8% de mediana y un 1,1-4,5% en el percentil 90. Se deja en 6%
# para no ir justo.
#
# NO es un latch: si la ventana se mueve o se redimensiona, las lecturas nuevas
# discrepan de forma sostenida y se vuelve a fijar. Se exigen varias seguidas
# porque una sola discrepante es ruido -en una sesion llegan al 13,6%- y
# re-fijar con ella seria peor que no fijar nada.
REF_MIN_PARA_FIJAR = 10
REF_TOLERANCIA = 0.06
REF_SEGUIDAS_PARA_REFIJAR = 15

# DESCARTAR EL FRAME es otra decision, y necesita otro umbral. Reutilizar el 6%
# de arriba tiraba el 40% de los frames por puro temblor del detector: son dos
# preguntas distintas -"¿me creo esta lectura para re-fijar?" y "¿esta la mesa
# donde dice?"- y comparten formula pero no umbral.
#
# Medido sobre 1.423 frames de las cinco sesiones del 28-29, el desvio de la
# lectura cruda respecto a la fijada sale con un valle limpio:
#
#     0,000-0,150   1.352 frames   <- el temblor normal de find_reference
#     0,150-0,175       0          <- el valle
#     0,175-0,400      71          <- la mesa tapada, o la ventana movida
#
# Con 0,16 se descarta el 5,0% de los frames, que es la tasa a la que el usuario
# abre paneles encima de la mesa. Y arregla de paso el detector de "es mi turno":
# en la sesion 224318, los frames en la banda dudosa pasan del 49,1% al 0%.
REF_DESCARTE = 0.16


def _desvio_relativo(a, b):
    """Cuanto se separan dos nucleos, en fraccion del fijado."""
    if b[2] <= 0 or b[3] <= 0:
        return 1.0
    return max(abs(a[0] - b[0]) / b[2], abs(a[1] - b[1]) / b[3],
               abs(a[2] - b[2]) / b[2], abs(a[3] - b[3]) / b[3])


class ReferenciaFijada:
    """El nucleo del tapete, calculado al principio y reutilizado.

    Vive fuera de vision/ (lo guarda quien lleva la sesion) porque es estado
    entre frames, igual que PlantillaBoton."""

    def __init__(self):
        self._muestras = []
        self._fija = None
        self._discrepantes = []

    @property
    def fijada(self):
        return self._fija

    def de(self, bgr):
        """Referencia a usar para este frame, y si HAY QUE FIARSE de este frame.

        Devuelve (x, y, w, h, no_fiarse). Mientras no haya suficientes lecturas
        buenas devuelve la del propio frame; despues, la fijada.

        EL QUINTO ELEMENTO ES UNA GUARDA, no un detalle. Antes esta funcion
        devolvia SIEMPRE `fija + (False,)` una vez fijada, o sea "fiate" pasara lo
        que pasara en este frame. Consecuencia, cazada por el usuario revisando el
        frame 0446 de sesion-2026-07-28_210655: abrio el panel de progreso de
        fichas, que TAPA LA MITAD DERECHA de la mesa; el ovalo se detecto en
        825x374 en vez de 1163x491 (un 29% mas pequeño), pero como la referencia
        fijada se devolvia igual, se siguio leyendo cada zona en su sitio de
        siempre. Resultado: un jugador INVENTADO en el asiento UR llamado
        "Ciegas" -una palabra del panel- que corrio el recuento de asientos y con
        el TODAS las posiciones. La app dijo HJ donde no lo era.

        La regla es del usuario y es la correcta: "cuando no veas una mesa en un
        frame, descarta ese frame, siempre y cuando hayas detectado una antes. Si
        ningun frame detecta la mesa, entonces si tendriamos un problema". Aqui se
        implementa el "siempre y cuando": con referencia ya fijada, un frame cuyo
        ovalo no aparece -o aparece donde no toca- se marca para descartar. Sin
        ella no hay nada con que comparar y se sigue como antes.

        Lo que NO cambia: una ventana que se mueve de verdad. Ahi el desvio se
        repite, y a las REF_SEGUIDAS_PARA_REFIJAR se re-fija y se vuelve a
        trabajar. Se pierden esos frames de transicion, que es exactamente lo que
        se quiere: durante la mudanza las zonas no estan donde dicen."""
        cruda = find_reference(bgr)
        if self._fija is None:
            if not cruda[4]:
                self._muestras.append(tuple(int(x) for x in cruda[:4]))
                if len(self._muestras) >= REF_MIN_PARA_FIJAR:
                    a = np.array(self._muestras)
                    self._fija = tuple(int(x) for x in np.median(a, axis=0))
            return cruda

        # QUE NO SE ENCUENTRE EL OVALO NO ES MOTIVO PARA DESCARTAR, y esto se
        # midio antes de decidirlo: pasa en el 26% de los frames, y en casi todos
        # la mesa sigue exactamente donde estaba -es el detector el que tiene un
        # mal momento-. Para eso existe la referencia fijada. Descartarlos dejaria
        # muda una cuarta parte de la sesion sin ninguna razon.
        if cruda[4]:
            return self._fija + (False,)

        c = tuple(int(x) for x in cruda[:4])
        if _desvio_relativo(c, self._fija) <= REF_DESCARTE:
            if _desvio_relativo(c, self._fija) <= REF_TOLERANCIA:
                self._discrepantes = []
            return self._fija + (False,)

        # EL OVALO ESTA, PERO NO DONDE ESTABA. Esa es la señal de verdad: algo lo
        # tapa (el panel de progreso de fichas, el de manos, otra ventana) o la
        # ventana se ha movido. En los dos casos las zonas no estan donde dicen y
        # leerlas produce lecturas de sitios equivocados -en el frame 0446 de
        # sesion-2026-07-28_210655 salio un jugador INVENTADO llamado "Ciegas",
        # que es una palabra del panel, y corrio todas las posiciones-.
        self._discrepantes.append(c)
        if len(self._discrepantes) >= REF_SEGUIDAS_PARA_REFIJAR:
            a = np.array(self._discrepantes)
            self._fija = tuple(int(x) for x in np.median(a, axis=0))
            self._muestras = list(self._discrepantes)
            self._discrepantes = []
            return self._fija + (False,)     # la ventana se movio: re-fijada
        return self._fija + (True,)


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


def button_shape_scores(bgr, ref, seats=None):
    """{asiento: area del mayor objeto AISLADO en su hueco / area del hueco}.
    Publico para poder auditar por que gano un hueco y no otro."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    felt = _color_del_tapete(hsv, ref)
    if felt is None:
        return {name: 0.0 for name in (seats or SEATS)}
    h = hsv[:, :, 0].astype(np.int32)
    s = hsv[:, :, 1].astype(np.int32)
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    area_nucleo = max(1, rw * rh)
    out = {}
    for name, cfg in (seats or SEATS).items():
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


def detect_button_seat_por_forma(bgr, ref, seats=None):
    """El asiento cuyo hueco de boton tiene algo, cuando los demas no tienen
    nada. None si empatan o si no hay nada en ninguno."""
    orden = sorted(button_shape_scores(bgr, ref, seats).items(), key=lambda kv: -kv[1])
    if not orden or orden[0][1] <= 0:
        return None
    if len(orden) > 1 and orden[1][1] > 0 and orden[0][1] < BOTON_FORMA_MARGEN * orden[1][1]:
        return None
    return orden[0][0]


def detect_button_seat_union(bgr, ref, plantilla=None, seats=None):
    """El boton por las tres vias, en orden de precision: color, forma y
    plantilla aprendida. Ninguna contradice a otra -0 desacuerdos en 438 y en
    1.027 comparaciones- asi que encadenarlas solo puede añadir cobertura.

    `plantilla` es un PlantillaBoton que el llamador mantiene entre frames; si no
    se pasa, se usan solo las dos primeras vias. Ademas se le da de comer cada
    respuesta segura, que es como aprende."""
    seat = (detect_button_seat(bgr, ref, seats)
            or detect_button_seat_por_forma(bgr, ref, seats))
    if plantilla is None:
        return seat
    if seat is not None:
        plantilla.aprender(bgr, ref, seat, seats)
        return seat
    return plantilla.buscar(bgr, ref, seats)


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


def _hueco_px(bgr, ref, seat, seats=None):
    rx, ry, rw, rh = ref[0], ref[1], ref[2], ref[3]
    fx, fy = (seats or SEATS)[seat]["button"]
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

    def aprender(self, bgr, ref, seat, seats=None):
        """Guarda el disco de un frame en que ya se sabe donde esta."""
        if seat is None or len(self._discos) >= PLANTILLA_MAX_DISCOS:
            return
        d = self._recortar(bgr, ref, seat, seats)
        if d is None:
            return
        self._discos.append(d)
        if len(self._discos) >= PLANTILLA_MIN_DISCOS:
            # la MEDIANA y no la media: un recorte con una ficha encima no debe
            # arrastrar la plantilla
            self._tpl = np.median(np.array(self._discos), axis=0).astype(np.uint8)

    def _recortar(self, bgr, ref, seat, seats=None):
        puntos = button_shape_scores(bgr, ref, seats)
        if puntos.get(seat, 0) <= 0:
            return None
        x0, y0, x1, y1 = _hueco_px(bgr, ref, seat, seats)
        r = int(PLANTILLA_RADIO_FRAC * ref[2])
        if r < 4:
            return None
        cy, cx = (y0 + y1) // 2, (x0 + x1) // 2
        a, b, c, d = cy - r, cy + r, cx - r, cx + r
        if a < 0 or c < 0 or b > bgr.shape[0] or d > bgr.shape[1]:
            return None
        return cv2.resize(bgr[a:b, c:d], (PLANTILLA_LADO, PLANTILLA_LADO),
                          interpolation=cv2.INTER_AREA)

    def buscar(self, bgr, ref, seats=None):
        """Asiento cuyo hueco se parece mas a la plantilla, o None si ninguno
        llega al minimo o si dos empatan."""
        if self._tpl is None:
            return None
        esc = (2 * int(PLANTILLA_RADIO_FRAC * ref[2])) / PLANTILLA_LADO
        if esc <= 0:
            return None
        tpl = cv2.resize(self._tpl, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA)
        out = []
        for seat in (seats or SEATS):
            x0, y0, x1, y1 = _hueco_px(bgr, ref, seat, seats)
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

CARD_BACK_ZONES_6MAX = {
    "TOPC": (0.39, -0.30, 0.62, -0.14),
    "UL":   (-0.10, -0.10, 0.13, 0.05),
    "UR":   (0.87, -0.10, 1.10, 0.05),
    "ML":   (-0.14, 0.51, 0.10, 0.69),
    "MR":   (0.91, 0.51, 1.15, 0.69),
}

# LAS DE 8 SON DERIVADAS, NO MEDIDAS, y la diferencia importa. Las zonas de
# nameplate y las anclas del boton se sacaron barriendo cientos de frames; estas
# se calculan aplicando al asiento de 8 el desplazamiento que el mismo asiento
# tiene en la mesa de 6. Se puede hacer porque ese desplazamiento es MUY estable:
# en los cuatro laterales de la mesa de 6 el dorso esta exactamente 0,125 por
# encima del centro del nameplate, con un tamaño de 0,23x0,16.
#
# VALIDADAS sobre 229 frames de las dos sesiones de 8, comparando la fraccion de
# dorso en la zona contra la misma zona desplazada (que es tapete):
#
#     TOPC   0,482 contra 0,025    separa
#     ML     0,388 (p90) contra 0  separa
#     MR     0,368 (p90) contra 0  separa
#     UL/UR  0,375-0,441 contra 0,085-0,097   separa, con menos margen
#     DL/DR  0,348-0,388 (p90) contra 0,087-0,126   NO SE PUDO VALIDAR: la zona
#            de control que se eligio para ellas cae sobre las de ML/MR, que
#            tambien tienen dorsos, asi que la comparacion no dice nada.
#
# O sea que DL y DR entran SIN comprobar. Es aceptable porque el fallo degrada
# hacia abajo -en el peor caso esos dos asientos se leen peor de lo que podrian,
# que sigue siendo mejor que no verlos, que es lo que pasa hoy- pero hay que
# medirlas con la primera sesion que se grabe jugando de verdad a 8.
CARD_BACK_ZONES_8MAX = {
    "TOPC": (0.38, -0.41, 0.60, -0.25),
    "UL":   (-0.11, -0.21, 0.12, -0.06),
    "UR":   (0.85, -0.20, 1.08, -0.05),
    "ML":   (-0.23, 0.23, 0.01, 0.41),
    "MR":   (1.00, 0.23, 1.25, 0.41),
    "DL":   (-0.04, 0.66, 0.20, 0.84),
    "DR":   (0.78, 0.66, 1.02, 0.84),
}

# DL y DR SE RE-MIDIERON el 30-07-2026 y se movieron. Entraron derivadas y con
# menos margen que las demas (p90 0,191 y 0,232 contra un umbral de 0,10, cuando
# las de arriba y de los lados andan por 0,29-0,36), y al medir la mesa de 9
# aparecio el mismo sintoma en su DR. Barriendo el entorno sobre 339 frames de la
# sesion del 29-07 a las 20:12:
#
#     DL   p90 0,191  ->  0,341   moviendola (+0,10, -0,06)
#     DR   p90 0,232  ->  0,342   moviendola (-0,10, -0,06)
#
# Los dos se van HACIA DENTRO Y HACIA ARRIBA, y en cantidades simetricas. O sea
# que derivar el desplazamiento del asiento equivalente de la mesa de 6 funciona
# arriba y en los lados y se queda corto ABAJO: ahi el cliente dibuja la carta mas
# pegada al nameplate, seguramente porque no tiene sitio. No esta medido como
# regla -son cuatro asientos entre las dos mesas- pero es suficiente para saber
# que los de abajo hay que comprobarlos uno a uno y no darlos por derivados.

# Derivadas del desplazamiento que cada asiento tiene en la mesa de 6, y luego
# VALIDADAS sobre 381 frames de la sesion del 29-07 a las 23:05. Siete de las
# ocho salieron bien a la primera: bimodales -p50 = 0 cuando no hay cartas- y con
# p90 entre 0,234 y 0,393 contra un umbral de 0,10.
#
# DR NO. Se quedaba en p90 = 0,123, o sea 1,2x el umbral: cualquier variacion la
# pierde. Se barrio su entorno y el gradiente era limpio y monotono hacia arriba
# y a la izquierda, con el optimo en (-0,13, -0,10) del sitio derivado y p90
# 0,369, en linea con las otras siete. Esa es la que esta escrita.
#
# Es lo mismo que ya paso con DL y DR en la mesa de 8, donde entraron con menos
# margen que las demas (1,9x el umbral frente a 2,9x): derivar el desplazamiento
# funciona en los asientos de arriba y de los lados, y se queda corto en los de
# ABAJO. Tiene sentido -ahi la carta se dibuja mas cerca del nameplate porque no
# hay sitio- pero no esta medido como regla, asi que los de abajo hay que
# comprobarlos uno a uno.
CARD_BACK_ZONES_9MAX = {
    "TL":   (0.12, -0.43, 0.36, -0.27),
    "TR":   (0.65, -0.40, 0.88, -0.24),
    "UL":   (-0.23, -0.13, 0.00, 0.02),
    "UR":   (1.00, -0.13, 1.23, 0.02),
    "ML":   (-0.27, 0.30, -0.03, 0.47),
    "MR":   (1.02, 0.29, 1.27, 0.46),
    "DL":   (-0.14, 0.73, 0.10, 0.91),
    "DR":   (0.77, 0.66, 1.02, 0.83),
}

CARD_BACK_ZONES = CARD_BACK_ZONES_6MAX


def card_back_fractions(bgr, ref, dorsos=None):
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
    for name, zona in (dorsos or CARD_BACK_ZONES).items():
        x0, y0, x1, y1 = zone_to_px(ref, zona, bgr.shape)
        sub = mask[y0:y1, x0:x1]
        if sub.size == 0:
            out[name] = 0.0
            continue
        n, _lab, stats, _c = cv2.connectedComponentsWithStats(sub, connectivity=8)
        mayor = max((stats[i, cv2.CC_STAT_AREA] for i in range(1, n)), default=0)
        out[name] = float(mayor) / sub.size
    return out


def detect_in_hand_seats(bgr, ref, dorsos=None):
    """Asientos rivales con cartas repartidas y TAPADAS (dorso visible).

    Solo ve dorsos, asi que por si sola se queda corta en cuanto el cliente gira
    las cartas: para eso esta revealed_pair_seats, y quien quiera saber quien
    esta en la mano tiene que unir las dos (lo hace table_state.analyze_layout)."""
    return {n for n, frac in card_back_fractions(bgr, ref, dorsos).items()
            if frac >= CARD_BACK_MIN_AREA_FRAC}


# --- quien esta en la mano cuando el cliente GIRA las cartas ---
#
# EL CASO QUE SE ESCAPABA. En un all-in el cliente da la vuelta a las manos
# implicadas: los dorsos desaparecen y card_back_fractions deja de ver a
# jugadores que SI estan en la mano. Infravalorar rivales INFLA la equity del
# hero, que es la direccion peligrosa.
#
# Medido en sesion-2026-07-28_012453/0484-0487: arrepia69 iba con A(c) Q(d) por
# delante -el cliente le pintaba "100 %"- y salia como retirado, asi que la
# equity se calculo contra UN rival en vez de dos y dio 12,7% donde la pantalla
# decia 0%. Y en el frame 0234, con TRES jugadores en all-in (71,4 / 12,1 /
# 16,6 %) y el hero todavia por hablar -que es justo cuando el numero importa-,
# se contaron dos.
#
# NO HACE FALTA GEOMETRIA NUEVA, y esa es la parte buena. Medido sobre 91 frames
# de all-in (con el board leido como control del encuadre), las manos reveladas
# caen dentro de las MISMAS zonas donde se buscan los dorsos:
#
#     asiento   centro medido (fx,fy)   centro de CARD_BACK_ZONES
#     TOPC        0.501  -0.234            0.505  -0.22
#     UL          0.016  -0.043            0.015  -0.025
#     UR          0.970  -0.046            0.985  -0.025
#     ML         -0.029   0.540           -0.020   0.60
#     MR          1.001   0.590            1.030   0.60
#
# asi que basta con mirar las mismas cajas con el OTRO detector: donde no hay
# dorso puede haber una mano boca arriba.
#
# El margen no es de cortesia. Las zonas estan calibradas para el BLOB del
# dorso, que asoma por detras del nameplate y es mas pequeño que la carta
# entera; con 0.04 la zona de TOPC cortaba las dos cartas por abajo y
# find_card_boxes devolvia 0 (find_card_boxes recorta a la region, asi que una
# carta a medias fuera pierde alto y no pasa el filtro de tamaño). Con 0.06
# entran. Ensanchar mas no cambia el resultado -probado hasta 0.14- y a 0.06 la
# zona no llega ni al board ni al asiento vecino.
REVELADA_MARGEN = 0.06


def revealed_zone_px(ref, seat, shape, dorsos=None):
    """La zona donde mirar la mano revelada de `seat`, en pixeles.

    Es la del dorso ensanchada con REVELADA_MARGEN. Vive aparte para que el
    margen este en UN sitio: lo usan el detector de aqui y quien luego va a leer
    el rango de esas cartas (table_state), y si se separan se leerian cajas
    distintas de las que se detectaron."""
    x0, y0, x1, y1 = (dorsos or CARD_BACK_ZONES)[seat]
    m = REVELADA_MARGEN
    return zone_to_px(ref, (x0 - m, y0 - m, x1 + m, y1 + m), shape)


def revealed_pair_seats(bgr, ref, dorsos=None):
    """Asientos rivales que enseñan su mano BOCA ARRIBA (all-in o showdown).

    Se exige un PAR y solo un par: una caja suelta es ruido de UI -un icono del
    avatar, una ficha- y tres o mas no es una mano de Hold'em. Medido sobre tres
    sesiones completas (9.865 zonas miradas con la referencia fijada de cada
    sesion, como en vivo): salta en el 2,9% de las zonas de frames con all-in y
    en el 0,2% del resto, y al mirar esas ultimas una a una resultaron ser
    showdowns de verdad, no falsos positivos."""
    return {nombre for nombre in (dorsos or CARD_BACK_ZONES)
            if len(color_card_detector.find_card_boxes(
                bgr, revealed_zone_px(ref, nombre, bgr.shape, dorsos))) == 2}


# --- ¿ES MI TURNO? por pixeles, sin OCR ---
#
# La idea es del usuario: "si hay botones tambien es una buena manera de saber
# que es mi turno". Y es mejor que buena, porque los botones SOLO existen cuando
# le toca al hero, que es exactamente el instante en que la decision importa.
#
# El cliente los pinta como rectangulos ROJOS grandes ("No ir", "Igualar N BB",
# "Subir a N BB"), y el tapete de detras no tiene nada parecido. Medido sobre
# 1.011 frames de sesion-2026-07-28_210655, la fraccion de rojo de la zona sale
# BIMODAL con un valle de tres observaciones en total:
#
#     0,00-0,08   791 frames    <- no es su turno
#     0,08-0,25     3           <- el valle
#     0,25-0,92   217           <- botones en pantalla
#
# LO QUE DESTAPA, y es la razon de que esto exista: de los 216 frames con
# botones, el OCR solo lee `facing` en 89. La app se pierde el 59% de los turnos
# del hero. Y al reves, en 40 frames dice que enfrenta algo sin haber botones.
# El OCR de esa zona es una lectura cara y poco fiable para una pregunta que se
# responde mirando el color.
#
# Coste: 0,26 ms. Cabe en el lazo rapido de 0,1 s sin despeinarse.
#
# OJO: esto depende de que la referencia sea buena. Con la mesa tapada la zona
# cae desplazada y el valor se queda a medias -es lo que pasaba en la sesion
# 224318, con el 49% de los frames en el valle-, asi que hay que llamarlo solo
# con una referencia en la que se confie (ver ReferenciaFijada.de).
BOTONES_ROJO_MIN = 0.15         # en el valle, mas cerca del lado vacio: un falso
                                # positivo cuesta un analisis de mas, y un falso
                                # negativo cuesta la decision entera


def hay_botones(bgr, ref):
    """True si el cliente esta mostrando los botones de accion, o sea si es el
    turno del hero. Sin OCR."""
    x0, y0, x1, y1 = zone_to_px(ref, ACTION_ZONE, bgr.shape)
    z = bgr[y0:y1, x0:x1]
    if z.size == 0:
        return False
    hsv = cv2.cvtColor(z, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.int32)
    s = hsv[:, :, 1].astype(np.int32)
    v = hsv[:, :, 2].astype(np.int32)
    rojo = ((h <= 8) | (h >= 172)) & (s > 120) & (v > 80)
    return float(rojo.mean()) >= BOTONES_ROJO_MIN


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
#
# LIMITACION CONOCIDA, medida y deliberadamente no arreglada: cuando el cliente
# PARTE el bote (all-in), los trozos se dibujan debajo del board y uno puede caer
# dentro de la zona de apuesta de un asiento. Pasa de verdad: en
# sesion-2026-07-28_012453/0484-0488, ML aparece con bet=29,6 que no es su
# apuesta sino el trozo izquierdo del bote (el bote entero valia 29,6 en el frame
# 0480 y al partirse en 0484 reaparece ahi).
#
# NO SE PUEDE SEPARAR POR GEOMETRIA. Los trozos de bote se reparten segun cuantos
# haya: medidos, caen en fx 0,225..0,762 y fy 0,59..0,69, justo por encima de las
# apuestas reales de ML/MR (fx 0,162..0,229 y 0,742..0,816, fy 0,61..0,72). Las
# dos poblaciones se tocan.
#
# Y NO HACE FALTA. El bote solo se parte cuando la ronda de apuestas esta CERRADA,
# y entonces el hero no tiene que hablar. Comprobado sobre el corpus: de 80 frames
# CON recomendacion, en 0 estaba el bote partido en pantalla; y de las 1.721
# recomendaciones que ha dado la app, 0 tenian board -decide() se abstiene
# postflop-. O sea que el fantasma ensucia player["bet"] en frames de showdown,
# donde el motor ya esta callado, y no llega nunca a una decision.
SEAT_BET_ZONES_6MAX = {
    "TOPC": (0.48, -0.02, 0.72, 0.14),
    "UL":   (0.12, 0.16, 0.36, 0.34),
    "UR":   (0.62, 0.12, 0.88, 0.30),
    "ML":   (0.10, 0.58, 0.30, 0.76),
    "MR":   (0.70, 0.58, 0.86, 0.76),
    "HERO": (0.30, 0.68, 0.58, 0.87),
}

# DERIVADAS igual que las de dorso, y con menos fundamento todavia: el
# desplazamiento de la zona de apuesta respecto al nameplate NO es tan estable
# como el del dorso -va de (+0,19,+0,15) en UL a (-0,20,-0,06) en MR- porque
# apunta al centro del tapete y cada asiento lo tiene en otra direccion. Se
# aplica el del asiento de angulo mas parecido.
#
# ENTRAN SIN VALIDAR, y se puede asumir por como se usan: el importe leido aqui
# NUNCA crea una subida, solo ATRIBUYE una que el boton "Igualar" ya ha
# demostrado que existe (ver decision/engine). Una zona mal puesta hace que no se
# atribuya, no que se invente. Ademas esta zona ya arrastra una limitacion
# medida y aceptada -los botes partidos la contaminan- asi que no es la señal
# de la que cuelga nada critico.
SEAT_BET_ZONES_8MAX = {
    "TOPC": (0.46, -0.13, 0.70, 0.03),
    "UL":   (0.11, 0.05, 0.35, 0.23),
    "UR":   (0.60, 0.02, 0.86, 0.20),
    "ML":   (0.02, 0.40, 0.22, 0.58),
    "MR":   (0.79, 0.38, 0.95, 0.56),
    "DL":   (0.10, 0.79, 0.30, 0.96),
    "DR":   (0.67, 0.79, 0.83, 0.97),
    "HERO": (0.24, 0.80, 0.53, 0.99),
}

SEAT_BET_ZONES_9MAX = {
    "TL":   (0.24, -0.13, 0.48, 0.03),
    "TR":   (0.52, -0.10, 0.76, 0.06),
    "UL":   (-0.01, 0.13, 0.23, 0.31),
    "UR":   (0.75, 0.09, 1.01, 0.27),
    "ML":   (-0.02, 0.44, 0.18, 0.62),
    "MR":   (0.81, 0.43, 0.97, 0.61),
    "DL":   (0.10, 0.80, 0.30, 0.98),
    "DR":   (0.69, 0.82, 0.85, 1.00),
    "HERO": (0.26, 0.83, 0.54, 1.02),
}

SEAT_BET_ZONES = SEAT_BET_ZONES_6MAX

# Las tres tablas por asiento van juntas: pedir una disposicion tiene que dar las
# TRES coherentes, o se leerian nameplates de una mesa y dorsos de otra.
ZONAS_POR_DISPOSICION = {
    6: {"seats": SEATS_6MAX, "dorsos": CARD_BACK_ZONES_6MAX,
        "apuestas": SEAT_BET_ZONES_6MAX},
    8: {"seats": SEATS_8MAX, "dorsos": CARD_BACK_ZONES_8MAX,
        "apuestas": SEAT_BET_ZONES_8MAX},
    9: {"seats": SEATS_9MAX, "dorsos": CARD_BACK_ZONES_9MAX,
        "apuestas": SEAT_BET_ZONES_9MAX},
}


def zonas(max_players=None):
    """Las tres tablas por asiento de una disposicion. Ver disposicion()."""
    return ZONAS_POR_DISPOSICION.get(max_players, ZONAS_POR_DISPOSICION[6])

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
