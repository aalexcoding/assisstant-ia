"""
Verificacion de la simulacion de equity (equity.py).

La prueba que de verdad importa es la primera: contrastar contra EQUITIES
PUBLICADAS y universalmente conocidas (AA contra una mano cualquiera es 85,2%).
Si el motor de simulacion o el evaluador tuvieran un sesgo, ahi se ve. Se usa el
nucleo _simular directamente con board vacio, porque las cifras autorizadas que
todo el mundo conoce son preflop, mientras que la API publica es postflop a
proposito (en preflop manda la tabla de rangos del usuario, no una simulacion).

TODAS las llamadas van con seed. Es Monte Carlo: sin semilla, el mismo test da
un numero distinto cada vez y una tolerancia de 1 pp seria una moneda al aire.
"""
import time

import numpy as np
import pytest

from decision import equity, hand_eval, hand_strength, opponent_ranges

FLOP = (["Ah", "Kh"], ["Th", "7h", "2c"])       # proyecto de color, el caso de referencia
MEDIOCRE = (["Kh", "Tc"], ["9c", "As", "7d"])   # mano floja: sensible al rango rival


def equity_preflop(mano, n_rivales, iteraciones=20000, seed=11):
    """Equity all-in preflop contra n rivales de mano cualquiera, por el nucleo
    de simulacion. Devuelve (equity, win)."""
    hero = hand_eval.card_ids(mano)
    board = np.empty(0, dtype=np.int32)
    mazo = np.setdiff1d(np.arange(52, dtype=np.int32), hero)
    rangos = [equity._sin_conflicto(opponent_ranges.random_combos(), hero)
              for _ in range(n_rivales)]
    rng = np.random.default_rng(seed)
    w, t, _l, _c, n = equity._simular(hero, board, mazo, rangos, iteraciones, rng)
    return (w + t / 2) / n, w / n


# --- 1. contra equities publicadas -------------------------------------------

@pytest.mark.lento
@pytest.mark.parametrize("mano, rivales, publicado, desc", [
    (["Ah", "Ad"], 1, 0.852, "AA vs 1 cualquiera"),
    (["Kh", "Kd"], 1, 0.824, "KK vs 1 cualquiera"),
    (["Ah", "Ks"], 1, 0.654, "AKo vs 1 cualquiera"),
    (["Ah", "Kh"], 1, 0.670, "AKs vs 1 cualquiera"),
    (["7h", "2d"], 1, 0.346, "72o vs 1 cualquiera (la peor mano)"),
    (["Ah", "Ad"], 4, 0.560, "AA vs 4 cualesquiera"),
])
def test_equity_preflop_contra_cifras_publicadas(mano, rivales, publicado, desc):
    """Si el simulador o el evaluador tuvieran un sesgo, se ve aqui y en ningun
    otro sitio: son las unicas cifras de este repo que no las produce el repo."""
    eq, _w = equity_preflop(mano, rivales)
    assert abs(eq - publicado) < 0.01, \
        f"{desc}: {100 * eq:.1f}% frente al {100 * publicado:.1f}% publicado"


# --- 2. coherencia interna ---------------------------------------------------

@pytest.fixture
def flop_ahkh():
    return equity.estimate_equity(*FLOP, "BTN", 1, seed=3)


def test_devuelve_un_resultado(flop_ahkh):
    assert flop_ahkh is not None


def test_las_probabilidades_suman_uno(flop_ahkh):
    suma = (flop_ahkh["win_probability"] + flop_ahkh["tie_probability"]
            + flop_ahkh["loss_probability"])
    assert abs(suma - 1.0) < 1e-3, f"suman {suma:.4f}"


def test_equity_es_win_mas_medio_tie(flop_ahkh):
    esperado = flop_ahkh["win_probability"] + flop_ahkh["tie_probability"] / 2
    assert abs(flop_ahkh["equity"] - esperado) < 1e-3


def test_el_error_estandar_es_coherente_con_las_iteraciones(flop_ahkh):
    assert 0.2 < flop_ahkh["std_error_pp"] < 1.0


def test_street_correcta(flop_ahkh):
    assert flop_ahkh["street"] == "flop"
    assert flop_ahkh["cards_to_come"] == 2


def test_determinista_con_el_mismo_seed(flop_ahkh):
    """Sin esto no se puede afirmar nada sobre un numero de Monte Carlo."""
    otra = equity.estimate_equity(*FLOP, "BTN", 1, seed=3)
    assert otra["win_probability"] == flop_ahkh["win_probability"]


# --- 3. monotonias que tienen que cumplirse ----------------------------------

def test_ganar_baja_al_anadir_rivales():
    wins = [equity.estimate_equity(*MEDIOCRE, "SB", n, stack_bb=20.0, seed=5,
                                   include_baselines=False)["win_probability"]
            for n in (1, 2, 3)]
    assert wins[0] > wins[1] > wins[2], [round(100 * w, 1) for w in wins]


def test_un_rango_mas_cerrado_baja_la_equity_de_una_mano_mediocre():
    """EP1 entra mas fuerte que BTN, y BTN mas que un rival de mano cualquiera:
    contra un rango mejor, KTo gana menos."""
    def win(**kw):
        return equity.estimate_equity(*MEDIOCRE, "SB", 1, seed=5,
                                      include_baselines=False, **kw)["win_probability"]
    ep1 = win(opponent_positions=["EP1"], stack_bb=20.0)
    btn = win(opponent_positions=["BTN"], stack_bb=20.0)
    aleatorio = win(opponent_positions=[None], stack_bb=None)
    assert ep1 <= btn <= aleatorio, \
        f"{100 * ep1:.1f} <= {100 * btn:.1f} <= {100 * aleatorio:.1f}"


# --- 4. casos extremos -------------------------------------------------------

def test_los_nuts_en_el_river_ganan_casi_siempre():
    """Escalera de color maxima: no hay mano que la bata."""
    r = equity.estimate_equity(["Ah", "Kh"], ["Qh", "Jh", "Th", "2c", "3d"], "BTN", 1,
                               seed=9, include_baselines=False)
    assert r["win_probability"] > 0.99, f"{100 * r['win_probability']:.1f}%"
    assert r["hand_potential"]["draws"] == [], "en el river no quedan proyectos"


# --- 5. hand_potential reutiliza hand_strength SIN recalcular ----------------

@pytest.fixture
def potencial():
    return equity.estimate_equity(*FLOP, "BTN", 1, seed=3,
                                  include_baselines=False)["hand_potential"]


def test_los_proyectos_son_exactamente_los_de_hand_strength(potencial):
    """Sin fork silencioso: si equity recalculara los proyectos por su cuenta, el
    HUD y la equity podrian discrepar sobre la misma mano."""
    assert potencial["draws"] == hand_strength.evaluate_hand(*FLOP)["draws"]


def test_hay_proyecto_de_color_en_este_board(potencial):
    assert any("color" in d["name"].lower() for d in potencial["draws"])


def test_la_nota_distingue_completar_el_proyecto_de_ganar_la_mano(potencial):
    assert "no de ganar la mano" in potencial["note"]


def test_la_distribucion_de_categoria_final_suma_uno(potencial):
    assert abs(sum(potencial["final_categories"].values()) - 1.0) < 0.02


# --- 6. abstenciones: mejor callar que responder sobre datos imposibles ------

@pytest.mark.parametrize("desc, args", [
    ("carta repetida entre mano y board (el fallo real del OCR)",
     (["Ah", "Kd"], ["4s", "7d", "9d", "7h", "9d"], "BTN", 1)),
    ("carta del hero repetida en el board", (["Ah", "Kd"], ["Ah", "7d", "2c"], "BTN", 1)),
    ("board de 2 cartas", (["Ah", "Kd"], ["7d", "2c"], "BTN", 1)),
    ("board de 6 cartas", (["Ah", "Kd"], ["7d", "2c", "3h", "4s", "5d", "6c"], "BTN", 1)),
    ("0 rivales", (["Ah", "Kd"], ["7d", "2c", "3h"], "BTN", 0)),
    ("6 rivales (no caben en la mesa)", (["Ah", "Kd"], ["7d", "2c", "3h"], "BTN", 6)),
    ("una sola carta del hero", (["Ah"], ["7d", "2c", "3h"], "BTN", 1)),
    ("carta invalida", (["Ah", "Zz"], ["7d", "2c", "3h"], "BTN", 1)),
])
def test_se_abstiene_con_motivo(desc, args):
    """Un numero inventado sobre un mazo imposible es peor que no dar numero."""
    avisos = []
    assert equity.estimate_equity(*args, warnings=avisos) is None, desc
    assert len(avisos) == 1, f"{desc}: se esperaba UN motivo, hay {avisos}"


# --- 7. procedencia de los rangos --------------------------------------------

@pytest.fixture
def con_procedencia():
    return equity.estimate_equity(*MEDIOCRE, "SB", 2,
                                  opponent_positions=["BTN", "BB"], stack_bb=20.0, seed=7)


def test_cada_rival_declara_de_que_celda_sale_su_rango(con_procedencia):
    metas = con_procedencia["positional_adjustment"]["opponent_ranges"]
    assert all("ranges.json" in (m.get("source") or "") for m in metas)


def test_y_con_que_anchura(con_procedencia):
    """BTN entra con ~47% de las manos y la BB con ~91%: son las tablas del
    usuario, no una tightness inventada."""
    metas = con_procedencia["positional_adjustment"]["opponent_ranges"]
    assert abs(metas[0]["pct_of_all"] - 0.472) < 0.01
    assert abs(metas[1]["pct_of_all"] - 0.91) < 0.02


def test_se_mide_el_efecto_del_rango_y_el_del_numero_de_rivales(con_procedencia):
    ajuste = con_procedencia["positional_adjustment"]
    assert ajuste["range_effect_pp"] is not None
    assert ajuste["opponent_count_effect_pp"] is not None


def test_la_explicacion_dice_que_la_posicion_no_cambia_la_equity(con_procedencia):
    assert "no cambia esta equity" in con_procedencia["positional_adjustment"]["explanation"]


def test_los_supuestos_dicen_que_es_un_techo_de_all_in(con_procedencia):
    assert any("TECHO" in a for a in con_procedencia["assumptions"])
    assert any("all-in" in a for a in con_procedencia["assumptions"])


# --- 8. coste ----------------------------------------------------------------

@pytest.mark.lento
def test_el_peor_caso_cabe_en_el_presupuesto():
    """5 rivales, flop y las 3 simulaciones. El ciclo de analisis entero son
    ~1 s: si esto se acerca, la equity deja de ir al ritmo del HUD."""
    t0 = time.perf_counter()
    equity.estimate_equity(*MEDIOCRE, "SB", 5, stack_bb=20.0, seed=1)
    dt = time.perf_counter() - t0
    assert dt < 0.400, f"peor caso en {dt * 1000:.0f} ms"


# --- manos VISTAS: el rival enseña las cartas (all-in / showdown) ------------
#
# Es la unica informacion cierta que hay de una mano ajena. Con ella el numero
# deja de ser "cuanto gano contra su rango" y pasa a ser la respuesta: donde
# habia 1.326 combos posibles queda uno, y esa parte deja de estimarse.

def test_una_mano_vista_da_la_respuesta_exacta_y_no_una_estimacion():
    """El caso que lo motivo, tal cual ocurrio en sesion-2026-07-28_012156/0075:
    el hero tenia escalera 2-6 y creyo ir ganando; el rival enseñaba 6c 4c, que
    con ese board es ESCALERA DE COLOR. Contra el rango salia 82,4%."""
    board = ["2c", "5c", "4s", "Qs", "3c"]
    vista = equity.estimate_equity(["Kh", "6d"], board, "SB", 1,
                                   opponent_hands=[["6c", "4c"]], seed=1)
    assert vista["win_probability"] == 0.0, "iba muerto"
    assert vista["tie_probability"] == 0.0
    assert vista["loss_probability"] == 1.0

    ciego = equity.estimate_equity(["Kh", "6d"], board, "SB", 1,
                                   opponent_positions=["BB"], stack_bb=35.0, seed=1)
    assert ciego["win_probability"] > 0.5, "contra un rango la misma mano parece buena"


def test_ver_las_cartas_no_deja_nada_al_azar():
    """Con el board completo y todos los rivales vistos no queda ni una carta por
    repartir, asi que el resultado no puede depender del seed."""
    kw = dict(opponent_hands=[["6c", "4c"]])
    a = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s", "Qs", "3c"], "SB", 1,
                               seed=1, **kw)
    b = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s", "Qs", "3c"], "SB", 1,
                               seed=999, **kw)
    assert a["win_probability"] == b["win_probability"]
    assert a["equity"] == b["equity"]


def test_el_rango_de_un_rival_visto_es_UN_combo():
    r = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s", "Qs", "3c"], "SB", 1,
                               opponent_hands=[["6c", "4c"]], seed=1)
    meta = r["positional_adjustment"]["opponent_ranges"][0]
    assert meta["combos"] == 1
    assert "VISTAS" in meta["source"]


def test_los_supuestos_sobre_rangos_DESAPARECEN_cuando_se_ven_todas():
    """Repetir "se supone que juegan como tu" cuando sus cartas estan sobre la
    mesa seria advertir de un error que ya no se comete, y el usuario dejaria de
    leer los supuestos."""
    r = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s", "Qs", "3c"], "SB", 1,
                               opponent_hands=[["6c", "4c"]], seed=1)
    texto = " ".join(r["assumptions"])
    assert "juegan como tu" not in texto
    assert "TECHO" not in texto
    assert "sin suponerles nada" in texto


def test_con_un_rival_visto_y_otro_tapado_se_dice_cuantos():
    r = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s", "Qs", "3c"], "SB", 2,
                               opponent_positions=["BB", "BTN"],
                               opponent_hands=[["6c", "4c"], None],
                               stack_bb=35.0, seed=1)
    texto = " ".join(r["assumptions"])
    assert "1 de 2" in texto
    assert "TECHO" in texto, "para el que sigue tapado el supuesto del rango SI aplica"
    metas = r["positional_adjustment"]["opponent_ranges"]
    assert [m["combos"] for m in metas][0] == 1
    assert metas[1]["combos"] > 1


def test_las_cartas_del_rival_salen_del_mazo():
    """Si no se quitaran, la simulacion podria repartirle a OTRO rival una carta
    que ya esta sobre la mesa, y contaria manos imposibles.

    Se comprueba donde se nota: el mazo del que sale el board por venir. Con dos
    cartas menos disponibles, un proyecto de color tiene menos outs."""
    kw = dict(opponent_positions=["BB", "BTN"], stack_bb=35.0, seed=3, iterations=20000)
    # el hero tiene proyecto de color a picas; las dos cartas vistas SON picas,
    # asi que verlas quita dos de sus outs
    tapadas = equity.estimate_equity(["As", "Ks"], ["2s", "9s", "4h"], "SB", 2, **kw)
    vistas = equity.estimate_equity(["As", "Ks"], ["2s", "9s", "4h"], "SB", 2,
                                    opponent_hands=[["7s", "Ts"], None], **kw)
    assert vistas["win_probability"] != tapadas["win_probability"], \
        "quitar dos picas del mazo tiene que cambiar el numero"

    # y el rango del rival que SIGUE tapado tampoco puede contener esas cartas
    combos, _m = opponent_ranges.entering_combos("BTN", 35.0)
    con_vistas = equity._sin_conflicto(
        combos, hand_eval.card_ids(["As", "Ks", "2s", "9s", "4h", "7s", "Ts"]))
    sin_vistas = equity._sin_conflicto(
        combos, hand_eval.card_ids(["As", "Ks", "2s", "9s", "4h"]))
    assert len(con_vistas) < len(sin_vistas)


@pytest.mark.parametrize("mano, desc", [
    (["6c", "2c"], "una carta suya ya esta en el board"),
    (["Kh", "4c"], "una carta suya es del hero"),
    (["4c", "4c"], "la misma carta dos veces"),
    (["6c"], "solo una carta leida"),
    (["Xx", "4c"], "codigo ilegible"),
])
def test_una_lectura_IMPOSIBLE_se_trata_como_mano_tapada(mano, desc):
    """Media lectura es peor que ninguna: invitaria a tratar como cierto algo que
    no lo es. Se vuelve al rango en vez de abstenerse, porque el rival sigue ahi
    y el resto del calculo es valido."""
    r = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s", "Qs", "3c"], "SB", 1,
                               opponent_positions=["BB"], opponent_hands=[mano],
                               stack_bb=35.0, seed=1)
    assert r is not None, desc
    assert r["positional_adjustment"]["opponent_ranges"][0]["combos"] > 1, desc


def test_sin_opponent_hands_todo_sigue_igual():
    """La firma nueva no puede cambiar lo que sale cuando nadie enseña nada."""
    kw = dict(opponent_positions=["BB"], stack_bb=35.0, seed=7)
    a = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s"], "SB", 1, **kw)
    b = equity.estimate_equity(["Kh", "6d"], ["2c", "5c", "4s"], "SB", 1,
                               opponent_hands=[None], **kw)
    assert a["win_probability"] == b["win_probability"]
    assert a["assumptions"] == b["assumptions"]
