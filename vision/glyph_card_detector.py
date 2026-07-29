"""
Deteccion de cartas para el mazo de 4 colores con CARA BLANCA y el palo en el
color del GLIFO, que es el que quedo configurado el 26-07-2026. El otro mazo de
4 colores -cara pintada del color del palo y rango en blanco- lo sigue cubriendo
color_card_detector.py; los dos conviven y table_state elige solo.

POR QUE HIZO FALTA OTRO MODULO. color_card_detector resuelve el palo por el
color del FONDO de la carta. Este mazo pinta el fondo blanco (o gris si ya no
estas en la mano) y colorea la tinta, asi que esa señal no existe: sobre la
sesion del 26-07 a las 18:31, el detector viejo pasa de 221 cajas en 65 frames
a 5, y las 5 son fichas azules. Cero cartas leidas en 267 frames.

    disposicion de la carta: rango pequeño en la esquina, rango grande, y el
    pip, LOS TRES del color del palo (confirmado por el usuario). Con tres
    componentes de tinta por carta sobra material para votar el color.

COLOR DE LA TINTA, medido sobre 40 cartas de board etiquetadas a mano (mediana
del interior de cada carta, HSV de OpenCV). Los colores son PLANOS -p10 = p50 =
p90 en cada carta-, porque el cliente los renderiza vectoriales:

    ♥ H=0    S=233  V=206      ♦ H=118  S=224  V=163
    ♣ H=65   S=219  V=123      ♠ tinta negra: S=0, V=1

El tapete verde es lo unico que se le podria parecer al trebol, y no llega:
H=44 con S=97 de mediana (p99 = 100). Exigir S>=110 para el voto de color lo
deja fuera entero, y ademas el tono esta a 21 grados del trebol. Con eso los
palos salen 40/40 en las 40 cartas etiquetadas.

SEGMENTAR CARTAS PEGADAS. Las caras blancas de cartas contiguas se funden en un
solo contorno (el board sale como 1 caja de 87px + 1 de 367px, no como 5), asi
que no vale con los contornos: hay que cortar. Se corta por el perfil de
columnas DENTRO DE LA BANDA DE FILAS de las cartas, no dentro del contorno: el
contorno se funde tambien con las fichas de abajo y entonces el umbral de corte
se calcula sobre un alto inflado y parte las cartas por la mitad. Con la banda,
las 10 imagenes etiquetadas dan el numero exacto de cartas (anchos 83-90 px) y
la unica caja de mas -59 px- es una carta a medio tirar, que el ancho minimo
descarta.

CARTA OSCURECIDA = EL HERO YA NO ESTA EN LA MANO. El cliente apaga tus cartas
cuando te retiras y las deja visibles para que sigas la jugada; el usuario lo
confirmo explicitamente ("no tienes que pensar que estoy en el juego"). La cara
pasa de V=255 a V=77, medido identico en los 3 frames revisados, asi que el
margen es enorme y la señal es fiable. Son el 21% de los frames de la sesion:
ignorarlos dejaria a la app ciega uno de cada cinco frames, y tratarlos como
mano viva seria peor todavia -recomendar una jugada en una mano ya abandonada-,
asi que se detectan y se marcan con dimmed=True.
"""
import cv2
import numpy as np

# --- cara de la carta -------------------------------------------------------
# Poco saturada y no oscura. El limite de brillo baja hasta 60 para recoger la
# cara apagada (V=77); por debajo empieza el nameplate, que es casi negro.
CARA_S_MAX = 70
CARA_V_MIN = 60

# Cara viva (255) frente a cara apagada (77). El corte va a mitad de camino: no
# hay nada medido entre medias.
CARA_V_VIVA = 160

# --- geometria --------------------------------------------------------------
# Una carta del board mide 87x121 y una del hero 87x73, porque al hero se le
# tapa la mitad de abajo con su propio nameplate: la proporcion alto/ancho va de
# 0.84 a 1.39 y el rango tiene que cubrir las dos.
BANDA_FRAC = 0.35     # fila de la banda: >= esta fraccion del maximo de filas
SEP_FRAC = 0.12       # columna separadora: casi ningun pixel de cara
MIN_W, MIN_H = 55, 60
AR_MIN, AR_MAX = 0.72, 1.90

# --- voto de palo -----------------------------------------------------------
COLOR_S_MIN = 110     # deja fuera el tapete (S=97 de mediana, p99=100)
NEGRO_V_MAX = 110
TINTA_MIN_PX = 60
MARGEN_TINTA = 0.10   # se descarta el borde: trae tapete y la carta de al lado
VENTAJA_MIN = 2.0     # el palo ganador tiene que doblar al segundo

# El palo se vota SOLO en el INDICE de la carta -la esquina de arriba a la
# izquierda, donde van el rango pequeño y el pip pequeño-, no en la carta
# entera.
#
# POR QUE. El mazo trae FIGURAS ILUSTRADAS: la J, la Q y la K no son un glifo
# sobre blanco sino un dibujo a todo color. Esa ilustracion es tinta, y entra en
# el voto. Medido en el board 10♥ 9♣ 2♥ Q♦ 8♦ (sesion del 29-07 a las 07:04,
# frame 275), votando sobre la carta entera:
#
#     10♥  heart 1903  segundo    0     ratio 1903    ok
#     9♣   club  1682  segundo    0     ratio 1682    ok
#     2♥   heart  729  segundo    0     ratio  729    ok
#     Q♦   diam   899  spade    452     ratio 1.99    None  <- pierde por 0,01
#     8♦   diam  1648  segundo    0     ratio 1648    ok
#
# Los 452 votos de picas son los trazos oscuros del vestido de la dama. La carta
# no se lee mal: se DESCARTA ENTERA, porque find_card_boxes tira la caja cuando
# el palo no es concluyente. Por eso la J/Q/K eran el 3,6% de las cartas de
# board de esa sesion cuando en un mazo justo son el 23%.
#
# NO se baja VENTAJA_MIN, que seria colar a la dama por los pelos y debilitar de
# paso las otras 51 cartas. Se quita el estorbo: en el indice hay rango y pip,
# los dos del color del palo, y no hay ilustracion. La misma dama pasa a ganar
# por 11x.
#
# MEDIDO sobre 5.571 frames de las 6 sesiones grabadas, comparando carta entera
# contra este indice:
#
#                                cartas encontradas   frames con recuento ilegal
#     sesion del mazo nuevo         1.557 -> 1.750            67 -> 0
#     las 5 del mazo solido         1.096 ->    33           663 -> 32
#
# El segundo bloque tambien es ganancia, aunque parezca perdida: en esas
# sesiones el mazo es el otro, asi que esas 1.096 cajas eran ruido -663 de ellas
# daban un board de tamaño imposible- y _cajas_de_carta se queda con EL QUE MAS
# ENCUENTRA, o sea que ese ruido podia tapar la lectura buena del otro detector.
#
# Y no cambia ningun palo ya resuelto: de 1.033 cartas que los dos criterios
# resuelven, coinciden en 1.028; las 5 discrepancias son cajas basura de
# sesiones del mazo solido. En la sesion del mazo nuevo: 757 iguales, 103
# rescatadas, 0 discrepancias.
#
# EL INDICE SE MIDE CONTRA EL ANCHO DE LA CARTA, NO CONTRA SU ALTO, y esto no es
# un detalle: a las cartas del hero el cliente les tapa la mitad de abajo con su
# propio nameplate, asi que miden 87x73 en vez de 87x122. El indice sigue estando
# entero -lo que se recorta es el borde de abajo, no la esquina de arriba- y
# sigue midiendo 40 px, pero como fraccion del alto VISIBLE pasaria de 0,33 a
# 0,55. Con la regla por alto, el indice del hero encogeria a 24 px y se quedaria
# por debajo de TINTA_MIN_PX: la app dejaria de leer TUS PROPIAS CARTAS, que es
# la lectura de la que depende todo lo demas. El ancho no lo recorta nadie.
#
#     medido en el board (carta de 87x122): indice de 28 x 40 px
#     = 0,32 del ancho x 0,33 del alto  = 0,32 del ancho x 0,46 del ancho
INDICE_ANCHO_FRAC = 0.32
INDICE_ALTO_FRAC = 0.46   # tambien del ANCHO; ver arriba

HUE = {
    "heart": (0, 12, 168, 180),      # rojo, a caballo del origen del tono
    "club": (50, 88, None, None),    # verde
    "diamond": (100, 135, None, None),  # azul
}


def _cara(hsv):
    s, v = hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    return (s < CARA_S_MAX) & (v > CARA_V_MIN)


def _banda_de_filas(cara):
    """Tramo de filas con mas pixeles de cara (la altura de las cartas). None si
    no hay nada. Se busca el tramo contiguo MAS LARGO por encima del umbral, no
    el primero: en la zona del hero el texto blanco del nameplate tambien pasa
    el filtro de cara y formaria una banda propia, mas corta."""
    filas = cara.sum(axis=1)
    if not filas.max():
        return None
    umbral = BANDA_FRAC * filas.max()
    mejor, i = (0, 0), 0
    while i < len(filas):
        if filas[i] >= umbral:
            j = i
            while j < len(filas) and filas[j] >= umbral:
                j += 1
            if j - i > mejor[1] - mejor[0]:
                mejor = (i, j)
            i = j
        else:
            i += 1
    return mejor if mejor[1] > mejor[0] else None


def _tramos_de_columnas(cara_banda):
    """Tramos horizontales separados por columnas sin cara: una carta cada uno."""
    alto = cara_banda.shape[0]
    perfil = cara_banda.sum(axis=0)
    sep = perfil < SEP_FRAC * alto
    out, i = [], 0
    while i < len(sep):
        if sep[i]:
            i += 1
            continue
        j = i
        while j < len(sep) and not sep[j]:
            j += 1
        out.append((i, j))
        i = j
    return out


def suit_votes(hsv_card, cara_card):
    """Pixeles de tinta a favor de cada palo. Publico para poder auditar por que
    una carta salio de un palo y no de otro."""
    tinta = ~cara_card
    h = hsv_card[:, :, 0].astype(int)[tinta]
    s = hsv_card[:, :, 1].astype(int)[tinta]
    v = hsv_card[:, :, 2].astype(int)[tinta]
    color = s >= COLOR_S_MIN
    votos = {"spade": int(((~color) & (v < NEGRO_V_MAX)).sum())}
    for palo, (lo, hi, lo2, hi2) in HUE.items():
        m = (h >= lo) & (h <= hi)
        if lo2 is not None:
            m |= (h >= lo2) & (h <= hi2)
        votos[palo] = int((color & m).sum())
    return votos


def _palo(hsv_card, cara_card):
    """Palo de una carta, o None si la tinta no es concluyente.

    Solo mira el INDICE de la esquina de arriba a la izquierda; ver
    INDICE_ANCHO_FRAC para el porque y la medicion."""
    alto, ancho = cara_card.shape
    alto = max(1, min(alto, int(ancho * INDICE_ALTO_FRAC)))
    ancho = max(1, int(ancho * INDICE_ANCHO_FRAC))
    hsv_card, cara_card = hsv_card[:alto, :ancho], cara_card[:alto, :ancho]
    dy, dx = int(alto * MARGEN_TINTA), int(ancho * MARGEN_TINTA)
    if alto - 2 * dy <= 0 or ancho - 2 * dx <= 0:
        return None
    r = (slice(dy, alto - dy), slice(dx, ancho - dx))
    votos = suit_votes(hsv_card[r], cara_card[r])
    orden = sorted(votos.values(), reverse=True)
    if orden[0] < TINTA_MIN_PX or orden[0] < VENTAJA_MIN * orden[1]:
        return None
    return max(votos, key=votos.get)


def _partir(tramos, alto, esperadas):
    """Reparte el bloque mas ancho en `esperadas` cartas cuando salieron pegadas.

    POR QUE HACE FALTA. El corte por perfil de columnas necesita que entre dos
    cartas haya un hueco, y las DOS CARTAS DEL HERO se dibujan sin el: en la
    sesion del 26-07 a las 23:28 salian como un solo bloque de 174x73 -relacion
    0,42, que el filtro de forma tira entero- y el hero se quedaba sin cartas en
    172 de 174 frames. Las del board si tienen hueco y se siguen separando solas,
    asi que esto NO se aplica cuando no se sabe cuantas cartas hay.

    POR QUE NO SE BUSCA LA COSTURA. El valle central existe pero no distingue:
    mide el 33-39% de la altura de la banda y los huecos que dejan los propios
    glifos llegan al 23-34%. Mirar solo las filas de arriba -donde no hay glifo,
    asi que la unica muesca posible seria la de dos esquinas redondeadas juntas-
    tampoco vale: en un frame daba 0 muescas y en una carta suelta del board
    daba 6.

    LO QUE SI ES FIRME es cuantas cartas hay: la mano del hero son DOS, siempre,
    por las reglas del juego. Con eso el reparto es aritmetica y no adivinanza.

    Se reparte SOLO el tramo mas ancho, y se tiran los demas. Los otros tramos de
    esa banda son ruido -un trozo de ficha, el disco del boton-, y dejarlos
    pasar era peor que el bug: en un frame real un resto de 43 px con forma
    valida de carta se colaba como tercera carta del hero."""
    if not esperadas or not tramos:
        return tramos
    validos = [t for t in tramos if AR_MIN <= alto / (t[1] - t[0]) <= AR_MAX]
    if len(validos) == esperadas:
        return validos
    a, z = max(tramos, key=lambda t: t[1] - t[0])
    w = z - a
    if alto / w >= AR_MIN:
        return tramos                      # no es un bloque pegado: no hay nada que repartir
    paso = w / esperadas
    trozos = [(a + int(i * paso), a + int((i + 1) * paso)) for i in range(esperadas)]
    if all(AR_MIN <= alto / (t[1] - t[0]) <= AR_MAX for t in trozos):
        return trozos
    return tramos


def find_card_boxes(bgr, region=None, esperadas=None):
    """[{x, y, w, h, suit, dimmed}] en coordenadas absolutas, ordenadas por x.

    Mismo contrato que color_card_detector.find_card_boxes mas dos campos:
    `dimmed` (la carta esta apagada, o sea el hero ya no juega esta mano) y
    `deck`, que le dice a color_rank_ocr con que polaridad leer el rango.

    `esperadas` es cuantas cartas tiene que haber en la zona cuando se sabe por
    las reglas del juego (la mano del hero son 2). Solo se usa para repartir un
    bloque de cartas pegadas sin hueco entre ellas; ver _partir."""
    if region is None:
        rx0, ry0, rx1, ry1 = 0, 0, bgr.shape[1], bgr.shape[0]
    else:
        rx0, ry0, rx1, ry1 = region
    sub = bgr[ry0:ry1, rx0:rx1]
    if sub.size == 0:
        return []
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    cara = _cara(hsv)
    banda = _banda_de_filas(cara)
    if banda is None:
        return []
    y0, y1 = banda
    alto = y1 - y0
    if alto < MIN_H:
        return []
    out = []
    for a, z in _partir(_tramos_de_columnas(cara[y0:y1]), alto, esperadas):
        ancho = z - a
        if ancho < MIN_W or not (AR_MIN <= alto / ancho <= AR_MAX):
            continue
        hc, cc = hsv[y0:y1, a:z], cara[y0:y1, a:z]
        palo = _palo(hc, cc)
        if palo is None:
            continue
        v_cara = hc[:, :, 2][cc]
        out.append({
            "x": rx0 + a, "y": ry0 + y0, "w": ancho, "h": alto, "suit": palo,
            "dimmed": bool(v_cara.size and np.median(v_cara) < CARA_V_VIVA),
            "deck": "glyph",
        })
    return sorted(out, key=lambda b: b["x"])
