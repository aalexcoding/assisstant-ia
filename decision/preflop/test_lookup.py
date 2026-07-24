"""
Script suelto de verificacion de lookup.py contra casos leidos directamente
de ranges.json (el proyecto no usa pytest todavia). Uso:
.venv/bin/python decision/preflop/test_lookup.py
"""
from lookup import normalize_hand, recommend

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


check("normalize_hand KsTd -> KTo", normalize_hand(["Ks", "Td"]) == "KTo")
check("normalize_hand 9d4d -> 94s", normalize_hand(["9d", "4d"]) == "94s")
check("normalize_hand AhAd -> AA", normalize_hand(["Ah", "Ad"]) == "AA")
check("normalize_hand cartas repetidas -> None", normalize_hand(["Ah", "Ah"]) is None)
check("normalize_hand incompleto -> None", normalize_hand(["Ah"]) is None)

# BTN a 40bb, KTs esta en OPEN RAISE (2 BB) segun ranges.json (verificado a mano)
r = recommend(["Kd", "Td"], "BTN", 40, facing="open_raise")
check("BTN 40bb KTs -> OPEN RAISE (2 BB)", r is not None and r["action"] == "OPEN RAISE (2 BB)")

# stack_bb=38 (sin key exacta) debe caer en la key mas cercana, "40"
r38 = recommend(["Kd", "Td"], "BTN", 38, facing="open_raise")
check("BTN 38bb (nearest->40) KTs -> OPEN RAISE (2 BB)", r38 is not None and r38["action"] == "OPEN RAISE (2 BB)")

# BTN a 40bb, 94s esta en fold segun ranges.json (verificado a mano)
r_fold = recommend(["9d", "4d"], "BTN", 40, facing="open_raise")
check("BTN 40bb 94s -> fold", r_fold is not None and r_fold["action"] == "fold")

# BTN a 20bb, KTs cae en LIMP (accion distinta de OPEN RAISE/fold, confirma que no
# se asume un vocabulario cerrado de acciones)
r_limp = recommend(["Kd", "Td"], "BTN", 20, facing="open_raise")
check("BTN 20bb KTs -> LIMP", r_limp is not None and r_limp["action"] == "LIMP")

# BB nunca abre bote: no hay datos de open_raise para BB
r_bb = recommend(["Ah", "Ad"], "BB", 40, facing="open_raise")
check("BB no tiene rango de open_raise -> None", r_bb is None)

# threebet_call: SB vs BTN a 15bb, AA esta en ALL IN o similar accion fuerte
r_3b = recommend(["Ah", "Ad"], "SB", 15, facing="threebet_call", vs_position="BTN")
check("SB vs BTN 15bb AA -> hay recomendacion", r_3b is not None)

# threebet_call sin vs_position -> None (dato necesario ausente)
r_3b_none = recommend(["Ah", "Ad"], "SB", 15, facing="threebet_call")
check("threebet_call sin vs_position -> None", r_3b_none is None)

# threebet_call: EP1 nunca enfrenta apertura (siempre abre el primero) -> sin datos
r_ep1 = recommend(["Ah", "Ad"], "EP1", 15, facing="threebet_call", vs_position="BTN")
check("EP1 no tiene rango de threebet_call como hero -> None", r_ep1 is None)

# cartas incompletas (mano parcial detectada por vision) -> None
r_incomplete = recommend(["Kd"], "BTN", 40, facing="open_raise")
check("mano incompleta -> None", r_incomplete is None)

# posicion desconocida -> None
r_no_pos = recommend(["Kd", "Td"], None, 40, facing="open_raise")
check("sin hero_position -> None", r_no_pos is None)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
