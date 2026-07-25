"""
Script suelto de verificacion de hand_result.parse_hand_result / hero_outcome
(el proyecto no usa pytest todavia). Prueba las lineas de chat reales
verificadas mas variantes con ruido de OCR. Uso:
.venv/bin/python vision/test_hand_result.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hand_result import hero_outcome, parse_hand_result

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


# --- caso real 1: linea de resultado completa (numero + ganador + importe + mano) ---
r = parse_hand_result([
    "Repartidor: Mano n.º 261531764294: fabiocs98 gana el bote (2.040) con pareja de nueves",
])
check("real: hand_number", r is not None and r["hand_number"] == "261531764294")
check("real: winner fabiocs98", r["winner"] == "fabiocs98")
check("real: amount 2.040", r["amount"] == "2.040")
check("real: winning_hand", r["winning_hand"] == "pareja de nueves")

# --- caso real 2: mismas lineas + revelacion de showdown + linea de turno (a ignorar) ---
r2 = parse_hand_result([
    "Repartidor: alex_delg, es tu turno...",
    "Repartidor: Mano n.º 261531764294: fabiocs98 gana el bote (2.040) con pareja de nueves",
    "Repartidor: fortu2010 tiene pareja de nueves",
])
check("real2: winner fabiocs98", r2["winner"] == "fabiocs98")
check("real2: showdown incluye fortu2010",
      any(s["player"] == "fortu2010" and s["hand"] == "pareja de nueves" for s in r2["showdown"]))

# --- linea de turno sola -> None (no hay resultado) ---
check("solo turno -> None", parse_hand_result(["Repartidor: alex_delg, es tu turno..."]) is None)

# --- chat vacio -> None ---
check("vacio -> None", parse_hand_result([]) is None)
check("None -> None", parse_hand_result(None) is None)

# --- ruido OCR: "n.º" leido como "n.o", separador raro, mano con acento ---
r3 = parse_hand_result([
    "Repartidor Mano n.o 261531764295 SHARKOS54 gana el bote (12.500) con trío de reyes",
])
check("ruido: hand_number", r3["hand_number"] == "261531764295")
check("ruido: winner SHARKOS54", r3["winner"] == "SHARKOS54")
check("ruido: amount 12.500", r3["amount"] == "12.500")
check("ruido: winning_hand trío de reyes", r3["winning_hand"] == "trío de reyes")

# --- gano sin showdown (todos foldearon): "gana el bote (N)" sin "con ..." ---
r4 = parse_hand_result([
    "Repartidor: Mano n.º 261531764296: alex_delg gana el bote (500)",
])
check("uncontested: winner", r4["winner"] == "alex_delg")
check("uncontested: amount", r4["amount"] == "500")
check("uncontested: sin winning_hand", r4["winning_hand"] is None)

# --- wrapping: la linea de resultado partida en dos lineas visuales por el OCR ---
r5 = parse_hand_result([
    "Repartidor: Mano n.º 261531764297: fabiocs98 gana",
    "el bote (2.040) con color de corazones",
])
check("wrap: winner fabiocs98", r5["winner"] == "fabiocs98")
check("wrap: hand_number", r5["hand_number"] == "261531764297")
check("wrap: winning_hand color de corazones", r5["winning_hand"] == "color de corazones")

# --- dos resultados en el historial visible: se queda con el mas reciente (abajo) ---
r6 = parse_hand_result([
    "Repartidor: Mano n.º 111111111111: pepe gana el bote (100) con par de doses",
    "Repartidor: Mano n.º 222222222222: juanito gana el bote (300) con escalera",
])
check("historial: mas reciente juanito", r6["winner"] == "juanito" and r6["hand_number"] == "222222222222")

# --- sin numero de mano legible pero con ganador: sigue devolviendo resultado ---
r7 = parse_hand_result(["fabiocs98 gana el bote (2.040) con pareja de nueves"])
check("sin numero: hay resultado", r7 is not None and r7["winner"] == "fabiocs98")
check("sin numero: hand_number None", r7["hand_number"] is None)

# --- hero_outcome: el hero es el ganador ---
o1 = hero_outcome(r, "fabiocs98")
check("outcome: hero gana", o1["status"] == "won" and o1["hero_hand"] == "pareja de nueves")

# --- hero_outcome: hero pierde, aparece en showdown ---
o2 = hero_outcome(r2, "fortu2010")
check("outcome: hero pierde con su mano", o2["status"] == "lost" and o2["hero_hand"] == "pareja de nueves")

# --- hero_outcome: hero no aparece por ningun lado -> unknown ---
o3 = hero_outcome(r2, "alex_delg")
check("outcome: hero desconocido", o3["status"] == "unknown" and o3["hero_hand"] is None)

# --- hero_outcome: sin nombre de hero cacheado -> unknown ---
o4 = hero_outcome(r, None)
check("outcome: sin hero_name -> unknown", o4["status"] == "unknown")

# --- names_match tolerante: truncamiento del nick por OCR ---
o5 = hero_outcome(r, "fabiocs9")
check("outcome: match tolerante (truncado)", o5["status"] == "won")

# --- BOTE DIVIDIDO: "empata por el bote", una linea por jugador, mismo n.o de mano.
# Lineas reales de vision/samples_layout2/: antes no se reconocian (el patron
# exigia "gana") y la mano salia como "resultado no legible". ---
rs = parse_hand_result([
    "Repartidor: Mano n.º 261531249025: Amsterdam974 empata por el bote",
    "Repartidor: Mano n.º 261531249025: rubydog77 empata por el bote (4.243)",
])
check("split: se reconoce", rs is not None and rs["split"] is True)
check("split: los dos jugadores", rs["winners"] == ["Amsterdam974", "rubydog77"])
check("split: winner = el primero", rs["winner"] == "Amsterdam974")
check("split: amount 4.243", rs["amount"] == "4.243")
check("split: hand_number", rs["hand_number"] == "261531249025")
check("split: hero empata -> status split", hero_outcome(rs, "rubydog77")["status"] == "split")
check("split: hero ajeno -> unknown", hero_outcome(rs, "pepito")["status"] == "unknown")

# un solo ganador NO debe marcarse como split
check("no-split: gana normal", r["split"] is False and r["winners"] == ["fabiocs98"])

# split viejo en el historial + mano nueva con un solo ganador: manda la nueva
rs2 = parse_hand_result([
    "Repartidor: Mano n.º 111111111111: aaa empata por el bote (100)",
    "Repartidor: Mano n.º 111111111111: bbb empata por el bote",
    "Repartidor: Mano n.º 222222222222: ccc gana el bote (300) con escalera",
])
check("split+nueva: manda la mas reciente", rs2["split"] is False and rs2["winner"] == "ccc")

# --- NICK CON ESPACIO: el OCR lee el guion bajo como espacio ("david_sagunt").
# Antes el regex capturaba solo "sagunt". ---
rn = parse_hand_result([
    "Repartidor: Mano n.º 261531241628: david sagunt gana el bote (2.197) con pareja de jotas",
])
check("nick con espacio: no se trunca", rn["winner"] == "david sagunt")
check("nick con espacio: casa con la forma con guion bajo",
      hero_outcome(rn, "david_sagunt")["status"] == "won")
check("nick con espacio: mano ganadora completa", rn["winning_hand"] == "pareja de jotas")
# y no se come la palabra previa cuando no es parte del nick
rn2 = parse_hand_result(["Repartidor: El jugador pepito gana el bote (50)"])
check("nick: no se come 'jugador'", rn2["winner"] == "pepito")

# --- MANO CON COMA: "doble pareja, damas y sietes" (linea real de showdown).
# Antes se cortaba en la coma y quedaba solo "doble pareja". ---
rc = parse_hand_result([
    "Repartidor: Mano n.º 261531300000: david sagunt gana el bote (900) con doble pareja, damas y sietes",
])
check("coma: mano completa", rc["winning_hand"] == "doble pareja, damas y sietes")
rc2 = parse_hand_result(["Repartidor: rubydog77 tiene doble pareja, reyes y doses",
                         "Repartidor: Mano n.º 261531300001: pepe gana el bote (10)"])
check("coma: showdown completo",
      any(s["hand"] == "doble pareja, reyes y doses" for s in rc2["showdown"]))

# --- ORDEN VISUAL: la continuacion del mensaje llega ANTES que su cabecera
# (tesseract en SPARSE_TEXT no garantiza orden de lectura). Con posicion, se
# reordena; la mano ganadora debe encontrarse igual. ---
ro = parse_hand_result([
    {"text": "el bote (2.040) con color de corazones", "top": 40, "left": 0},
    {"text": "Repartidor: Mano n.º 261531764297: fabiocs98 gana", "top": 20, "left": 0},
])
check("orden visual: winner", ro is not None and ro["winner"] == "fabiocs98")
check("orden visual: winning_hand", ro["winning_hand"] == "color de corazones")

# --- la frase de mano NO debe invadir el mensaje siguiente ---
rt = parse_hand_result([
    "Repartidor: Mano n.º 261531400000: pepe gana el bote (120) con pareja de jotas",
    "Repartidor: alex_delg, es tu turno. Tienes 7 segundos para actuar",
])
check("no invade el mensaje siguiente", rt["winning_hand"] == "pareja de jotas")

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
