import pytest

from core.board_tracker import BoardTracker
from decision import engine


def estado(board):
    return {"board": board, "warnings": []}


def test_confirma_cada_calle_dos_veces_y_no_retrocede():
    tracker = BoardTracker()
    flop = ["As", "Kd", "7c"]
    turn = flop + ["2h"]

    primero = estado(flop)
    assert tracker.aplicar(primero, mano=1) == []
    assert "pendiente" in primero["warnings"][0]

    assert tracker.aplicar(estado(flop), mano=1) == flop
    assert tracker.aplicar(estado(turn), mano=1) == turn
    assert tracker.aplicar(estado(turn), mano=1) == turn

    perdida = estado([])
    assert tracker.aplicar(perdida, mano=1) == turn
    assert "transitoria" in perdida["warnings"][0]


def test_un_runout_rapido_confirma_cada_calle_por_su_prefijo():
    tracker = BoardTracker()
    flop = ["9d", "7s", "Js"]
    turn = flop + ["5s"]
    river = turn + ["4s"]

    assert tracker.aplicar(estado(flop), mano=1) == []
    assert tracker.aplicar(estado(turn), mano=1) == turn
    assert tracker.aplicar(estado(river), mano=1) == river
    assert tracker.aplicar(estado(river), mano=1) == river


def test_corrige_un_prefijo_equivocado_si_la_lectura_se_repite():
    tracker = BoardTracker(confirmaciones=2)
    flop = ["As", "Kd", "7c"]
    assert tracker.aplicar(estado(flop), mano=1) == []
    assert tracker.aplicar(estado(flop), mano=1) == flop

    corregido = ["Ac", "Kd", "7c", "2h"]
    primero = estado(corregido)
    assert tracker.aplicar(primero, mano=1) == flop
    assert "pendiente" in primero["warnings"][0]
    assert tracker.aplicar(estado(corregido), mano=1) == corregido


def test_una_sola_contradiccion_no_reescribe_el_board():
    tracker = BoardTracker(confirmaciones=2)
    correcto = ["As", "Kd", "7c"]
    tracker.aplicar(estado(correcto), mano=1)
    assert tracker.aplicar(estado(correcto), mano=1) == correcto

    corrupto = estado(["Ac", "Kd", "7c"])
    assert tracker.aplicar(corrupto, mano=1) == correcto
    assert "pendiente" in corrupto["warnings"][0]


def test_un_slot_incompleto_no_comprime_ni_borra_el_board_confirmado():
    tracker = BoardTracker(confirmaciones=1)
    assert tracker.aplicar(estado(["As", "Kd", "7c"]), mano=1) == ["As", "Kd", "7c"]

    parcial = estado([])
    parcial["board_slots"] = ["As", "Kd", "7c", None]
    parcial["board_detected_count"] = 4
    assert tracker.aplicar(parcial, mano=1) == ["As", "Kd", "7c"]
    assert "incompleta" in parcial["warnings"][0]


def test_un_turn_parcial_puede_confirmar_el_prefijo_del_flop():
    tracker = BoardTracker()
    assert tracker.aplicar(estado(["As", "Kd", "7c"]), mano=1) == []

    parcial = estado([])
    parcial["board_slots"] = ["As", "Kd", "7c", None]
    parcial["board_detected_count"] = 4
    assert tracker.aplicar(parcial, mano=1) == ["As", "Kd", "7c"]
    assert "incompleta" in parcial["warnings"][0]


def test_fusiona_huecos_por_slot_cuando_cada_carta_se_repite():
    tracker = BoardTracker()

    izquierda = estado([])
    izquierda["board_slots"] = ["As", "Kd", None]
    derecha = estado([])
    derecha["board_slots"] = ["As", None, "7c"]

    assert tracker.aplicar(izquierda, mano=1) == []
    assert tracker.aplicar(derecha, mano=1) == []
    assert tracker.aplicar(izquierda, mano=1) == []
    assert tracker.aplicar(derecha, mano=1) == ["As", "Kd", "7c"]


def test_no_fusiona_una_carta_que_solo_aparecio_una_vez():
    tracker = BoardTracker()

    con_tercera = estado([])
    con_tercera["board_slots"] = ["As", None, "7c"]
    sin_tercera = estado([])
    sin_tercera["board_slots"] = ["As", "Kd", None]

    tracker.aplicar(con_tercera, mano=1)
    tracker.aplicar(sin_tercera, mano=1)
    tracker.aplicar(sin_tercera, mano=1)

    assert tracker.aplicar(sin_tercera, mano=1) == []


def test_una_contradiccion_reinicia_solo_el_candidato_de_ese_slot():
    tracker = BoardTracker()

    uno = estado([])
    uno["board_slots"] = ["As", "Kd", None]
    dos = estado([])
    dos["board_slots"] = ["As", "Qd", "7c"]
    tres = estado([])
    tres["board_slots"] = ["As", None, "7c"]

    tracker.aplicar(uno, mano=1)
    tracker.aplicar(uno, mano=1)
    tracker.aplicar(dos, mano=1)
    tracker.aplicar(tres, mano=1)

    assert tracker.aplicar(tres, mano=1) == []


def test_la_fusion_de_slots_no_cruza_el_limite_de_mano():
    tracker = BoardTracker()

    viejo = estado([])
    viejo["board_slots"] = ["As", "Kd", None]
    tracker.aplicar(viejo, mano=1)
    tracker.aplicar(viejo, mano=1)

    nuevo = estado([])
    nuevo["board_slots"] = ["As", None, "7c"]
    tracker.aplicar(nuevo, mano=2)
    tracker.aplicar(nuevo, mano=2)

    assert tracker.aplicar(nuevo, mano=2) == []


def test_mano_nueva_no_hereda_el_board_anterior():
    tracker = BoardTracker(confirmaciones=1)
    assert tracker.aplicar(estado(["As", "Kd", "7c"]), mano=1) == ["As", "Kd", "7c"]
    assert tracker.aplicar(estado([]), mano=2) == []
    assert tracker.aplicar(estado(["Qh", "Qs", "2d"]), mano=2) == ["Qh", "Qs", "2d"]


@pytest.mark.parametrize("board", [["As"], ["As", "Kd"], ["As"] * 3, ["As", "Kd", "As"]])
def test_descarta_boards_ilegales(board):
    tracker = BoardTracker(confirmaciones=1)
    s = estado(board)
    assert tracker.aplicar(s, mano=1) == []
    assert "inválida" in s["warnings"][0]


def test_valida_los_parametros():
    for valor in (0, True, "2"):
        with pytest.raises(ValueError):
            BoardTracker(confirmaciones=valor)


def test_un_flop_pendiente_no_se_convierte_en_una_recomendacion_preflop():
    tracker = BoardTracker()
    state = {
        "board": ["As", "Kd", "7c"],
        "board_detected_count": 3,
        "hero_cards": ["Ah", "Kh"],
        "hero_position": "BTN",
        "facing": None,
        "stack_unit": "bb",
        "warnings": [],
        "mano_seguida": 1,
        "players": [{
            "seat": "HERO",
            "position": "BTN",
            "is_hero": True,
            "stack": 40.0,
            "in_hand": True,
        }],
    }

    tracker.aplicar(state, mano=1)

    assert state["board"] == []
    assert engine.decide(state, context=engine.DecisionContext()) is None
    assert any("3 caja(s)" in warning for warning in state["warnings"])
