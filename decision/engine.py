"""
Fase 4 (primera pieza): motor de decision. Toma el GameState que produce
vision/table_state.py (analyze()/analyze_color_deck()) y, si hay datos
suficientes, devuelve una recomendacion consultando decision/preflop/lookup.py.

Solo cubre preflop (board vacio): si ya hay flop/turn/river no hay nada que
recomendar con este motor, eso es la Fase 4.3 (RAG postflop), que todavia
no existe.

Limitacion conocida, no resuelta aqui: el GameState actual no registra el
historial de acciones de la mano (quien ha subido, por cuanto), asi que no
hay forma fiable de saber si el hero esta abriendo el bote o respondiendo a
una subida ajena. Por ahora se asume siempre facing="open_raise": es el
caso mas comun y el unico con cobertura completa de stacks en ranges.json
(threebet_call no tiene los stacks 4/6/8/12.5bb). Cuando el GameState
registre el historial de apuestas de la mano, esto se puede corregir para
distinguir open_raise de threebet_call de verdad.

Requiere decision/preflop en sys.path (lo hace el caller, igual que
vision/table_state.py no gestiona su propio sys.path para importar a sus
hermanos de vision/).
"""
from lookup import recommend


def _hero_player(state):
    for p in state.get("players", []):
        if p.get("is_hero"):
            return p
    return None


def decide(state):
    warnings = state.setdefault("warnings", [])

    if state.get("board"):
        warnings.append("hay board (ya no es preflop); este motor solo cubre preflop, "
                         "el postflop es la Fase 4.3 (RAG) y todavia no existe")
        return None

    hero_cards = state.get("hero_cards") or []
    if len(hero_cards) != 2:
        warnings.append("faltan las 2 cartas del hero; no se puede recomendar")
        return None

    hero = _hero_player(state)
    hero_position = state.get("hero_position") or (hero.get("position") if hero else None)
    if hero_position is None:
        warnings.append("no se detecto la posicion del hero; no se puede recomendar")
        return None

    blinds = state.get("blinds")
    if not blinds or not blinds.get("bb"):
        warnings.append("no se detectaron las ciegas; no se puede calcular el stack en bb")
        return None

    if hero is None or hero.get("stack") is None:
        warnings.append("no se encontro el stack del hero; no se puede calcular el stack en bb")
        return None

    stack_bb = hero["stack"] / blinds["bb"]

    result = recommend(hero_cards, hero_position, stack_bb, facing="open_raise")
    if result is None:
        warnings.append(f"sin rango para {hero_position} a {stack_bb:.1f}bb (facing=open_raise)")
        return None

    return {
        "action": result["action"],
        "reasoning": f"Rango preflop de {hero_position} a {stack_bb:.1f}bb efectivos "
                     f"(asumiendo que el hero abre el bote; el motor no distingue todavia "
                     f"open_raise de respuesta a una subida ajena)",
        "hero_cards": hero_cards,
        "hero_position": hero_position,
        "stack_bb": stack_bb,
    }
