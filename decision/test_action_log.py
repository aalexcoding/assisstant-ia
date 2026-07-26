"""
Verificacion del historial de acciones (decision/action_log.py).

Lo que de verdad protege:

  1. La DEDUPLICACION. El mismo verbo esta en pantalla varios frames seguidos;
     contarlo dos veces convertiria una subida en dos y haria creer que hay una
     3bet donde solo hubo un open. Y lo contrario tambien: dos subidas de verdad
     del mismo asiento no pueden colapsarse en una.
  2. Que la lista NUNCA se presente como completa. El verbo dura menos que el
     periodo de muestreo, asi que faltan acciones por construccion; afirmar lo
     contrario llevaria a clasificar mal el spot.

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python decision/test_action_log.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import action_log as al

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


# --- normalizacion del verbo -----------------------------------------------
print("# --- verbo del cliente -> accion ---")
for verbo, esperado in (("Pasar", "check"), ("Pasa", "check"),
                        ("Igualar", "call"), ("Paga", "call"),
                        ("Apostar", "bet"), ("Subir", "raise"), ("Resubir", "raise"),
                        ("No ir", "fold"), ("All-in", "allin"), ("all in", "allin")):
    check(f"{verbo!r} -> {esperado}", al.normalizar(verbo) == esperado)

check("un nick no es una accion", al.normalizar("Dav6934") is None)
check("vacio tampoco", al.normalizar("") is None and al.normalizar(None) is None)
check("'Ausente' es un ESTADO, no una accion: no puede entrar en la secuencia",
      al.normalizar("Ausente") is None)
check("'Sentado' tampoco", al.normalizar("Sentado") is None)

# --- deduplicacion: lo mas importante --------------------------------------
print("\n# --- deduplicacion ---")
log = al.ActionLog()
log.nueva_mano()
for _ in range(4):
    log.observar("UL", "Subir")
check("el mismo verbo en 4 frames seguidos es UNA sola subida",
      len(log.acciones()["acciones"]) == 1)

log.observar("UL", None)              # vuelve a verse el nick: cierra el evento
log.observar("UL", "Subir")
check("si vuelve a verse el nick y luego SUBE otra vez, son dos subidas",
      len(log.acciones()["acciones"]) == 2)

log2 = al.ActionLog()
log2.nueva_mano()
log2.observar("UL", "Subir")
log2.observar("UL", "Igualar")
check("dos verbos distintos seguidos son dos acciones",
      len(log2.acciones()["acciones"]) == 2)

# --- orden y contenido ------------------------------------------------------
print("\n# --- orden ---")
log = al.ActionLog()
log.nueva_mano()
log.observar("ML", "Poner", position="SB")
log.observar("UL", "Subir", position="CO")
log.observar("MR", "No ir", position="BTN")
log.observar("HERO", "Igualar", position="BB")
acc = log.acciones()["acciones"]
check("se conserva el orden en que se vieron",
      [a["accion"] for a in acc] == ["post", "raise", "fold", "call"])
check("y de quien fue cada una",
      [a["position"] for a in acc] == ["SB", "CO", "BTN", "BB"])
check("con numero de orden correlativo", [a["orden"] for a in acc] == [1, 2, 3, 4])
check("el resumen se lee de un vistazo",
      log.resumen() == "SB pone ciega · CO sube · BTN no va · BB paga")

# --- la ultima agresiva, que es lo que dice si el bote esta subido ----------
print("\n# --- ultima accion agresiva ---")
check("la ultima agresiva es la subida de CO",
      log.ultima_agresiva()["position"] == "CO")
log.observar("MR", "Apostar", position="BTN")
check("una apuesta posterior la sustituye",
      log.ultima_agresiva()["position"] == "BTN")
log.observar("HERO", "Pasar", position="BB")
check("un pase NO la sustituye: pasar no es agresivo",
      log.ultima_agresiva()["position"] == "BTN")

vacio = al.ActionLog()
vacio.nueva_mano()
check("sin acciones no hay ultima agresiva", vacio.ultima_agresiva() is None)
vacio.observar("UL", "Pasar")
check("y con solo pases tampoco", vacio.ultima_agresiva() is None)

# --- LA HONESTIDAD: nunca se presenta como completo -------------------------
print("\n# --- la lista nunca es completa ---")
check("acciones() marca completo=False SIEMPRE: el verbo dura menos que el "
      "periodo de muestreo, asi que faltan acciones por construccion",
      log.acciones()["completo"] is False)

# --- fronteras de mano ------------------------------------------------------
print("\n# --- fronteras ---")
log = al.ActionLog()
log.nueva_mano()
log.observar("UL", "Subir")
antes = log.mano
log.nueva_mano()
check("una mano nueva vacia el historial", log.acciones()["acciones"] == [])
check("y sube el contador", log.mano == antes + 1)
log.observar("UL", "Subir")
check("y el mismo verbo vuelve a contar (es otra mano)",
      len(log.acciones()["acciones"]) == 1)

# --- desde un GameState entero ---------------------------------------------
print("\n# --- integracion con el GameState ---")
log = al.ActionLog()
log.nueva_mano()
st = {"players": [{"seat": "UL", "action": "Subir", "position": "CO"},
                  {"seat": "MR", "action": None, "position": "BTN", "name": "pepe"},
                  {"seat": "HERO", "action": "Igualar", "position": "BB", "is_hero": True}]}
nuevas = log.observar_estado(st)
check("de un GameState salen las acciones de todos los asientos", len(nuevas) == 2)
check("y el que muestra su nick no aporta ninguna",
      all(n["seat"] != "MR" for n in nuevas))
check("repetir el MISMO estado no duplica nada", log.observar_estado(st) == [])
check("un GameState sin jugadores no revienta", al.ActionLog().observar_estado({}) == [])

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
