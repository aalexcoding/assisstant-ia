"""Leer el RANGO deslizando las plantillas sobre la zona, sin buscar la carta.

La cadena normal tiene cinco eslabones en serie -tapete, zona, segmentar la
carta, aislar el glifo, leerlo- y basta que uno falle para perder la carta. Las
del hero fallan en 'segmentar': salen CORTADAS por su propio nameplate, asi que
la caja de la carta no existe como tal y todo lo que viene despues se queda sin
entrada.

Aqui no hace falta encontrar la carta. Se desliza cada plantilla de rango sobre
la mascara de la zona entera; donde hay un pico, hay un rango. Si se ve el
numero, se lee.

Es un CAMINO PARALELO, no un reemplazo. En la zona del hero, medido sobre los
mismos 300 frames de sesion-2026-07-27_163519,

    pipeline actual        167 frames con las 2 cartas
    este modelo            178
    los dos en union       179          0 contradicciones entre los dos

Cableado de verdad en table_state la union da 177 y no 179, porque ahi este
camino solo entra cuando el otro falla y ademas EscalaGlifo necesita sus
primeros frames para fijar el tamaño. Los 177 son el numero de produccion; los
179 son el techo del modelo medido aparte.

Se queda de segundo camino y no de primero aunque lea mas, porque el pipeline
normal trae ademas el 'dimmed' -si el hero ya se retiro de la mano- y las cajas
de las cartas, que este no puede dar.

EN EL BOARD NO SE USA, y se probo. Alli las cartas no las corta nada, asi que la
cadena normal no tiene el problema que este modulo resuelve:

    pipeline actual        132 boards legales de 300 frames
    este modelo              8
    los dos en union       135          3 CONTRADICCIONES de 147

Tres de mas por tres frames de mas no es un cambio, es ruido con riesgo: las tres
son un 'Jh' que no esta en la mesa (0124, 0199 y 0282 de la sesion de arriba). En
la zona del hero la misma medida da cero contradicciones, y la diferencia es que
alli solo puede haber DOS cartas y aqui cinco, asi que no hay invariante barato
que filtre la de mas.
"""
import cv2
import numpy as np

from vision import color_card_detector as ccd
from vision import color_rank_ocr as cro

# Correlacion minima para aceptar un pico como rango. OJO: NO es la misma
# magnitud que cro.GLIFO_UMBRAL, y por eso no se puede heredar su 0.95. Alli se
# compara un glifo YA AISLADO contra la plantilla y la cifra es "que fraccion se
# calca". Aqui es TM_CCOEFF_NORMED de la plantilla contra una mascara que lleva
# dentro todo lo demas -el nameplate, las fichas, el borde de la carta-, asi que
# el techo alcanzable es mas bajo.
#
# El umbral NO esta puesto a ojo: sale de barrer 300 frames y mirar donde se
# rompe el invariante duro de que el hero solo puede tener DOS cartas.
#
#     umbral   frames con 2 cartas   frames con MAS DE 2 (imposible)
#      0.50            32                       147
#      0.55            48                       130
#      0.60           110                        68
#      0.64           142                        36
#      0.66           178                         0
#      0.68           178                         0
#      0.70           172                         0
#
# El acantilado esta entre 0.64 y 0.66. Se coge 0.68 porque da el maximo de
# lecturas y a la vez deja 4 puntos de margen por encima de la rotura, en vez de
# quedarse pegado al borde.
MIN_PICO = 0.68
# Dos picos mas cerca que esto -en fraccion del tamaño de la plantilla- son el
# mismo glifo visto por dos plantillas parecidas, y se queda el de mas pico.
SOLAPE_MIN_FRAC = 0.6
# Suelo para creerse el palo. La ventana que se mira a la derecha del numero
# tiene del orden de 1500 pixeles, asi que esto no es un umbral fino sino un
# "hay carta ahi": con menos de esto lo que hay al lado del numero es tapete o
# nameplate y la respuesta honesta es no decir el palo.
PALO_MIN_PIXELES = 40

_ATLAS = None


def _atlas():
    """Plantillas recortadas a su tinta, una por rango. Se carga una vez: leer el
    png en cada frame costaba mas que la propia correlacion."""
    global _ATLAS
    if _ATLAS is None:
        img = cv2.imread(cro.GLIFOS_FICHERO, cv2.IMREAD_GRAYSCALE)
        out = []
        if img is not None:
            L = cro.GLIFO_LADO
            for i, r in enumerate(cro.GLIFOS_ETIQUETAS):
                t = img[:, i * L:(i + 1) * L]
                ys, xs = np.where(t > 127)
                if len(xs):
                    out.append((r, t[ys.min():ys.max() + 1, xs.min():xs.max() + 1]))
        _ATLAS = tuple(out)
    return _ATLAS


def mascara_zona(bgr):
    """Tinta blanca que esta SOBRE UNA CARTA.

    El blanco solo no vale: la zona del hero incluye su nameplate, y el
    "Tiempo 25 seg" de dentro es tan blanco como el rango. Lo que distingue al
    rango es que su alrededor es cuerpo de carta -uno de los cuatro colores de
    palo- mientras que el texto del plate esta sobre gris oscuro.

    ADEMAS ES LO QUE DEJA FUERA LAS CARTAS APAGADAS, y eso importa: apagada
    significa que el hero ya se retiro de la mano. Pedir V > WHITE_MIN_VALUE
    (170) las descarta sin necesidad de una comprobacion aparte, porque la cara
    apagada cae a V=77 (medido en glyph_card_detector). Comprobado sobre los 37
    frames con las cartas apagadas de las ocho sesiones grabadas: en los 37 este
    camino no lee NADA.

    Aflojar ese valor haria que la app recomendase sobre manos abandonadas; hay
    un caso de regresion para ello en test_rango_directo."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    blanco = (S < cro.WHITE_MAX_SATURATION) & (V > cro.WHITE_MIN_VALUE)
    cuerpo = np.zeros(H.shape, bool)
    for perfiles in ccd.SUIT_HSV_PROFILES.values():
        for hlo, hhi, slo, shi, vlo, vhi in perfiles:
            tono = ((H >= hlo) | (H <= hhi)) if hlo > hhi else ((H >= hlo) & (H <= hhi))
            cuerpo |= tono & (S >= slo) & (S <= shi) & (V >= vlo) & (V <= vhi)
    cerca = cv2.dilate(cuerpo.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    return (blanco & cerca).astype(np.uint8) * 255


def _palo_a_la_derecha(bgr, x, y, w, h):
    """Palo por el color JUSTO A LA DERECHA del numero.

    En esta baraja el rango va arriba a la izquierda de la carta y el pip a su
    derecha, los dos DENTRO DE LA MISMA CARTA. Mirar ahi es lo unico que no se
    contagia de la carta vecina.

    Se probo antes partir la franja de cartas por la mitad y quedarse con el
    color dominante de cada lado. Falla porque las dos cartas del hero se
    solapan -se tocan justo entre el pip de la izquierda y el numero de la
    derecha-, asi que el color de la primera gana en los dos lados: 50
    contradicciones de 89 lecturas, todas del tipo 'Kh 5s' leido 'Kh 5h'."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    y0, y1 = max(0, y - h // 6), min(bgr.shape[0], y + h + h // 6)
    x0, x1 = min(bgr.shape[1] - 1, x + w), min(bgr.shape[1], x + w + int(1.2 * w))
    hh, ss, vv = H[y0:y1, x0:x1], S[y0:y1, x0:x1], V[y0:y1, x0:x1]
    blanco = (ss < cro.WHITE_MAX_SATURATION) & (vv > cro.WHITE_MIN_VALUE)
    mejor, votos = None, 0
    for suit, perfiles in ccd.SUIT_HSV_PROFILES.items():
        m = np.zeros(hh.shape, bool)
        for hlo, hhi, slo, shi, vlo, vhi in perfiles:
            tono = ((hh >= hlo) | (hh <= hhi)) if hlo > hhi else ((hh >= hlo) & (hh <= hhi))
            m |= tono & (ss >= slo) & (ss <= shi) & (vv >= vlo) & (vv <= vhi)
        n = int((m & ~blanco).sum())
        if n > votos:
            mejor, votos = suit, n
    return mejor if votos > PALO_MIN_PIXELES else None


def buscar_escala(bgr, altos=range(20, 62, 2)):
    """Alto de glifo en pixeles que hace picar mas a las plantillas, o None.

    Se llama unas pocas veces al empezar la sesion y luego se fija: el tamaño de
    la mesa no cambia mientras la ventana no cambie. Barrer 21 escalas en cada
    frame costaria 21 veces lo que cuesta leer."""
    atlas = _atlas()
    if not atlas:
        return None
    mask = mascara_zona(bgr)
    if (mask > 0).sum() < 100:
        return None
    mejor = (0.0, None)
    for alto in altos:
        pico = 0.0
        for _r, t in atlas:
            e = alto / t.shape[0]
            tw, th = max(4, int(t.shape[1] * e)), max(4, int(t.shape[0] * e))
            if mask.shape[0] < th or mask.shape[1] < tw:
                continue
            tt = cv2.resize(t, (tw, th), interpolation=cv2.INTER_AREA)
            pico = max(pico, float(cv2.matchTemplate(mask, tt, cv2.TM_CCOEFF_NORMED).max()))
        if pico > mejor[0]:
            mejor = (pico, alto)
    return mejor[1] if mejor[0] >= 0.85 else None


class EscalaGlifo:
    """El alto del glifo de la sesion, buscado una vez y reutilizado.

    Vive fuera de vision/ -lo guarda quien lleva la sesion- igual que
    PlantillaBoton y ReferenciaFijada: vision/ es puro por frame.

    Es literalmente lo que pidio el usuario: "si necesitas hacer calculos en
    cada frame repetitivos, guardalos con el primero e intenta darlos por
    validos". Barrer las 21 escalas cuesta 21 veces lo que cuesta leer, y el
    tamaño de la mesa no cambia mientras no cambie la ventana.

    Se exige que MUESTRAS_PARA_FIJAR frames independientes coincidan antes de
    fijar, porque un frame de animacion de reparto puede dar una escala rara."""

    MUESTRAS_PARA_FIJAR = 3

    def __init__(self):
        self._muestras = []
        self._fija = None

    @property
    def fijada(self):
        return self._fija

    def de(self, bgr):
        """Alto de glifo a usar para este frame, o None si aun no se sabe."""
        if self._fija is not None:
            return self._fija
        alto = buscar_escala(bgr)
        if alto is not None:
            self._muestras.append(alto)
            if len(self._muestras) >= self.MUESTRAS_PARA_FIJAR:
                self._fija = int(np.median(self._muestras))
        return self._fija


def leer_zona(bgr, alto_glifo):
    """[(x, rango, palo, pico)] de todos los rangos que se vean, de izquierda a
    derecha. `alto_glifo` sale de buscar_escala(), no de haber encontrado una
    carta."""
    atlas = _atlas()
    if not atlas or not alto_glifo:
        return []
    mask = mascara_zona(bgr)
    picos = []
    for r, t in atlas:
        e = alto_glifo / t.shape[0]
        tw, th = max(4, int(t.shape[1] * e)), max(4, int(t.shape[0] * e))
        if mask.shape[0] < th or mask.shape[1] < tw:
            continue
        tt = cv2.resize(t, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(mask, tt, cv2.TM_CCOEFF_NORMED)
        for y, x in zip(*np.where(res >= MIN_PICO)):
            picos.append((float(res[y, x]), int(x), int(y), r, tw, th))
    picos.sort(reverse=True)
    elegidos = []
    for pico, x, y, r, tw, th in picos:      # el pico mas alto se queda el sitio
        if any(abs(x - ox) < SOLAPE_MIN_FRAC * tw and abs(y - oy) < SOLAPE_MIN_FRAC * th
               for _p, ox, oy, _r, _w, _h in elegidos):
            continue
        elegidos.append((pico, x, y, r, tw, th))
    cartas = []
    for pico, x, y, r, tw, th in sorted(elegidos, key=lambda t: t[1]):
        palo = _palo_a_la_derecha(bgr, x, y, tw, th)
        if palo:
            cartas.append((x, r, palo, pico))
    return cartas
