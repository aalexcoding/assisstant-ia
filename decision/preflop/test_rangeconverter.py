from decision import engine
from decision.preflop import rangeconverter as rc
from decision.preflop.actions import translate_action


def test_cada_profundidad_tiene_los_28_emparejamientos_8max_completos():
    data = rc.data()
    tables = data["response_to_3bet"]
    assert set(tables) == {"20", "30", "40", "50", "60", "100"}
    for table in tables.values():
        matchups = [
            buckets
            for opponents in table.values()
            for buckets in opponents.values()
        ]
        assert len(matchups) == 28
        assert all(sum(map(len, buckets.values())) == 169
                   for buckets in matchups)
    assert all(
        len(positions) in (6, 7)
        and all(sum(map(len, buckets.values())) == 169
                for buckets in positions.values())
        for positions in data["open_raise"].values()
    )
    assert "SB" not in data["open_raise"]["50"], (
        "el PDF de 50 BB no publica SB; no se rellena la zona vacía con folds")


def test_celdas_visibles_del_pdf_40bb_btn_vs_sb():
    buckets = rc.data()["response_to_3bet"]["40"]["BTN"]["SB"]
    action_by_hand = {
        hand: action
        for action, hands in buckets.items()
        for hand in hands
    }
    assert action_by_hand["AA"] == "CALL"
    assert action_by_hand["AKs"] == "ALL IN"
    assert action_by_hand["A3s"] == "CALL 50% / ALL IN 50%"
    assert action_by_hand["92s"] == "NOT_IN_RFI"


def test_lookup_no_extrapola_ni_fuera_del_rfi():
    assert rc.recommend_response_to_3bet(
        ["As", "Kh"], "BTN", "SB", 10.0) is None
    result = rc.recommend_response_to_3bet(
        ["9s", "2s"], "BTN", "SB", 40.0)
    assert result["action"] == "NOT_IN_RFI"


def test_lookup_conserva_la_mezcla_al_cincuenta_por_ciento():
    result = rc.recommend_response_to_3bet(
        ["As", "3s"], "BTN", "SB", 40.0)
    assert result["action"] == "CALL 50% / ALL IN 50%"
    assert result["stack_key"] == 40.0
    assert result["source_url"].endswith(
        "8-max-MTT-40bb-Tournament-Poker-Charts")


def test_rfi_rellena_sb_50bb_solo_entre_las_tablas_40_y_60():
    result = rc.recommend_open_raise(["As", "5s"], "SB", 50)
    assert result["action"] == "OPEN RAISE 75% / LIMP 25%"
    assert result["action_probabilities"] == {
        "OPEN RAISE": 0.75,
        "LIMP": 0.25,
    }
    assert result["source"] == "interpolated_chart"
    assert result["donor_stack_keys"] == [40.0, 60.0]
    assert len(result["source_urls"]) == 2


def test_respuesta_a_3bet_interpola_entre_dos_profundidades_normales():
    result = rc.recommend_response_to_3bet(
        ["2s", "2h"], "BTN", "SB", 45, threebet_all_in=False)
    assert result["action"] == "CALL 75% / ALL IN 25%"
    assert result["source"] == "interpolated_chart"
    assert result["donor_stack_keys"] == [40.0, 50.0]


def test_respuesta_a_3bet_no_cruza_shove_20bb_con_3bet_normal_30bb():
    assert rc.recommend_response_to_3bet(
        ["As", "Ah"], "BTN", "SB", 25, threebet_all_in=False) is None


def test_respuesta_a_3bet_se_abstiene_si_un_donante_esta_fuera_del_rfi():
    assert rc.recommend_response_to_3bet(
        ["5s", "3s"], "BTN", "SB", 45,
        threebet_all_in=False,
    ) is None


def test_rfi_60bb_coincide_con_celdas_visibles_del_pdf():
    assert rc.recommend_open_raise(["As", "Ah"], "EP1", 60)["action"] == (
        "OPEN RAISE")
    assert rc.recommend_open_raise(["As", "2s"], "EP1", 60)["action"] == "FOLD"
    assert rc.recommend_open_raise(["Ks", "6s"], "EP1", 60)["action"] == (
        "FOLD 50% / OPEN RAISE 50%")


def _response_state(cards=("As", "Ah"), *, max_players=8, caller=False,
                    rival_action="raise", hero_position="BTN",
                    rival_position="SB"):
    actions = [
        {"seat": "HERO", "position": hero_position, "accion": "raise", "t": 1.0},
    ]
    if caller:
        actions.append(
            {"seat": "COLD", "position": "SB", "accion": "call", "t": 2.0})
    actions.append({
        "seat": "RIVAL",
        "position": rival_position,
        "accion": rival_action,
        "t": 3.0,
    })
    return {
        "board": [],
        "hero_cards": list(cards),
        "hero_position": hero_position,
        "stack_unit": "bb",
        "max_players": max_players,
        "mano_seguida": 1,
        "warnings": [],
        "acciones": {"acciones": actions, "completo": False},
        "players": [
            {
                "seat": "HERO", "position": hero_position, "is_hero": True,
                "stack": 38.0, "committed": 2.0,
            },
            {
                "seat": "RIVAL", "position": rival_position,
                "stack": 32.0, "committed": 8.0,
            },
            {
                "seat": "COLD", "position": "SB",
                "stack": 38.0, "committed": 2.0,
            } if caller else {
                "seat": "BB", "position": "BB",
                "stack": 39.0, "committed": 1.0,
            },
        ],
    }


def test_engine_cubre_open_del_hero_seguido_de_3bet():
    result = engine.decide(
        _response_state(), context=engine.DecisionContext())
    assert result is not None
    assert result["action"] == "CALL"
    assert result["facing_used"] == "response_to_3bet"
    assert result["effective_stack_bb"] == 40.0
    assert result["source"] == "rangeconverter_public_chart"


def test_engine_expone_frecuencias_y_donantes_en_respuesta_interpolada():
    state = _response_state(cards=("2s", "2h"))
    hero = next(p for p in state["players"] if p["seat"] == "HERO")
    rival = next(p for p in state["players"] if p["seat"] == "RIVAL")
    hero["stack"] = 43.0
    rival["stack"] = 37.0
    result = engine.decide(state, context=engine.DecisionContext())
    assert result["action"] == "CALL 75% / ALL IN 25%"
    assert result["action_es"] == (
        "pagar el 75% / con todo (all in) el 25%")
    assert result["source"] == "interpolated_chart"
    assert result["effective_stack_bb"] == 45.0
    assert result["donor_stack_keys"] == [40.0, 50.0]
    assert "interpolación lineal" in result["reasoning"]


def test_engine_no_convierte_un_squeeze_multiway_en_3bet_heads_up():
    state = _response_state(caller=True)
    assert engine.decide(state, context=engine.DecisionContext()) is None
    assert any("squeeze multiway" in warning for warning in state["warnings"])


def test_engine_se_abstiene_si_la_mano_no_estaba_en_el_rfi_fuente():
    state = _response_state(cards=("9s", "2s"))
    assert engine.decide(state, context=engine.DecisionContext()) is None
    assert any("no forma parte del RFI" in warning for warning in state["warnings"])


def test_engine_no_usa_respuesta_a_3bet_normal_contra_un_allin_40bb():
    state = _response_state(rival_action="allin")
    assert engine.decide(state, context=engine.DecisionContext()) is None
    assert any("3bet normal" in warning for warning in state["warnings"])


def test_engine_espera_el_importe_para_no_confundir_subir_con_allin():
    state = _response_state()
    rival = next(p for p in state["players"] if p["seat"] == "RIVAL")
    rival["committed"] = 0.0
    assert engine.decide(state, context=engine.DecisionContext()) is None
    assert any("primera línea de un all-in" in warning
               for warning in state["warnings"])


def test_engine_deja_de_extrapolar_40bb_en_rfi_profundo():
    state = {
        "board": [],
        "hero_cards": ["As", "Ah"],
        "hero_position": "HJ",
        "stack_unit": "bb",
        "max_players": 8,
        "mano_seguida": 1,
        "warnings": [],
        "players": [{
            "seat": "HERO", "position": "HJ", "is_hero": True,
            "stack": 60.0, "committed": 0.0,
        }],
    }
    result = engine.decide(state, context=engine.DecisionContext())
    assert result["action"] == "OPEN RAISE"
    assert result["source"] == "rangeconverter_public_chart"
    assert result["stack_bb"] == 60.0


def test_engine_rellena_el_hueco_sb_50bb_con_interpolacion_trazable():
    state = {
        "board": [],
        "hero_cards": ["As", "5s"],
        "hero_position": "SB",
        "stack_unit": "bb",
        "max_players": 8,
        "mano_seguida": 1,
        "warnings": [],
        "players": [{
            "seat": "HERO", "position": "SB", "is_hero": True,
            "stack": 50.0, "committed": 0.0,
        }],
    }
    result = engine.decide(state, context=engine.DecisionContext())
    assert result["action"] == "OPEN RAISE 75% / LIMP 25%"
    assert result["source"] == "interpolated_chart"
    assert result["donor_stack_keys"] == [40.0, 60.0]
    assert result["action_probabilities"] == {
        "OPEN RAISE": 0.75,
        "LIMP": 0.25,
    }
    assert any("no es una celda publicada" in assumption
               for assumption in result["assumptions"])


def test_engine_fuera_de_100bb_conserva_fallback_local_y_lo_avisa():
    state = {
        "board": [],
        "hero_cards": ["As", "Ah"],
        "hero_position": "HJ",
        "stack_unit": "bb",
        "max_players": 8,
        "mano_seguida": 1,
        "warnings": [],
        "players": [{
            "seat": "HERO", "position": "HJ", "is_hero": True,
            "stack": 120.0,
        }],
    }
    result = engine.decide(state, context=engine.DecisionContext())
    assert result is not None
    assert result["source"] == "chart"
    assert any("FUERA de tu tabla" in warning for warning in state["warnings"])


def test_traduce_una_mezcla_nueva_sin_perder_frecuencias():
    assert translate_action("CALL 50% / ALL IN 50%") == (
        "CALL 50% / ALL IN 50%",
        "pagar el 50% / con todo (all in) el 50%",
    )
    assert translate_action("CALL 50% / 4BET NON-ALL-IN 50%")[1] == (
        "pagar el 50% / resubir sin ir all in el 50%")
