"""
Test suelto (sin pytest) de decision/hand_strength.py con casos conocidos a
mano. Uso: .venv/bin/python decision/test_hand_strength.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hand_strength as hs

fails = 0


def check(desc, cond):
    global fails
    status = "OK  " if cond else "FAIL"
    if not cond:
        fails += 1
    print(f"  [{status}] {desc}")


def find_draw(res, needle):
    for d in res["draws"]:
        if needle.lower() in d["name"].lower():
            return d
    return None


def show(title, hero, board):
    res = hs.evaluate_hand(hero, board)
    print(f"\n{title}: hero={hero} board={board}")
    print(f"  mano: {res['made_name']}  ({res['made_category']}, {res['street']})")
    for d in res["draws"]:
        pr = f"~{d['pct_river']}% river" if d["pct_river"] is not None else "-"
        print(f"    draw: {d['name']}: {d['outs']} outs, ~{d['pct_next']}% sig, {pr}"
              f"  [regla 2/4: {d['pct_next_rule']}%/{d['pct_river_rule']}%]")
    return res


print("=== Mano formada ===")
r = show("Doble pareja", ["Ah", "Kh"], ["Ac", "Kc", "Qh"])
check("nombre = 'Doble pareja (Ases y Reyes)'", r["made_name"] == "Doble pareja (Ases y Reyes)")
check("sin proyectos", r["draws"] == [])

r = show("Full house", ["As", "Kh"], ["Ah", "Ad", "Kc"])
check("Full de Ases con Reyes", r["made_name"] == "Full de Ases con Reyes")

r = show("Color", ["3h", "9c"], ["Ah", "7h", "2h", "Kh"])
check("categoria = Color", r["made_category"] == "Color")
check("Color de corazones", "Color de corazones" in r["made_name"])

r = show("Escalera formada", ["Ts", "Jd"], ["9h", "8c", "7d", "2s"])
check("Escalera al Jota", r["made_name"] == "Escalera al Jota")

r = show("Poker", ["8h", "8d"], ["8c", "8s", "Kd"])
check("Poker de Ochos", r["made_name"] == "Poker de Ochos")

print("\n=== Preflop ===")
r = show("Preflop suited", ["As", "Ks"], [])
check("AK suited", r["made_name"] == "AK suited")
r = show("Preflop offsuit", ["Ad", "Kc"], [])
check("AK offsuit", r["made_name"] == "AK offsuit")
r = show("Preflop par", ["8h", "8d"], [])
check("Pareja de Ochos", r["made_name"] == "Pareja de Ochos")

print("\n=== Proyectos ===")
r = show("Proyecto de color (flop)", ["Ah", "Kh"], ["Th", "7h", "2c"])
fd = find_draw(r, "color")
check("proyecto de color detectado", fd is not None)
check("9 outs", fd and fd["outs"] == 9)
check("~35% al river (exacto)", fd and fd["pct_river"] == 35)
check("regla del 4 = 36%", fd and fd["pct_river_rule"] == 36)

r = show("Escalera abierta (OESD)", ["Ts", "Js"], ["9h", "8c", "2d"])
sd = find_draw(r, "abierta")
check("OESD detectada", sd is not None)
check("8 outs", sd and sd["outs"] == 8)

r = show("Gutshot", ["Js", "Qd"], ["9h", "8c", "2d"])
gs = find_draw(r, "gutshot")
check("gutshot detectado", gs is not None)
check("4 outs", gs and gs["outs"] == 4)

r = show("Broadway = gutshot (no OESD)", ["Ah", "Kd"], ["Qs", "Jc", "2d"])
gs = find_draw(r, "gutshot")
check("broadway AKQJ es gutshot (4 outs a T)", gs is not None and gs["outs"] == 4)

r = show("Doble proyecto (color + escalera)", ["Jh", "8h"], ["Th", "9h", "2c"])
fd = find_draw(r, "color de")
sd = find_draw(r, "abierta")
combo = find_draw(r, "doble proyecto")
check("proyecto de color (9 outs)", fd is not None and fd["outs"] == 9)
check("escalera abierta (8 outs)", sd is not None and sd["outs"] == 8)
check("doble proyecto = 15 outs limpios", combo is not None and combo["outs"] == 15)
check("doble proyecto ~54% al river (exacto, no 60)", combo is not None and combo["pct_river"] == 54)

r = show("Turn: solo 1 carta por venir", ["Ah", "Kh"], ["Th", "7h", "2c", "3s"])
fd = find_draw(r, "color")
check("en turn pct_river es None", fd is not None and fd["pct_river"] is None)
check("en turn ~20% (9/46) a la siguiente", fd is not None and fd["pct_next"] == 20)

r = show("River: sin proyectos", ["Ah", "Kh"], ["Th", "7h", "2c", "3s", "9d"])
check("river sin draws", r["draws"] == [])

print("\n=== Robustez ===")
check("hero vacio -> None", hs.evaluate_hand([], []) is None)
check("hero incompleto -> None", hs.evaluate_hand(["Ah"], []) is None)

print(f"\n{'TODOS OK' if fails == 0 else str(fails) + ' FALLOS'}")
sys.exit(1 if fails else 0)
