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

Investigado (2026-07-24) si se podia inferir "facing"/vs_position sin ese
historial, con una sola imagen, contra las 93 capturas reales de
vision/samples_pokerstars/. Dos señales candidatas, ninguna resulto fiable:
- Ficha de importe delante de cada asiento: es legible y persiste varios
  frames seguidos (a diferencia de las fichas de ciega del commit
  212262d, que solo se ven un frame), pero el importe por si solo no
  distingue una subida real de un limp/complete de ciega: en
  sample_1784855328674.png / sample_1784855333696.png (mano reconstruida
  y cuadrada contra el bote) un jugador en HJ iguala la BB y otro en SB
  completa su ciega, ambos dejando 30.000 delante -mismo aspecto que una
  subida real, indistinguible sin saber cual era el importe a igualar en
  ese momento, algo que no se registra en ningun sitio. Ademas, el mismo
  marcador de "este jugador acaba de actuar" que hace visible el importe
  sustituye temporalmente su nombre y rompe el emparejamiento nombre+stack
  de find_players(), desincronizando las posiciones de todos los demas
  jugadores justo en el frame que interesa (ver sample_1784854879707.png:
  el raise de djordy24100 a 107.000 le hace desaparecer de la lista de
  jugadores esa misma imagen).
- Texto del boton de accion del hero ("Igualar X" vs "Pasar"): en
  sample_1784855333696.png se confirma con el marcador verde de turno que
  es el turno del hero (gaobig) y aun asi no aparece ningun boton de
  accion dentro de la region capturada; 0 de 93 capturas lo muestran en
  ningun momento. La region de calibracion (capture/calibration, fuera de
  alcance de esta investigacion) probablemente no llega a esa franja de
  la ventana.
Forzar cualquiera de las dos habria dado recomendaciones incorrectas en
casos reales verificables (arriba), asi que se descarta: sigue sin haber
forma fiable de saber si el hero abre o responde a una subida ajena.

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
