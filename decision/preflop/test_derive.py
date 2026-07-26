"""
Verificacion de la capa derivada del preflop (derive.py), de momento la opcion
de la BB.

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

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python decision/preflop/test_derive.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import derive
from actions import translate_action
from lookup import RANGES

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


PROFUNDIDADES = sorted(RANGES["open_raise"], key=float)
MANOS = sorted({m for k in PROFUNDIDADES
                for manos in RANGES["open_raise"][k]["SB"].values() for m in manos})


def cartas(mano):
    """'AKs' -> ['Ah','Kh'] ; 'AKo' -> ['Ah','Kd'] ; 'AA' -> ['Ah','Ad']"""
    if len(mano) == 2:
        return [mano[0] + "h", mano[1] + "d"]
    return [mano[0] + "h", mano[1] + ("h" if mano[2] == "s" else "d")]


print(f"# --- {len(MANOS)} manos x {len(PROFUNDIDADES)} profundidades ---")

# --- 1. nunca se retira ----------------------------------------------------
folds = []
sin_respuesta = []
acciones = set()
for k in PROFUNDIDADES:
    for mano in MANOS:
        r = derive.bb_option(cartas(mano), float(k), limpers=1)
        if r is None:
            sin_respuesta.append((k, mano))
            continue
        acciones.add(r["action"])
        if "FOLD" in r["action"].upper():
            folds.append((k, mano, r["action"]))
check("con la opcion NUNCA se retira (pasar es gratis)", not folds)
check("y hay respuesta para todas las manos de todas las profundidades",
      not sin_respuesta)
print(f"    acciones que produce: {sorted(acciones)}")

# --- 2. no se inventa nada -------------------------------------------------
etiquetas_datos = {e for k in PROFUNDIDADES for e in RANGES["open_raise"][k]["SB"]}
sin_mapear = [e for e in etiquetas_datos if derive._traducir(e) is None]
check("toda etiqueta que existe en la fila SB esta mapeada "
      f"({len(etiquetas_datos)} etiquetas en los datos)", not sin_mapear)
if sin_mapear:
    print("     sin mapear:", sin_mapear)

check("una etiqueta desconocida NO se traduce a ciegas",
      derive._traducir("SOMETHING NEW") is None)

# el mapeo, caso por caso
check("LIMP -> CHECK", derive._traducir("LIMP") == "CHECK")
check("fold -> CHECK, que es la traduccion forzada por las reglas",
      derive._traducir("fold") == "CHECK")
check("OPEN RAISE ALL IN -> ALL IN", derive._traducir("OPEN RAISE ALL IN") == "ALL IN")
check("el sizing del donante se CONSERVA, no se recalcula",
      derive._traducir("OPEN RAISE (3.5 BB)") == "RAISE OVER LIMPERS (3.5 BB)")
check("y la version marginal tambien",
      derive._traducir("MARGINAL OPEN RAISE") == "MARGINAL RAISE OVER LIMPERS")

# la respuesta es SIEMPRE el donante mapeado
discrepan = []
for k in ("6", "20", "40"):
    for mano in MANOS:
        r = derive.bb_option(cartas(mano), float(k), limpers=1)
        if r and derive._traducir(r["donor_action"]) != r["action"]:
            discrepan.append((k, mano))
check("cada respuesta es exactamente la etiqueta del donante mapeada", not discrepan)

# --- 3. castellano para todo lo que produce --------------------------------
sin_es = [a for a in acciones if translate_action(a)[1] is None]
check("toda accion derivada tiene castellano para el HUD", not sin_es)
if sin_es:
    print("     sin castellano:", sin_es)

# --- 4. procedencia: se dice SIEMPRE de donde sale -------------------------
print("\n# --- procedencia ---")
r = derive.bb_option(["Ah", "Ad"], 25.0, limpers=1)
check("marca que es derivado, no una tabla suya", r["source"] == "derived")
check("y nombra la celda donante", "SB" in r["donor"] and "25" in r["donor"])
check("y dice que decia el donante", r["donor_action"] == "OPEN RAISE (3.5 BB)")

# --- 5. las guardas --------------------------------------------------------
print("\n# --- guardas ---")
check("con 2 limpers no hay donante valido -> None (el motor deja el CHECK)",
      derive.bb_option(["Ah", "Ad"], 25.0, limpers=2) is None)
check("con 3 tampoco", derive.bb_option(["Ah", "Ad"], 25.0, limpers=3) is None)
check("con 1 si", derive.bb_option(["Ah", "Ad"], 25.0, limpers=1) is not None)

r = derive.bb_option(["Ah", "Ad"], 25.0, limpers=None)
check("si no se pudo contar, se responde igual pero con confianza BAJA",
      r is not None and r["confidence"] == "baja")
check("y se dice el supuesto que se ha hecho",
      any("se asume UN rival" in s for s in r["assumptions"]))
# CERO se trata como desconocido: con la opcion de verdad siempre hay alguien
# dentro (si no, la mano habria terminado), asi que contar cero es no haber
# visto, no que no haya nadie.
cero = derive.bb_option(["Ah", "Ad"], 25.0, limpers=0)
check("contar CERO limpers no da confianza media: con la opcion siempre hay "
      "alguien dentro, asi que cero significa que no se ha visto",
      cero is not None and cero["confidence"] == "baja")
check("con 1 limper contado, la confianza sube a media",
      derive.bb_option(["Ah", "Ad"], 25.0, limpers=1)["confidence"] == "media")

check("sin cartas legibles -> None", derive.bb_option(["Ah"], 25.0, 1) is None)
check("sin stack -> None", derive.bb_option(["Ah", "Ad"], None, 1) is None)

# --- 6. el caso que motivo todo esto ---------------------------------------
print("\n# --- el caso que motivo la Fase E ---")
# Antes, AA con 5bb en la BB recibia "pasa y ve el flop gratis", lo mismo que 72o.
aa = derive.bb_option(["Ah", "Ad"], 5.0, limpers=1)
basura = derive.bb_option(["7c", "2d"], 5.0, limpers=1)
check("AA a 5bb ya no es 'pasa': es ALL IN, que es lo que dicen sus tablas",
      aa["action"] == "ALL IN")
check("y 72o a 5bb sigue siendo CHECK", basura["action"] == "CHECK")
check("o sea que la respuesta YA depende de la mano", aa["action"] != basura["action"])

# el ancho de lo que se recomienda subir, por profundidad, para que quede escrito
print("\n    % de manos (de 169) a las que se sube, por profundidad:")
for k in PROFUNDIDADES:
    n = sum(1 for m in MANOS
            if (derive.bb_option(cartas(m), float(k), 1) or {}).get("action", "") != "CHECK")
    print(f"      {k:>5}bb  {100 * n / len(MANOS):5.1f}%")

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
