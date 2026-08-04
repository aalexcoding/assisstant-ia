import pytest

from decision import postflop_gto as pg


def acciones(*registros):
    """Historial con la ciega puesta primero: estado_preflop descarta lo que no
    sea posterior al último ``post``."""
    base = [{"seat": "S9", "position": "BB", "accion": "post",
             "street": "preflop", "orden": 0, "t": 1.0}]
    for i, (seat, position, accion) in enumerate(registros, start=1):
        base.append({"seat": seat, "position": position, "accion": accion,
                     "street": "preflop", "orden": i, "t": 1.0 + i})
    return {"acciones": base}


def state(**overrides):
    """Hero BTN abrió, la BB pagó, flop K72 arcoíris. Heads-up y en posición."""
    base = {
        "board": ["Kh", "7d", "2c"],
        "hero_cards": ["Ac", "Qs"],
        "hero_position": "BTN",
        "pot": 6.0,
        "to_call": None,
        "facing": "check",
        "stack_unit": "bb",
        "players": [
            {"seat": "HERO", "is_hero": True, "in_hand": True,
             "position": "BTN", "stack": 40.0, "committed_calle": 0.0},
            {"seat": "S9", "is_hero": False, "in_hand": True,
             "position": "BB", "stack": 38.0},
        ],
        "acciones": acciones(("HERO", "BTN", "raise"), ("S9", "BB", "call")),
    }
    base.update(overrides)
    return base


# --- posición ---------------------------------------------------------------

def test_el_boton_habla_el_ultimo_postflop():
    assert pg.posicion_relativa("BTN", [{"position": "BB"}]) == "IP"
    assert pg.posicion_relativa("BB", [{"position": "BTN"}]) == "OOP"


def test_la_sb_abre_la_calle_postflop_aunque_preflop_hable_penultima():
    """El orden postflop NO es el preflop: las ciegas pasan a hablar primero."""
    assert pg.posicion_relativa("SB", [{"position": "EP1"}]) == "OOP"
    assert pg.posicion_relativa("EP1", [{"position": "SB"}]) == "IP"


def test_sin_la_posicion_de_un_rival_no_se_supone_que_hay_posicion():
    assert pg.posicion_relativa("BTN", [{"position": None}]) is None
    assert pg.posicion_relativa(None, [{"position": "BB"}]) is None
    assert pg.posicion_relativa("BTN", []) is None


# --- rama de c-bet ----------------------------------------------------------

def test_cbet_en_board_seco_alta_frecuencia_y_tamano_pequeno():
    """K72 arcoíris: desconectado + arcoíris + carta alta = lo más apostable."""
    r = pg.evaluar(state(), {"equity": 0.62})
    assert r["spot"] == "cbet"
    assert r["cbet"]["banda_frecuencia"] == "muy alta"
    assert r["cbet"]["tamano_pct_del_bote"] == 33
    assert r["cbet"]["tamano_bb"] == pytest.approx(1.98)
    assert r["action"] == "BET (1.98 BB)"
    assert r["action_es"] == "apostar a 1,98 BB"


def test_el_monocolor_hunde_la_frecuencia():
    """La fuente lo dice con esa palabra: en monocolor la caída es drástica.

    Se comprueba la CAÍDA (dos bandas enteras sobre el mismo board cambiando
    solo los palos) y no una banda concreta: el mismo K72 pasa de la banda más
    alta a la del medio. Fijar aquí una etiqueta absoluta ataría el test a los
    pesos y no a lo que dice la fuente.
    """
    bandas = [b for _u, b, _g in pg._BANDAS]
    seco = pg.evaluar(state(), {"equity": 0.5})["cbet"]
    mono = pg.evaluar(state(board=["Kh", "7h", "2h"]), {"equity": 0.5})["cbet"]
    assert mono["puntos_textura"] < seco["puntos_textura"]
    assert (bandas.index(mono["banda_frecuencia"])
            - bandas.index(seco["banda_frecuencia"])) >= 2
    assert mono["tamano_pct_del_bote"] == 33


def test_el_board_emparejado_se_apuesta_mas_pero_pequeno():
    r = pg.evaluar(state(board=["7h", "7d", "2c"]), {"equity": 0.5})["cbet"]
    assert r["tamano_pct_del_bote"] == 33
    assert any("emparejado" in d["factor"] for d in r["detalle_textura"])
    assert "trío" in r["motivo_tamano"]


def test_con_proyecto_de_escalera_sube_el_tamano_por_proteccion():
    r = pg.evaluar(state(board=["Th", "9d", "4c"]), {"equity": 0.5})["cbet"]
    assert r["tamano_pct_del_bote"] == 66
    assert r["alternativa_polarizada_pct"] is None


def test_el_board_desconectado_ofrece_la_alternativa_polarizada():
    r = pg.evaluar(state(), {"equity": 0.5})["cbet"]
    assert r["alternativa_polarizada_pct"] == 130
    assert "ventaja de nuts" in pg.evaluar(state(), {"equity": 0.5})["reasoning"]


def test_la_banda_de_frecuencia_solo_se_da_en_el_flop():
    """La fuente se titula 'Flop Heuristics' y ordena texturas por cuánto se
    apuesta EN EL FLOP. En turn y river la frecuencia correcta depende además de
    la carta que ha caído y de cómo se partió el rango antes, que aquí no se
    miran: se omite en vez de extrapolarla."""
    flop = pg.evaluar(state(), {"equity": 0.5})
    assert flop["cbet"]["banda_frecuencia"] == "muy alta"

    for board, calle in ((["Kh", "7d", "2c", "4s"], "turn"),
                         (["Kh", "7d", "2c", "4s", "9h"], "river")):
        r = pg.evaluar(state(board=board), {"equity": 0.5})
        assert r["cbet"]["banda_frecuencia"] is None
        assert r["cbet"]["puntos_textura"] is None
        assert f"esto es el {calle}" in r["reasoning"]
        assert any(calle in s for s in r["assumptions"])


def test_en_turn_y_river_se_conservan_tamano_y_aritmetica():
    """El sizing habla de lo que el board permite al defensor y eso no deja de
    ser cierto porque caiga otra carta; alpha y el ratio son aritmética del
    bote, exactos en cualquier calle."""
    r = pg.evaluar(state(board=["9h", "8h", "5h", "2d"]), {"equity": 0.5})
    assert r["action"].startswith("BET")
    assert r["cbet"]["tamano_pct_del_bote"] == 33     # color posible: pequeño
    assert r["cbet"]["alpha"] == pytest.approx(0.2481, abs=1e-3)
    assert r["cbet"]["ratio_valor_farol"] == pytest.approx(4.03, abs=0.01)
    assert "trasladado al turn" in r["confidence"]


def test_multiway_recorta_la_frecuencia_y_lo_dice():
    tres = state()
    tres["players"] = tres["players"] + [
        {"seat": "S5", "is_hero": False, "in_hand": True,
         "position": "CO", "stack": 30.0}]
    r = pg.evaluar(tres, {"equity": 0.5})
    assert r["rivales_vivos"] == 2
    assert r["cbet"]["puntos_textura"] < pg.evaluar(
        state(), {"equity": 0.5})["cbet"]["puntos_textura"]
    assert any("ajuste conservador propio" in s for s in r["assumptions"])


def test_fuera_de_posicion_lo_avisa_y_baja_la_confianza():
    """La fuente resuelve la c-bet EN posición; trasladarla se dice."""
    oop = state(hero_position="SB")
    oop["players"][0]["position"] = "SB"
    r = pg.evaluar(oop, {"equity": 0.5})
    assert r["posicion"] == "OOP"
    assert "FUERA de posición" in r["reasoning"]
    assert "media-baja" in r["confidence"]


def test_sin_iniciativa_no_hay_cbet():
    """Si el que abrió fue el rival, esto es un donk-bet y está fuera de lo
    importado: la fuente cubre la continuación del AGRESOR."""
    sin = state(acciones=acciones(("S9", "BB", "raise"), ("HERO", "BTN", "call")))
    r = pg.evaluar(sin, {"equity": 0.5})
    assert r["spot"] == "sin_iniciativa"
    assert "action" not in r
    assert "donk-bet" in r["motivo"]


def test_sin_botones_leidos_se_da_la_guia_pero_se_avisa():
    """Los botones solo se leen en el 10% de los frames; exigirlos dejaría el
    panel vacío casi siempre. Mismo criterio que decide() en preflop."""
    r = pg.evaluar(state(facing=None), {"equity": 0.5})
    assert r["action"].startswith("BET")
    assert any("no sea tu turno" in w for w in r["warnings"])


# --- rama de defensa --------------------------------------------------------

def defendiendo(**overrides):
    base = dict(facing="bet", to_call=2.0, pot=8.0)
    base.update(overrides)
    return state(**base)


def test_defensa_calcula_alpha_mdf_y_precio_del_tamano_real():
    """8 BB de bote CON los 2 dentro = apuesta de 2 en un bote previo de 6, o
    sea un tercio: alpha 25%, MDF 75%, equilibrio 4:1."""
    r = pg.evaluar(defendiendo(), {"equity": 0.35})
    p = r["precio"]
    assert p["tamano_rival_pct"] == pytest.approx(33.3, abs=0.1)
    assert p["alpha_rival"] == pytest.approx(0.25)
    assert p["mdf"] == pytest.approx(0.75)
    assert p["ratio_valor_farol_equilibrado"] == pytest.approx(4.0)
    assert p["equity_requerida"] == pytest.approx(0.20)


def test_call_cuando_la_equity_supera_el_precio_con_margen():
    r = pg.evaluar(defendiendo(), {"equity": 0.35})
    assert r["action"] == "CALL"
    assert r["precio"]["margen_pp"] == pytest.approx(15.0)


def test_fold_por_debajo_del_precio():
    r = pg.evaluar(defendiendo(), {"equity": 0.15})
    assert r["action"] == "FOLD"
    assert "techo" in r["reasoning"]


def test_empate_tecnico_no_se_convierte_en_una_orden_limpia():
    """Entre el precio y el precio+margen la etiqueta es MARGINAL: la equity
    está calculada contra rangos de entrada y sobreestima."""
    r = pg.evaluar(defendiendo(), {"equity": 0.22})
    assert r["action"] == "MARGINAL CALL"
    assert r["action_es"] == "pagar, justo"


def test_con_mucha_ventaja_propone_subir_y_cuantifica_la_subida():
    r = pg.evaluar(defendiendo(), {"equity": 0.80})
    assert r["action"] == "RAISE (6 BB)"
    assert r["subida"]["a_bb"] == pytest.approx(6.0)
    # 6 arriesgadas para ganar el bote de 8 que ya está en la mesa
    assert r["subida"]["alpha"] == pytest.approx(6 / 14, abs=1e-3)


def test_si_el_hero_ya_aposto_esta_calle_no_se_propone_un_tamano_de_subida():
    """3x describe una SUBIDA sobre la apuesta del rival. Si el hero ya había
    apostado, lo que tiene delante es una resubida y ese múltiplo daría un
    importe que no corresponde a ninguna acción real."""
    st = defendiendo()
    st["players"][0]["committed_calle"] = 2.0
    r = pg.evaluar(st, {"equity": 0.80})
    assert r["action"] == "CALL"
    assert "subida" not in r
    assert "RESUBIDA" in r["reasoning"]


def test_sin_saber_lo_puesto_en_la_calle_tampoco_se_inventa_la_subida():
    """Las sesiones grabadas antes de que existiera el campo no lo traen."""
    st = defendiendo()
    st["players"][0].pop("committed_calle")
    assert pg.evaluar(st, {"equity": 0.80})["action"] == "CALL"


def test_sin_equity_hay_precio_y_mdf_pero_no_accion():
    r = pg.evaluar(defendiendo(), None)
    assert r["precio"]["mdf"] == pytest.approx(0.75)
    assert "action" not in r
    assert "sin equity estimada" in r["motivo"]


def test_un_bote_que_no_supera_la_apuesta_no_produce_un_mdf_inventado():
    """PokerStars dibuja el bote CON la apuesta dentro; si el OCR devuelve un
    bote menor, una de las dos lecturas está mal."""
    r = pg.evaluar(defendiendo(pot=1.5, to_call=2.0), {"equity": 0.5})
    assert "precio" not in r
    assert "action" not in r
    assert any("incoherentes" in w for w in r["warnings"])


# --- abstenciones -----------------------------------------------------------

@pytest.mark.parametrize("cambio", [
    {"board": []},
    {"board": ["Kh", "7d"]},
    {"hero_cards": []},
    {"hero_cards": ["Ac"]},
    {"hero_cards_dimmed": True},
])
def test_sin_postflop_que_juzgar_devuelve_none(cambio):
    assert pg.evaluar(state(**cambio), {"equity": 0.5}) is None


def test_sin_rivales_vivos_no_se_recomienda_sobre_una_mano_terminada():
    solo = state()
    solo["players"] = [solo["players"][0]]
    r = pg.evaluar(solo, {"equity": 1.0})
    assert "action" not in r
    assert "showdown" in r["motivo"]


def test_siempre_lleva_su_procedencia():
    r = pg.evaluar(state(), {"equity": 0.5})
    assert r["source"] == "gto_heuristics"
    assert r["source_urls"] and all(u.startswith("https://") for u in r["source_urls"])
    assert r["assumptions"]
