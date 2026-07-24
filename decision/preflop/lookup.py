"""
Fase 4.1: lookup puro sobre decision/preflop/ranges.json (generado por
parse_ranges.py, no tocar). Dado hero_cards + posicion + stack efectivo,
devuelve la etiqueta de accion del rango digitalizado, o None si falta
algun dato o la posicion/stack no tiene rango para ese facing.
"""
import json
import os

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}

RANGES_PATH = os.path.join(os.path.dirname(__file__), "ranges.json")
with open(RANGES_PATH) as f:
    RANGES = json.load(f)


def normalize_hand(hero_cards):
    """["Ks","6c"] -> "K6o" ; ["Ah","Ad"] -> "AA". None si no hay 2 cartas
    validas (rangos fuera de RANKS, cartas repetidas, etc)."""
    if len(hero_cards) != 2:
        return None
    r1, r2 = hero_cards[0][0], hero_cards[1][0]
    if r1 not in RANK_INDEX or r2 not in RANK_INDEX:
        return None
    if hero_cards[0] == hero_cards[1]:
        return None
    if r1 == r2:
        return r1 + r2
    hi, lo = (r1, r2) if RANK_INDEX[r1] < RANK_INDEX[r2] else (r2, r1)
    suited = "s" if hero_cards[0][1] == hero_cards[1][1] else "o"
    return hi + lo + suited


def _nearest_stack_key(stack_bb, stack_keys):
    return min(stack_keys, key=lambda k: abs(float(k) - stack_bb))


def recommend(hero_cards, hero_position, stack_bb, facing="open_raise", vs_position=None):
    if hero_position is None or stack_bb is None:
        return None
    hand = normalize_hand(hero_cards)
    if hand is None:
        return None
    stack_table = RANGES.get(facing)
    if not stack_table:
        return None

    stack_key = _nearest_stack_key(stack_bb, stack_table.keys())
    pos_table = stack_table[stack_key].get(hero_position)
    if pos_table is None:
        return None

    if facing == "threebet_call":
        if vs_position is None:
            return None
        pos_table = pos_table.get(vs_position)
        if pos_table is None:
            return None

    for action, hands in pos_table.items():
        if hand in hands:
            return {"action": action, "hands_bucket": hands}
    return None
