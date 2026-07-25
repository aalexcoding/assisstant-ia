"""
Verificacion del evaluador vectorizado (hand_eval.py) contra un ORACULO de
fuerza bruta escrito aqui mismo: para cada mano de 7 cartas, prueba las 21
combinaciones de 5 y clasifica cada una con kickers completos, en Python puro y
sin numpy. Es lento (~250x) pero obviamente correcto, y no depende de ninguna
libreria externa, asi que sirve de verdad como referencia.

Lo que se comprueba no es solo la categoria: es el ORDEN. Un evaluador que
acierte la categoria y falle el desempate arruinaria la simulacion de equity en
silencio, contando como empate lo que es victoria o al reves.

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python decision/test_hand_eval.py
"""
import itertools
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import hand_strength as hs
from hand_eval import CATEGORY_ES, card_id, card_ids, category, score

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


# --- oraculo de fuerza bruta --------------------------------------------------

def _clasifica5(cinco):
    """5 cartas (rango 0..12, palo) -> tupla comparable con kickers completos."""
    rangos = sorted((c >> 2 for c in cinco), reverse=True)
    palos = [c & 3 for c in cinco]
    cuentas = {r: rangos.count(r) for r in set(rangos)}
    # ordenar por (multiplicidad, rango) descendente: asi los kickers caen solos
    por_grupo = sorted(cuentas.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    patron = [c for _, c in por_grupo]
    orden = [r for r, _ in por_grupo]

    color = len(set(palos)) == 1
    unicos = sorted(set(rangos), reverse=True)
    escalera_alta = None
    if len(unicos) == 5:
        if unicos[0] - unicos[4] == 4:
            escalera_alta = unicos[0]
        elif unicos == [12, 3, 2, 1, 0]:      # rueda A-2-3-4-5
            escalera_alta = 3

    if color and escalera_alta is not None:
        return (8, escalera_alta)
    if patron == [4, 1]:
        return (7, *orden)
    if patron == [3, 2]:
        return (6, *orden)
    if color:
        return (5, *rangos)
    if escalera_alta is not None:
        return (4, escalera_alta)
    if patron == [3, 1, 1]:
        return (3, *orden)
    if patron == [2, 2, 1]:
        return (2, *orden)
    if patron == [2, 1, 1, 1]:
        return (1, *orden)
    return (0, *rangos)


def ref7(siete):
    """Mejor de las 21 combinaciones de 5. Devuelve la tupla comparable."""
    return max(_clasifica5(c) for c in itertools.combinations(siete, 5))


# --- 1. concordancia masiva contra el oraculo --------------------------------
print("--- oraculo de fuerza bruta sobre manos aleatorias ---")
rng = random.Random(20260725)
N = 4000
manos = [rng.sample(range(52), 7) for _ in range(N)]
esperado = [ref7(m) for m in manos]
obtenido = score(np.array(manos, dtype=np.int32))
cats = category(obtenido)

fallos_cat = sum(1 for i in range(N) if int(cats[i]) != esperado[i][0])
check(f"categoria correcta en las {N} manos ({fallos_cat} fallos)", fallos_cat == 0)

# el orden: para cada par, el signo de la comparacion debe coincidir
pares = [(rng.randrange(N), rng.randrange(N)) for _ in range(20000)]
fallos_orden = 0
for i, j in pares:
    a, b = esperado[i], esperado[j]
    esperado_signo = (a > b) - (a < b)
    got = int(obtenido[i]) - int(obtenido[j])
    got_signo = (got > 0) - (got < 0)
    if esperado_signo != got_signo:
        fallos_orden += 1
check(f"orden correcto en {len(pares)} comparaciones ({fallos_orden} fallos)", fallos_orden == 0)

# --- 2. los casos que hand_strength._classify se come -------------------------
print("\n--- desempates que el clasificador del HUD no sabe hacer ---")


def sc(*codes):
    return int(score(card_ids(list(codes)).reshape(1, 7))[0])


# el palo NO puede desempatar un color (el bug de ("flush", suit, high))
color_h = sc("Ah", "Kh", "Qh", "Jh", "9h", "2c", "3d")
color_s = sc("As", "Ks", "Qs", "Js", "9s", "2c", "3d")
check("dos colores identicos empatan (el palo no desempata)", color_h == color_s)

# kickers de doble pareja
check("doble pareja: el kicker decide",
      sc("Ah", "Ad", "Kh", "Kd", "Qc", "2s", "3d") > sc("Ah", "Ad", "Kh", "Kd", "Jc", "2s", "3d"))
# kicker de poker
check("poker: el kicker decide",
      sc("9h", "9d", "9s", "9c", "Ah", "2s", "3d") > sc("9h", "9d", "9s", "9c", "Kh", "2s", "3d"))
# kickers de pareja simple
check("pareja: el tercer kicker decide",
      sc("9h", "9d", "Ah", "Kd", "Qc", "2s", "3d") > sc("9h", "9d", "Ah", "Kd", "Jc", "2s", "3d"))
# la rueda es la escalera mas baja
check("la rueda (A2345) es escalera",
      category(np.array([sc("Ah", "2d", "3s", "4c", "5h", "9s", "Kd")]))[0] == 4)
check("la rueda pierde contra una escalera al 6",
      sc("Ah", "2d", "3s", "4c", "5h", "9s", "Kd") < sc("2d", "3s", "4c", "5h", "6d", "9s", "Kd"))
# dos trios hacen full, no trio
check("dos trios -> full",
      category(np.array([sc("9h", "9d", "9s", "8c", "8h", "8d", "2c")]))[0] == 6)
check("con dos trios manda el mayor: full de nueves > full de ochos",
      sc("9h", "9d", "9s", "8c", "8h", "8d", "2c") > sc("8c", "8h", "8d", "7h", "7d", "7s", "2c"))
# dos escaleras solapadas en 7 cartas: debe ganar la ALTA
check("con dos escaleras solapadas manda la alta",
      sc("Ac", "Jh", "Tc", "9s", "8c", "7d", "6h") > sc("Kc", "Tc", "9d", "8c", "7s", "6d", "3s"))
# escalera de color
check("escalera de color bate al poker",
      sc("9h", "8h", "7h", "6h", "5h", "2c", "3d") > sc("9c", "9d", "9s", "9h", "Ah", "2s", "3d"))
# color de 5 dentro de 7 con dos palos
check("color: se toman los 5 rangos mas altos del palo",
      sc("Ah", "Kh", "Qh", "Jh", "9h", "8h", "2c") > sc("Ah", "Kh", "Qh", "Jh", "8h", "7h", "2c"))

# --- 3. formato de carta ------------------------------------------------------
print("\n--- formato de carta ---")
check("'10s' y 'Ts' son la misma carta", card_id("10s") == card_id("Ts"))
check("minusculas toleradas", card_id("ah") == card_id("Ah"))
check("carta invalida -> None", card_id("Xz") is None)
try:
    card_ids(["Ah", "Zz"])
    ok = False
except ValueError:
    ok = True
check("card_ids lanza ValueError con carta invalida (no pasa en silencio)", ok)

# --- 4. coherencia con los nombres en castellano del HUD ---------------------
print("\n--- coherencia con hand_strength (los nombres del HUD) ---")
CASOS = [
    (["Ah", "Kd"], ["Qc", "Js", "9h"], "Carta alta"),
    (["Ah", "Ad"], ["Qc", "Js", "9h"], "Pareja"),
    (["Ah", "Ad"], ["Kc", "Ks", "9h"], "Doble pareja"),
    (["Ah", "Ad"], ["Ac", "Js", "9h"], "Trio"),
    (["Ah", "2d"], ["3c", "4s", "5h"], "Escalera"),
    (["Ah", "Kh"], ["Qh", "Jh", "9h"], "Color"),
    (["Ah", "Ad"], ["Ac", "Ks", "Kh"], "Full"),
    (["Ah", "Ad"], ["Ac", "As", "Kh"], "Poker"),
    (["Ah", "Kh"], ["Qh", "Jh", "Th"], "Escalera de color"),
]
desacuerdos = []
for hero, board, esperado_cat in CASOS:
    # se evalua con exactamente 7 cartas: hero(2) + board(3) + dos rellenos bajos
    # que no alteran la categoria de ninguno de los nueve casos
    s = int(score(card_ids(hero + board + ["2c", "3d"]).reshape(1, 7))[0])
    mia = CATEGORY_ES[int(category(np.array([s]))[0])]
    suya = hs.evaluate_hand(hero, board)["made_category"]
    if mia != suya:
        desacuerdos.append((hero, board, mia, suya))
check(f"las 9 categorias coinciden con hand_strength ({len(desacuerdos)} desacuerdos)",
      not desacuerdos)
for d in desacuerdos:
    print("     ", d)

# --- 5. coste ----------------------------------------------------------------
print("\n--- coste ---")
lote = np.array([rng.sample(range(52), 7) for _ in range(10000)], dtype=np.int32)
score(lote)                      # calentar
t0 = time.perf_counter()
score(lote)
dt = time.perf_counter() - t0
print(f"     10.000 manos de 7 en {dt * 1000:.1f} ms  ({10000 / dt / 1e6:.2f} M manos/s)")
check("10.000 manos por debajo de 100 ms", dt < 0.100)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
