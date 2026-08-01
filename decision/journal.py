"""Adaptador de persistencia para las decisiones emitidas.

El motor no construye ni escribe JSONL: solo entrega el estado y su salida a
este borde de infraestructura. Un fallo del diario nunca altera una decisión.
"""
import json
import os
import time

from domain.state import GameState, Recommendation


DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "decisions.local.jsonl")


class DecisionJournal:
    def __init__(self, path=DEFAULT_PATH, active=None):
        self.path = path
        self.active = (os.environ.get("POKER_DECISIONS_LOG", "1") != "0"
                       if active is None else active)

    def record(self, state: GameState, recommendation: Recommendation | None,
               abstain_reason: str | None):
        if not self.active:
            return
        try:
            entry = {
                "t": time.time(),
                "image": state.get("image"),
                "hero_cards": state.get("hero_cards") or [],
                "board_empty": not state.get("board"),
                "hero_position": state.get("hero_position"),
                "facing": state.get("facing"),
                "vs_position": state.get("vs_position"),
                "stack_unit": state.get("stack_unit"),
            }
            if recommendation is not None:
                entry["stack_bb"] = round(recommendation.get("stack_bb", 0), 2)
                entry["action"] = recommendation.get("action")
                entry["facing_used"] = recommendation.get("facing_used")
                entry["vs_position"] = recommendation.get("vs_position")
                entry["source"] = recommendation.get("source")
                if recommendation.get("effective_stack_bb") is not None:
                    entry["effective_stack_bb"] = round(
                        recommendation["effective_stack_bb"], 2)
            else:
                entry["abstain"] = abstain_reason
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass


_DEFAULT = DecisionJournal()


def record(state: GameState, recommendation: Recommendation | None,
           abstain_reason: str | None):
    _DEFAULT.record(state, recommendation, abstain_reason)


def set_enabled(active: bool):
    """Control explícito para tests y herramientas de replay."""
    _DEFAULT.active = active
