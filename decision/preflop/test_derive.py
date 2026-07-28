"""
Verificacion de la capa derivada del preflop (derive.py): la opcion de la BB,
frente a un limp y el squeeze.

Lo que de verdad protege, en orden de gravedad:

  1. LA BB CON LA OPCION NUNCA SE RETIRA. Pasar es gratis, asi que traducir el
     'fold' del donante por un fold seria decirle al usuario que tire una mano
     que puede ver gratis. Se comprueba sobre las 169 manos y las 11
     profundidades: ni una sola respuesta es fold.
  2. NO SE INVENTA NADA. Cada respuesta tiene que ser la etiqueta del donante
     pasada por el mapeo, nunca una accion nueva; y toda etiqueta que exista en
     la fila SB de ranges.json tiene que estar mapeada (si el usuario
     redigitaliza y aparece una nueva, falla el test, no la mesa).
  3. TODA ETIQUETA DERIVADA TIENE CASTELLANO, o el HUD se queda medio mudo.
"""
import pytest

from decision.preflop import derive, lookup
from decision.preflop.actions import translate_action
from decision.preflop.lookup import recommend

PROFUNDIDADES = sorted(lookup.RANGES["open_raise"], key=float)
MANOS = sorted({m for k in PROFUNDIDADES
                for manos in lookup.RANGES["open_raise"][k]["SB"].values() for m in manos})


def cartas(mano):
    """'AKs' -> ['Ah','Kh'] ; 'AKo' -> ['Ah','Kd'] ; 'AA' -> ['Ah','Ad']"""
    if len(mano) == 2:
        return [mano[0] + "h", mano[1] + "d"]
    return [mano[0] + "h", mano[1] + ("h" if mano[2] == "s" else "d")]


@pytest.fixture(scope="module")
def barrido_bb():
    """bb_option sobre las 169 manos x las 11 profundidades. De modulo porque son
    ~1.800 llamadas y varios tests miran la misma pasada desde angulos distintos."""
    respuestas, sin_respuesta = {}, []
    for k in PROFUNDIDADES:
        for mano in MANOS:
            r = derive.bb_option(cartas(mano), float(k), limpers=1)
            if r is None:
                sin_respuesta.append((k, mano))
            else:
                respuestas[(k, mano)] = r
    return {"respuestas": respuestas, "sin_respuesta": sin_respuesta,
            "acciones": {r["action"] for r in respuestas.values()}}


# --- 1. nunca se retira ------------------------------------------------------

def test_la_bb_con_la_opcion_nunca_se_retira(barrido_bb):
    """Pasar es gratis: un fold aqui seria tirar una mano que se puede ver sin
    pagar. Es el fallo mas grave que puede tener esta capa."""
    folds = [(k, m, r["action"]) for (k, m), r in barrido_bb["respuestas"].items()
             if "FOLD" in r["action"].upper()]
    assert not folds, folds[:10]


def test_hay_respuesta_para_todas_las_manos_de_todas_las_profundidades(barrido_bb):
    assert not barrido_bb["sin_respuesta"], barrido_bb["sin_respuesta"][:10]


# --- 2. no se inventa nada ---------------------------------------------------

def test_toda_etiqueta_de_la_fila_sb_esta_mapeada():
    """Si el usuario redigitaliza sus rangos y aparece una etiqueta nueva, tiene
    que fallar aqui y no quedarse muda en la mesa."""
    etiquetas = {e for k in PROFUNDIDADES for e in lookup.RANGES["open_raise"][k]["SB"]}
    sin_mapear = [e for e in etiquetas if derive._traducir(e) is None]
    assert not sin_mapear, f"de {len(etiquetas)} etiquetas, sin mapear: {sin_mapear}"


def test_una_etiqueta_desconocida_no_se_traduce_a_ciegas():
    assert derive._traducir("SOMETHING NEW") is None


@pytest.mark.parametrize("donante, derivada", [
    ("LIMP", "CHECK"),
    ("fold", "CHECK"),                                   # forzado por las reglas
    ("OPEN RAISE ALL IN", "ALL IN"),
    ("OPEN RAISE (3.5 BB)", "RAISE OVER LIMPERS (3.5 BB)"),   # el sizing se CONSERVA
    ("MARGINAL OPEN RAISE", "MARGINAL RAISE OVER LIMPERS"),
])
def test_el_mapeo_caso_por_caso(donante, derivada):
    assert derive._traducir(donante) == derivada


def test_cada_respuesta_es_la_etiqueta_del_donante_mapeada(barrido_bb):
    """No se recalcula ninguna etiqueta: el 94% de los buckets no son contiguos
    en el orden de fuerza, asi que recalcular seria inventar."""
    discrepan = [(k, m) for (k, m), r in barrido_bb["respuestas"].items()
                 if derive._traducir(r["donor_action"]) != r["action"]]
    assert not discrepan, discrepan[:10]


# --- 3. castellano para todo lo que produce ----------------------------------

def test_toda_accion_derivada_tiene_castellano(barrido_bb):
    sin_es = [a for a in barrido_bb["acciones"] if translate_action(a)[1] is None]
    assert not sin_es, sin_es


# --- 4. procedencia: se dice SIEMPRE de donde sale ---------------------------

def test_la_respuesta_viaja_con_su_procedencia():
    """El HUD la pinta en ambar precisamente por esto: no es una lectura de
    tabla, es una celda ajena adaptada, y hay que poder ver cual."""
    r = derive.bb_option(["Ah", "Ad"], 25.0, limpers=1)
    assert r["source"] == "derived"
    assert "SB" in r["donor"] and "25" in r["donor"]
    assert r["donor_action"] == "OPEN RAISE (3.5 BB)"


# --- 5. las guardas ----------------------------------------------------------

@pytest.mark.parametrize("limpers", [2, 3])
def test_con_mas_de_un_limper_no_hay_donante_valido(limpers):
    """El motor deja el CHECK: mejor eso que una celda que no corresponde."""
    assert derive.bb_option(["Ah", "Ad"], 25.0, limpers=limpers) is None


def test_con_un_limper_si_hay_respuesta():
    assert derive.bb_option(["Ah", "Ad"], 25.0, limpers=1) is not None


def test_si_no_se_pudo_contar_se_responde_con_confianza_baja():
    r = derive.bb_option(["Ah", "Ad"], 25.0, limpers=None)
    assert r is not None
    assert r["confidence"] == "baja"
    assert any("se asume UN rival" in s for s in r["assumptions"])


def test_contar_cero_limpers_es_no_haber_visto_no_que_no_haya_nadie():
    """Con la opcion de verdad siempre hay alguien dentro: si no, la mano habria
    terminado. Asi que cero no puede dar mas confianza que desconocido."""
    r = derive.bb_option(["Ah", "Ad"], 25.0, limpers=0)
    assert r is not None
    assert r["confidence"] == "baja"


def test_con_un_limper_contado_la_confianza_sube_a_media():
    assert derive.bb_option(["Ah", "Ad"], 25.0, limpers=1)["confidence"] == "media"


@pytest.mark.parametrize("args", [(["Ah"], 25.0, 1), (["Ah", "Ad"], None, 1)])
def test_sin_cartas_o_sin_stack_no_hay_respuesta(args):
    assert derive.bb_option(*args) is None


# --- 6. el caso que motivo la Fase E -----------------------------------------

def test_aa_a_5bb_en_la_bb_ya_no_es_lo_mismo_que_72o():
    """Antes, AA con 5bb en la BB recibia "pasa y ve el flop gratis", exactamente
    igual que 72o. La respuesta YA depende de la mano."""
    aa = derive.bb_option(["Ah", "Ad"], 5.0, limpers=1)
    basura = derive.bb_option(["7c", "2d"], 5.0, limpers=1)
    assert aa["action"] == "ALL IN", "es lo que dicen sus propias tablas"
    assert basura["action"] == "CHECK"


# --- frente a un limp, con el hero fuera de las ciegas -----------------------
# El donante es otra celda REAL suya: su rango de apertura desde la posicion que
# esta `limpers` asientos mas temprana. Medido sobre ranges.json, cada asiento
# hacia EP aprieta el rango un 20% (ratio 0.802, sd 0.114, n=77) y es monotono en
# las once profundidades.

def test_con_un_limper_el_donante_es_el_asiento_inmediatamente_mas_tight():
    r = derive.vs_limp(["Ah", "Ad"], "CO", 20.0, limpers=1)
    assert r is not None
    assert "HJ" in r["donor"]
    assert r["source"] == "derived"
    assert r["confidence"] == "media-alta", "es una celda real y el salto esta medido"


def test_fuera_de_la_bb_una_mano_mala_si_se_retira():
    """La diferencia clave con la opcion de la BB: aqui entrar cuesta dinero."""
    assert derive.vs_limp(["7c", "2d"], "CO", 20.0, limpers=1)["action"] == "fold"


def test_y_una_buena_sube_sobre_los_limpers():
    r = derive.vs_limp(["Ah", "Ad"], "CO", 20.0, limpers=1)
    assert r["action"].startswith("RAISE OVER LIMPERS")


def test_con_dos_limpers_se_retroceden_dos_asientos():
    dos = derive.vs_limp(["9c", "8c"], "BTN", 20.0, limpers=2)
    assert dos is not None
    assert "HJ" in dos["donor"], "BTN -> CO -> HJ"
    assert dos["confidence"] == "media", "el desplazamiento se encadena"
    assert any("asiento" in a for a in dos["assumptions"])


@pytest.mark.parametrize("desc, args", [
    ("en EP1 no hay fila mas tight que copiar", (["Ah", "Ad"], "EP1", 20.0, 1)),
    ("desde EP2 con 2 limpers se cae por debajo de EP1", (["Ah", "Ad"], "EP2", 20.0, 2)),
    ("la SB queda fuera: su fila esta construida sobre LIMP y romperia la "
     "monotonia del eje (mover de SB a BTN no aprieta, ensancha)",
     (["Ah", "Ad"], "SB", 20.0, 1)),
    ("la BB tiene su propia funcion", (["Ah", "Ad"], "BB", 20.0, 1)),
    ("sin limpers no hay nada que derivar", (["Ah", "Ad"], "CO", 20.0, 0)),
    ("ni con un numero raro de limpers", (["Ah", "Ad"], "CO", 20.0, None)),
    ("sin cartas", (["Ah"], "CO", 20.0, 1)),
    ("sin stack", (["Ah", "Ad"], "CO", None, 1)),
])
def test_guardas_de_vs_limp(desc, args):
    assert derive.vs_limp(*args) is None, desc


@pytest.mark.lento
def test_toda_accion_de_vs_limp_tiene_castellano():
    acciones = set()
    for k in PROFUNDIDADES:
        for pos in ("EP2", "MP1", "MP2", "HJ", "CO", "BTN"):
            for mano in MANOS:
                x = derive.vs_limp(cartas(mano), pos, float(k), 1)
                if x:
                    acciones.add(x["action"])
    assert acciones, "el barrido no produjo ninguna accion; algo va mal"
    assert not [a for a in acciones if translate_action(a)[1] is None]


# --- SQUEEZE: una subida Y ademas quien la ha pagado -------------------------
# Medido sobre ranges.json, eje del HERO en threebet_call (sin las ciegas): n=105,
# media 0.848, sd 0.081. Cada asiento hacia EP aprieta la defensa un 15%.

def test_con_un_pagador_detras_el_donante_es_el_asiento_mas_tight():
    sq = derive.squeeze(["9c", "8c"], "BTN", "HJ", 20.0, callers=1)
    assert sq is not None
    assert "CO" in sq["donor"], "BTN -> CO"
    assert sq["source"] == "derived"
    assert sq["confidence"] == "media-baja"
    assert any("15%" in a for a in sq["assumptions"])


def test_el_squeeze_aprieta_respecto_a_la_defensa_heads_up():
    """98s pasa de pagar a retirarse cuando hay alguien mas dentro."""
    normal = recommend(["9c", "8c"], "BTN", 20.0, facing="threebet_call", vs_position="HJ")
    sq = derive.squeeze(["9c", "8c"], "BTN", "HJ", 20.0, callers=1)
    assert normal["action"] == "MARGINAL CALL"
    assert sq["action"] == "fold"


def test_una_mano_fuerte_sigue_metiendo():
    assert derive.squeeze(["Ah", "Ks"], "BTN", "HJ", 20.0, 1)["action"] == "ALL IN"


@pytest.mark.parametrize("donante, derivada", [
    ("3BET (5 BB)", "SQUEEZE (5 BB)"),      # es lo que es: una resubida con alguien dentro
    ("CALL", "CALL"),
    ("fold", "fold"),
    ("ALL IN", "ALL IN"),
    ("ALGO NUEVO", None),                   # no se traduce a ciegas
])
def test_el_mapeo_del_squeeze(donante, derivada):
    assert derive._traducir_squeeze(donante) == derivada


@pytest.mark.parametrize("desc, args", [
    ("sin pagadores no hay squeeze", (["9c", "8c"], "BTN", "HJ", 20.0, 0)),
    ("en EP1 no hay fila mas tight", (["9c", "8c"], "EP1", "EP1", 20.0, 1)),
    ("la SB queda fuera del eje, igual que en vs_limp", (["9c", "8c"], "SB", "HJ", 20.0, 1)),
    ("si al desplazar el donante cae sobre el propio raiser no hay celda",
     (["9c", "8c"], "BTN", "CO", 20.0, 1)),
    ("sin raiser tampoco", (["9c", "8c"], "BTN", None, 20.0, 1)),
])
def test_guardas_del_squeeze(desc, args):
    assert derive.squeeze(*args) is None, desc


@pytest.mark.lento
def test_toda_accion_del_squeeze_tiene_castellano():
    acciones = set()
    for k in PROFUNDIDADES:
        for mano in MANOS:
            x = derive.squeeze(cartas(mano), "BTN", "HJ", float(k), 1)
            if x:
                acciones.add(x["action"])
    assert acciones, "el barrido no produjo ninguna accion; algo va mal"
    assert not [a for a in acciones if translate_action(a)[1] is None]
