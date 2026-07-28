"""
Los rangos de rival (decision/opponent_ranges.py), que hasta ahora no tenian ni
un test pese a ser la pieza que MAS mueve la respuesta del modulo de equity.

Lo dice el propio modulo con numeros: sobre un spot real, la equity del hero pasa
de 28% (rivales con mano aleatoria) a 14% (rango de BTN) a 6% (rango de EP1). El
supuesto de rango pesa mas que ninguna otra decision del modelo, asi que un
error aqui no revienta nada: devuelve un porcentaje plausible y equivocado.

Que se protege, en tres niveles:

  1. LOS PESOS. 169 manos no son 169 casos igual de probables: una pareja son 6
     combinaciones, una suited 4 y una offsuit 12. Muestrear las manos en vez de
     los combos haria AA tan frecuente como AKo, un sesgo de 2x a favor de las
     parejas justo en la parte alta del rango.
  2. LA MONOTONIA. El rango tiene que abrirse de posicion temprana a tardia. Es
     la propiedad que hace que el numero signifique algo, y se comprueba en TODAS
     las profundidades digitalizadas, no solo en la del docstring.
  3. LA PROCEDENCIA. Cada rango tiene que decir de donde sale y avisar cuando
     extrapola. Un rango sin procedencia es una tightness inventada, que es justo
     lo que el modulo existe para no hacer.
"""
import numpy as np
import pytest

from decision import hand_eval
from decision import opponent_ranges as orr
from decision.preflop import lookup

POSICIONES = ("EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB")

# Fraccion de los 1326 combos a 20bb. Son las cifras del docstring del modulo,
# medidas sobre ranges.json; si ranges.json cambia, estas cambian y hay que
# mirar por que.
ANCHURA_20BB = {"EP1": 0.170, "EP2": 0.186, "MP1": 0.208, "MP2": 0.250,
                "HJ": 0.276, "CO": 0.350, "BTN": 0.472, "SB": 0.855}


def profundidades():
    return sorted(float(k) for k in lookup.ranges()["open_raise"])


# --- 1. los pesos: 169 manos -> 1326 combos ---------------------------------

@pytest.mark.parametrize("mano, n, desc", [
    ("AA", 6, "una pareja son 6 combinaciones (4 palos tomados de 2 en 2)"),
    ("22", 6, "todas las parejas igual"),
    ("AKs", 4, "una suited son 4: un combo por palo"),
    ("72s", 4, "idem"),
    ("AKo", 12, "una offsuit son 12: 4x4 menos los 4 del mismo palo"),
    ("K6o", 12, "idem"),
])
def test_cada_mano_pesa_lo_que_debe(mano, n, desc):
    assert len(orr._combos_de_mano(mano)) == n, desc


def test_las_169_manos_suman_exactamente_los_1326_combos():
    """La comprobacion que cierra los pesos: si la expansion estuviera mal en
    algun tipo de mano, el total no cuadraria."""
    todas = []
    for i, r1 in enumerate(orr._NOTACION):
        for j, r2 in enumerate(orr._NOTACION):
            if i == j:
                todas.append(r1 + r2)
            elif i < j:
                todas += [r1 + r2 + "s", r1 + r2 + "o"]
    assert len(todas) == 169
    assert sum(len(orr._combos_de_mano(m)) for m in todas) == 1326


@pytest.mark.parametrize("mano", ["AA", "AKs", "AKo", "72o", "TT"])
def test_ningun_combo_usa_la_misma_carta_dos_veces(mano):
    for a, b in orr._combos_de_mano(mano):
        assert a != b, mano


def test_una_suited_lleva_las_dos_cartas_del_mismo_palo():
    """El id de carta es rango*4 + palo, asi que el palo es id % 4."""
    for a, b in orr._combos_de_mano("AKs"):
        assert a % 4 == b % 4


def test_una_offsuit_nunca_lleva_las_dos_del_mismo_palo():
    for a, b in orr._combos_de_mano("AKo"):
        assert a % 4 != b % 4


def test_los_rangos_de_la_mano_son_los_que_dice_la_notacion():
    a, b = orr._combos_de_mano("AKs")[0]
    assert a // 4 == hand_eval.RANK_INDEX["A"]
    assert b // 4 == hand_eval.RANK_INDEX["K"]


def test_expandir_devuelve_una_matriz_de_pares():
    m = orr._expandir(["AA", "AKs"])
    assert m.shape == (10, 2)
    assert m.dtype == np.int32


def test_expandir_una_lista_vacia_no_revienta():
    assert orr._expandir([]).shape == (0, 2)


# --- el techo teorico -------------------------------------------------------

def test_el_rango_aleatorio_son_los_1326_combos_sin_repetir():
    todos = orr.random_combos()
    assert len(todos) == 1326
    assert len({tuple(sorted(p)) for p in todos.tolist()}) == 1326
    assert all(a != b for a, b in todos.tolist())


def test_el_rango_aleatorio_se_reutiliza_y_no_se_recalcula():
    assert orr.random_combos() is orr.random_combos()


# --- 2. la monotonia: el rango se abre de posicion temprana a tardia --------

@pytest.mark.parametrize("pos", POSICIONES)
def test_la_anchura_medida_a_20bb_no_ha_cambiado(pos):
    """Las cifras del docstring del modulo, pinadas. Si ranges.json se
    reprocesa, estas se mueven y hay que mirar por que."""
    _c, meta = orr.entering_combos(pos, 20.0)
    assert meta["pct_of_all"] == pytest.approx(ANCHURA_20BB[pos], abs=0.002)


@pytest.mark.parametrize("stack", profundidades())
def test_el_rango_se_abre_de_posicion_temprana_a_tardia(stack):
    """En TODAS las profundidades digitalizadas, no solo a 20bb. Es la propiedad
    que hace que el numero signifique algo: si se invirtiera, la equity contra un
    BTN saldria mas alta que contra un EP1, al reves de la realidad."""
    anchuras = []
    for pos in POSICIONES:
        combos, meta = orr.entering_combos(pos, stack)
        if combos is None:
            continue
        anchuras.append((pos, meta["pct_of_all"]))
    assert len(anchuras) >= 6, f"a {stack}bb solo hay {len(anchuras)} posiciones"
    valores = [v for _p, v in anchuras]
    assert valores == sorted(valores), f"a {stack}bb: {anchuras}"


@pytest.mark.parametrize("stack", profundidades())
def test_ninguna_posicion_abre_con_todo_ni_con_nada(stack):
    for pos in POSICIONES:
        combos, meta = orr.entering_combos(pos, stack)
        if combos is None:
            continue
        assert 0 < meta["pct_of_all"] <= 1.0, f"{pos} a {stack}bb: {meta['pct_of_all']}"


@pytest.mark.parametrize("stack", profundidades())
def test_todo_combo_servido_es_un_par_de_cartas_legal(stack):
    """Un id fuera de 0..51 o repetido reventaria la simulacion mucho despues,
    en forma de mano imposible."""
    for pos in POSICIONES:
        combos, _m = orr.entering_combos(pos, stack)
        if combos is None:
            continue
        assert combos.min() >= 0 and combos.max() <= 51, pos
        assert (combos[:, 0] != combos[:, 1]).all(), f"{pos} a {stack}bb tiene un combo repetido"


# --- la BB defiende, no abre ------------------------------------------------

def test_la_BB_usa_un_rango_de_DEFENSA_y_no_de_apertura():
    """La BB nunca abre: ya tiene la ciega puesta. El objeto estructuralmente
    correcto es un rango de defensa, y darle uno de apertura la haria parecer
    muchisimo mas cerrada de lo que es."""
    _c, meta = orr.entering_combos("BB", 20.0, vs_position="BTN")
    assert meta["role"] == "defensa"
    assert "threebet_call" in meta["source"]


def test_la_BB_defiende_mucho_mas_ancho_que_cualquier_apertura():
    _c, bb = orr.entering_combos("BB", 20.0, vs_position="BTN")
    _c2, btn = orr.entering_combos("BTN", 20.0)
    assert bb["pct_of_all"] > btn["pct_of_all"]
    assert bb["pct_of_all"] > 0.85, "rondan el 86-91% de los combos"


def test_sin_saber_contra_quien_defendio_se_unen_las_defensas_y_se_dice():
    """Postflop no se sabe contra quien defendio -las apuestas preflop ya estan
    en el bote-, asi que se une todo. Cuesta poco porque las defensas de la BB
    son casi aleatorias, pero tiene que ir dicho."""
    _c, meta = orr.entering_combos("BB", 20.0, vs_position="NO_EXISTE")
    assert meta["role"] == "defensa"
    assert any("se une la defensa" in w for w in meta["warnings"])


def test_la_falta_de_defensa_a_una_profundidad_se_resuelve_y_se_avisa():
    """A 10bb la carpeta de origen 3BET-CALL/10BB/BB esta vacia de verdad. Se
    busca la profundidad mas cercana que si la tenga, y se dice cual."""
    combos, meta = orr.entering_combos("BB", 10.0, vs_position="BTN")
    assert combos is not None
    assert any("no existe en el material de origen" in w for w in meta["warnings"])


# --- 3. la procedencia ------------------------------------------------------

def test_sin_posicion_NO_se_inventa_una():
    """Sin boton detectado no se sabe la posicion del rival. Suponerle una seria
    exactamente el fallo mudo que este proyecto evita: elegir EP1 o BTN cambia la
    equity a la mitad o al doble."""
    combos, meta = orr.entering_combos(None, 20.0)
    assert len(combos) == 1326
    assert meta["role"] == "unknown"
    assert meta["pct_of_all"] == 1.0
    assert any("no se conoce la posicion" in w for w in meta["warnings"])


@pytest.mark.parametrize("pos", POSICIONES)
def test_todo_rango_declara_de_donde_sale(pos):
    _c, meta = orr.entering_combos(pos, 20.0)
    assert meta["source"] and "ranges.json" in meta["source"]
    assert meta["stack_key"] is not None


def test_una_posicion_que_no_existe_devuelve_None_con_el_motivo():
    combos, meta = orr.entering_combos("SILLA_7", 20.0)
    assert combos is None
    assert meta["role"] is None
    assert any("no tiene rango" in w for w in meta["warnings"])


@pytest.mark.parametrize("stack, fuera", [(200.0, True), (1.0, True), (20.0, False)])
def test_una_profundidad_fuera_de_la_rejilla_se_marca_como_extrapolacion(stack, fuera):
    """Misma politica que engine._stack_key_note: servir el rango mas cercano
    esta bien, callar que se ha extrapolado no."""
    _c, meta = orr.entering_combos("BTN", stack)
    assert meta["extrapolated"] is fuera
    assert any("extrapolacion" in w for w in meta["warnings"]) is fuera


def test_la_profundidad_servida_es_la_mas_cercana_de_la_rejilla():
    rejilla = profundidades()
    _c, meta = orr.entering_combos("BTN", 200.0)
    assert meta["stack_key"] == max(rejilla)
    _c, meta = orr.entering_combos("BTN", 1.0)
    assert meta["stack_key"] == min(rejilla)


# --- el rango generico ------------------------------------------------------

def test_el_generico_sale_de_los_datos_y_no_de_una_tightness_inventada():
    _c, meta = orr.generic_combos(20.0)
    assert "rangos de entrada" in meta["source"]
    assert meta["stack_key"] == 20.0


def test_el_generico_cae_entre_las_posiciones_tempranas_y_las_tardias():
    """Es "un rival del que no se sabe la posicion pero si que entro al bote", asi
    que tiene que quedar en medio; si saliera mas ancho que el BTN o mas cerrado
    que EP1 no representaria a nadie."""
    _c, gen = orr.generic_combos(20.0)
    _c, ep1 = orr.entering_combos("EP1", 20.0)
    _c, btn = orr.entering_combos("BTN", 20.0)
    assert ep1["pct_of_all"] < gen["pct_of_all"] < btn["pct_of_all"]


def test_el_generico_es_mas_cerrado_que_suponer_cualquier_mano():
    """Si no lo fuera, no aportaria nada sobre el aleatorio."""
    _c, gen = orr.generic_combos(20.0)
    assert gen["pct_of_all"] < 1.0


@pytest.mark.parametrize("stack", profundidades())
def test_el_generico_existe_en_todas_las_profundidades(stack):
    combos, meta = orr.generic_combos(stack)
    assert combos is not None and len(combos) > 0
    assert (combos[:, 0] != combos[:, 1]).all()


# --- la cache ---------------------------------------------------------------

def test_la_cache_devuelve_el_mismo_array_para_la_misma_clave():
    """Se expanden decenas de miles de combos por rango; recalcularlos en cada
    frame se notaria en el ciclo."""
    a, _ = orr.entering_combos("BTN", 20.0)
    b, _ = orr.entering_combos("BTN", 20.0)
    assert a is b


def test_la_cache_no_confunde_posiciones_ni_profundidades():
    """Una clave mal construida serviria el rango de otro asiento, que es
    exactamente el fallo que no se veria mirando el resultado."""
    btn20, _ = orr.entering_combos("BTN", 20.0)
    ep120, _ = orr.entering_combos("EP1", 20.0)
    btn8, _ = orr.entering_combos("BTN", 8.0)
    assert btn20 is not ep120
    assert len(btn20) != len(ep120)
    if len(btn8) != len(btn20):
        assert btn8 is not btn20


def test_la_cache_distingue_contra_quien_defiende_la_BB():
    vs_btn, m1 = orr.entering_combos("BB", 20.0, vs_position="BTN")
    vs_ep1, m2 = orr.entering_combos("BB", 20.0, vs_position="EP1")
    assert m1["source"] != m2["source"]
    if len(vs_btn) != len(vs_ep1):
        assert vs_btn is not vs_ep1


def test_los_arrays_cacheados_no_se_modifican_al_usarlos():
    """Se comparten entre llamadas, asi que quien los reciba no puede escribirlos.
    Si equity los tocara, el siguiente frame veria un rango corrompido."""
    antes, _ = orr.entering_combos("BTN", 20.0)
    copia = antes.copy()
    from decision import equity
    equity._sin_conflicto(antes, hand_eval.card_ids(["Ah", "Kd"]))
    despues, _ = orr.entering_combos("BTN", 20.0)
    assert np.array_equal(despues, copia)
