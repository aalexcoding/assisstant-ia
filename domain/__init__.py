"""Contratos de dominio compartidos entre vision, core y decision.

Este paquete no importa ninguna capa concreta: asi evita ciclos y permite que
las tres dependan de la misma forma de GameState.
"""

from domain.state import GameState, PlayerState, Recommendation, new_game_state

__all__ = ["GameState", "PlayerState", "Recommendation", "new_game_state"]
