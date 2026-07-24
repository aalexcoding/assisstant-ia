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
threebet_call no tiene 4/6/8/12.5bb, asi que a esas profundidades no habra
rango y se abstiene); en frames de transicion entre manos el cliente puede
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
seria insufrible).

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

from lookup import recommend

_MANUAL_BLINDS_PATH = os.path.join(os.path.dirname(__file__), "..", "blinds.local.json")
_DECISIONS_LOG_PATH = os.path.join(os.path.dirname(__file__), "decisions.local.jsonl")

_HERO_STACK_TTL_S = 90.0
_last_hero_stack = {"value": None, "t": 0.0, "unit": None}


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


def _detect_raiser(players, bb):
    """Gemelo de seat_map.detect_raiser, reimplementado aqui para no acoplar el
    motor a vision/ (cv2): con el importe apostado por asiento y la ciega
    grande EFECTIVA, decide si hay una subida unica que enfrentar. Devuelve
    (vs_position, code) con code en {single, no_raise, multiway, hero_raised,
    raiser_no_pos, no_bb}. Ver seat_map.detect_raiser para el detalle."""
    if not bb:
        return None, "no_bb"
    above = [p for p in players
             if isinstance(p.get("bet"), (int, float)) and p["bet"] > bb]
    if any(p.get("is_hero") for p in above):
        return None, "hero_raised"
    opp = [p for p in above if not p.get("is_hero")]
    if not opp:
        return None, "no_raise"
    if len(opp) > 1:
        return None, "multiway"
    pos = opp[0].get("position")
    if pos is None:
        return None, "raiser_no_pos"
    return pos, "single"


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
    """Lee blinds.local.json (si existe y es valido). None si no hay o esta mal."""
    try:
        with open(_MANUAL_BLINDS_PATH) as f:
            data = json.load(f)
        bb = data.get("bb")
        if isinstance(bb, (int, float)) and bb > 0:
            return {"sb": data.get("sb"), "bb": bb, "ante": data.get("ante")}
    except (FileNotFoundError, ValueError, TypeError):
        pass
    return None


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
    unit = state.get("stack_unit") or "chips"
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
        manual = _manual_blinds()
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

    nota_cache = " stack cacheado de un frame anterior;" if stack_cacheado else ""

    # Defensa vs subida ajena: si el hero enfrenta una apuesta (facing="bet") y
    # se identifica una subida unica, se usa el rango threebet_call contra el
    # raiser. La ciega grande efectiva (1 en modo BB) decide que cuenta como
    # subida, por eso se recomputa aqui.
    facing = "open_raise"
    vs_position = None
    if state.get("facing") == "bet":
        vs_position, code = _detect_raiser(state.get("players", []), bb_efectiva)
        if vs_position is not None:
            facing = "threebet_call"
        elif code != "no_raise":
            return abstain(_RAISE_ABSTAIN[code])

    if facing == "threebet_call":
        result = recommend(hero_cards, hero_position, stack_bb,
                           facing="threebet_call", vs_position=vs_position)
        if result is None:
            return abstain(f"sin rango de defensa para {hero_position} vs {vs_position} "
                           f"a {stack_bb:.1f}bb (threebet_call)")
        action = result["action"]
        reasoning = (f"Defensa (3bet/call) de {hero_position} a {stack_bb:.1f}bb efectivos "
                     f"contra la subida de {vs_position} ({fuente};{nota_cache} "
                     f"subida inferida del importe apostado en la mesa)")
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
                     f"({fuente};{nota_cache} sin subida que enfrentar, el hero abre el bote)")

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
