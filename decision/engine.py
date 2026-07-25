"""
Fase 4 (primera pieza): motor de decision. Toma el GameState que produce
vision/table_state.py (analyze()/analyze_color_deck()) y, si hay datos
suficientes, devuelve una recomendacion consultando decision/preflop/lookup.py.

Solo cubre preflop (board vacio): si ya hay flop/turn/river no hay nada que
recomendar con este motor, eso es la Fase 4.3 (RAG postflop), que todavia
no existe.

Defensa contra una subida ajena (facing="threebet_call"): si el GameState
trae facing="bet" (hay un boton "Igualar/Pagar", asi que hay una apuesta que
enfrentar) y a partir del importe apostado por asiento (table_state /
seat_map.detect_raiser) se identifica UNA sola subida clara -un unico rival
con apuesta por encima de la ciega grande-, se consulta el rango de defensa
con vs_position = la posicion de ese raiser. La ciega grande usada es la
EFECTIVA (blinds.local.json manda sobre la detectada), de ahi que la subida
se recompute aqui y no se confie sin mas en state["vs_position"].

Conservador por diseño: si hay varias apuestas por encima de la ciega
(bote multiway o 3bet ya presente), si el propio hero ya ha subido (enfrenta
una resubida), o si el raiser no tiene posicion asignada, NO se adivina ->
se abstiene con un warning (una defensa contra la posicion equivocada es
peor que ninguna). Si no hay ninguna subida (solo ciegas/limps, o no hay
apuesta que enfrentar) se sigue con open_raise como antes: el hero abre.

Limitaciones aceptadas: solo se cubre la subida unica heads-up (el rango
threebet_call solo tiene 10/15/20/25/30/35/40bb; por debajo de 10bb NO se
abstiene -como decia antes este docstring, y era falso- sino que
lookup._nearest_stack_key redondea a la clave mas cercana y se avisa, ver
_stack_key_note); en frames de transicion entre manos el cliente puede
mostrar importes de una mano ya resuelta -no se distingue de una subida en
curso con una sola imagen-; y sigue sin registrarse el historial de apuestas
de la calle, asi que el juicio es sobre lo que hay dibujado en ese frame.

Requiere decision/preflop en sys.path (lo hace el caller, igual que
vision/table_state.py no gestiona su propio sys.path para importar a sus
hermanos de vision/).

Unidades (state["stack_unit"], lo pone la vision): el cliente muestra los
importes en FICHAS o en BIG BLINDS ("123,4 BB") segun la config del usuario.
En modo BB el stack leido YA es la profundidad en bb: se usa directamente
como stack_bb y NO hacen falta ciegas (ni detectadas ni manuales), y una
subida es cualquier apuesta > 1 bb. En modo fichas todo sigue igual: se
divide el stack por la ciega grande efectiva.

Ciegas manuales (solo modo fichas): el nivel de ciegas es transitorio en
pantalla (solo sale en el chat al subir de nivel) pero el usuario lo sabe y
cambia cada varios minutos, asi que se puede fijar a mano. Si existe
blinds.local.json en la raiz del repo (lo escribe el comando ./set-blinds
mientras la app corre), su valor MANDA sobre lo que detecte la vision. El
stack del hero sigue siendo automatico (cambia cada mano; meterlo a mano
seria insufrible). Como el fichero no caduca solo y en torneo los niveles
suben cada pocos minutos, se mide su antiguedad por el mtime y pasados
_MANUAL_BLINDS_STALE_S se AVISA (sin descartarlas: son lo unico que hay),
tanto en warnings como en el propio reasoning que ve el usuario.

Profundidad fuera de rejilla: lookup._nearest_stack_key redondea a la clave de
stack mas cercana sin limite, asi que a 100bb (principio de torneo) devuelve el
rango de 40bb -el maximo digitalizado- como si fuera el del spot. _stack_key_note
distingue dos casos contra la rejilla REAL de cada familia (_stack_grid, leida de
los propios datos): si la profundidad cae ENTRE dos claves que existen es una
interpolacion y se nombra la tabla usada y la vecina; si cae FUERA de la tabla es
una extrapolacion y ademas se avisa. En los dos casos se sigue recomendando
-es la mejor referencia disponible- pero no se presenta como exacta.

Cache del stack del hero: cuando es el turno del hero, su nameplate deja
de mostrar el numero de fichas y muestra la accion ("Igualar X", "All-in",
"Ganado"...) o lo tapan los botones -es decir, el stack desaparece de
pantalla justo en el momento en que se quiere recomendar. Se cachea el
ultimo stack leido (visible unos frames antes, cuando aun no era el turno)
y se reutiliza si el frame actual no lo trae, mientras sea reciente
(_HERO_STACK_TTL_S). Es una aproximacion (el stack efectivo baja al meter
fichas), pero para elegir el rango preflop por profundidad es suficiente y
es mucho mejor que no recomendar. Se anota en el reasoning cuando se usa.
"""
import json
import os
import time

from lookup import RANGES, recommend

_MANUAL_BLINDS_PATH = os.path.join(os.path.dirname(__file__), "..", "blinds.local.json")
_DECISIONS_LOG_PATH = os.path.join(os.path.dirname(__file__), "decisions.local.jsonl")

_HERO_STACK_TTL_S = 90.0
_last_hero_stack = {"value": None, "t": 0.0, "unit": None}

# a partir de esta edad, unas ciegas manuales se consideran sospechosas de estar
# desfasadas: los niveles de torneo duran tipicamente entre 3 y 15 min, asi que
# 10 min sin actualizar es motivo suficiente para avisar (no para descartarlas).
_MANUAL_BLINDS_STALE_S = 600.0

# tolerancia (en bb) para considerar que la profundidad COINCIDE con una clave de
# la tabla. Por debajo de esto no se dice nada; por encima se nombra la tabla
# vecina, para que el usuario sepa que su profundidad cae entre dos de sus
# gráficos y cual se uso.
_STACK_KEY_EXACT_TOL = 0.25

# Un umbral FIJO no servia. Antes habia un solo _STACK_KEY_FAR_BB = 2.6 y no
# distinguia dos situaciones muy distintas:
#   - INTERPOLACION: la profundidad cae ENTRE dos claves que si existen (22,7bb
#     entre 20 y 25). El rango sale de una tabla real suya, solo que de la vecina.
#   - EXTRAPOLACION: la profundidad cae FUERA de la tabla (>40bb, todo el
#     principio de torneo; o <4bb). Ahi el rango devuelto NO es su rango para ese
#     spot y hay que avisar de verdad.
# Ademas el umbral fijo tenia un agujero: las claves de threebet_call son
# 10/15/20/25/30/35/40, asi que una defensa a 12,5bb queda a 2,5bb de la clave de
# 10 y 2,5 < 2,6 -> se servia el grafico de 10bb SIN NINGUN AVISO. Y 12,5bb si es
# una profundidad digitalizada en open_raise, asi que el hueco era invisible.
# Ahora el juicio se hace contra la rejilla REAL de cada familia (_stack_grid).


def _cached_hero_stack(hero, unit):
    """Stack del hero, con cache reciente: cuando es su turno el nameplate deja
    de mostrar el numero de fichas (muestra la accion o lo tapan los botones),
    asi que se reutiliza el ultimo leido si es reciente y de la MISMA unidad
    (fichas o bb; no se mezclan si el usuario cambia de modo). Devuelve
    (valor, cacheado)."""
    val = hero.get("stack") if hero else None
    if val is not None:
        _last_hero_stack.update(value=val, t=time.monotonic(), unit=unit)
        return val, False
    if (_last_hero_stack["value"] is not None and _last_hero_stack["unit"] == unit
            and time.monotonic() - _last_hero_stack["t"] <= _HERO_STACK_TTL_S):
        return _last_hero_stack["value"], True
    return None, False


# ver seat_map.BB_POSTED_MAX_MULT: la apuesta del asiento BB es ciega + ante
# (obligatorio), no una subida, hasta este multiplo de la ciega grande.
_BB_POSTED_MAX_MULT = 2.0


def _detect_raiser(players, bb):
    """Gemelo de seat_map.detect_raiser, reimplementado aqui para no acoplar el
    motor a vision/ (cv2): con el importe apostado por asiento y la ciega
    grande EFECTIVA, decide si hay una subida unica que enfrentar. Devuelve
    (vs_position, code) con code en {single, no_raise, multiway, hero_raised,
    bb_raised, raiser_no_pos, no_bb}. Ver seat_map.detect_raiser para el detalle
    y para por que el asiento BB se trata aparte (BB-ante)."""
    if not bb:
        return None, "no_bb"
    above = [p for p in players
             if isinstance(p.get("bet"), (int, float)) and p["bet"] > bb]
    if any(p.get("is_hero") for p in above):
        return None, "hero_raised"
    opp = [p for p in above if not p.get("is_hero")]
    bb_seat = [p for p in opp if p.get("position") == "BB"]
    if bb_seat and any(p["bet"] > bb * _BB_POSTED_MAX_MULT for p in bb_seat):
        return None, "bb_raised"
    opp = [p for p in opp if p.get("position") != "BB"]
    if not opp:
        return None, "no_raise"
    if len(opp) > 1:
        return None, "multiway"
    pos = opp[0].get("position")
    if pos is None:
        return None, "raiser_no_pos"
    return pos, "single"


_STACK_GRID_CACHE = {}


def _stack_grid(facing):
    """Claves de profundidad (float, ordenadas) que existen de verdad en la tabla
    de ese facing. Se lee de lookup.RANGES para que la rejilla nunca se desincronice
    con los datos: open_raise tiene 4/6/8/10/12.5/15/20/25/30/35/40 y threebet_call
    solo 10/15/20/25/30/35/40 (no hay defensa digitalizada por debajo de 10bb)."""
    if facing not in _STACK_GRID_CACHE:
        _STACK_GRID_CACHE[facing] = sorted(float(k) for k in RANGES.get(facing, {}))
    return _STACK_GRID_CACHE[facing]


def _stack_key_note(result, stack_bb, facing, warnings):
    """Devuelve una nota para el reasoning segun donde cae la profundidad real
    respecto a la rejilla de SU tabla, y avisa en warnings solo cuando toca.

    lookup._nearest_stack_key redondea a la clave mas cercana SIN limite, asi que
    hay que distinguir dos casos que antes se trataban igual:

      - EXTRAPOLACION (fuera de la rejilla): con 100bb devuelve el rango de 40bb
        como si fuera el del spot. El rango NO es el suyo para esa profundidad ->
        warning + nota visible.
      - INTERPOLACION (entre dos claves que si existen): 22,7bb sale del grafico de
        25bb, que es una tabla real suya. No es un error, es la resolucion de la
        rejilla -> se nombra la tabla usada y la vecina, sin ensuciar warnings."""
    key = result.get("stack_key")
    if key is None:
        return ""
    grid = _stack_grid(facing)
    if not grid:
        return ""

    lo, hi = grid[0], grid[-1]
    if stack_bb > hi + _STACK_KEY_EXACT_TOL or stack_bb < lo - _STACK_KEY_EXACT_TOL:
        borde = hi if stack_bb > hi else lo
        warnings.append(f"profundidad {stack_bb:.1f}bb FUERA de tu tabla de {facing} "
                        f"(cubre {lo:g}-{hi:g}bb): la accion sale del grafico de "
                        f"{borde:g}bb, no es tu rango para {stack_bb:.1f}bb")
        return (f" [OJO: extrapolado del rango de {borde:g}bb; tu tabla solo cubre "
                f"{lo:g}-{hi:g}bb]")

    if abs(stack_bb - key) <= _STACK_KEY_EXACT_TOL:
        return ""

    vecinas = [k for k in grid if k != key]
    vecina = min(vecinas, key=lambda k: abs(k - stack_bb)) if vecinas else None
    if vecina is None:
        return ""
    return (f" [interpolado: se usa tu grafico de {key:g}bb; el de {vecina:g}bb "
            f"queda a {abs(vecina - stack_bb):.1f}bb]")


def _log_decision(state, recommendation, abstain_reason):
    """Anota una linea JSONL por cada decision (recomendacion o abstencion con
    motivo). Semilla para 'aprender el estilo' mas adelante; por ahora es solo
    registro. Un fallo al escribir nunca debe tumbar decide()."""
    try:
        entry = {
            "t": time.time(),
            "image": state.get("image"),
            "hero_cards": state.get("hero_cards") or [],
            "board_empty": not state.get("board"),
            "hero_position": state.get("hero_position"),
            "facing": state.get("facing"),
            "vs_position": state.get("vs_position"),
            "stack_unit": state.get("stack_unit"),
        }
        if recommendation is not None:
            entry["stack_bb"] = round(recommendation.get("stack_bb"), 2)
            entry["action"] = recommendation.get("action")
            entry["facing_used"] = recommendation.get("facing_used")
            entry["vs_position"] = recommendation.get("vs_position")
        else:
            entry["abstain"] = abstain_reason
        with open(_DECISIONS_LOG_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _manual_blinds():
    """Lee blinds.local.json (si existe y es valido). Devuelve (blinds, edad_s),
    con blinds None si no hay o esta mal.

    La EDAD importa: en torneo el nivel de ciegas sube cada pocos minutos, pero
    el fichero manual manda sobre lo detectado y no caduca solo. Unas ciegas
    manuales viejas dan una profundidad en bb equivocada -y por tanto el rango
    equivocado- sin que nada lo delate. Se mide por el mtime del fichero en vez
    de guardar un timestamp dentro, asi ./set-blinds y el panel de la GUI siguen
    escribiendo el mismo formato de siempre sin cambiar nada."""
    try:
        with open(_MANUAL_BLINDS_PATH) as f:
            data = json.load(f)
        bb = data.get("bb")
        if isinstance(bb, (int, float)) and bb > 0:
            try:
                age = max(0.0, time.time() - os.path.getmtime(_MANUAL_BLINDS_PATH))
            except OSError:
                age = None
            return {"sb": data.get("sb"), "bb": bb, "ante": data.get("ante")}, age
    except (FileNotFoundError, ValueError, TypeError):
        pass
    return None, None


def _hero_player(state):
    for p in state.get("players", []):
        if p.get("is_hero"):
            return p
    return None


_RAISE_ABSTAIN = {
    "multiway": "hay varias apuestas por encima de la ciega (bote multiway o 3bet ya "
                "presente); no se recomienda defensa contra una posicion incierta",
    "hero_raised": "el hero ya ha subido y enfrenta una resubida; fuera del modelo "
                   "(open_raise / threebet_call)",
    "bb_raised": "la ciega grande ha subido (mas que ciega+ante). La BB habla ultima "
                 "preflop, asi que no hay rango de defensa contra ella en las tablas: "
                 "los vs_position digitalizados son solo posiciones que hablan ANTES",
    "raiser_no_pos": "se detecto una subida pero el raiser no tiene posicion asignada; "
                     "sin defensa fiable",
    "no_bb": "no se pudo determinar la ciega grande para juzgar la subida",
}


def decide(state):
    warnings = state.setdefault("warnings", [])

    def abstain(reason):
        warnings.append(reason)
        _log_decision(state, None, reason)
        return None

    if state.get("board"):
        return abstain("hay board (ya no es preflop); este motor solo cubre preflop, "
                       "el postflop es la Fase 4.3 (RAG) y todavia no existe")

    hero_cards = state.get("hero_cards") or []
    if len(hero_cards) != 2:
        return abstain("faltan las 2 cartas del hero; no se puede recomendar")

    hero = _hero_player(state)
    hero_position = state.get("hero_position") or (hero.get("position") if hero else None)
    if hero_position is None:
        return abstain("no se detecto la posicion del hero; no se puede recomendar")

    # Profundidad efectiva en bb. En modo BB el stack leido YA esta en bb (no
    # hacen falta ciegas). En modo fichas se divide por la ciega grande
    # efectiva (blinds.local.json manda sobre la detectada).
    # La unidad tiene que venir DECLARADA por la vision. El default silencioso que
    # habia aqui ("chips" si el campo faltaba) era una trampa: analyze() y
    # analyze_color_deck() son rutas de diagnostico que producen stacks en FICHAS
    # ENTERAS y no declaran stack_unit, asi que en cuanto el default pase a "bb"
    # (el paso siguiente, la app va a ser BB-only) un stack de 3955 fichas se leeria
    # como 3955bb -> tabla de 40bb -> una recomendacion con conviccion y falsa.
    # Rechazando el estado sin unidad, esa clase de fallo no puede existir en
    # ninguna de las dos direcciones. Produccion es table_state.analyze_layout().
    unit = state.get("stack_unit")
    if unit is None:
        return abstain("este GameState no declara la unidad de los importes "
                       "(stack_unit): viene de una ruta de diagnostico "
                       "(analyze/analyze_color_deck), cuyos stacks estan en fichas "
                       "enteras y no se pueden interpretar como profundidad. "
                       "Produccion es table_state.analyze_layout()")
    if unit == "bb":
        stack_val, stack_cacheado = _cached_hero_stack(hero, "bb")
        if stack_val is None:
            return abstain("no se encontro el stack del hero en bb (ni reciente en cache); "
                           "no se puede calcular la profundidad")
        stack_bb = stack_val
        bb_efectiva = 1
        blinds = None
        fuente = "stacks en BB"  # sin ciegas necesarias
    else:
        manual, manual_age_s = _manual_blinds()
        blinds = manual or state.get("blinds")
        if not blinds or not blinds.get("bb"):
            return abstain("no hay ciegas (ni manuales via ./set-blinds ni detectadas); "
                           "no se puede calcular el stack en bb")
        stack_val, stack_cacheado = _cached_hero_stack(hero, "chips")
        if stack_val is None:
            return abstain("no se encontro el stack del hero (ni reciente en cache); "
                           "no se puede calcular el stack en bb")
        stack_bb = stack_val / blinds["bb"]
        bb_efectiva = blinds["bb"]
        fuente = "ciegas manuales" if manual else "ciegas del chat"
        # ciegas manuales viejas: se siguen usando (son lo unico que hay) pero se
        # avisa, porque si el nivel ha subido la profundidad en bb esta inflada.
        if manual and manual_age_s is not None and manual_age_s > _MANUAL_BLINDS_STALE_S:
            mins = int(manual_age_s // 60)
            warnings.append(f"las ciegas manuales se fijaron hace {mins} min; si el nivel ya "
                            f"subio, la profundidad en bb (y con ella el rango) esta mal. "
                            f"Actualizalas con ./set-blinds o en el panel de ciegas")
            fuente = f"ciegas manuales de hace {mins} min, comprueba el nivel"

    nota_cache = " stack cacheado de un frame anterior;" if stack_cacheado else ""

    # Defensa vs subida ajena: si el hero enfrenta una apuesta (facing="bet") y
    # se identifica una subida unica, se usa el rango threebet_call contra el
    # raiser. La ciega grande efectiva (1 en modo BB) decide que cuenta como
    # subida, por eso se recomputa aqui.
    # Coherencia entre la lectura de los BOTONES y la de la POSICION: preflop solo
    # la BB puede PASAR (para cualquier otro asiento la ciega grande es una apuesta
    # viva, asi que los botones ofrecerian "Igualar"). Si los botones dicen "Pasar"
    # y la posicion leida no es BB, una de las dos lecturas esta mal; y si la que
    # falla es la posicion, el rango elegido tambien sera el equivocado.
    if state.get("facing") == "check" and hero_position != "BB":
        return abstain(f"contradiccion entre lecturas: los botones ofrecen PASAR (solo la "
                       f"BB puede pasar preflop) pero la posicion detectada es "
                       f"{hero_position}; una de las dos es erronea")

    # NOTA sobre facing=None: NO se abstiene. Seria lo "correcto" en teoria (sin
    # botones no es el turno del hero), pero los botones solo se leen en el 9,9% de
    # los frames del corpus, y sobre el log de una sesion real 55 de los 74 frames
    # decidibles (2 cartas + posicion) tenian facing=None -de ahi salieron casi
    # todas las recomendaciones-. Abstenerse mataria ~75% de la utilidad para
    # protegerse de un caso que no es el peligroso: recomendar una APERTURA cuando
    # el hero no tiene accion pendiente es un preview inofensivo. El caso de verdad
    # peligroso -enfrentar una subida que no se ha detectado- se cubre aparte, con
    # el importe del boton "Igualar" (ver la red de seguridad de to_call).
    facing = "open_raise"
    vs_position = None
    if state.get("facing") == "bet":
        vs_position, code = _detect_raiser(state.get("players", []), bb_efectiva)
        if vs_position is not None:
            facing = "threebet_call"
        elif code != "no_raise":
            return abstain(_RAISE_ABSTAIN[code])
        else:
            # "no_raise" con facing="bet" es normal y correcto cuando el hero es la
            # SB y solo completa (el boton pide 0,5bb) o cuando hay limpers. Pero
            # si el BOTON pide mas de una ciega grande y ningun asiento tiene un
            # importe que lo explique, hay una subida que no se ha sabido atribuir
            # -tipicamente porque el OCR del importe de la mesa fallo-. Seguir por
            # open_raise ahi seria recomendar el rango de APERTURA enfrentando una
            # subida: plausible y falso, el peor fallo posible en esta app.
            to_call = state.get("to_call")
            if isinstance(to_call, (int, float)) and to_call > bb_efectiva:
                return abstain(f"el boton pide {to_call:g} BB para igualar, o sea que hay una "
                               f"subida, pero ningun asiento tiene un importe que la explique "
                               f"(no se leyo la apuesta en la mesa); sin defensa fiable")

    if facing == "threebet_call":
        result = recommend(hero_cards, hero_position, stack_bb,
                           facing="threebet_call", vs_position=vs_position)
        if result is None:
            return abstain(f"sin rango de defensa para {hero_position} vs {vs_position} "
                           f"a {stack_bb:.1f}bb (threebet_call)")
        action = result["action"]
        reasoning = (f"Defensa (3bet/call) de {hero_position} a {stack_bb:.1f}bb efectivos "
                     f"contra la subida de {vs_position} ({fuente};{nota_cache} "
                     f"subida inferida del importe apostado en la mesa)"
                     + _stack_key_note(result, stack_bb, facing, warnings))
    elif hero_position == "BB":
        # La BB nunca ABRE el bote. Si aqui no hay subida que enfrentar, es la
        # opcion de la BB en un bote limpeado/sin subir. No tenemos digitalizado
        # el rango de "raise over limpers" (solo Open Raise y 3bet/Call), asi que
        # por defecto pasar (ver flop gratis) y avisar de la limitacion.
        action = "Pasar (opcion de la BB)"
        reasoning = (f"Estas en la BB con opcion a {stack_bb:.1f}bb ({fuente};{nota_cache} "
                     f"nadie ha subido). Por defecto PASAR y ver el flop gratis; no tengo "
                     f"digitalizado tu rango de 'raise over limpers' para decir si subir.")
    else:
        result = recommend(hero_cards, hero_position, stack_bb, facing="open_raise")
        if result is None:
            return abstain(f"sin rango de apertura para {hero_position} a {stack_bb:.1f}bb "
                           f"(open_raise); revisa que la posicion/stack esten en las tablas")
        action = result["action"]
        reasoning = (f"Rango de apertura de {hero_position} a {stack_bb:.1f}bb efectivos "
                     f"({fuente};{nota_cache} sin subida que enfrentar, el hero abre el bote)"
                     + _stack_key_note(result, stack_bb, facing, warnings))

    recommendation = {
        "action": action,
        "reasoning": reasoning,
        "hero_cards": hero_cards,
        "hero_position": hero_position,
        "stack_bb": stack_bb,
        "stack_unit": unit,
        "stack_cacheado": stack_cacheado,
        "blinds": blinds,
        "facing_used": facing,
        "vs_position": vs_position,
    }
    _log_decision(state, recommendation, None)
    return recommendation
