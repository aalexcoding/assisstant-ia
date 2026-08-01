import pytest

from decision.rag import strategy_cards as cards


def _context(**changes):
    context = {
        "board": ["Ah", "7d", "2c"],
        "hero_observed": True,
        "street": "flop",
        "pot_type": "single_raised",
        "initiative": "con_iniciativa",
        "position_relation": "IP",
        "opponents": 1,
        "to_call_bb": 0,
        "effective_stack_bb": 30,
        "actions": [],
    }
    context.update(changes)
    return context


def _ids(context):
    return [card["id"] for card in cards.match(context, limit=10)]


def test_textura_estatica_y_dinamica_son_exclusivas():
    assert "static" in cards.board_texture(["Ah", "7d", "2c"])
    assert "dynamic" not in cards.board_texture(["Ah", "7d", "2c"])
    assert "dynamic" in cards.board_texture(["9h", "8h", "7c"])
    assert "static" not in cards.board_texture(["9h", "8h", "7c"])
    assert "dynamic" in cards.board_texture(["Qh", "8d", "7c"])
    assert "static" in cards.board_texture(["Kh", "Qd", "2c"])


def test_el_as_conecta_por_abajo():
    texture = cards.board_texture(["Ah", "2d", "3c"])
    assert "connected" in texture
    assert "dynamic" in texture


def test_cbet_ip_elige_una_ficha_distinta_segun_el_board():
    assert "srp_ip_cbet_static" in _ids(_context())
    assert "srp_ip_cbet_dynamic" not in _ids(_context())
    dynamic = _context(board=["9h", "8h", "7c"])
    assert "srp_ip_cbet_dynamic" in _ids(dynamic)
    assert "srp_ip_cbet_static" not in _ids(dynamic)


def test_no_hay_ficha_de_cbet_si_falta_iniciativa_observada():
    assert "srp_ip_cbet_static" not in _ids(_context(initiative=None))


def test_no_estudia_una_mesa_si_no_se_observaron_cartas_del_hero():
    assert cards.match(_context(hero_observed=False)) == []
    assert cards.match(_context(hero_observed=None)) == []


def test_multiway_activa_su_ficha_y_no_una_regla_heads_up():
    ids = _ids(_context(opponents=2))
    assert ids[0] == "multiway_tight_linear"
    assert "srp_ip_cbet_static" not in ids


def test_distingue_tresbet_de_cuatrobet():
    threebet = _context(
        pot_type="3bet", position_relation="OOP",
        initiative="con_iniciativa")
    assert "threebet_oop_aggressor_cbet" in _ids(threebet)
    assert "fourbet_oop_caller_check" not in _ids(threebet)

    fourbet = _context(
        pot_type="4bet_plus", position_relation="OOP",
        initiative="sin_iniciativa")
    assert "fourbet_oop_caller_check" in _ids(fourbet)
    assert "threebet_oop_aggressor_cbet" not in _ids(fourbet)


def test_defensa_solo_aparece_si_hay_apuesta_que_pagar():
    spot = _context(
        initiative="sin_iniciativa", position_relation="OOP")
    assert "blind_defense_cbet_size" not in _ids(spot)
    assert "blind_defense_cbet_size" in _ids(
        dict(spot, to_call_bb=1.5))
    assert "blind_defense_cbet_size" not in _ids(
        dict(spot, to_call_bb=100))


def test_to_call_ausente_no_se_interpreta_como_check():
    spot = _context(
        initiative="sin_iniciativa", position_relation="IP",
        to_call_bb=None,
        actions=[{"street": "flop", "accion": "check", "seat": "V1"}])
    assert "ip_cold_caller_after_check" not in _ids(spot)


def test_tresbet_ip_distingue_agresor_y_caller():
    aggressor = _context(pot_type="3bet", initiative="con_iniciativa")
    assert "threebet_ip_aggressor_cbet" in _ids(aggressor)
    assert "threebet_ip_caller_position" not in _ids(aggressor)
    caller = dict(aggressor, initiative="sin_iniciativa")
    assert "threebet_ip_caller_position" in _ids(caller)
    assert "threebet_ip_aggressor_cbet" not in _ids(caller)


def test_una_tresbet_identificada_como_squeeze_no_usa_fichas_heads_up():
    spot = _context(
        pot_type="3bet", initiative="con_iniciativa",
        squeeze_observed=True)
    assert not any(card_id.startswith("threebet_") for card_id in _ids(spot))


def test_bluffcatch_river_necesita_call_observado_y_heads_up():
    river = _context(street="river", board=["Ah", "7d", "2c", "9s", "Kd"])
    assert "river_bluffcatch_price_first" not in _ids(river)
    assert "river_bluffcatch_price_first" in _ids(
        dict(river, to_call_bb=4.0))
    assert "river_bluffcatch_price_first" not in _ids(
        dict(river, to_call_bb=4.0, opponents=2))


def test_probe_turn_exige_dos_checks_observados_en_flop():
    spot = _context(
        board=["Ah", "7d", "2c", "9s"], street="turn",
        initiative="sin_iniciativa", position_relation="OOP",
        actions=[
            {"street": "flop", "accion": "check", "seat": "HERO"},
            {"street": "flop", "accion": "check", "seat": "V1"},
        ])
    assert "local_turn_probe_after_xx" in _ids(spot)
    assert "local_turn_probe_after_xx" not in _ids(
        dict(spot, actions=spot["actions"][:1]))


def test_catalogo_es_solo_estudio_y_todas_las_fuentes_son_trazables():
    found_public = found_local = False
    for card in cards.catalog():
        assert card["recommendation_level"] == "study_only"
        assert "action" not in card
        source = card["source"]
        if source["kind"] == "public_guide":
            found_public = True
            assert source["url"].startswith("https://")
        elif source["kind"] == "local_transcript":
            found_local = True
            assert source["video_path"].endswith(".mp4")
            assert source["timestamp_s"] >= 0
        else:
            pytest.fail(f"tipo de fuente desconocido: {source['kind']}")
    assert found_public and found_local


@pytest.mark.parametrize("limit", [0, -1, True, "3"])
def test_limite_invalido(limit):
    with pytest.raises(ValueError, match="entero positivo"):
        cards.match(_context(), limit=limit)
