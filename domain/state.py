"""Contrato estable de los datos que cruzan el pipeline de poker.

La percepcion puede no leer un campo; por eso los TypedDict son parciales. Los
defaults comunes se centralizan aqui para que las rutas de vision no diverjan
silenciosamente al añadir un campo nuevo.
"""
from typing import Any, Literal, TypedDict


class PlayerState(TypedDict, total=False):
    seat: str
    name: str | None
    stack: float | None
    position: str | None
    is_hero: bool
    in_hand: bool
    cards: list[str] | None
    bet: float | None
    committed: float | None
    committed_calle: float | None
    committed_acuerdo: str
    action: str | None


class Recommendation(TypedDict, total=False):
    action: str
    action_en: str
    action_es: str
    stack_bb: float
    effective_stack_bb: float
    facing_used: str
    vs_position: str | None
    reasoning: str
    source: str
    source_name: str
    source_url: str
    confidence: str
    assumptions: list[str]


class GameState(TypedDict, total=False):
    image: str
    max_players: int | None
    hero_cards: list[str]
    hero_cards_dimmed: bool
    board: list[str]
    board_detected_count: int
    board_slots: list[str | None]
    board_slot_confidence: list[float]
    board_observed_street: Literal["flop", "turn", "river"] | None
    table_reference_valid: bool
    pot: float | None
    blinds: Any
    players: list[PlayerState]
    hero_position: str | None
    facing: Literal["bet", "check"] | None
    vs_position: str | None
    stack_unit: Literal["bb"] | None
    to_call: float | None
    chat_lines: list[dict[str, Any]]
    warnings: list[str]
    tiempos: dict[str, float]
    acciones: dict[str, Any]
    preflop_action: dict[str, Any]
    # Guía postflop de decision/postflop_gto.py (textura, precio, MDF y, cuando
    # hay equity, una acción propuesta). Va en el estado y no en Recommendation
    # porque NO sale de los rangos digitalizados: es una fuente distinta y el
    # HUD la pinta en su propio panel para que no se confundan.
    gto: dict[str, Any] | None
    vigilancia: dict[str, Any]


def new_game_state(image: str, *, live: bool = False) -> GameState:
    """Crea el estado mínimo, idéntico para todas las rutas de visión.

    ``live=True`` añade los campos que el motor necesita en la ruta BB-only de
    producción. Las rutas de diagnóstico conservan ``blinds`` y no declaran la
    unidad para que el motor se abstenga de forma segura.
    """
    state: GameState = {
        "image": image,
        "hero_cards": [],
        "board": [],
        "pot": None,
        "players": [],
        "warnings": [],
    }
    if live:
        state.update({
            "hero_position": None,
            "facing": None,
            "vs_position": None,
            "stack_unit": "bb",
            "to_call": None,
            "chat_lines": [],
            "board_detected_count": 0,
            "board_slots": [],
            "board_slot_confidence": [],
            "board_observed_street": None,
            "table_reference_valid": False,
        })
    else:
        state["blinds"] = None
    return state
