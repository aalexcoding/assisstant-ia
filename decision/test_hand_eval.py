"""
Verificacion del evaluador vectorizado (hand_eval.py) contra un ORACULO de
fuerza bruta escrito aqui mismo: para cada mano de 7 cartas, prueba las 21
combinaciones de 5 y clasifica cada una con kickers completos, en Python puro y
sin numpy. Es lento (~250x) pero obviamente correcto, y no depende de ninguna
libreria externa, asi que sirve de verdad como referencia.

Lo que se comprueba no es solo la categoria: es el ORDEN. Un evaluador que
acierte la categoria y falle el desempate arruinaria la simulacion de equity en
silencio, contando como empate lo que es victoria o al reves.
"""
import itertools
import random
import time

import numpy as np
import pytest

from decision import hand_strength as hs
from decision.hand_eval import CATEGORY_ES, card_id, card_ids, category, score

# La semilla es FIJA. Un oraculo sobre manos aleatorias distintas en cada
# ejecucion daria un test que a veces pasa y a veces no, y encima sin poder
# reproducir el caso que fallo.
SEMILLA = 20260725
N_MANOS = 4000
N_COMPARACIONES = 20000


# --- oraculo de fuerza bruta -------------------------------------------------

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


def sc(*codes):
    """Puntuacion de una mano de 7 cartas dada por codigos."""
    return int(score(card_ids(list(codes)).reshape(1, 7))[0])


@pytest.fixture(scope="module")
def contra_oraculo():
    """Las N_MANOS manos aleatorias, con lo que dice el oraculo y lo que dice
    hand_eval. Ambito de modulo porque el oraculo tarda unos segundos y los dos
    tests que lo usan miran lo mismo desde angulos distintos."""
    rng = random.Random(SEMILLA)
    manos = [rng.sample(range(52), 7) for _ in range(N_MANOS)]
    return {"esperado": [ref7(m) for m in manos],
            "obtenido": score(np.array(manos, dtype=np.int32))}


# --- 1. concordancia masiva contra el oraculo --------------------------------

@pytest.mark.lento
def test_la_categoria_coincide_con_el_oraculo(contra_oraculo):
    cats = category(contra_oraculo["obtenido"])
    fallos = [i for i in range(N_MANOS)
              if int(cats[i]) != contra_oraculo["esperado"][i][0]]
    assert not fallos, f"{len(fallos)} manos con categoria distinta del oraculo"


@pytest.mark.lento
def test_el_orden_coincide_con_el_oraculo(contra_oraculo):
    """Lo importante no es la categoria, es el DESEMPATE: un evaluador que
    acierte la categoria y falle el kicker arruina la equity en silencio."""
    rng = random.Random(SEMILLA + 1)
    esperado, obtenido = contra_oraculo["esperado"], contra_oraculo["obtenido"]
    fallos = 0
    for _ in range(N_COMPARACIONES):
        i, j = rng.randrange(N_MANOS), rng.randrange(N_MANOS)
        a, b = esperado[i], esperado[j]
        got = int(obtenido[i]) - int(obtenido[j])
        if ((a > b) - (a < b)) != ((got > 0) - (got < 0)):
            fallos += 1
    assert fallos == 0, f"{fallos} de {N_COMPARACIONES} comparaciones mal ordenadas"


# --- 2. los casos que hand_strength._classify se come ------------------------

def test_el_palo_no_desempata_un_color():
    """El bug de ("flush", suit, high): dos colores con los mismos rangos son un
    empate, y meter el palo en la clave convertia el empate en victoria."""
    assert sc("Ah", "Kh", "Qh", "Jh", "9h", "2c", "3d") == \
           sc("As", "Ks", "Qs", "Js", "9s", "2c", "3d")


@pytest.mark.parametrize("mejor, peor, motivo", [
    (("Ah", "Ad", "Kh", "Kd", "Qc", "2s", "3d"),
     ("Ah", "Ad", "Kh", "Kd", "Jc", "2s", "3d"), "doble pareja: el kicker decide"),
    (("9h", "9d", "9s", "9c", "Ah", "2s", "3d"),
     ("9h", "9d", "9s", "9c", "Kh", "2s", "3d"), "poker: el kicker decide"),
    (("9h", "9d", "Ah", "Kd", "Qc", "2s", "3d"),
     ("9h", "9d", "Ah", "Kd", "Jc", "2s", "3d"), "pareja: el tercer kicker decide"),
    (("2d", "3s", "4c", "5h", "6d", "9s", "Kd"),
     ("Ah", "2d", "3s", "4c", "5h", "9s", "Kd"), "la rueda es la escalera mas baja"),
    (("9h", "9d", "9s", "8c", "8h", "8d", "2c"),
     ("8c", "8h", "8d", "7h", "7d", "7s", "2c"), "con dos trios manda el mayor"),
    (("Ac", "Jh", "Tc", "9s", "8c", "7d", "6h"),
     ("Kc", "Tc", "9d", "8c", "7s", "6d", "3s"), "con dos escaleras solapadas manda la alta"),
    (("9h", "8h", "7h", "6h", "5h", "2c", "3d"),
     ("9c", "9d", "9s", "9h", "Ah", "2s", "3d"), "escalera de color bate al poker"),
    (("Ah", "Kh", "Qh", "Jh", "9h", "8h", "2c"),
     ("Ah", "Kh", "Qh", "Jh", "8h", "7h", "2c"), "color: los 5 rangos mas altos del palo"),
])
def test_desempates(mejor, peor, motivo):
    assert sc(*mejor) > sc(*peor), motivo


@pytest.mark.parametrize("cartas, cat", [
    (("Ah", "2d", "3s", "4c", "5h", "9s", "Kd"), 4),   # la rueda ES escalera
    (("9h", "9d", "9s", "8c", "8h", "8d", "2c"), 6),   # dos trios hacen FULL
])
def test_categoria_de_los_casos_raros(cartas, cat):
    assert int(category(np.array([sc(*cartas)]))[0]) == cat


# --- 3. formato de carta -----------------------------------------------------

def test_diez_se_escribe_de_las_dos_formas():
    assert card_id("10s") == card_id("Ts")


def test_minusculas_toleradas():
    assert card_id("ah") == card_id("Ah")


def test_carta_invalida_da_none():
    assert card_id("Xz") is None


def test_card_ids_lanza_con_una_carta_invalida():
    """No puede pasar en silencio: una carta ilegible que se colara como otra
    convertiria el mazo en imposible sin que nada lo dijera."""
    with pytest.raises(ValueError):
        card_ids(["Ah", "Zz"])


# --- 4. coherencia con los nombres en castellano del HUD ---------------------

@pytest.mark.parametrize("hero, board, categoria", [
    (["Ah", "Kd"], ["Qc", "Js", "9h"], "Carta alta"),
    (["Ah", "Ad"], ["Qc", "Js", "9h"], "Pareja"),
    (["Ah", "Ad"], ["Kc", "Ks", "9h"], "Doble pareja"),
    (["Ah", "Ad"], ["Ac", "Js", "9h"], "Trio"),
    (["Ah", "2d"], ["3c", "4s", "5h"], "Escalera"),
    (["Ah", "Kh"], ["Qh", "Jh", "9h"], "Color"),
    (["Ah", "Ad"], ["Ac", "Ks", "Kh"], "Full"),
    (["Ah", "Ad"], ["Ac", "As", "Kh"], "Poker"),
    (["Ah", "Kh"], ["Qh", "Jh", "Th"], "Escalera de color"),
])
def test_las_categorias_coinciden_con_hand_strength(hero, board, categoria):
    """El evaluador rapido y el que pone los nombres del HUD tienen que decir lo
    mismo: si divergen, el usuario ve una mano y la equity calcula otra."""
    # se evalua con exactamente 7 cartas: hero(2) + board(3) + dos rellenos bajos
    # que no alteran la categoria de ninguno de los nueve casos
    s = sc(*(hero + board + ["2c", "3d"]))
    assert CATEGORY_ES[int(category(np.array([s]))[0])] == categoria
    assert hs.evaluate_hand(hero, board)["made_category"] == categoria


# --- 5. coste ----------------------------------------------------------------

@pytest.mark.lento
def test_diez_mil_manos_por_debajo_de_cien_ms():
    """La equity son 10.000 iteraciones por frame: si esto se sale de
    presupuesto, el HUD deja de ir al ritmo del analisis."""
    rng = random.Random(SEMILLA)
    lote = np.array([rng.sample(range(52), 7) for _ in range(10000)], dtype=np.int32)
    score(lote)                      # calentar
    t0 = time.perf_counter()
    score(lote)
    dt = time.perf_counter() - t0
    assert dt < 0.100, f"10.000 manos en {dt * 1000:.1f} ms"
