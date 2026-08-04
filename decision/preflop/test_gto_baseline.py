import pytest

from decision.preflop import gto_baseline as gb
from vision.seat_map import SEATING_BY_N


def test_la_equivalencia_de_posiciones_sale_de_seat_map_y_no_de_los_nombres():
    """El bug que ya se arregló en seat_map y que aquí podía volver a entrar.

    El primero en hablar de una mesa de 6 NO es el 'UTG' del canon de 9: tiene
    cinco jugadores detrás, así que esta app lo llama MP2. Si alguien cambia la
    equivalencia por el nombre bonito, este test cae.
    """
    for plazas in (6, 9):
        orden = SEATING_BY_N[plazas]
        # el orden de habla preflop empieza justo después de la BB
        habla = orden[orden.index("BB") + 1:] + orden[:orden.index("BB") + 1]
        assert gb.posicion_publicada(habla[0], plazas) == "UTG"
    assert gb.posicion_publicada("MP2", 6) == "UTG"
    assert gb.posicion_publicada("EP1", 9) == "UTG"


# --- expansión de la notación ----------------------------------------------

def test_expandir_parejas():
    assert gb.expandir("22+") == {r * 2 for r in "AKQJT98765432"}
    assert gb.expandir("TT") == {"TT"}


def test_expandir_sube_el_kicker_hasta_una_carta_por_debajo_de_la_alta():
    assert gb.expandir("ATs+") == {"ATs", "AJs", "AQs", "AKs"}
    assert gb.expandir("97s+") == {"97s", "98s"}
    assert gb.expandir("KQs+") == {"KQs"}


def test_expandir_respeta_el_palo():
    assert gb.expandir("AJo+") == {"AJo", "AQo", "AKo"}
    assert "AJs" not in gb.expandir("AJo+")


def test_expandir_una_lista_completa():
    assert gb.expandir("22+, ATs+, KQs") == (
        {r * 2 for r in "AKQJT98765432"} | {"ATs", "AJs", "AQs", "AKs", "KQs"})


@pytest.mark.parametrize("token", ["", "A", "AXs", "TTs", "2As", "AK", "ZZ+"])
def test_una_notacion_mal_escrita_revienta_en_vez_de_recortar_el_rango(token):
    """Un rango silenciosamente recortado es un rango demasiado tight que nadie
    nota: la app abriría de menos en TODAS las manos de esa posición."""
    with pytest.raises(ValueError):
        gb.expandir(token)


def test_las_listas_de_manos_cuadran_con_el_rotulo_de_la_fuente():
    """La red que caza una transcripción incompleta.

    Cada fila lleva su porcentaje impreso; si la lista de manos se copió a
    medias, el rango expandido sale mucho más tight que ese rótulo. Así se
    detectó la primera versión de la tabla, a la que le faltaban las manos
    offsuit de CO, BTN y SB en 6-max: el botón daba 30,9% donde el gráfico
    rotula 43%.

    La tolerancia es amplia (5 puntos) a propósito: los rótulos de la fuente
    están redondeados y no cuadran exactamente ni con sus propias listas. Sirve
    para cazar un token perdido, no para auditar al autor del gráfico.
    """
    for plazas, filas in gb._NOTACION.items():
        for posicion, (notacion, pct) in filas.items():
            real = 100.0 * gb.combos(gb.expandir(notacion)) / gb.COMBOS_TOTALES
            assert real == pytest.approx(pct, abs=5.0), (
                f"{plazas}-max {posicion}: la lista abre el {real:.1f}% y el "
                f"gráfico rotula {pct}%")


def test_se_expone_el_porcentaje_real_y_no_solo_el_rotulo():
    """Lo que la app aplica es la LISTA, así que el número que se enseña tiene
    que salir de la lista y no del rótulo."""
    r = gb.recommend(["Ah", "Kd"], "MP2", 6, 100)
    manos, _rotulo, real = gb._rango(6, "UTG")
    assert r["range_pct_real"] == real
    assert r["range_pct"] == 15


# --- recomendación ----------------------------------------------------------

def test_abre_lo_que_esta_en_el_rango_y_foldea_lo_que_no():
    dentro = gb.recommend(["Ah", "Kd"], "EP1", 9, 100)
    assert dentro["action"] == "OPEN RAISE"
    assert dentro["table_position"] == "UTG"
    fuera = gb.recommend(["7h", "2d"], "EP1", 9, 100)
    assert fuera["action"] == "FOLD"


def test_el_rango_se_abre_segun_avanza_la_posicion():
    """ATo no abre UTG en una mesa de 9 y sí desde el botón."""
    assert gb.recommend(["Ah", "Td"], "EP1", 9, 100)["action"] == "FOLD"
    assert gb.recommend(["Ah", "Td"], "BTN", 9, 100)["action"] == "OPEN RAISE"


def test_no_se_sirve_por_debajo_del_punto_medio_con_la_tabla_digitalizada():
    """Por debajo de 70 BB la tabla de 40 BB del usuario está más cerca, así que
    esta no debe desplazarla."""
    assert gb.recommend(["Ah", "Kd"], "BTN", 9, 69.9) is None
    assert gb.recommend(["Ah", "Kd"], "BTN", 9, 70.0) is not None


def test_las_posiciones_intermedias_de_una_mesa_de_nueve_no_se_inventan():
    """La fuente publica UTG, MP, HJ, CO, BTN y SB. El segundo en hablar (EP2)
    y el cuarto (MP2, el 'LJ' del argot) no están y no se interpolan: un rango
    inventado se jugaría igual de convencido que uno publicado."""
    for posicion in ("EP2", "MP2"):
        assert gb.posicion_publicada(posicion, 9) is None
        assert gb.recommend(["Ah", "Kd"], posicion, 9, 100) is None
    # MP sí está publicada, y es el TERCERO en hablar de una mesa de nueve
    assert gb.posicion_publicada("MP1", 9) == "MP"


def test_solo_mesas_de_seis_y_de_nueve():
    for plazas in (2, 3, 5, 7, 8):
        assert gb.recommend(["Ah", "Kd"], "BTN", plazas, 100) is None


@pytest.mark.parametrize("cartas", [[], ["Ah"], ["Ah", "Ah"], ["Xh", "Kd"], None])
def test_sin_dos_cartas_legibles_no_hay_recomendacion(cartas):
    assert gb.recommend(cartas, "BTN", 9, 100) is None


def test_la_confianza_baja_al_alejarse_de_las_cien_ciegas():
    cerca = gb.recommend(["Ah", "Kd"], "BTN", 9, 100)
    lejos = gb.recommend(["Ah", "Kd"], "BTN", 9, 75)
    assert cerca["stack_distance_bb"] == 0.0
    assert lejos["stack_distance_bb"] == 25.0
    assert "media-alta" in cerca["confidence"]
    assert "media-alta" not in lejos["confidence"]


def test_lleva_procedencia_y_supuestos():
    r = gb.recommend(["Ah", "Kd"], "BTN", 6, 100)
    assert r["source"] == "gto_baseline_chart"
    assert r["source_url"].startswith("https://")
    assert any("100 BB" in s for s in r["assumptions"])
    assert any("MP2" in s and "UTG" not in s or "equivale" in s
               for s in r["assumptions"])
