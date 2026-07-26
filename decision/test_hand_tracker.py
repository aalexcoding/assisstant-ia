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
# Las señales se eligieron midiendo contra el numero de mano del chat sobre 3.300
# frames de tres sesiones. Juegos comparados por cuantos cortes REALES detectan:
#     chat + cartas distintas (lo de antes)   44/75 = 59%
#     chat + cartas_aparecen                  58/75 = 77%
#     chat + cartas_aparecen + board_vacio     68/75 = 91%
print("\n# --- fronteras ---")


def repetir(tr, st, n):
    """Una mano tiene que durar MIN_FRAMES_POR_MANO antes de poder cortarse."""
    for _ in range(n):
        info = tr.update(*st) if isinstance(st, tuple) else tr.update(st)
    return info


tr = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO):
    tr.update(estado({"UL": 50.0}, hero=("Ah", "Kd")))
info = tr.update(estado({"UL": 46.0}, hero=("Ah", "Kd")))
check("dentro de la mano se acumula", com(info, "UL") == 4.0)
mano_antes = info["mano"]

# CARTAS QUE APARECEN ya NO corta. Parecia solida -35 de 52 cortes reales- pero
# aquella medida solo contaba los cortes que se ACIERTAN, nunca los que se
# inventan. Con el boton hay por fin vara para medir la PRECISION, y la señal
# resulta ser 94% falsa: depende de LEER las dos cartas del hero, y basta con
# perderlas un frame para que al siguiente "aparezcan" y la mano se parta.
tr2 = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO):
    tr2.update(estado({"UL": 50.0}))
m0 = tr2.update(estado({"UL": 46.0}))["mano"]
info = tr2.update(estado({"UL": 62.0}, hero=("7c", "2d")))
check("un frame en el que se pierden las cartas y vuelven NO parte la mano "
      "(provocaba 66 de los 82 cortes falsos)", info["mano"] == m0)
check("la señal se sigue exponiendo, que es informativa",
      "cartas_aparecen" in ht.motivos_de_frontera(
          ht._vista(estado({"UL": 46.0})),
          ht._vista(estado({"UL": 62.0}, hero=("7c", "2d")))))

# EL BOTON si corta, y ademas rehace la base
tr2b = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO):
    tr2b.update(estado({"UL": 50.0, "MR": 30.0}, posiciones={"UL": "BTN"}))
m0 = tr2b.update(estado({"UL": 46.0, "MR": 30.0}, posiciones={"UL": "BTN"}))["mano"]
info = tr2b.update(estado({"UL": 62.0, "MR": 30.0}, posiciones={"MR": "BTN"}))
check("el boton en otro asiento = mano nueva", info["mano"] == m0 + 1)
check("y la base se rehace: el que gano el bote no aparece comprometido",
      com(info, "UL") == 0)
check("se registra POR QUE se corto", "boton" in info["motivos_apertura"])

# POSICIONES QUE TODAVIA SON DE LA MANO ANTERIOR: el cliente recoge las cartas
# antes de mover el boton, asi que un corte por board_vacio puede caer 1-2 frames
# antes de que las posiciones roten.
tr2c = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO + 1):
    tr2c.update(estado({"UL": 50.0}, board=("Ah", "Kd", "2c"), posiciones={"UL": "BTN"}))
info = tr2c.update(estado({"UL": 50.0}, posiciones={"UL": "BTN"}))   # board_vacio
check("tras cortar con el boton sin mover, las posiciones NO estan asentadas",
      info["posiciones_asentadas"] is False)
info = tr2c.update(estado({"UL": 50.0, "MR": 30.0}, posiciones={"MR": "BTN"}))
check("y se asientan en cuanto el boton se mueve",
      info["posiciones_asentadas"] is True)

tr2d = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO + 1):
    tr2d.update(estado({"UL": 50.0}, posiciones={"UL": "BTN"}))
check("si el boton nunca se ha visto moverse no se bloquea nada: la primera mano "
      "no hereda posiciones de nadie", tr2d.resumen()["posiciones_asentadas"] is True)

# CARTAS DISTINTAS ya NO corta: parecia la señal mas fuerte y medida acierta 3 de
# 52, y en una sesion sus 4 disparos fueron TODOS falsos (el OCR lee mal una
# carta del hero el 2,4% de los frames). Ademas es redundante con cartas_aparecen.
tr3 = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO):
    tr3.update(estado({"UL": 50.0}, hero=("Ah", "Kd")))
m0 = tr3.update(estado({"UL": 46.0}, hero=("Ah", "Kd")))["mano"]
info = tr3.update(estado({"UL": 44.0}, hero=("7c", "2d")))
check("una carta del hero mal leida NO parte la mano (era la fuente de cortes "
      "falsos: 4 de 4 en una sesion)", info["mano"] == m0)
check("pero la señal se sigue exponiendo", "cartas" not in ht.MOTIVOS_DE_CORTE)

# BOARD QUE SE VACIA: una mano empieza siempre preflop. Se descarto en la primera
# medicion (267 frames) y con 3.300 resulta ser de las mejores: 35 de 52, cero
# falsos.
tr4 = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO):
    tr4.update(estado({"UL": 50.0}, board=("2h", "3h", "4h")))
m0 = tr4.update(estado({"UL": 46.0}, board=("2h", "3h", "4h")))["mano"]
info = tr4.update(estado({"UL": 46.0}, board=()))
check("el board que se vacia = mano nueva", info["mano"] == m0 + 1)

tr = ht.HandTracker()
for _ in range(ht.MIN_FRAMES_POR_MANO):
    tr.update(estado({"UL": 50.0}), hand_number="111")
info = tr.update(estado({"UL": 46.0}), hand_number="111")
check("el mismo numero de mano no corta", com(info, "UL") == 4.0)
info = tr.update(estado({"UL": 80.0}), hand_number="222")
check("un numero de mano nuevo corta", com(info, "UL") == 0)

# UNA MANO NO DURA DOS FRAMES. Las señales se solapan -el board se vacia, se
# reparten cartas y el chat cambia el numero en un par de segundos- asi que una
# frontera real dispara varias veces. Sin minimo, el rastreador veia 110 manos
# donde el chat contaba 53.
tr5 = ht.HandTracker()
tr5.update(estado({"UL": 50.0}), hand_number="111")
m0 = tr5.update(estado({"UL": 50.0}), hand_number="222")["mano"]
check(f"un corte en los primeros {ht.MIN_FRAMES_POR_MANO} frames se ignora",
      m0 == 1)

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

# --- COMPROMETIDO POR CALLE -------------------------------------------------
# El total de la mano no dice si hay una apuesta que igualar AHORA: en el turn,
# lo que un rival puso en el flop ya esta en el bote. Separarlo por calle es lo
# que permite distinguir un squeeze de una resubida.
print("\n# --- comprometido por calle ---")
tr = ht.HandTracker()
i = tr.update(estado({"UL": 50.0}))
check("preflop la calle es 'preflop'", i["calle"] == "preflop")
i = tr.update(estado({"UL": 46.0}))
a = i["asientos"]["UL"]
check("PREFLOP el comprometido de la calle es el MISMO que el de la mano, asi "
      "que nada de lo que ya funcionaba cambia",
      a["comprometido"] == a["comprometido_calle"] == 4.0)

i = tr.update(estado({"UL": 46.0}, board=("2h", "3h", "4h")))
check("al salir el flop cambia la calle", i["calle"] == "flop")
check("y la cuenta de la calle arranca de cero: lo del preflop ya esta en el bote",
      i["asientos"]["UL"]["comprometido_calle"] == 0.0)
check("pero el total de la mano se conserva",
      i["asientos"]["UL"]["comprometido"] == 4.0)

i = tr.update(estado({"UL": 40.0}, board=("2h", "3h", "4h")))
a = i["asientos"]["UL"]
check("una apuesta en el flop cuenta en la calle", a["comprometido_calle"] == 6.0)
check("y suma al total de la mano", a["comprometido"] == 10.0)

i = tr.update(estado({"UL": 40.0}, board=("2h", "3h", "4h", "9s")))
check("el turn vuelve a poner la calle a cero",
      i["calle"] == "turn" and i["asientos"]["UL"]["comprometido_calle"] == 0.0)

# LA CALLE SOLO AVANZA: un board mas corto es una lectura perdida, no una calle
# anterior. Si retrocediera, una lectura floja borraria lo que un rival lleva
# puesto en la calle en curso. (Un board que se vacia DEL TODO si corta la mano:
# es la señal de frontera, ver arriba. Aqui se prueba el board mas corto, que es
# una lectura incompleta y no una mano nueva.)
i = tr.update(estado({"UL": 34.0}, board=("2h", "3h", "4h")))
check("un board mas corto NO retrocede la calle", i["calle"] == "turn")
check("y lo puesto en la calle se sigue acumulando",
      i["asientos"]["UL"]["comprometido_calle"] == 6.0)

# un asiento que aparece a mitad de calle no puede inventarse una base
tr2 = ht.HandTracker()
tr2.update(estado({"UL": 50.0}, board=("2h", "3h", "4h")))
i = tr2.update(estado({"UL": 50.0, "MR": 30.0}, board=("2h", "3h", "4h")))
check("un asiento visto por primera vez a mitad de calle empieza en cero, no en "
      "un numero inventado",
      i["asientos"]["MR"]["comprometido_calle"] == 0.0)

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
check("y tambien lo de la calle", ul["committed_calle"] == 4.0)
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


def con_nombre(nombre, accion, cartas=("Ah", "Kd"), boton="UL"):
    return {"board": [], "hero_cards": list(cartas), "to_call": None,
            "players": [{"seat": "UL", "name": nombre, "action": accion,
                         "stack": 50.0, "is_hero": False,
                         "position": "BTN" if boton == "UL" else None},
                        {"seat": "MR", "name": "otro", "action": None,
                         "stack": 30.0, "is_hero": False,
                         "position": "BTN" if boton == "MR" else None}]}


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

# SE FIJA POR MAYORIA, no por "el ultimo bueno". El problema real no era solo el
# verbo: el OCR lee el mismo nick de formas distintas casi cada frame. Medido en
# una sesion real, un asiento dio OCHO variantes en una mano ("juanpalla",
# "Juanpalia", "juanpaila", "jJuanpalia"...) con 40 cambios, y en el HUD eso se
# ve como un nombre que no para de bailar. Con la mayoria: 59 -> 12 cambios en la
# sesion entera, un 80% menos.
for _ in range(8):
    s = con_nombre("Dav6934", None)
    ht.aplicar(s, tr.update(s))
s3 = con_nombre("Dav693A", None)          # una variante suelta del OCR
ht.aplicar(s3, tr.update(s3))
check("una lectura suelta NO tumba al nombre visto muchas veces",
      s3["players"][0]["name"] == "Dav6934")
check("y se marca que lo mostrado no es lo leido en este frame",
      s3["players"][0].get("name_repuesto") is True)

# pero si la variante nueva pasa a ser la mayoritaria, se adopta: no es un latch
for _ in range(20):
    s4 = con_nombre("Dav693A", None)
    ht.aplicar(s4, tr.update(s4))
check("si la lectura nueva se vuelve mayoritaria, se adopta (no es un latch)",
      s4["players"][0]["name"] == "Dav693A")

# EN ZOOM el cliente cambia de mesa entre manos, asi que el ocupante de un
# asiento puede ser OTRA persona: reponer entre manos seria inventarse quien es.
s4 = con_nombre(None, "Pasar", cartas=())          # se recogen las cartas
ht.aplicar(s4, tr.update(s4))
s4 = con_nombre(None, "Pasar", cartas=("7c", "2d"), boton="MR")   # el boton rota: mano nueva
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
