"""
Verificacion de la simulacion de equity (equity.py).

La prueba que de verdad importa es la primera: contrastar contra EQUITIES
PUBLICADAS y universalmente conocidas (AA contra una mano cualquiera es 85,2%).
Si el motor de simulacion o el evaluador tuvieran un sesgo, ahi se ve. Se usa el
nucleo _simular directamente con board vacio, porque las cifras autorizadas que
todo el mundo conoce son preflop, mientras que la API publica es postflop a
proposito (en preflop manda la tabla de rangos del usuario, no una simulacion).

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python decision/test_equity.py
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "preflop"))

import numpy as np

import equity
import hand_eval
import hand_strength
import opponent_ranges

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def equity_preflop(mano, n_rivales, iteraciones=20000, seed=11):
    """Equity all-in preflop contra n rivales de mano cualquiera, por el nucleo
    de simulacion. Devuelve (equity, win)."""
    hero = hand_eval.card_ids(mano)
    board = np.empty(0, dtype=np.int32)
    mazo = np.setdiff1d(np.arange(52, dtype=np.int32), hero)
    rangos = [equity._sin_conflicto(opponent_ranges.random_combos(), hero)
              for _ in range(n_rivales)]
    rng = np.random.default_rng(seed)
    w, t, l, _c, n = equity._simular(hero, board, mazo, rangos, iteraciones, rng)
    return (w + t / 2) / n, w / n


# --- 1. contra equities publicadas -------------------------------------------
print("--- equities preflop publicadas (tolerancia 1 pp) ---")
PUBLICADAS = [
    (["Ah", "Ad"], 1, 0.852, "AA vs 1 cualquiera"),
    (["Kh", "Kd"], 1, 0.824, "KK vs 1 cualquiera"),
    (["Ah", "Ks"], 1, 0.654, "AKo vs 1 cualquiera"),
    (["Ah", "Kh"], 1, 0.670, "AKs vs 1 cualquiera"),
    (["7h", "2d"], 1, 0.346, "72o vs 1 cualquiera (la peor mano)"),
    (["Ah", "Ad"], 4, 0.560, "AA vs 4 cualesquiera"),
]
for mano, n, esperado, desc in PUBLICADAS:
    eq, _w = equity_preflop(mano, n)
    check(f"{desc}: {100*eq:.1f}% (publicado {100*esperado:.1f}%)", abs(eq - esperado) < 0.01)

# --- 2. coherencia interna ----------------------------------------------------
print("\n--- coherencia interna ---")
r = equity.estimate_equity(["Ah", "Kh"], ["Th", "7h", "2c"], "BTN", 1, seed=3)
check("devuelve un resultado", r is not None)
suma = r["win_probability"] + r["tie_probability"] + r["loss_probability"]
check(f"las probabilidades suman 1 ({suma:.4f})", abs(suma - 1.0) < 1e-3)
check("equity == win + tie/2",
      abs(r["equity"] - (r["win_probability"] + r["tie_probability"] / 2)) < 1e-3)
check("el error estandar es coherente con el numero de iteraciones",
      0.2 < r["std_error_pp"] < 1.0)
check("street correcta", r["street"] == "flop" and r["cards_to_come"] == 2)

# mismo seed -> mismo resultado
r2 = equity.estimate_equity(["Ah", "Kh"], ["Th", "7h", "2c"], "BTN", 1, seed=3)
check("determinista con el mismo seed", r["win_probability"] == r2["win_probability"])

# --- 3. monotonias que tienen que cumplirse -----------------------------------
print("\n--- monotonias ---")
wins = []
for n in (1, 2, 3):
    rr = equity.estimate_equity(["Kh", "Tc"], ["9c", "As", "7d"], "SB", n,
                                stack_bb=20.0, seed=5, include_baselines=False)
    wins.append(rr["win_probability"])
check(f"ganar baja al añadir rivales ({[round(100*w,1) for w in wins]})",
      wins[0] > wins[1] > wins[2])

# un rango mas cerrado tiene que bajar la equity de una mano mediocre
eqs = {}
for pos in ("EP1", "BTN"):
    rr = equity.estimate_equity(["Kh", "Tc"], ["9c", "As", "7d"], "SB", 1,
                                opponent_positions=[pos], stack_bb=20.0, seed=5,
                                include_baselines=False)
    eqs[pos] = rr["win_probability"]
rr = equity.estimate_equity(["Kh", "Tc"], ["9c", "As", "7d"], "SB", 1,
                            opponent_positions=[None], stack_bb=None, seed=5,
                            include_baselines=False)
eqs["aleatorio"] = rr["win_probability"]
check(f"vs EP1 <= vs BTN <= vs aleatorio "
      f"({100*eqs['EP1']:.1f} <= {100*eqs['BTN']:.1f} <= {100*eqs['aleatorio']:.1f})",
      eqs["EP1"] <= eqs["BTN"] <= eqs["aleatorio"])

# --- 4. casos extremos --------------------------------------------------------
print("\n--- casos extremos ---")
# nuts en el river: escalera de color maxima, imposible de batir
r = equity.estimate_equity(["Ah", "Kh"], ["Qh", "Jh", "Th", "2c", "3d"], "BTN", 1,
                           seed=9, include_baselines=False)
check(f"nuts en el river gana casi siempre ({100*r['win_probability']:.1f}%)",
      r["win_probability"] > 0.99)
check("y en el river no quedan proyectos", r["hand_potential"]["draws"] == [])

# --- 5. hand_potential reutiliza hand_strength SIN recalcular -----------------
print("\n--- hand_potential ---")
hero, board = ["Ah", "Kh"], ["Th", "7h", "2c"]
r = equity.estimate_equity(hero, board, "BTN", 1, seed=3, include_baselines=False)
esperados = hand_strength.evaluate_hand(hero, board)["draws"]
check("los proyectos son EXACTAMENTE los de hand_strength (sin fork silencioso)",
      r["hand_potential"]["draws"] == esperados)
check("y hay proyecto de color en este board", any("color" in d["name"].lower() for d in esperados))
check("la nota distingue completar el proyecto de ganar la mano",
      "no de ganar la mano" in r["hand_potential"]["note"])
check("la distribucion de categoria final suma ~1",
      abs(sum(r["hand_potential"]["final_categories"].values()) - 1.0) < 0.02)

# --- 6. abstenciones: mejor callar que responder sobre datos imposibles -------
print("\n--- abstenciones ---")
for desc, args, kw in [
    ("carta repetida entre mano y board (el fallo real del OCR)",
     (["Ah", "Kd"], ["4s", "7d", "9d", "7h", "9d"], "BTN", 1), {}),
    ("carta del hero repetida en el board", (["Ah", "Kd"], ["Ah", "7d", "2c"], "BTN", 1), {}),
    ("board de 2 cartas", (["Ah", "Kd"], ["7d", "2c"], "BTN", 1), {}),
    ("board de 6 cartas", (["Ah", "Kd"], ["7d", "2c", "3h", "4s", "5d", "6c"], "BTN", 1), {}),
    ("0 rivales", (["Ah", "Kd"], ["7d", "2c", "3h"], "BTN", 0), {}),
    ("6 rivales (no caben en la mesa)", (["Ah", "Kd"], ["7d", "2c", "3h"], "BTN", 6), {}),
    ("una sola carta del hero", (["Ah"], ["7d", "2c", "3h"], "BTN", 1), {}),
    ("carta invalida", (["Ah", "Zz"], ["7d", "2c", "3h"], "BTN", 1), {}),
]:
    w = []
    res = equity.estimate_equity(*args, warnings=w, **kw)
    check(f"{desc} -> None con motivo", res is None and len(w) == 1)

# --- 7. procedencia de los rangos --------------------------------------------
print("\n--- procedencia ---")
r = equity.estimate_equity(["Kh", "Tc"], ["9c", "As", "7d"], "SB", 2,
                           opponent_positions=["BTN", "BB"], stack_bb=20.0, seed=7)
metas = r["positional_adjustment"]["opponent_ranges"]
check("cada rival declara de que celda de ranges.json sale su rango",
      all("ranges.json" in (m.get("source") or "") for m in metas))
check("y con que anchura (BTN ~47%, BB ~91%)",
      abs(metas[0]["pct_of_all"] - 0.472) < 0.01 and abs(metas[1]["pct_of_all"] - 0.91) < 0.02)
check("se mide el efecto del rango en puntos",
      r["positional_adjustment"]["range_effect_pp"] is not None)
check("y el de tener mas rivales",
      r["positional_adjustment"]["opponent_count_effect_pp"] is not None)
check("la explicacion dice que la posicion NO cambia la equity",
      "no cambia esta equity" in r["positional_adjustment"]["explanation"])
check("los supuestos dicen que es un TECHO",
      any("TECHO" in a for a in r["assumptions"]))
check("y que es equity de all-in",
      any("all-in" in a for a in r["assumptions"]))

# --- 8. coste ------------------------------------------------------------------
print("\n--- coste ---")
t0 = time.perf_counter()
equity.estimate_equity(["Kh", "Tc"], ["9c", "As", "7d"], "SB", 5,
                       stack_bb=20.0, seed=1)
dt = time.perf_counter() - t0
print(f"     peor caso (5 rivales, flop, con las 3 simulaciones): {dt*1000:.0f} ms")
check("el peor caso cabe de sobra en el presupuesto de 5s (<400 ms)", dt < 0.400)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
