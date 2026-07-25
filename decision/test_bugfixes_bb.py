"""
Regresion de los siete bugs de la Fase 0 (los que se arreglaron antes de pasar
la app a BB-only). Cada bloque documenta el fallo REAL que cubria, con el dato
medido que lo destapo, para que si alguien revierte el arreglo el test diga
exactamente que se rompe y por que importaba.

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python decision/test_bugfixes_bb.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for d in ("vision", "decision", os.path.join("decision", "preflop")):
    sys.path.insert(0, os.path.join(BASE, d))

import engine
import hand_strength as hs
import seat_map
from seat_map import detect_raiser, parse_amount_bb
from table_state import _plate_occupied
from text_extract import find_pot, find_pot_bb

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def L(text):
    """Una linea OCR con la forma que devuelve parse_tsv_lines."""
    return {"text": text, "cx": 0, "cy": 0, "left": 0, "top": 0, "right": 10, "bottom": 10}


def P(position, bet, hero=False):
    return {"position": position, "bet": bet, "is_hero": hero}


# --- 0.1 parse_amount_bb: separador decimal y tope de digitos -----------------
# El OCR lee la coma decimal como punto. Antes '57.2 BB' devolvia 2: un hero a
# 57bb se leia a 2bb -> tabla de 4bb -> "OPEN RAISE ALL IN". Fallo MUDO, del tipo
# que produce una recomendacion plausible y falsa.
check("0.1 coma decimal", parse_amount_bb([L("57,2 BB")]) == 57.2)
check("0.1 el OCR lee la coma como punto", parse_amount_bb([L("57.2 BB")]) == 57.2)
check("0.1 cuatro digitos no se truncan", parse_amount_bb([L("1234,5 BB")]) == 1234.5)
check("0.1 dos decimales", parse_amount_bb([L("123,45 BB")]) == 123.45)
check("0.1 entero sin decimales", parse_amount_bb([L("89 BB")]) == 89.0)
check("0.1 con etiqueta delante", parse_amount_bb([L("Bote: 3,75 BB")]) == 3.75)
# separador de MILES no debe casar: en modo BB no existe, es OCR corrupto de un
# importe en fichas, y aceptarlo reintroduciria un error de 1000x
check("0.1 separador de miles NO casa", parse_amount_bb([L("1.900 BB")]) is None)
check("0.1 separador de miles NO casa (2)", parse_amount_bb([L("12.500 BB")]) is None)
check("0.1 ignora la marca de bounty", parse_amount_bb([L("0,31 € 2,5 BB")]) == 2.5)

# --- 0.2 BB-ante: la apuesta de la BB no es prueba de subida ------------------
# Con BB-ante (casi todos los torneos modernos) bet_BB = 1+ante > bb, asi que se
# detectaba a la BB como raiser y se buscaba threebet_call[stack][hero]["BB"],
# que NO EXISTE para ningun hero: la BB habla ULTIMA preflop, asi que nunca es el
# agresor al que uno defiende (los vs_position digitalizados son solo posiciones
# que hablan antes). Resultado: abstencion en TODAS las manos. Rastro real en el
# log: "sin rango de defensa para CO vs BB a 14.1bb (threebet_call)".
BB_ANTE = [P("BB", 2.0), P("SB", 0.5), P("CO", None, hero=True)]
check("0.2 BB con ante no es una subida", detect_raiser(BB_ANTE, 1.0) == (None, "no_raise"))
check("0.2 el gemelo del motor coincide", engine._detect_raiser(BB_ANTE, 1.0) == (None, "no_raise"))

CON_APERTURA = [P("BB", 2.0), P("SB", 0.5), P("CO", 2.5), P("BTN", None, hero=True)]
check("0.2 con BB-ante se sigue viendo la apertura ajena",
      detect_raiser(CON_APERTURA, 1.0) == ("CO", "single"))
check("0.2 el gemelo coincide (apertura)",
      engine._detect_raiser(CON_APERTURA, 1.0) == ("CO", "single"))

# la BB SI puede subir de verdad (el hero limpeo y la BB ataca): es un spot
# distinto, sin rango digitalizado, y debe decirlo en vez de fingir una defensa
BB_SUBE = [P("BB", 4.0), P("SB", 1.0, hero=True)]
check("0.2 la BB subiendo de verdad -> bb_raised", detect_raiser(BB_SUBE, 1.0) == (None, "bb_raised"))
check("0.2 bb_raised tiene motivo de abstencion", "bb_raised" in engine._RAISE_ABSTAIN)

# lo que ya funcionaba debe seguir igual
check("0.2 sin ante, BB=1.0 -> no_raise",
      detect_raiser([P("BB", 1.0), P("SB", 0.5), P("CO", None, hero=True)], 1.0) == (None, "no_raise"))
check("0.2 multiway sigue igual",
      detect_raiser([P("BB", 1.0), P("HJ", 2.0), P("CO", 2.0), P("BTN", None, hero=True)], 1.0)
      == (None, "multiway"))
check("0.2 hero_raised sigue igual",
      detect_raiser([P("BB", 1.0), P("CO", 3.0, hero=True), P("BTN", 6.0)], 1.0)
      == (None, "hero_raised"))

# --- 0.3 la ocupacion era ciega a los nameplates en BB ------------------------
# _is_number_candidate("36,6") es falso y "BB" no es ni nombre ni numero, asi que
# un asiento con stack perfectamente legible contaba como VACIO. Y como las
# posiciones se asignan por el RECUENTO de ocupados (SEATING_BY_N), perder un
# asiento desplaza la posicion de TODOS. Medido en samples_bb/sample_bb_1.png: el
# asiento ML lee ['makeao31','36,6 BB'] y se juzgaba vacio -su nick lo rechaza la
# blacklist por subcadena ("make" dentro de "makeao31")-, con lo que se contaban
# 4 asientos en vez de 5 y el hero pasaba de HJ a CO.
check("0.3 un stack en BB marca el asiento como ocupado", _plate_occupied([L("36,6 BB")]) is True)
check("0.3 el caso real completo (nick que la blacklist mata + stack BB)",
      _plate_occupied([L("makeao31"), L("36,6 BB")]) is True)
check("0.3 un asiento vacio sigue vacio", _plate_occupied([L("* * *"), L("~—")]) is False)
check("0.3 el stack en fichas sigue marcando ocupado", _plate_occupied([L("5.892")]) is True)

# --- 0.4 el bote estaba roto en modo BB ---------------------------------------
# POT_RE + _to_int tratan la , y el . como separador de MILES, asi que el decimal
# se comia. Verificado end-to-end: el bote real de samples_bb/sample_bb_1.png es
# 3,75 BB y analyze_layout devolvia 375.
check("0.4 bote con decimales", find_pot_bb([L("Bote: 3,75 BB")]) == 3.75)
check("0.4 el modo fichas lo daba x100", find_pot([L("Bote: 3,75 BB")]) == 375)
check("0.4 bote de dos cifras", find_pot_bb([L("Bote: 12,5 BB")]) == 12.5)
# MIN_PLAUSIBLE_POT=100 descartaba cualquier bote en bb realista (1,5-30)
check("0.4 bote pequeño ya no se descarta", find_pot_bb([L("Bote: 8,5 BB")]) == 8.5)
check("0.4 el modo fichas lo descartaba", find_pot([L("Bote: 8,5 BB")]) is None)
check("0.4 acepta la etiqueta en ingles", find_pot_bb([L("Pot: 4 BB")]) == 4.0)
# se EXIGE la etiqueta: en modo BB todos los importes llevan el mismo sufijo, asi
# que sin ella un stack de la zona se confundiria con el bote
check("0.4 sin etiqueta Bote/Pot no es el bote", find_pot_bb([L("47,8 BB")]) is None)

# --- 0.5 coherencia entre la lectura de botones y la de posicion --------------
# Preflop solo la BB puede PASAR (para el resto la ciega grande es una apuesta
# viva). Si los botones dicen "Pasar" y la posicion leida no es BB, una de las dos
# lecturas esta mal; si es la posicion, el rango elegido tambien lo estara.
# NOTA: facing=None NO se abstiene a proposito. Medido sobre el log de una sesion
# real, 55 de los 74 frames decidibles tenian facing=None y de ahi salieron casi
# todas las recomendaciones: abstenerse mataria ~75% de la utilidad para cubrir un
# caso que no es el peligroso (recomendar una apertura sin accion pendiente es un
# preview inofensivo).
CONTRADICCION = {
    "board": [], "hero_cards": ["Ah", "Kd"], "hero_position": "CO", "facing": "check",
    "stack_unit": "bb", "players": [P("CO", None, hero=True)], "warnings": [],
}
CONTRADICCION["players"][0]["stack"] = 25.0
engine._last_hero_stack.update(value=None, t=0.0, unit=None)
check("0.5 facing=check con hero != BB -> abstiene", engine.decide(CONTRADICCION) is None)
check("0.5 y nombra la contradiccion",
      any("contradiccion" in w for w in CONTRADICCION["warnings"]))

SIN_BOTONES = {
    "board": [], "hero_cards": ["Ah", "Kd"], "hero_position": "BTN", "facing": None,
    "stack_unit": "bb", "players": [dict(P("BTN", None, hero=True), stack=40.0)],
    "warnings": [],
}
engine._last_hero_stack.update(value=None, t=0.0, unit=None)
check("0.5 facing=None SIGUE recomendando (decision medida, no descuido)",
      engine.decide(SIN_BOTONES) is not None)

# --- 0.6 interpolacion vs extrapolacion, contra la rejilla real ---------------
# Antes habia un unico umbral fijo de 2.6bb que no distinguia "cae entre dos
# tablas tuyas" de "cae fuera de tus tablas". Y tenia un agujero: las claves de
# threebet_call son 10/15/20/..., asi que una defensa a 12,5bb queda a 2,5bb de la
# de 10 y 2,5 < 2,6 -> se servia el grafico de 10bb SIN AVISO.
check("0.6 la rejilla de open_raise sale de los datos",
      engine._stack_grid("open_raise")[0] == 4.0 and engine._stack_grid("open_raise")[-1] == 40.0)
check("0.6 threebet_call empieza en 10bb (no hay defensa digitalizada por debajo)",
      engine._stack_grid("threebet_call")[0] == 10.0)

w = []
nota = engine._stack_key_note({"stack_key": 40.0}, 100.0, "open_raise", w)
check("0.6 100bb esta FUERA de la tabla -> extrapolado", "extrapolado" in nota)
check("0.6 y avisa en warnings", len(w) == 1 and "FUERA" in w[0])

w = []
nota = engine._stack_key_note({"stack_key": 10.0}, 12.5, "threebet_call", w)
check("0.6 defensa a 12,5bb: ahora SI se dice (antes, silencio total)", nota != "")
check("0.6 y se nombra la tabla vecina", "15bb" in nota)
check("0.6 pero no es un error, asi que no ensucia warnings", w == [])

w = []
check("0.6 profundidad que coincide con una clave -> sin nota",
      engine._stack_key_note({"stack_key": 40.0}, 40.0, "open_raise", w) == "" and w == [])

# --- 0.7 cartas imposibles por OCR --------------------------------------------
# Medido: 4 de los 64 frames con board (6,2%) traen una carta repetida. Sin guard,
# evaluate_hand devolvia una mano formada que el usuario NO tiene.
check("0.7 board con carta repetida -> None",
      hs.evaluate_hand(["Ah", "Kd"], ["4s", "7d", "9d", "7h", "9d"]) is None)
check("0.7 hero con dos cartas identicas -> None", hs.evaluate_hand(["Ah", "Ah"], []) is None)
check("0.7 una carta del hero repetida en el board -> None",
      hs.evaluate_hand(["Ah", "Kd"], ["Ah", "7d", "2c"]) is None)
check("0.7 board imposiblemente largo -> None",
      hs.evaluate_hand(["Ah", "Kd"], ["2c", "3d", "4h", "5s", "6c", "7d"]) is None)
# lo valido debe seguir funcionando
check("0.7 un board valido sigue evaluandose",
      hs.evaluate_hand(["Ah", "Kd"], ["4s", "7d", "9d"])["made_name"] == "Carta alta: As")

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
