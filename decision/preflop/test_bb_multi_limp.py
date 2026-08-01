import pytest

from decision.preflop import bb_multi_limp as multi


@pytest.mark.parametrize("limpers,size", [(2, 6.0), (3, 7.0), (4, 8.0)])
def test_tamano_suma_base_limpers_y_una_bb_oop(limpers, size):
    assert multi.iso_size_bb(limpers) == size


@pytest.mark.parametrize("limpers", [None, 0, 1, True, 2.5])
def test_no_se_usa_fuera_del_spot_multiway(limpers):
    assert multi.iso_size_bb(limpers) is None


@pytest.mark.parametrize("cards", [("Ah", "Ad"), ("Ks", "Kh")])
def test_aa_kk_suben_por_valor(cards):
    result = multi.recommend(cards, 80.0, 3)
    assert result["action"] == "RAISE OVER LIMPERS (7 BB)"
    assert result["source"] == "public_heuristic"
    assert result["source_url"].startswith("https://")
    assert result["fallback"] is False


def test_premium_con_stack_menor_que_el_tamano_va_allin():
    assert multi.recommend(("Ah", "Ad"), 5.0, 3)["action"] == "ALL IN"


@pytest.mark.parametrize("cards", [
    ("Qh", "Qd"), ("As", "3s"), ("7h", "2c"), ("Th", "9h"),
])
def test_fuera_del_nucleo_premium_el_fallback_es_check(cards):
    result = multi.recommend(cards, 80.0, 3)
    assert result["action"] == "CHECK"
    assert result["source"] == "safety_default"
    assert result["confidence"] == "baja"
    assert result["fallback"] is True
    assert any("falta una tabla multiway" in item
               for item in result["assumptions"])


@pytest.mark.parametrize("cards,stack,limpers", [
    (("Ah",), 80.0, 3),
    (("Ah", "Ad"), None, 3),
    (("Ah", "Ad"), 80.0, 1),
])
def test_datos_incompletos_no_producen_accion(cards, stack, limpers):
    assert multi.recommend(cards, stack, limpers) is None
