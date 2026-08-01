"""
Verificacion de la capa de traduccion de acciones (actions.py).

Lo que de verdad protege es el primer test: recorre decision/preflop/ranges.json
y exige que TODA etiqueta presente en los datos tenga traduccion al castellano.
Asi, si algun dia se redigitalizan los rangos y aparece una etiqueta nueva, o si
la capa derivada del preflop introduce las suyas, el fallo salta aqui en vez de
que el HUD se quede medio mudo en plena mano.
"""
import json
import os

import pytest

from decision.preflop.actions import CHECK_BB_OPTION, translate_action, translate_into

RANGES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ranges.json")


def etiquetas_de(node, out):
    """Recorre ranges.json hasta las hojas {accion: [manos]} y recoge las claves
    de accion."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                out.add(k)
            else:
                etiquetas_de(v, out)
    return out


# --- cobertura completa de los datos reales ----------------------------------

def test_todas_las_etiquetas_de_ranges_json_tienen_castellano():
    with open(RANGES_PATH) as fh:
        etiquetas = sorted(etiquetas_de(json.load(fh), set()))
    assert etiquetas, "ranges.json no tiene ninguna etiqueta; algo va mal"
    sin_traducir = [e for e in etiquetas if translate_action(e)[1] is None]
    assert not sin_traducir, f"de {len(etiquetas)} etiquetas, sin castellano: {sin_traducir}"


def test_la_etiqueta_sintetica_del_motor_tambien():
    assert translate_action(CHECK_BB_OPTION)[1] is not None


# --- el sizing se conserva y se localiza -------------------------------------

@pytest.mark.parametrize("etiqueta, en, es", [
    ("OPEN RAISE (3.5 BB)", "OPEN RAISE (3.5 BB)", "abrir subiendo a 3,5 BB"),
    ("3BET (6.5 BB)", "3BET (6.5 BB)", "resubir a 6,5 BB"),
    ("OPEN RAISE (2 BB)", "OPEN RAISE (2 BB)", "abrir subiendo a 2 BB"),
    ("fold", "FOLD", "no ir"),
    (CHECK_BB_OPTION, "CHECK", "pasar (opcion de la BB)"),
    ("CALL 50% / FOLD 50%", "CALL 50% / FOLD 50%",
     "pagar el 50% / no ir el 50%"),
])
def test_traduccion(etiqueta, en, es):
    """El importe viaja intacto en ingles y con coma decimal en castellano."""
    assert translate_action(etiqueta) == (en, es)


def test_traduce_una_mezcla_interpolada_con_porcentajes_arbitrarios():
    assert translate_action("OPEN RAISE 75% / LIMP 25%") == (
        "OPEN RAISE 75% / LIMP 25%",
        "abrir subiendo el 75% / pagar la ciega sin subir el 25%",
    )


# --- la coincidencia es EXACTA, no por prefijo -------------------------------

@pytest.mark.parametrize("etiqueta, es", [
    ("OPEN RAISE ALL IN", "abrir con todo (all in)"),   # no lo captura "OPEN RAISE"
    ("MARGINAL CALL", "pagar, justo"),                  # no lo captura "CALL"
])
def test_una_etiqueta_larga_no_la_captura_su_prefijo(etiqueta, es):
    assert translate_action(etiqueta) == (etiqueta, es)


# --- la capa derivada (Fase E) -----------------------------------------------

@pytest.mark.parametrize("etiqueta", [
    "CHECK",
    "RAISE OVER LIMPERS (2 BB)",
    "MARGINAL RAISE OVER LIMPERS",
    "SQUEEZE (5 BB)",
])
def test_las_acciones_derivadas_tienen_ingles_y_castellano(etiqueta):
    """Estas no salen de ranges.json: las produce decision/preflop/derive.py."""
    en, es = translate_action(etiqueta)
    assert en == etiqueta
    assert es is not None


# --- robustez ----------------------------------------------------------------

def test_una_etiqueta_desconocida_no_revienta():
    """La capa derivada sigue creciendo y el HUD tiene que seguir enseñando la
    linea grande mientras tanto. (Este caso usaba "SQUEEZE", que dejo de servir
    en cuanto se implemento el squeeze: el test hizo su trabajo y aviso.)"""
    assert translate_action("STRADDLE (4 BB)") == ("STRADDLE (4 BB)", None)


@pytest.mark.parametrize("entrada", ["", None])
def test_etiqueta_vacia_o_none_no_revientan(entrada):
    assert translate_action(entrada) == ("", None)


def test_espacios_de_sobra_se_toleran():
    assert translate_action("  OPEN   RAISE  (2 BB) ") == \
           ("OPEN RAISE (2 BB)", "abrir subiendo a 2 BB")


def test_minusculas_se_toleran():
    assert translate_action("call")[0] == "CALL"


# --- translate_into sobre un dict de recomendacion ---------------------------

def test_translate_into_anade_los_dos_idiomas_y_conserva_la_etiqueta_cruda():
    """La etiqueta cruda es la que enlaza con ranges.json y con el log de
    decisiones: traducir no puede perderla."""
    rec = {"action": "3BET (6 BB)", "reasoning": "..."}
    translate_into(rec)
    assert rec["action_en"] == "3BET (6 BB)"
    assert rec["action_es"] == "resubir a 6 BB"
    assert rec["action"] == "3BET (6 BB)"


def test_translate_into_tolera_un_dict_sin_accion():
    assert translate_into({}) == {}


def test_translate_into_tolera_none():
    assert translate_into(None) is None
