"""Los ejemplos numéricos son los del artículo que cita el módulo, no valores
inventados para que cuadre: https://blog.gtowizard.com/mdf-alpha/"""
import pytest

from decision import gto


def test_alpha_y_mdf_del_ejemplo_publicado():
    """60 en un bote de 100: 37,5% de foldeos necesarios, 62,5% de defensa."""
    assert gto.alpha(60, 100) == pytest.approx(0.375)
    assert gto.mdf(60, 100) == pytest.approx(0.625)


def test_una_subida_no_se_cuenta_como_una_apuesta():
    """El caso que más fácil se calcula mal: se apuesta 60 en 100, el rival sube
    a 200. Arriesga 200 para ganar 160, no para ganar 260."""
    assert gto.alpha_de_subida(200, 160) == pytest.approx(0.5555, abs=1e-4)
    assert gto.alpha(200, 260) != pytest.approx(0.5555, abs=1e-4)


@pytest.mark.parametrize("pct, ratio", [
    (33, 4.03), (50, 3.0), (66, 2.51), (100, 2.0), (125, 1.8),
])
def test_ratio_valor_farol_por_tamano(pct, ratio):
    """La tabla del resumen: 33%->4:1 · 50%->3:1 · 66%->2,5:1 · 100%->2:1."""
    assert gto.ratio_valor_farol(pct, 100) == pytest.approx(ratio, abs=0.01)


def test_la_fraccion_de_farol_es_la_inversa_del_ratio():
    for pct in (25, 33, 50, 75, 100, 150):
        f = gto.fraccion_farol(pct, 100)
        assert (1 - f) / f == pytest.approx(gto.ratio_valor_farol(pct, 100), abs=1e-6)


def test_equity_requerida_usa_el_bote_ya_con_la_apuesta_dentro():
    """Apuesta de bote: 100 para ganar 200+100. El 33% clásico."""
    assert gto.equity_requerida(100, 200) == pytest.approx(1 / 3, abs=1e-4)


def test_los_dos_convenios_de_bote_dan_lo_mismo():
    """Es la garantía de que no se puede mezclar sin que salte: alpha con el
    bote previo y alpha con el bote de la pantalla son el mismo número cuando se
    les da la MISMA situación."""
    bote_antes, apuesta = 100, 60
    mostrado = bote_antes + apuesta
    assert gto.alpha_desde_bote_mostrado(apuesta, mostrado) == pytest.approx(
        gto.alpha(apuesta, bote_antes))
    assert gto.mdf_desde_bote_mostrado(apuesta, mostrado) == pytest.approx(
        gto.mdf(apuesta, bote_antes))


def test_confundir_los_dos_botes_da_un_numero_plausible_y_distinto():
    """Justificación de que existan dos funciones y no una: con una apuesta de
    bote, usar el bote mostrado como si fuera el previo da 33% donde toca 50%."""
    assert gto.alpha(100, 200) == pytest.approx(1 / 3, abs=1e-4)
    assert gto.alpha_desde_bote_mostrado(100, 200) == pytest.approx(0.5)


def test_ev_de_un_farol_de_bote():
    """125 en un bote de 100 que se paga el 40%: +10 fichas."""
    assert gto.ev_farol(0.60, 100, 125) == pytest.approx(10.0)


def test_el_breakeven_del_ev_es_exactamente_alpha():
    a = gto.alpha(125, 100)
    assert gto.ev_farol(a, 100, 125) == pytest.approx(0.0, abs=1e-9)


def test_faroles_permitidos_por_combos_de_valor():
    """Con 12 combos de valor y apuesta de bote (2:1) caben 6 faroles."""
    assert gto.faroles_permitidos(12, 100, 100) == pytest.approx(6.0)


def test_bote_antes_de_rechaza_una_lectura_imposible():
    """Si el bote mostrado no es mayor que la apuesta, una de las dos lecturas
    del OCR está mal y no se devuelve un bote de 0 ni negativo."""
    assert gto.bote_antes_de(160, 60) == 100
    assert gto.bote_antes_de(60, 60) is None
    assert gto.bote_antes_de(50, 60) is None


@pytest.mark.parametrize("apuesta, bote", [
    (0, 100), (-5, 100), (100, 0), (100, -1), (None, 100), (100, None),
    (True, 100), (100, True), ("60", 100),
])
def test_se_abstiene_en_vez_de_devolver_cero(apuesta, bote):
    """Un 0 silencioso aquí se leería como 'no necesita foldeos nunca'."""
    assert gto.alpha(apuesta, bote) is None
    assert gto.mdf(apuesta, bote) is None
    assert gto.resumen(apuesta, bote) is None


def test_resumen_nombra_el_tamano_sobre_el_bote_previo():
    r = gto.resumen(66, 100)
    assert r["tamano_pct"] == pytest.approx(66.0)
    assert r["alpha"] == pytest.approx(0.3976, abs=1e-3)
    assert r["mdf"] == pytest.approx(0.6024, abs=1e-3)
    assert r["fuente_url"] == gto.FUENTE_URL
