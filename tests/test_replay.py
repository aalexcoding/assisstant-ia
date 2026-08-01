import json

import replay


def test_el_replay_usa_mesa_y_mazo_de_la_sesion(tmp_path):
    (tmp_path / "_sesion.json").write_text(json.dumps({
        "max_players": 8,
        "mazo": "solid",
    }))

    assert replay.configuracion_sesion(str(tmp_path)) == (8, "solid")


def test_un_numero_de_plazas_explicito_manda_sobre_la_sesion(tmp_path):
    (tmp_path / "_sesion.json").write_text(json.dumps({
        "max_players": 6,
        "mazo": None,
    }))

    assert replay.configuracion_sesion(str(tmp_path), max_players=9) == (9, None)


def test_una_sesion_sin_metadata_cae_al_mazo_principal(tmp_path):
    assert replay.configuracion_sesion(str(tmp_path)) == (None, "solid")
