"""Contrato mínimo compartido entre visión y decisión."""
from domain.state import new_game_state


def test_el_estado_de_diagnostico_no_declara_unidad_ni_finge_bb():
    state = new_game_state("frame.png")
    assert state["blinds"] is None
    assert "stack_unit" not in state
    assert state["hero_cards"] == state["board"] == []


def test_el_estado_en_vivo_declara_los_campos_que_necesita_el_motor():
    state = new_game_state("frame.png", live=True)
    assert state["stack_unit"] == "bb"
    assert state["chat_lines"] == []
    assert state["facing"] is None
    assert state["board_detected_count"] == 0
    assert state["board_slots"] == []
    assert state["board_slot_confidence"] == []
    assert state["board_observed_street"] is None
    assert state["table_reference_valid"] is False
    assert "blinds" not in state
