"""
Verificacion del estudio post-mano (decision/rag/postmano.py).

Lo que de verdad protege:

  1. Que la CONSULTA solo lleve lo observado. Enriquecerla con cosas que no se
     han visto -iniciativa, tipo de rival- buscaria una mano que no es la que se
     jugo, y las referencias parecerian pertinentes sin serlo.
  2. Que la falta de indice, de modelo o de red NO tumbe nada: esto es una ayuda
     para despues de la mano, no parte del analisis.
  3. Que haya un UMBRAL de similitud. El indice siempre devuelve los k mas
     parecidos aunque el mas parecido no se parezca en nada; sin umbral, una mano
     rara acabaria con tres referencias irrelevantes presentadas como si vinieran
     a cuento.

describir() es puro: se prueba sin indice ni modelo.
Uso: .venv/bin/python decision/rag/test_postmano.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import postmano as pm

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


# --- la consulta ------------------------------------------------------------
print("# --- construccion de la consulta ---")
q = pm.describir(board=["Qc", "Qs", "8s"], mano_ganadora="doble pareja",
                 hero_en_showdown=True)
check("lleva el board", "Qc" in q and "Qs" in q and "8s" in q)
check("y la mano ganadora tal y como la escribio el cliente", "doble pareja" in q)
check("y que llego a showdown", "showdown" in q)

check("un board emparejado se nombra", "emparejado" in q)
check("y dos del mismo palo tambien", "dos del mismo palo" in q)
check("y las cartas altas", "cartas altas" in q)

rainbow = pm.describir(board=["2h", "7d", "9c"])
check("un board sin repetir palo es rainbow",
      "rainbow" in rainbow and "emparejado" not in rainbow)
mono = pm.describir(board=["2h", "7h", "9h"])
check("tres del mismo palo es monocolor", "monocolor" in mono)

check("sin showdown se dice tambien",
      "sin showdown" in pm.describir(board=["2h", "7d", "9c"], hero_en_showdown=False))
check("sin datos no se inventa una consulta", pm.describir() == "")
check("un board a medio leer no revienta", isinstance(pm.describir(board=["Qc", None]), str))

# lo que NO debe aparecer: nada que no se haya observado
todo = pm.describir(board=["Qc", "Qs", "8s"], mano_ganadora="doble pareja",
                    hero_en_showdown=True).lower()
for inventado in ("iniciativa", "agresivo", "rango", "deberias", "recomiendo"):
    check(f"la consulta NO inventa '{inventado}'", inventado not in todo)

# --- robustez ---------------------------------------------------------------
print("\n# --- nunca tumba nada ---")
check("una consulta vacia devuelve [] sin tocar el indice", pm.buscar("") == [])
check("estudiar() sin datos devuelve la forma esperada",
      pm.estudiar() == {"consulta": "", "referencias": []})

# el umbral: con un minimo imposible no puede colarse nada
r = pm.estudiar(board=["Qc", "Qs", "8s"], mano_ganadora="doble pareja")
check("estudiar() devuelve consulta y referencias",
      set(r) == {"consulta", "referencias"} and isinstance(r["referencias"], list))
check("con un minimo de 1.1 (imposible) no se devuelve ninguna referencia",
      pm.buscar("board Qc Qs 8s", minimo=1.1) == [])
check("hay un umbral por defecto, no se enseña cualquier cosa",
      0 < pm.SIMILITUD_MINIMA < 1)

# --- formato del minuto -----------------------------------------------------
print("\n# --- minuto para saltar al video ---")
check("725 s -> 12:05", pm.minuto(725.3) == "12:05")
check("0 -> 0:00", pm.minuto(0) == "0:00")
check("None no revienta", pm.minuto(None) == "0:00")
check("59 s no salta de minuto", pm.minuto(59) == "0:59")

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
