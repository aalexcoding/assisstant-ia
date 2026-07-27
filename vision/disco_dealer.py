"""Encontrar el disco del dealer BARRIENDO la mesa, no mirando seis sitios fijos.

La idea es del usuario: "parece que el boton del dealer va moviendose por la mesa
y nunca es fijo, hay que montar un sistema que mapee la mesa buscando el boton
basandose en una version sample en codigo... y la menor distancia a un jugador
determina que ese es el que tiene el boton asignado".

POR QUE HACIA FALTA. Hoy el disco solo se busca EN LAS SEIS ANCLAS de seat_map, y
eso falla de dos maneras: si el cliente lo dibuja unos pixeles fuera del ancla no
se ve, y la plantilla que se aprende en sesion (PlantillaBoton) solo puede
aprenderse de frames donde la deteccion por ancla YA funciono, asi que en una
mesa donde nunca acierta no aprende nunca. Medido sobre la mesa naranja
(sesion 230132, 267 frames):

    boton detectado por color          115 / 267
    boton detectado por forma          126 / 267
    boton detectado (union)            132 / 267   <- la mitad de los frames
    y de los que detecta, la ciega grande NO cuadra 17 veces contra 14

En la mesa verde de la misma noche esas mismas cifras eran 76% y 91%. O sea que
no es ruido: es que el ancla no vale para todas las mesas.

QUE SE USA COMO PLANTILLA. La PICA CON LA ESTRELLA, en binario. El disco cambia
de aspecto con el tema -se han visto dos, blanco y dorado- pero el logo es el
mismo dibujo. Medido sobre 12 sesiones, las mascaras de la pica coinciden entre
el 90,7% y el 97,8%, incluido dorado contra blanco (0,907). Por eso la plantilla
es la pica y no el disco entero: el disco entero traeria el fieltro de fondo, que
es justo lo que cambia.

Se guarda UN ejemplar exacto a resolucion nativa (22x26), no un promedio, por la
misma razon que el atlas de glifos: promediar muestras mal alineadas engorda el
dibujo y reescalar lo dentella.
"""
import math
import os

import cv2
import numpy as np

import seat_map

PLANTILLA_FICHERO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "disco_boton.png")

# Alto de la pica como fraccion del ANCHO del nucleo del tapete. Todo en este
# modulo se expresa asi, igual que el resto del mapa de asientos, para que
# escale solo con la ventana. Medido sobre la captura de la que sale la
# plantilla: 22 px de alto con un nucleo de 939 de ancho.
ALTO_FRAC = 0.0234

# Se prueban varias escalas alrededor de la nominal porque el disco cambia algo
# de tamaño entre temas y porque el nucleo se mide con su propio error.
ESCALAS = (0.80, 0.90, 1.00, 1.10, 1.25)

# Rojo del logo. No es un color de tema: es el rojo de PokerStars, el mismo en
# las dos versiones del disco.
ROJO_S_MIN, ROJO_V_MIN = 110, 80

_PLANTILLA = None


def _plantilla():
    global _PLANTILLA
    if _PLANTILLA is None:
        m = cv2.imread(PLANTILLA_FICHERO, cv2.IMREAD_GRAYSCALE)
        _PLANTILLA = m if m is not None else np.zeros((0, 0), np.uint8)
    return _PLANTILLA


def mascara_roja(bgr):
    """Pixeles del rojo del logo."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    rojo = ((h <= 8) | (h >= 172)) & (s >= ROJO_S_MIN) & (v >= ROJO_V_MIN)
    return rojo.astype(np.uint8) * 255


def buscar_disco(bgr, ref):
    """(x, y, pico) del mejor candidato a disco dentro del tapete, o None.

    Barre TODO el nucleo, no seis puntos. Las coordenadas son absolutas y
    apuntan al centro de la pica."""
    plant = _plantilla()
    if not plant.size:
        return None
    x0, y0, w, h = ref[0], ref[1], ref[2], ref[3]
    # margen: el disco se dibuja pegado al borde interior del rail y el nucleo
    # se mide con su propio error, asi que se mira algo mas que la caja justa
    m = int(0.04 * w)
    X0, Y0 = max(0, x0 - m), max(0, y0 - m)
    X1, Y1 = min(bgr.shape[1], x0 + w + m), min(bgr.shape[0], y0 + h + m)
    zona = mascara_roja(bgr[Y0:Y1, X0:X1])
    if zona.size == 0:
        return None
    alto = ALTO_FRAC * w
    mejor = None
    for e in ESCALAS:
        th = max(6, int(round(alto * e)))
        tw = max(6, int(round(plant.shape[1] * th / plant.shape[0])))
        if zona.shape[0] < th or zona.shape[1] < tw:
            continue
        t = cv2.resize(plant, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(zona, t, cv2.TM_CCOEFF_NORMED)
        _mn, mx, _ml, ml = cv2.minMaxLoc(res)
        if mejor is None or mx > mejor[2]:
            mejor = (X0 + ml[0] + tw // 2, Y0 + ml[1] + th // 2, float(mx))
    return mejor


# Correlacion minima para creerse que ese pico es el disco y no otra cosa roja
# (una carta de corazones, una ficha del 5), y cuanto mas cerca tiene que estar
# el asiento ganador que el segundo.
#
# NO estan puestos a ojo. Se barren los dos contra un invariante que no depende
# de leer nada mas: EL BOTON AVANZA UN SOLO ASIENTO POR MANO. Un detector que se
# equivoca produce saltos de 3, 4 o 5 asientos, que no pueden pasar. Medido
# sobre 3.087 candidatos de 14 sesiones:
#
#     MIN_PICO  VENTAJA   acepta   avanza 1   salta 3+
#       0.40     0.55      2677      67%        14%
#       0.50     0.65      2767      67%        13%
#       0.55     0.75      2891      73%        11%
#       0.60     0.75      2812      75%         9%
#       0.70     0.75      2810      75%         9%
#       0.75     0.75      2804      76%         8%
#
# De 0.60 a 0.75 el resultado es plano y la cobertura casi no baja (2812 ->
# 2804): los picos del disco de verdad estan muy por encima del ruido, no hay
# nada en medio. Se coge 0.70, en el centro de esa meseta, para tener margen por
# los dos lados.
#
# El 9% de saltos que queda NO es todo error: cuando alguien se queda sin fichas
# el boton salta el asiento vacio, asi que dos son legitimos. El detector por
# anclas, con este mismo invariante, avanza un asiento el 55% de las veces y
# salta 3+ el 24%.
MIN_PICO = 0.70
VENTAJA_MIN = 0.75


def asiento_mas_cercano(ref, punto):
    """(asiento, distancia, distancia_al_segundo) midiendo al ANCLA de cada
    asiento, que es donde el cliente dibuja el disco de ese jugador."""
    ds = []
    for s, info in seat_map.SEATS.items():
        fx, fy = info["button"]
        ax, ay = ref[0] + fx * ref[2], ref[1] + fy * ref[3]
        ds.append((math.hypot(punto[0] - ax, punto[1] - ay), s))
    ds.sort()
    return ds[0][1], ds[0][0], ds[1][0]


def detectar(bgr, ref):
    """Asiento que tiene el boton, o None si no se ve claro."""
    d = buscar_disco(bgr, ref)
    if d is None or d[2] < MIN_PICO:
        return None
    asiento, primera, segunda = asiento_mas_cercano(ref, (d[0], d[1]))
    if segunda <= 0 or primera / segunda > VENTAJA_MIN:
        return None                    # a medio camino: no se sabe de quien es
    return asiento
