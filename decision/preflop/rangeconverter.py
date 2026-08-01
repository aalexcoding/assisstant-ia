"""Lookup estricto de los rangos públicos 8-max de RangeConverter."""
import json
from pathlib import Path

from decision.preflop.interpolate import (
    MAX_DONOR_GAP_BB,
    interpolate_actions,
)
from decision.preflop.lookup import normalize_hand


DATA_PATH = Path(__file__).with_name("rangeconverter_ranges.json")
MAX_NEAREST_DISTANCE_BB = 5.0
_DATA = None


def load(path=None, data=None):
    global _DATA
    if data is not None:
        _DATA = data
    else:
        _DATA = json.loads(
            Path(path or DATA_PATH).read_text(encoding="utf-8"))
    return _DATA


def data():
    return _DATA if _DATA is not None else load()


def _nearest_stack(family, effective_stack_bb):
    table = data().get(family) or {}
    keys = sorted(float(key) for key in table)
    if not keys:
        return None, None
    nearest = min(keys, key=lambda key: abs(key - effective_stack_bb))
    if (effective_stack_bb < keys[0]
            or effective_stack_bb > keys[-1]
            or abs(nearest - effective_stack_bb) > MAX_NEAREST_DISTANCE_BB):
        return None, None
    return nearest, table.get(f"{nearest:g}")


def _result(action, nearest):
    return {
        "action": action,
        "stack_key": nearest,
        "source": "rangeconverter_public_chart",
        "source_name": data().get("_meta", {}).get("source_name"),
        "source_url": (
            data().get("_meta", {})
            .get("source_urls", {})
            .get(f"{nearest:g}")
        ),
        "assumptions": [
            "MTT 8-max",
            "ante total 1 BB",
            "chip-EV, sin ICM",
            "frecuencias redondeadas al 50%",
        ],
    }


def _action_in(buckets, hand):
    for action, hands in (buckets or {}).items():
        if hand in hands:
            return action
    return None


def _available_cells(family, selector, hand, allowed_stack=None):
    cells = {}
    for key, table in (data().get(family) or {}).items():
        stack = float(key)
        if allowed_stack is not None and not allowed_stack(stack):
            continue
        action = _action_in(selector(table), hand)
        if action is not None:
            cells[stack] = action
    return cells


def _interpolated_result(family, target, lower, upper, interpolation):
    meta = data().get("_meta", {})
    urls = meta.get("source_urls", {})
    donor_urls = [
        urls.get(f"{stack:g}")
        for stack in (lower, upper)
        if urls.get(f"{stack:g}")
    ]
    assumptions = [
        "MTT 8-max",
        "ante total 1 BB",
        "chip-EV, sin ICM",
        "estimación lineal entre dos tablas públicas de la misma familia",
        (
            f"donantes {lower:g} y {upper:g} BB; no es una celda publicada "
            "ni una solución GTO nueva"
        ),
    ]
    return {
        **interpolation,
        "stack_key": float(target),
        "source": "interpolated_chart",
        "source_name": meta.get("source_name"),
        "source_url": donor_urls[0] if donor_urls else None,
        "source_urls": donor_urls,
        "family": family,
        "assumptions": assumptions,
    }


def _recommend(family, hand, target, selector, allowed_stack=None):
    cells = _available_cells(
        family, selector, hand, allowed_stack=allowed_stack)
    if not cells:
        return None

    exact = next(
        (stack for stack in cells if abs(stack - target) <= 1e-6),
        None,
    )
    if exact is not None:
        return _result(cells[exact], exact)

    lower = max((stack for stack in cells if stack < target), default=None)
    upper = min((stack for stack in cells if stack > target), default=None)
    if lower is not None and upper is not None:
        # Una separación grande no se mezcla. Se conserva debajo el fallback
        # vecino que ya existía para objetivos a <=5 BB de una tabla publicada.
        if upper - lower <= MAX_DONOR_GAP_BB:
            interpolation = interpolate_actions(
                cells[lower], cells[upper], lower, upper, target)
            # Si había dos donantes válidos pero la mano cambia demasiado o sale
            # del RFI en uno de ellos, abstenerse es parte del contrato.
            if interpolation is None:
                return None
            return _interpolated_result(
                family, target, lower, upper, interpolation)

    nearest, _table = _nearest_stack(family, target)
    if nearest is None or nearest not in cells:
        return None
    return _result(cells[nearest], nearest)


def recommend_open_raise(hero_cards, hero_position, stack_bb):
    hand = normalize_hand(hero_cards)
    if hand is None or stack_bb is None:
        return None
    return _recommend(
        "open_raise",
        hand,
        float(stack_bb),
        lambda table: table.get(hero_position),
    )


def recommend_response_to_3bet(
        hero_cards, hero_position, threebettor_position, effective_stack_bb,
        threebet_all_in=None):
    """Respuesta al 3-bet o None si el PDF no cubre el spot.

    Una tabla exacta tiene prioridad. Entre dos tablas compatibles interpola
    solo si las celdas no se contradicen; si no existe ese par, conserva el
    fallback histórico a una tabla vecina a un máximo de 5 BB. Nunca cruza la
    familia de shove de 20 BB con las respuestas a 3bet normal de 30+ BB.
    El llamador valida formato y ante.
    """
    hand = normalize_hand(hero_cards)
    if hand is None or effective_stack_bb is None:
        return None
    if threebet_all_in is True:
        allowed_stack = lambda stack: stack == 20.0
    elif threebet_all_in is False:
        allowed_stack = lambda stack: stack >= 30.0
    else:
        # Nunca se interpola cruzando la tabla de 20 BB (respuesta a shove)
        # con las de 30+ BB (respuesta a 3bet normal).
        target_is_shove_family = float(effective_stack_bb) <= 25.0
        allowed_stack = (
            (lambda stack: stack == 20.0)
            if target_is_shove_family
            else (lambda stack: stack >= 30.0)
        )
    return _recommend(
        "response_to_3bet",
        hand,
        float(effective_stack_bb),
        lambda table: (
            table.get(hero_position, {}).get(threebettor_position)
        ),
        allowed_stack=allowed_stack,
    )
