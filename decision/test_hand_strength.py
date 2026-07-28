"""
decision/hand_strength.py con casos conocidos a mano: la mano formada y los
proyectos que se enseñan en el HUD.

Los porcentajes se comprueban EXACTOS (combinatoria) y ademas contra la regla
del 2 y 4, porque son numeros distintos y el HUD enseña los dos: el dia que
alguien "simplifique" usando solo la regla, el doble proyecto pasaria de 54% a
60% y aqui saltaria.
"""
import pytest

from decision import hand_strength as hs


def proyecto(res, aguja):
    """El proyecto cuyo nombre contiene `aguja`, o None."""
    for d in res["draws"]:
        if aguja.lower() in d["name"].lower():
            return d
    return None


# --- mano formada ------------------------------------------------------------

@pytest.mark.parametrize("hero, board, esperado", [
    (["Ah", "Kh"], ["Ac", "Kc", "Qh"], "Doble pareja (Ases y Reyes)"),
    (["As", "Kh"], ["Ah", "Ad", "Kc"], "Full de Ases con Reyes"),
    (["Ts", "Jd"], ["9h", "8c", "7d", "2s"], "Escalera al Jota"),
    (["8h", "8d"], ["8c", "8s", "Kd"], "Poker de Ochos"),
])
def test_nombre_de_la_mano_formada(hero, board, esperado):
    assert hs.evaluate_hand(hero, board)["made_name"] == esperado


def test_doble_pareja_no_tiene_proyectos():
    assert hs.evaluate_hand(["Ah", "Kh"], ["Ac", "Kc", "Qh"])["draws"] == []


def test_color():
    r = hs.evaluate_hand(["3h", "9c"], ["Ah", "7h", "2h", "Kh"])
    assert r["made_category"] == "Color"
    assert "Color de corazones" in r["made_name"]


# --- preflop -----------------------------------------------------------------

@pytest.mark.parametrize("hero, esperado", [
    (["As", "Ks"], "AK suited"),
    (["Ad", "Kc"], "AK offsuit"),
    (["8h", "8d"], "Pareja de Ochos"),
])
def test_preflop(hero, esperado):
    assert hs.evaluate_hand(hero, [])["made_name"] == esperado


# --- proyectos ---------------------------------------------------------------

def test_proyecto_de_color_en_flop():
    r = hs.evaluate_hand(["Ah", "Kh"], ["Th", "7h", "2c"])
    fd = proyecto(r, "color")
    assert fd is not None, "proyecto de color detectado"
    assert fd["outs"] == 9
    assert fd["pct_river"] == 35, "exacto por combinatoria"
    assert fd["pct_river_rule"] == 36, "regla del 4"


def test_escalera_abierta():
    sd = proyecto(hs.evaluate_hand(["Ts", "Js"], ["9h", "8c", "2d"]), "abierta")
    assert sd is not None, "OESD detectada"
    assert sd["outs"] == 8


def test_gutshot():
    gs = proyecto(hs.evaluate_hand(["Js", "Qd"], ["9h", "8c", "2d"]), "gutshot")
    assert gs is not None
    assert gs["outs"] == 4


def test_broadway_es_gutshot_no_escalera_abierta():
    """AKQJ solo liga con una T: son 4 outs, no 8."""
    gs = proyecto(hs.evaluate_hand(["Ah", "Kd"], ["Qs", "Jc", "2d"]), "gutshot")
    assert gs is not None
    assert gs["outs"] == 4


def test_doble_proyecto_color_mas_escalera():
    r = hs.evaluate_hand(["Jh", "8h"], ["Th", "9h", "2c"])
    fd, sd, combo = proyecto(r, "color de"), proyecto(r, "abierta"), proyecto(r, "doble proyecto")
    assert fd is not None and fd["outs"] == 9, "proyecto de color"
    assert sd is not None and sd["outs"] == 8, "escalera abierta"
    assert combo is not None and combo["outs"] == 15, "15 outs LIMPIOS (no 17: dos se solapan)"
    assert combo["pct_river"] == 54, "exacto; la regla del 4 diria 60 y seria optimista"


def test_en_turn_solo_queda_una_carta_por_venir():
    fd = proyecto(hs.evaluate_hand(["Ah", "Kh"], ["Th", "7h", "2c", "3s"]), "color")
    assert fd is not None
    assert fd["pct_river"] is None, "en turn no hay 'al river': la siguiente ES el river"
    assert fd["pct_next"] == 20, "9/46"


def test_en_river_no_hay_proyectos():
    assert hs.evaluate_hand(["Ah", "Kh"], ["Th", "7h", "2c", "3s", "9d"])["draws"] == []


# --- robustez ----------------------------------------------------------------

@pytest.mark.parametrize("hero", [[], ["Ah"]])
def test_sin_las_dos_cartas_del_hero_devuelve_none(hero):
    assert hs.evaluate_hand(hero, []) is None
