"""
Verificacion del rastreador de mano (decision/hand_tracker.py).

Lo que de verdad protege: la DIRECCION de los errores. El comprometido derivado
es una cota inferior y se usa solo para ATRIBUIR una subida que el boton
"Igualar" ya ha demostrado; si esa asimetria se rompe, el motor puede acabar
recomendando una defensa contra un raiser inventado, que es el peor fallo posible
en esta app.

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python decision/test_hand_tracker.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hand_tracker as ht

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def estado(stacks, board=(), hero=(), bets=None, posiciones=None, to_call=None):
    """GameState minimo: {asiento: stack}. stack None = nameplate ilegible."""
    bets = bets or {}
    posiciones = posiciones or {}
    return {
        "board": list(board),
        "hero_cards": list(hero),
        "to_call": to_call,
        "players": [{"seat": s, "stack": v, "bet": bets.get(s),
                     "position": posiciones.get(s),
                     "is_hero": s == "HERO"}
                    for s, v in stacks.items()],
    }


def com(info, seat):
    return info["asientos"][seat]["comprometido"]


# --- lo basico: el stack baja, eso es lo que ha puesto ----------------------
print("# --- comprometido = bajada de stack ---")
tr = ht.HandTracker()
tr.update(estado({"UL": 87.9, "HERO": 50.0}))
info = tr.update(estado({"UL": 60.5, "HERO": 50.0}))
check("una bajada de 27,4 se lee como 27,4 comprometidos", com(info, "UL") == 27.4)
check("el que no se movio sigue a cero", com(info, "HERO") == 0)

info = tr.update(estado({"UL": 60.5, "HERO": 50.0}))
check("y no se acumula por volver a ver el mismo stack", com(info, "UL") == 27.4)

# --- un nameplate ilegible no puede borrar lo que ya se sabia --------------
print("\n# --- huecos de lectura ---")
tr = ht.HandTracker()
tr.update(estado({"UL": 40.0}))
tr.update(estado({"UL": 36.0}))
info = tr.update(estado({"UL": None}))
check("un frame sin lectura conserva el comprometido", com(info, "UL") == 4.0)
info = tr.update(estado({"UL": 30.0}))
check("y la lectura siguiente sigue contando desde la base de la mano",
      com(info, "UL") == 10.0)

# --- LO CRITICO: una lectura ALTA no puede reventar la base ----------------
print("\n# --- lecturas imposibles (el error de OCR medido) ---")
tr = ht.HandTracker()
tr.update(estado({"UL": 106.5}))
tr.update(estado({"UL": 100.0}))
info = tr.update(estado({"UL": 1065.0}))       # el punto decimal perdido, real
check("una lectura por encima de la base se descarta (dentro de una mano el "
      "stack no puede subir)", com(info, "UL") == 6.5)
check("y se cuenta como lectura descartada, para poder desconfiar del asiento",
      info["asientos"]["UL"]["lecturas_descartadas"] == 1)
info = tr.update(estado({"UL": 98.0}))
check("la serie sigue siendo utilizable despues del disparate", com(info, "UL") == 8.5)

# --- fronteras de mano -----------------------------------------------------
print("\n# --- fronteras ---")
tr = ht.HandTracker()
tr.update(estado({"UL": 50.0}, hero=("Ah", "Kd")))
info = tr.update(estado({"UL": 46.0}, hero=("Ah", "Kd")))
check("dentro de la mano se acumula", com(info, "UL") == 4.0)
mano_antes = info["mano"]
info = tr.update(estado({"UL": 62.0}, hero=("7c", "2d")))
check("cartas del hero distintas = mano nueva", info["mano"] == mano_antes + 1)
check("y la base se rehace: el que gano el bote no aparece comprometido",
      com(info, "UL") == 0)
check("se registra POR QUE se corto", "cartas" in info["motivos_apertura"])

tr = ht.HandTracker()
tr.update(estado({"UL": 50.0}), hand_number="111")
info = tr.update(estado({"UL": 46.0}), hand_number="111")
check("el mismo numero de mano no corta", com(info, "UL") == 4.0)
info = tr.update(estado({"UL": 80.0}), hand_number="222")
check("un numero de mano nuevo corta", com(info, "UL") == 0)

# --- las señales que NO cortan, y por que (medido) -------------------------
print("\n# --- señales descartadas con datos ---")
tr = ht.HandTracker()
tr.update(estado({"UL": 50.0}, board=("Qc", "Qs", "8s", "Ks", "Tc")))
info = tr.update(estado({"UL": 44.0}, board=("7c", "Ac")))
check("un board de longitud ilegal (2 cartas) no parte la mano: es basura de OCR",
      com(info, "UL") == 6.0)
tr = ht.HandTracker()
tr.update(estado({"UL": 50.0}, board=("Qc", "Qs", "8s")))
info = tr.update(estado({"UL": 44.0}, board=()))
check("perder el board un frame tampoco la parte", com(info, "UL") == 6.0)

v1 = ht._vista(estado({"UL": 50.0}, board=("Qc", "Qs", "8s")))
v2 = ht._vista(estado({"UL": 50.0}, board=("2h", "3h", "4h")))
check("aun asi la señal de board se EXPONE (sirve para depurar)",
      "board" in ht.motivos_de_frontera(v1, v2))
check("pero no esta entre las que cortan", "board" not in ht.MOTIVOS_DE_CORTE)
check("ni la subida de stack, que medida resulto ser error de OCR",
      "stack_sube" not in ht.MOTIVOS_DE_CORTE)

# --- corroboracion con el importe leido en la mesa -------------------------
print("\n# --- acuerdo entre las dos señales ---")
check("coinciden dentro de la tolerancia", ht.acuerdo(3.75, 3.8) == "coinciden")
check("discrepan cuando no", ht.acuerdo(3.9, 2.52) == "discrepan")
check("solo derivado cuando la mesa no dio nada", ht.acuerdo(4.0, None) == "solo_derivado")
check("solo leido cuando no hay base", ht.acuerdo(None, 4.0) == "solo_leido")

# --- LA REGLA DE SEGURIDAD: el comprometido no CREA subidas ---------------
print("\n# --- atribuir, nunca inventar ---")
jugadores = [
    {"seat": "UL", "position": "CO", "committed": 4.0, "is_hero": False},
    {"seat": "ML", "position": "BB", "committed": 1.0, "is_hero": False},
    {"seat": "HERO", "position": "BTN", "committed": 0.0, "is_hero": True},
]
pos, seat = ht.atribuir_subida(jugadores, to_call=4.0)
check("con el boton pidiendo 4 BB se atribuye al que tiene 4 comprometidos",
      pos == "CO" and seat == "UL")

pos, motivo = ht.atribuir_subida(jugadores, to_call=None)
check("SIN boton que pida nada no se atribuye NADA, por muy grande que sea el "
      "comprometido: el derivado no puede inventarse un raiser",
      pos is None and motivo == "sin_to_call")

pos, motivo = ht.atribuir_subida(jugadores, to_call=20.0)
check("si nadie llega a lo que pide el boton, se dice que nadie lo explica",
      pos is None and motivo == "nadie_lo_explica")

dos = jugadores + [{"seat": "UR", "position": "HJ", "committed": 4.0, "is_hero": False}]
pos, motivo = ht.atribuir_subida(dos, to_call=4.0)
check("con dos candidatos no se adivina (igual que detect_raiser)",
      pos is None and motivo == "varios_candidatos")

sin_pos = [{"seat": "UL", "position": None, "committed": 4.0, "is_hero": False}]
pos, motivo = ht.atribuir_subida(sin_pos, to_call=4.0)
check("un candidato sin posicion no sirve para elegir rango",
      pos is None and motivo == "candidato_sin_posicion")

solo_hero = [{"seat": "HERO", "position": "BTN", "committed": 9.0, "is_hero": True}]
pos, motivo = ht.atribuir_subida(solo_hero, to_call=4.0)
check("el propio hero nunca es el raiser al que defender",
      pos is None and motivo == "nadie_lo_explica")

# el comprometido es COTA INFERIOR: se admite quedarse algo corto
pos, _ = ht.atribuir_subida(
    [{"seat": "UL", "position": "CO", "committed": 3.8, "is_hero": False}], to_call=4.0)
check("se tolera quedarse un poco corto (la base puede estar ya rebajada)",
      pos == "CO")
pos, motivo = ht.atribuir_subida(
    [{"seat": "UL", "position": "CO", "committed": 3.0, "is_hero": False}], to_call=4.0)
check("pero no quedarse corto de mas", pos is None)

# --- aplicar() cuelga el dato de los jugadores ----------------------------
print("\n# --- integracion con el GameState ---")
tr = ht.HandTracker()
st = estado({"UL": 50.0, "HERO": 30.0}, posiciones={"UL": "CO", "HERO": "BTN"})
tr.update(st)
st2 = estado({"UL": 46.0, "HERO": 30.0}, posiciones={"UL": "CO", "HERO": "BTN"})
ht.aplicar(st2, tr.update(st2))
ul = next(p for p in st2["players"] if p["seat"] == "UL")
check("aplicar() cuelga committed de cada jugador", ul["committed"] == 4.0)
check("y el acuerdo con la mesa", ul["committed_acuerdo"] == "solo_derivado")
check("y deja el numero de mano seguida en el estado", st2["mano_seguida"] == 1)

# --- un GameState sin seat no puede rastrearse, y no debe reventar --------
tr = ht.HandTracker()
info = tr.update({"players": [{"stack": 50.0, "is_hero": True}], "board": [], "hero_cards": []})
check("un GameState sin 'seat' (ruta de diagnostico) no rastrea nada ni lanza",
      info["asientos"] == {})

# --- el nombre no se pierde cuando el cliente lo tapa con el verbo ---------
# El cliente sustituye el nick por la accion ("Pasar", "Igualar") JUSTO cuando el
# jugador actua, que es cuando mas falta hace saber quien es. Se repone el ultimo
# nombre bueno de ESA mano.
print("\n# --- nombre pegajoso dentro de la mano ---")


def con_nombre(nombre, accion, cartas=("Ah", "Kd")):
    return {"board": [], "hero_cards": list(cartas), "to_call": None,
            "players": [{"seat": "UL", "name": nombre, "action": accion,
                         "stack": 50.0, "is_hero": False}]}


tr = ht.HandTracker()
s1 = con_nombre("Dav6934", None)
ht.aplicar(s1, tr.update(s1))
check("un nombre legible se muestra tal cual",
      s1["players"][0]["name"] == "Dav6934" and not s1["players"][0].get("name_repuesto"))

s2 = con_nombre(None, "Igualar")
ht.aplicar(s2, tr.update(s2))
check("cuando el cliente lo tapa con el verbo, se repone el nombre",
      s2["players"][0]["name"] == "Dav6934")
check("y se marca que viene repuesto, no leido",
      s2["players"][0].get("name_repuesto") is True)

s3 = con_nombre("otroNick", "Pasar")
ht.aplicar(s3, tr.update(s3))
check("una lectura buena del frame actual siempre manda sobre la repuesta",
      s3["players"][0]["name"] == "otroNick")

# EN ZOOM el cliente cambia de mesa entre manos, asi que el ocupante de un
# asiento puede ser OTRA persona: reponer entre manos seria inventarse quien es.
s4 = con_nombre(None, "Pasar", cartas=("7c", "2d"))
ht.aplicar(s4, tr.update(s4))
check("en una mano NUEVA no se repone (en Zoom el asiento puede ser de otro)",
      s4["players"][0]["name"] is None)

# --- integracion con el motor ---------------------------------------------
# La propiedad que hace SEGURO el cambio: el comprometido solo puede convertir
# una ABSTENCION en recomendacion, nunca cambiar una recomendacion que ya habia.
# Medido sobre una sesion real entera (1.173 frames): 20 nuevas, 0 cambiadas, 0
# perdidas. Aqui se fija con casos sinteticos para que no se pueda romper sin que
# salte un test.
print("\n# --- el motor solo gana recomendaciones, no las cambia ---")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "preflop"))
import engine  # noqa: E402

engine._log_decision = lambda *a, **k: None      # no ensuciar el log de decisiones


def spot(committed=None, bet=None, to_call=None):
    """Hero en CO con AKo a 20bb, enfrentando algo. UL es el rival en HJ."""
    engine._last_hero_stack.update(value=None, t=0.0, unit=None)
    return {
        "hero_cards": ["Ah", "Kd"], "board": [], "pot": None, "blinds": None,
        "stack_unit": "bb", "hero_position": "CO", "facing": "bet",
        "to_call": to_call, "warnings": [],
        "players": [
            {"seat": "UL", "position": "HJ", "stack": 20.0, "bet": bet,
             "committed": committed, "is_hero": False},
            {"seat": "HERO", "position": "CO", "stack": 20.0, "bet": None,
             "committed": 0.0, "is_hero": True},
        ],
    }


sin = engine.decide(spot(committed=None, bet=None, to_call=4.0))
check("hoy, sin importe en la mesa que explique la subida, el motor se abstiene",
      sin is None)

con = engine.decide(spot(committed=4.0, bet=None, to_call=4.0))
check("con el comprometido derivado si recomienda, y es una DEFENSA",
      con is not None and con["facing_used"] == "threebet_call")
check("contra la posicion correcta", con and con["vs_position"] == "HJ")
check("y el razonamiento dice DE DONDE salio la subida, que no es lo mismo que "
      "leerla en la mesa",
      con and "bajada de stack" in con["reasoning"])

# el importe de la mesa manda cuando existe: es la señal que ya estaba validada
leido = engine.decide(spot(committed=None, bet=4.0, to_call=4.0))
enganya = engine.decide(spot(committed=99.0, bet=4.0, to_call=4.0))
check("si la mesa SI explica la subida, el comprometido no cambia nada",
      leido is not None and enganya is not None
      and leido["vs_position"] == enganya["vs_position"] == "HJ")

# la garantia central: sin boton que pida nada, un comprometido enorme no hace
# aparecer un raiser de la nada
sin_boton = engine.decide(spot(committed=99.0, bet=None, to_call=None))
check("SIN to_call, un comprometido disparatado NO crea una defensa: se sigue "
      "por el rango de apertura",
      sin_boton is not None and sin_boton["facing_used"] == "open_raise")

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
