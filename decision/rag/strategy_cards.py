"""Fichas de estrategia postflop con condiciones comprobables.

Esta capa complementa el RAG: una transcripción recuperada por similitud sirve
para localizar una lección, mientras que una ficha solo aparece si el estado
observado cumple todas sus condiciones. Las fichas son material de estudio
postmano; deliberadamente no contienen una acción ejecutable ni participan en
``decision.engine.decide``.
"""

from copy import deepcopy
import json
from pathlib import Path


CARDS_PATH = Path(__file__).with_name("strategy_cards.json")
_CARDS = None
_RANK_VALUE = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "T": 10, "10": 10, "J": 11, "Q": 12, "K": 13, "A": 14,
}


def board_texture(board):
    """Devuelve etiquetas derivadas únicamente de las cartas observadas."""
    cards = [str(card).strip() for card in (board or []) if card]
    ranks = []
    suits = []
    for card in cards:
        if len(card) < 2:
            continue
        rank = card[:-1].upper()
        value = _RANK_VALUE.get(rank)
        if value is None:
            continue
        ranks.append(value)
        suits.append(card[-1].lower())
    if len(ranks) < 3:
        return []

    tags = []
    if len(set(ranks)) < len(ranks):
        tags.append("paired")

    max_suit = max((suits.count(suit) for suit in set(suits)), default=0)
    if max_suit >= 3:
        tags.append("monotone")
    elif max_suit == 2:
        tags.append("two_tone")
    else:
        tags.append("rainbow")

    raw_ordered = sorted(set(ranks))
    unique = set(raw_ordered)
    if 14 in unique:
        unique.add(1)  # el as también conecta por abajo
    ordered = sorted(unique)
    three_card_connection = any(
        ordered[end] - ordered[start] <= 4
        for start in range(len(ordered))
        for end in range(start + 2, len(ordered))
    )
    # Dos cartas medias próximas también abren muchas escaleras con dos hole
    # cards (Q87r, JT2r...). Se evita llamar conectado a KQ2r: aunque K-Q sean
    # consecutivas, ese flop sigue comportándose mucho más como board alto del
    # agresor que como uno bajo y coordinado.
    medium_connection = any(
        high <= 11 and high - low <= 2
        for index, low in enumerate(raw_ordered)
        for high in raw_ordered[index + 1:]
    )
    connected = three_card_connection or medium_connection
    if connected:
        tags.append("connected")
    if sum(value >= 10 for value in ranks[:3]) >= 2:
        tags.append("broadway_heavy")
    if max(ranks[:3]) <= 9:
        tags.append("low_medium")

    # Etiqueta amplia y exclusiva para que una ficha de board seco y otra de
    # board dinámico no se muestren a la vez.
    tags.append(
        "dynamic"
        if connected or max_suit >= 2
        else "static"
    )
    return tags


def _load_cards():
    global _CARDS
    if _CARDS is None:
        with CARDS_PATH.open(encoding="utf-8") as fh:
            data = json.load(fh)
        cards = data.get("cards")
        if data.get("schema_version") != 1 or not isinstance(cards, list):
            raise ValueError("catálogo de fichas postflop incompatible")
        ids = [card.get("id") for card in cards]
        if any(not card_id for card_id in ids) or len(ids) != len(set(ids)):
            raise ValueError("las fichas postflop necesitan ids únicos")
        for card in cards:
            if card.get("recommendation_level") != "study_only":
                raise ValueError(
                    f"{card.get('id')}: solo se admiten fichas de estudio")
            if "action" in card or "recommended_action" in card:
                raise ValueError(
                    f"{card.get('id')}: una ficha no puede ejecutar acciones")
        _CARDS = cards
    return _CARDS


def reset_cards():
    """Vacía la caché; útil para tests y edición local del catálogo."""
    global _CARDS
    _CARDS = None


def catalog():
    """Catálogo completo como copia, para auditoría y tests."""
    return deepcopy(_load_cards())


def enrich_context(context):
    """Añade únicamente rasgos calculables, sin mutar el contexto de entrada."""
    result = dict(context or {})
    result["board_texture"] = board_texture(result.get("board"))
    to_call = result.get("to_call_bb")
    result["facing_bet"] = (
        to_call > 0
        if isinstance(to_call, (int, float)) and not isinstance(to_call, bool)
        else None
    )
    effective = result.get("effective_stack_bb")
    result["reliable_call_price"] = (
        True
        if result["facing_bet"] is True
        and isinstance(effective, (int, float))
        and not isinstance(effective, bool)
        and effective > 0
        and to_call <= effective + 0.05
        else False if result["facing_bet"] is True else None
    )
    return result


def _matches_action_counts(required, actions):
    for wanted in required or []:
        minimum = wanted.get("min", 1)
        count = 0
        for action in actions:
            if all(action.get(key) == value for key, value in wanted.items()
                   if key != "min"):
                count += 1
        if count < minimum:
            return False
    return True


def _matches(conditions, context):
    for key in ("street", "pot_type", "initiative", "position_relation"):
        allowed = conditions.get(key)
        if allowed is not None and context.get(key) not in allowed:
            return False

    opponents = context.get("opponents")
    for name, compare in (
        ("opponents_min", lambda actual, limit: actual >= limit),
        ("opponents_max", lambda actual, limit: actual <= limit),
    ):
        if name in conditions:
            if not isinstance(opponents, int) or not compare(
                    opponents, conditions[name]):
                return False

    if "facing_bet" in conditions:
        if context.get("facing_bet") is not conditions["facing_bet"]:
            return False
    if "reliable_call_price" in conditions:
        if context.get("reliable_call_price") is not conditions[
                "reliable_call_price"]:
            return False

    texture_any = conditions.get("texture_any")
    if texture_any and not set(texture_any).intersection(
            context.get("board_texture") or []):
        return False
    texture_all = conditions.get("texture_all")
    if texture_all and not set(texture_all).issubset(
            context.get("board_texture") or []):
        return False

    if not _matches_action_counts(
            conditions.get("observed_action_counts"),
            context.get("actions") or []):
        return False
    return True


def match(context, limit=3):
    """Selecciona fichas cuyas condiciones están demostradas por el contexto.

    La prioridad resuelve solapamientos y ``exclusive_group`` evita presentar
    dos heurísticas alternativas para el mismo tipo de spot.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit debe ser un entero positivo")
    observed = enrich_context(context)
    # Una mesa con board puede seguir capturándose después de que el hero se
    # retirase preflop. Sin dos cartas observadas del hero no es su spot para
    # estudiar, aunque queden jugadores activos.
    if observed.get("hero_observed") is not True:
        return []
    # Las guías heads-up de 3-bet usadas por este catálogo excluyen squeezes.
    # Si el log vio positivamente open -> call -> 3bet, es mejor no mostrar una
    # ficha que usar rangos de un bote resubido ordinario. La ausencia de esta
    # señal no afirma que la lista incompleta contenga toda la secuencia.
    exclude_threebet = (
        observed.get("pot_type") == "3bet"
        and observed.get("squeeze_observed") is True
    )
    candidates = [
        card for card in _load_cards()
        if not (exclude_threebet
                and "3bet" in (card.get("conditions") or {}).get(
                    "pot_type", []))
        and _matches(card.get("conditions") or {}, observed)
    ]
    candidates.sort(key=lambda card: (-card.get("priority", 0), card["id"]))
    output = []
    groups = set()
    for card in candidates:
        group = card.get("exclusive_group")
        if group and group in groups:
            continue
        if group:
            groups.add(group)
        item = deepcopy(card)
        item["matched_context"] = {
            key: observed.get(key) for key in (
                "street", "pot_type", "initiative", "position_relation",
                "opponents", "board_texture", "facing_bet",
                "reliable_call_price")
            if observed.get(key) is not None
        }
        output.append(item)
        if len(output) >= limit:
            break
    return output
