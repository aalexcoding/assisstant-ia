"""
Verificacion del segundo camino de lectura de cartas (vision/rango_directo.py):
deslizar las plantillas de rango sobre la zona, sin buscar la carta.

Lo que de verdad protege:

  1. Que el PALO salga de la derecha del numero. Es el cambio entero. Antes se
     partia la franja de cartas por la mitad y se cogia el color dominante de
     cada lado; como las dos cartas del hero se solapan, el color de la de la
     izquierda ganaba en los dos lados y salian 50 contradicciones de 89
     lecturas, todas del tipo 'Kh 5s' leido 'Kh 5h'. El caso 2 lo reproduce.
  2. Que una carta TAPADA POR ABAJO se siga leyendo. Es la razon de existir del
     modulo: las cartas del hero salen cortadas por su propio nameplate, la
     cadena normal no puede segmentarlas y las pierde enteras.
  3. Que el umbral no deje colar rangos que no estan. Con MIN_PICO por debajo de
     0.66 aparecian TRES cartas en la mano del hero, que es imposible.
  4. Que EscalaGlifo fije el tamaño y deje de buscarlo. Barrer 21 escalas en
     cada frame cuesta 21 veces lo que cuesta leer.

Las imagenes se generan aqui, con las plantillas reales del atlas y los colores
de cuerpo de carta de color_card_detector, asi que el test no depende de tener
las capturas.
Uso: .venv/bin/python vision/test_rango_directo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import color_card_detector as ccd
import rango_directo as rd

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def _bgr(h, s, v):
    return tuple(int(x) for x in cv2.cvtColor(
        np.array([[[h, s, v]]], np.uint8), cv2.COLOR_HSV2BGR)[0, 0])


# un color de cuerpo dentro del perfil de cada palo (ver SUIT_HSV_PROFILES)
CUERPO = {
    "heart": _bgr(5, 180, 230),
    "club": _bgr(80, 220, 170),
    "diamond": _bgr(110, 100, 190),
    "spade": _bgr(20, 20, 140),
}
ALTO = 36
ANCHO_CARTA, ALTO_CARTA = 96, 132


def _plantilla(rango, alto=ALTO):
    for r, t in rd._atlas():
        if r == rango:
            e = alto / t.shape[0]
            return cv2.resize(t, (max(4, int(t.shape[1] * e)), alto),
                              interpolation=cv2.INTER_AREA)
    raise AssertionError("rango sin plantilla en el atlas: " + rango)


def _carta(rango, palo, alto=ALTO):
    """Una carta como las del cliente: cuerpo del color del palo, numero blanco
    arriba a la izquierda."""
    img = np.zeros((ALTO_CARTA, ANCHO_CARTA, 3), np.uint8)
    img[:, :] = CUERPO[palo]
    t = _plantilla(rango, alto)
    m = t > 127
    trozo = img[8:8 + t.shape[0], 8:8 + t.shape[1]]
    trozo[m] = (255, 255, 255)
    return img


def _zona(cartas, fondo=(30, 90, 40), solape=0):
    """Franja con las cartas una al lado de otra, opcionalmente solapadas como
    salen en la mano del hero."""
    paso = ANCHO_CARTA - solape
    z = np.zeros((ALTO_CARTA + 40, paso * (len(cartas) - 1) + ANCHO_CARTA + 40, 3), np.uint8)
    z[:, :] = fondo
    for i, (rango, palo) in enumerate(cartas):
        x = 20 + i * paso
        z[20:20 + ALTO_CARTA, x:x + ANCHO_CARTA] = _carta(rango, palo)
    return z


def _leidas(zona, alto=ALTO):
    out = []
    for _x, r, p, _pico in rd.leer_zona(zona, alto):
        if (r, p) not in out:
            out.append((r, p))
    return out


print("# --- caso 1: dos cartas sueltas, rango y palo ---")
z = _zona([("K", "heart"), ("5", "spade")])
leidas = _leidas(z)
check("lee exactamente dos cartas", len(leidas) == 2)
check("rangos K y 5 en orden de izquierda a derecha",
      [r for r, _p in leidas] == ["K", "5"])
check("palos heart y spade", [p for _r, p in leidas] == ["heart", "spade"])

print()
print("# --- caso 2: cartas SOLAPADAS, el palo no se contagia del vecino ---")
# El fallo real: 'Kh 5s' se leia 'Kh 5h' porque el rojo de la carta de la
# izquierda dominaba las dos mitades de la franja.
z = _zona([("K", "heart"), ("5", "spade")], solape=28)
leidas = _leidas(z)
check("solapadas: siguen siendo dos cartas", len(leidas) == 2)
check("solapadas: la segunda NO hereda el palo de la primera",
      dict(leidas).get("5") == "spade")
check("solapadas: la primera conserva el suyo", dict(leidas).get("K") == "heart")

for izq, der in (("heart", "spade"), ("spade", "heart"),
                 ("club", "diamond"), ("diamond", "club")):
    z = _zona([("Q", izq), ("9", der)], solape=28)
    d = dict(_leidas(z))
    check(f"solapadas {izq}/{der}: cada carta con su palo",
          d.get("Q") == izq and d.get("9") == der)

print()
print("# --- caso 3: el color se mira A LA DERECHA del numero, no alrededor ---")
# Se mancha el hueco a la IZQUIERDA del numero con el color de otro palo. Si la
# lectura mirase alrededor, cambiaria; mirando a la derecha, no.
z = _zona([("8", "club")])
z[20:20 + ALTO_CARTA, 4:20] = CUERPO["heart"]
check("una mancha de otro palo a la izquierda no cambia el palo",
      dict(_leidas(z)).get("8") == "club")

print()
print("# --- caso 4: carta TAPADA POR ABAJO (el nameplate del hero) ---")
z = _zona([("A", "diamond"), ("7", "club")])
z[20 + ALTO_CARTA // 2:, :] = (45, 45, 45)      # el plate gris oscuro encima
leidas = _leidas(z)
check("tapada media carta: se leen las dos igual", len(leidas) == 2)
check("tapada media carta: rangos correctos", [r for r, _p in leidas] == ["A", "7"])
check("tapada media carta: palos correctos",
      [p for _r, p in leidas] == ["diamond", "club"])

print()
print("# --- caso 5: no se inventa lo que no hay ---")
z = np.zeros((172, 300, 3), np.uint8)
z[:, :] = (30, 90, 40)
check("tapete vacio: ninguna carta", _leidas(z) == [])
z = _zona([("K", "heart"), ("5", "spade")])
check("dos cartas nunca dan mas de dos (el hero solo tiene dos)",
      len(_leidas(z)) <= 2)

print()
print("# --- caso 6: los trece rangos ---")
malos = []
for rango in ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"):
    d = dict(_leidas(_zona([(rango, "club")])))
    if list(d) != [rango]:
        malos.append((rango, list(d)))
check(f"los trece rangos se leen solos y bien (fallan: {malos})", not malos)

print()
print("# --- caso 7: el umbral esta por encima del acantilado ---")
# Medido sobre 300 frames: por debajo de 0.66 aparecen frames con TRES cartas en
# la mano del hero (36 a 0.64, 147 a 0.50). Ver la tabla en el modulo.
check("MIN_PICO por encima de donde se rompe el invariante", rd.MIN_PICO >= 0.66)
check("MIN_PICO no tan alto que deje de leer", rd.MIN_PICO <= 0.72)

print()
print("# --- caso 8: EscalaGlifo se fija y deja de buscar ---")
z = _zona([("K", "heart"), ("5", "spade")])
esc = rd.EscalaGlifo()
check("no se fija con una sola muestra", esc.de(z) is None and esc.fijada is None)
for _ in range(rd.EscalaGlifo.MUESTRAS_PARA_FIJAR):
    alto = esc.de(z)
check("se fija tras MUESTRAS_PARA_FIJAR frames", esc.fijada is not None)
check("la escala encontrada es la que se dibujo", abs(esc.fijada - ALTO) <= 4)

llamadas = []
_buscar = rd.buscar_escala
rd.buscar_escala = lambda *a, **k: (llamadas.append(1), _buscar(*a, **k))[1]
try:
    esc.de(z)
    check("una vez fijada no vuelve a buscar", not llamadas)
finally:
    rd.buscar_escala = _buscar

check("buscar_escala devuelve None en una zona sin cartas",
      rd.buscar_escala(np.full((172, 300, 3), 40, np.uint8)) is None)

print()
print("# --- caso 9: una carta APAGADA no se lee ---")
# Es lo unico peligroso de este segundo camino. Apagada significa que el hero ya
# se retiro de la mano; recomendar sobre ella seria aconsejar una mano
# abandonada. Y como este camino no encuentra cajas de carta, table_state no
# puede calcular su 'dimmed' -en 10 de 300 frames medidos entraria sin cajas y
# 'dimmed' saldria False por omision-.
#
# La garantia no es un umbral aparte sino la propia mascara: exige tinta con
# V > WHITE_MIN_VALUE (170) y una cara apagada cae a V=77 (medido en
# glyph_card_detector). Se comprueba aqui para que nadie afloje ese valor sin
# darse cuenta de que lo que sujeta es esto.
z = _zona([("K", "heart"), ("5", "spade")])
check("viva: se lee", len(_leidas(z)) == 2)
apagada = (z.astype(np.float32) * (77.0 / 255.0)).astype(np.uint8)
check("apagada: no se lee ninguna carta", _leidas(apagada) == [])
check("apagada: tampoco se encuentra escala", rd.buscar_escala(apagada) is None)

print()
print("# --- caso 10: el atlas se carga una vez ---")
check("el atlas trae los trece rangos", len(rd._atlas()) == 13)
check("el atlas es el mismo objeto en la segunda llamada", rd._atlas() is rd._atlas())
check("las plantillas vienen recortadas a su tinta",
      all(t.shape[0] > 0 and t.shape[1] > 0 and (t > 127).any() for _r, t in rd._atlas()))

print()
ok = sum(1 for _d, c in checks if c)
print(f"{ok}/{len(checks)} OK")
if ok != len(checks):
    print("FALLAN:")
    for d, c in checks:
        if not c:
            print("  - " + d)
    sys.exit(1)
