"""Tabla suplementaria para responder a un open-shove de 10 BB.

No forma parte de ``ranges.json``: ese fichero se genera exclusivamente desde
las capturas de ZeroS Poker del usuario. Esta familia procede de una tabla
pública distinta y solo se consulta cuando el estado demuestra sus supuestos:
mesa 8-max, ante total de 1 BB, un único RFI all-in y profundidad efectiva
cercana a 10 BB.
"""
import json
import os

from decision.preflop.lookup import normalize_hand


DATA_PATH = os.path.join(os.path.dirname(__file__), "supplemental_ranges.json")
STACK_BB = 10.0
STACK_TOLERANCE_BB = 0.5
ANTE_TOTAL_BB = 1.0
ANTE_TOLERANCE_BB = 0.3

_DATA = None


def load_ranges(path=None, datos=None):
    """Carga o inyecta la tabla suplementaria (inyección útil en tests)."""
    global _DATA
    if datos is not None:
        _DATA = datos
    else:
        with open(path or DATA_PATH, encoding="utf-8") as f:
            _DATA = json.load(f)
    return _DATA


def ranges():
    return _DATA if _DATA is not None else load_ranges()


def recommend(hero_cards, hero_position, vs_position, effective_stack_bb,
              table_max_players, seated_players, ante_total_bb):
    """Devuelve CALL/FOLD para el spot exacto, o ``None`` si no es compatible.

    Una mano ausente de los buckets publicados es FOLD. No se busca la
    profundidad más cercana ni se traslada la tabla a 6-max/9-max: esas
    extrapolaciones cambiarían el número de jugadores, el dinero muerto o ambos.
    """
    if table_max_players != 8:
        return None
    if seated_players != 8:
        return None
    if effective_stack_bb is None or ante_total_bb is None:
        return None
    if abs(float(effective_stack_bb) - STACK_BB) > STACK_TOLERANCE_BB:
        return None
    if abs(float(ante_total_bb) - ANTE_TOTAL_BB) > ANTE_TOLERANCE_BB:
        return None

    hand = normalize_hand(hero_cards)
    if hand is None or hero_position is None or vs_position is None:
        return None
    spot = (ranges().get("call_vs_open_push", {})
            .get("10", {})
            .get(hero_position, {})
            .get(vs_position))
    if spot is None:
        return None

    for action, hands in spot.items():
        if hand in hands:
            return {
                "action": action,
                "stack_key": STACK_BB,
                "source": "supplemental_chart",
                "source_name": ranges().get("_meta", {}).get("name"),
                "source_url": ranges().get("_meta", {}).get("source_url"),
            }
    return {
        "action": "FOLD",
        "stack_key": STACK_BB,
        "source": "supplemental_chart",
        "source_name": ranges().get("_meta", {}).get("name"),
        "source_url": ranges().get("_meta", {}).get("source_url"),
    }
