import pytest

from decision import postflop_math as pm


def state(**overrides):
    base = {
        "board": ["9d", "8h", "5c"],
        "facing": "bet",
        "pot": 5.75,
        "to_call": 1.0,
        "players": [
            {"is_hero": True, "in_hand": True, "stack": 24.0},
            {"is_hero": False, "in_hand": True, "stack": 19.0},
        ],
    }
    base.update(overrides)
    return base


def test_pot_de_pokerstars_ya_incluye_la_apuesta_rival():
    """Frame real 0400: centro 4,75 + apuesta 1 = etiqueta Bote 5,75."""
    r = pm.calcular(state())
    assert r["final_pot_bb"] == 6.75
    assert r["required_equity"] == pytest.approx(1 / 6.75, abs=0.0001)
    assert r["pot_includes_opponent_bet"] is True
    assert r["effective_stack_bb"] == 19.0
    assert r["current_spr"] == pytest.approx(19 / 5.75, abs=.01)


def test_compara_equity_bruta_sin_convertirla_en_orden():
    r = pm.calcular(state(), {"equity": 0.25})
    assert r["raw_margin_pp"] == pytest.approx(10.2, abs=.1)
    assert r["raw_call_ev_bb"] == pytest.approx(.69, abs=.01)
    assert "CALL" not in r and "FOLD" not in r
    assert "orientativa" in r["note"]


@pytest.mark.parametrize("changes", [
    {"board": []}, {"facing": "check"}, {"facing": None},
    {"pot": None}, {"pot": 0}, {"to_call": None}, {"to_call": 0},
])
def test_se_abstiene_sin_una_decision_de_call_completa(changes):
    assert pm.calcular(state(**changes)) is None


def test_el_precio_viene_con_el_equilibrio_del_mismo_tamano():
    """5,75 de bote CON 1 dentro = apuesta de 1 sobre un bote previo de 4,75, o
    sea el 21%: necesitaba un 17,4% de foldeos y hay que defender el 82,6%."""
    r = pm.calcular(state())
    assert r["bet_pct_of_pot"] == pytest.approx(21.1, abs=0.1)
    assert r["alpha"] == pytest.approx(1 / 5.75, abs=1e-4)
    assert r["mdf"] == pytest.approx(4.75 / 5.75, abs=1e-4)
    assert r["value_to_bluff"] == pytest.approx(5.75, abs=0.01)
    assert r["alpha"] + r["mdf"] == pytest.approx(1.0, abs=1e-3)


def test_un_bote_que_no_supera_la_apuesta_deja_el_equilibrio_en_blanco():
    """El bote mostrado incluye la apuesta rival, así que no puede ser menor.
    Si el OCR devuelve eso, el precio se sigue dando -es una división honesta-
    pero alpha y MDF quedan a None en vez de calcularse sobre un bote negativo."""
    r = pm.calcular(state(pot=1.0, to_call=1.0))
    assert r["required_equity"] == pytest.approx(0.5)
    assert r["alpha"] is None and r["mdf"] is None
    assert r["value_to_bluff"] is None and r["bet_pct_of_pot"] is None


def test_un_call_de_un_bb_postflop_es_valido():
    """El >1 BB preflop distingue una subida de las ciegas; aquí 1 BB sí puede
    ser una apuesta real y el botón ``Igualar 1 BB`` la confirma."""
    assert pm.calcular(state(to_call=1.0)) is not None
