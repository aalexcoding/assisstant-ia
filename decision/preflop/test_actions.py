"""
Verificacion de la capa de traduccion de acciones (actions.py).

Lo que de verdad protege este script es el primer bloque: recorre
decision/preflop/ranges.json y exige que TODA etiqueta presente en los datos
tenga traduccion al castellano. Asi, si algun dia se redigitalizan los rangos y
aparece una etiqueta nueva, o si la capa probabilistica del preflop introduce
las suyas, el fallo salta aqui en vez de que el HUD se quede medio mudo en plena
mano.

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python decision/preflop/test_actions.py
"""
import json
import os

from actions import CHECK_BB_OPTION, translate_action, translate_into

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def labels_in(node, out):
    """Recorre ranges.json hasta las hojas {accion: [manos]} y recoge las claves
    de accion."""
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, list):
                out.add(k)
            else:
                labels_in(v, out)
    return out


# --- cobertura completa de los datos reales ----------------------------------
RANGES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ranges.json")
with open(RANGES_PATH) as fh:
    etiquetas = sorted(labels_in(json.load(fh), set()))

print(f"--- etiquetas encontradas en ranges.json: {len(etiquetas)} ---")
sin_traducir = [e for e in etiquetas if translate_action(e)[1] is None]
check(f"las {len(etiquetas)} etiquetas de ranges.json tienen castellano", not sin_traducir)
if sin_traducir:
    print("     sin traducir:", sin_traducir)
check("la etiqueta sintetica del motor tambien", translate_action(CHECK_BB_OPTION)[1] is not None)

# --- el sizing se conserva y se localiza -------------------------------------
en, es = translate_action("OPEN RAISE (3.5 BB)")
check("sizing conservado en ingles", en == "OPEN RAISE (3.5 BB)")
check("sizing con coma decimal en castellano", es == "abrir subiendo a 3,5 BB")

en, es = translate_action("3BET (6.5 BB)")
check("3bet ingles", en == "3BET (6.5 BB)")
check("3bet castellano", es == "resubir a 6,5 BB")

en, es = translate_action("OPEN RAISE (2 BB)")
check("sizing entero sin decimales", en == "OPEN RAISE (2 BB)" and es == "abrir subiendo a 2 BB")

# --- el caso que pidio el usuario --------------------------------------------
check("fold -> FOLD / no ir", translate_action("fold") == ("FOLD", "no ir"))

# --- la coincidencia es EXACTA, no por prefijo -------------------------------
# "OPEN RAISE ALL IN" no debe caer en la entrada de "OPEN RAISE"
en, es = translate_action("OPEN RAISE ALL IN")
check("OPEN RAISE ALL IN no lo captura OPEN RAISE",
      en == "OPEN RAISE ALL IN" and es == "abrir con todo (all in)")
en, es = translate_action("MARGINAL CALL")
check("MARGINAL CALL no lo captura CALL", en == "MARGINAL CALL" and es == "pagar, justo")

# --- la BB pasando ------------------------------------------------------------
check("opcion de la BB", translate_action(CHECK_BB_OPTION) == ("CHECK", "pasar (opcion de la BB)"))

# --- robustez ----------------------------------------------------------------
# una etiqueta desconocida NO debe reventar: la capa probabilistica del preflop
# va a introducir etiquetas nuevas y el HUD tiene que seguir enseñando la linea
# grande mientras tanto
en, es = translate_action("SQUEEZE (6 BB)")
check("etiqueta desconocida -> ingles en mayusculas, castellano None",
      en == "SQUEEZE (6 BB)" and es is None)
check("etiqueta vacia no revienta", translate_action("") == ("", None))
check("None no revienta", translate_action(None) == ("", None))
check("espacios de sobra se toleran",
      translate_action("  OPEN   RAISE  (2 BB) ") == ("OPEN RAISE (2 BB)", "abrir subiendo a 2 BB"))
check("minusculas se toleran", translate_action("call")[0] == "CALL")

# --- translate_into sobre un dict de recomendacion ---------------------------
rec = {"action": "3BET (6 BB)", "reasoning": "..."}
translate_into(rec)
check("translate_into añade action_en", rec["action_en"] == "3BET (6 BB)")
check("translate_into añade action_es", rec["action_es"] == "resubir a 6 BB")
check("y conserva la etiqueta cruda (enlaza con ranges.json y con el log)",
      rec["action"] == "3BET (6 BB)")
check("translate_into tolera un dict sin accion", translate_into({}) == {})
check("translate_into tolera None", translate_into(None) is None)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
