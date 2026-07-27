"""
Verificacion de la busqueda del disco del dealer BARRIENDO la mesa
(vision/disco_dealer.py), el modelo que pidio el usuario: plantilla en codigo,
mapear la mesa, y el asiento mas cercano se lleva el boton.

Lo que de verdad protege:

  1. Que se encuentre el disco ESTE DONDE ESTE, no solo en seis puntos fijos.
     Es la razon de existir del modulo: el detector por anclas veia el disco en
     728 de 895 frames y este en 855, y en la mesa naranja bajaba al 49%.
  2. Que NO dependa del color del tapete ni del aspecto del disco. Se han visto
     dos discos (blanco y dorado) y seis tapetes; lo unico constante es la pica
     con la estrella, que es la plantilla.
  3. Que si el disco cae a medio camino entre dos asientos se diga que NO se
     sabe. Asignarlo al azar corre TODAS las posiciones, que es el fallo mas
     caro de esta app.
  4. Que una carta roja o una ficha roja no pasen por disco.

Las imagenes se generan aqui a partir de la plantilla real del repo, asi que el
test no depende de tener las capturas.
Uso: .venv/bin/python vision/test_disco_dealer.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import disco_dealer as dd
import seat_map

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


REF = (200, 180, 1000, 470)          # nucleo del tapete tipico
ALTO, ANCHO = 960, 1400


def mesa(fondo=(60, 120, 40)):
    img = np.zeros((ALTO, ANCHO, 3), np.uint8)
    img[:, :] = fondo
    return img


def pinta_disco(img, centro, cuerpo=(235, 235, 235), escala=1.0):
    """Dibuja un disco como el del cliente: un ovalo claro con la pica roja
    encima. La pica sale de la plantilla real del repo."""
    t = dd._plantilla()
    alto = max(6, int(round(dd.ALTO_FRAC * REF[2] * escala)))
    ancho = max(6, int(round(t.shape[1] * alto / t.shape[0])))
    t = cv2.resize(t, (ancho, alto), interpolation=cv2.INTER_AREA)
    cx, cy = centro
    cv2.ellipse(img, (cx, cy), (int(ancho * 0.85), int(alto * 0.80)), 0, 0, 360, cuerpo, -1)
    y0, x0 = cy - alto // 2, cx - ancho // 2
    trozo = img[y0:y0 + alto, x0:x0 + ancho]
    trozo[t > 127] = (40, 40, 220)          # rojo del logo, en BGR
    return img


def ancla(seat):
    fx, fy = seat_map.SEATS[seat]["button"]
    return int(REF[0] + fx * REF[2]), int(REF[1] + fy * REF[3])


print("# --- caso 1: el disco se encuentra en cualquier asiento ---")
malos = []
for s in seat_map.SEATS:
    img = pinta_disco(mesa(), ancla(s))
    if dd.detectar(img, REF) != s:
        malos.append((s, dd.detectar(img, REF)))
check(f"los seis asientos se detectan (fallan: {malos})", not malos)

print()
print("# --- caso 2: da igual el color del tapete y el aspecto del disco ---")
# seis tapetes medidos en sesiones reales (naranja, verde, verde claro, azul,
# oliva y negro), en BGR aproximado
TAPETES = [(40, 90, 200), (60, 120, 40), (90, 190, 120),
           (150, 90, 40), (80, 140, 150), (35, 35, 35)]
malos = []
for i, f in enumerate(TAPETES):
    img = pinta_disco(mesa(f), ancla("UR"))
    if dd.detectar(img, REF) != "UR":
        malos.append(("tapete", i, dd.detectar(img, REF)))
check(f"seis tapetes distintos, mismo resultado (fallan: {malos})", not malos)

# disco DORADO: cambia el cuerpo, no la pica
img = pinta_disco(mesa(), ancla("ML"), cuerpo=(90, 200, 235))
check("el disco dorado se detecta igual que el blanco", dd.detectar(img, REF) == "ML")

print()
print("# --- caso 3: a medio camino entre dos asientos NO se adivina ---")
# asignar mal el boton corre TODAS las posiciones; callarse es lo correcto
a, b = ancla("UL"), ancla("TOPC")
img = pinta_disco(mesa(), ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))
check("disco justo entre dos anclas: se devuelve None", dd.detectar(img, REF) is None)
check("pero el disco SI se encuentra (lo que falta es a quien asignarlo)",
      dd.buscar_disco(img, REF) is not None
      and dd.buscar_disco(img, REF)[2] >= dd.MIN_PICO)

print()
print("# --- caso 4: no se confunde con otras cosas rojas ---")
img = mesa()
cv2.rectangle(img, (600, 300), (680, 420), (40, 40, 200), -1)      # carta roja
check("una carta roja no es un disco", dd.detectar(img, REF) is None)
img = mesa()
cv2.circle(img, (640, 360), 18, (40, 40, 210), -1)                 # ficha roja
cv2.circle(img, (640, 360), 18, (255, 255, 255), 3)
check("una ficha roja redonda tampoco", dd.detectar(img, REF) is None)
img = mesa()
check("un tapete vacio no da boton", dd.detectar(img, REF) is None)

print()
print("# --- caso 5: el disco gana aunque haya cartas rojas en la mesa ---")
img = mesa()
cv2.rectangle(img, (600, 300), (680, 420), (40, 40, 200), -1)
pinta_disco(img, ancla("MR"))
check("con una carta roja al lado, sigue eligiendo el disco",
      dd.detectar(img, REF) == "MR")

print()
print("# --- caso 6: tolera que el disco no caiga exacto en el ancla ---")
# es justo el motivo del modulo: el cliente no lo dibuja siempre en el mismo sitio
malos = []
for dx, dy in ((14, 0), (-14, 0), (0, 14), (0, -14), (10, 10)):
    x, y = ancla("HERO")
    img = pinta_disco(mesa(), (x + dx, y + dy))
    if dd.detectar(img, REF) != "HERO":
        malos.append(((dx, dy), dd.detectar(img, REF)))
check(f"desplazado hasta 14 px sigue siendo del mismo asiento (fallan: {malos})",
      not malos)

print()
print("# --- caso 7: los umbrales estan donde los dejo la medicion ---")
# Barridos contra el invariante "el boton avanza UN asiento por mano" sobre
# 3.087 candidatos de 14 sesiones. De 0.60 a 0.75 el resultado es plano; se
# eligio 0.70, en el centro de esa meseta.
check("MIN_PICO dentro de la meseta medida", 0.60 <= dd.MIN_PICO <= 0.75)
check("VENTAJA_MIN exige que el ganador este claramente mas cerca",
      0.5 < dd.VENTAJA_MIN < 1.0)

print()
print("# --- caso 8: la plantilla del repo ---")
t = dd._plantilla()
check("la plantilla existe y no esta vacia", t.size > 0 and (t > 127).any())
check("es binaria (mascara, no foto)", set(np.unique(t)) <= {0, 255})
check("se carga una vez", dd._plantilla() is dd._plantilla())
# forma de pica: se ensancha hasta pasada la mitad y luego se estrecha de golpe
# en el pie. No se comprueba "mas arriba que abajo" -es falso, la estrella recorta
# la parte de arriba- sino el perfil, que es lo que la distingue de un circulo.
anchos = (t > 127).sum(axis=1)
fila_ancha = int(np.argmax(anchos))
check("la fila mas ancha cae pasada la mitad, como en una pica",
      0.45 <= fila_ancha / t.shape[0] <= 0.75)
check("y el pie es mucho mas estrecho que el cuerpo",
      anchos[-1] < 0.5 * anchos[fila_ancha])
check("lleva la estrella recortada: hay hueco dentro del contorno",
      (t[2:fila_ancha] <= 127).any())

print()
ok = sum(1 for _d, c in checks if c)
print(f"{ok}/{len(checks)} OK")
if ok != len(checks):
    print("FALLAN:")
    for d, c in checks:
        if not c:
            print("  - " + d)
    sys.exit(1)
