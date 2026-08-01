"""
Verificacion de lookup.py contra casos leidos A MANO de ranges.json.

Los valores esperados no salen de otra funcion del repo: se miraron en el JSON
generado por parse_ranges.py. Si un dia se redigitalizan los rangos y estos
casos dejan de cumplirse, hay que volver a mirar el JSON, no ajustar el test.
"""
import pytest

from decision.preflop.lookup import normalize_hand, recommend


# --- normalizacion de la mano a la notacion del rango ------------------------

@pytest.mark.parametrize("cartas, esperado", [
    (["Ks", "Td"], "KTo"),
    (["9d", "4d"], "94s"),
    (["Ah", "Ad"], "AA"),
    (["Ah", "Ah"], None),          # cartas repetidas: lectura imposible
    (["Ah"], None),                # mano incompleta
])
def test_normalize_hand(cartas, esperado):
    assert normalize_hand(cartas) == esperado


# --- casos verificados a mano en ranges.json ---------------------------------

def test_btn_40bb_kts_abre_subiendo():
    r = recommend(["Kd", "Td"], "BTN", 40, facing="open_raise")
    assert r is not None
    assert r["action"] == "OPEN RAISE (2 BB)"


def test_una_profundidad_sin_clave_exacta_cae_en_la_mas_cercana():
    """38bb no es una clave de la tabla; la mas cercana es 40."""
    r = recommend(["Kd", "Td"], "BTN", 38, facing="open_raise")
    assert r is not None
    assert r["action"] == "OPEN RAISE (2 BB)"


def test_btn_40bb_94s_es_fold():
    r = recommend(["9d", "4d"], "BTN", 40, facing="open_raise")
    assert r is not None
    assert r["action"] == "fold"


def test_el_vocabulario_de_acciones_no_esta_cerrado():
    """A 20bb el BTN con KTs LIMPEA: no es ni OPEN RAISE ni fold. La etiqueta se
    devuelve tal cual sale de la leyenda, sin traducirla a un enum propio."""
    r = recommend(["Kd", "Td"], "BTN", 20, facing="open_raise")
    assert r is not None
    assert r["action"] == "LIMP"


# --- ausencias que son correctas: no hay datos porque el spot no existe ------

def test_la_bb_no_tiene_rango_de_apertura():
    """La BB nunca abre bote: habla la ultima preflop."""
    assert recommend(["Ah", "Ad"], "BB", 40, facing="open_raise") is None


def test_ep1_no_tiene_rango_de_defensa():
    """EP1 abre el primero, asi que nunca enfrenta una apertura ajena."""
    assert recommend(["Ah", "Ad"], "EP1", 15, facing="threebet_call",
                     vs_position="BTN") is None


def test_defensa_sb_vs_btn():
    assert recommend(["Ah", "Ad"], "SB", 15, facing="threebet_call",
                     vs_position="BTN") is not None


def test_defensa_bb_vs_mp1_20bb_recuperada_de_la_captura_6():
    """La imagen fuente existía, pero el ranges.json antiguo había perdido el
    spot completo al sobrescribir una posición OCR duplicada."""
    result = recommend(["Ah", "Ad"], "BB", 20, facing="threebet_call",
                       vs_position="MP1")
    assert result is not None
    assert result["action"] == "3BET (5 BB)"


# --- datos ausentes: se calla, no adivina ------------------------------------

@pytest.mark.parametrize("desc, kwargs", [
    ("threebet_call sin vs_position",
     dict(hero_cards=["Ah", "Ad"], hero_position="SB", stack_bb=15,
          facing="threebet_call")),
    ("mano incompleta (la vision solo leyo una carta)",
     dict(hero_cards=["Kd"], hero_position="BTN", stack_bb=40)),
    ("sin hero_position",
     dict(hero_cards=["Kd", "Td"], hero_position=None, stack_bb=40)),
])
def test_sin_los_datos_necesarios_devuelve_none(desc, kwargs):
    assert recommend(**kwargs) is None, desc
