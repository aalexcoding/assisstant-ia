"""
Fase 4.4: ESTUDIO POST-MANO. Cuando una mano termina, busca en las
transcripciones de los videos los trozos que hablan de situaciones parecidas.

QUE ES Y QUE NO ES. Esto NO es consejo sobre la mano que acabas de jugar. Lo que
devuelve es prosa recuperada de un video por parecido semantico: puede hablar de
un board parecido con stacks distintos, o de la idea general y no de tu caso.
Presentarlo como "deberias haber hecho X" seria afirmar algo inverificable sobre
una mano concreta, que es justo lo que este proyecto evita.

Por eso vive AQUI, en el post-mano, y no en el motor de decision:

  - la mano ya ha terminado, asi que no hay ninguna accion que condicionar;
  - la latencia no importa (la primera consulta carga el modelo y tarda segundos);
  - y el encuadre honesto es "mira este minuto de este video", con el video y el
    timestamp delante, para que se pueda comprobar.

LA CONSULTA se construye de lo observado en el último frame postflop: hero,
board, mano formada, posiciones, agresiones preflop vistas, bote/SPR y acciones
capturadas con su calle; al cierre se añaden la mano ganadora del chat y si hubo
showdown. La lista de acciones sigue declarada incompleta: su ausencia no se usa
para inventar iniciativa ni un bote limpeado.

describir() es puro y se puede probar sin indice ni modelo.
"""

from decision import action_log

# Cuantos trozos se ofrecen. Pocos: son minutos de video que hay que ver, y una
# lista larga no se mira.
K_POR_DEFECTO = 3

# Por debajo de esta similitud no se enseña nada. El indice SIEMPRE devuelve los k
# mas parecidos, aunque el mas parecido no se parezca en nada; sin umbral, una
# mano rara acabaria con tres referencias irrelevantes presentadas como si
# vinieran a cuento.
SIMILITUD_MINIMA = 0.45


_ORDEN_POSTFLOP = {
    "SB": 0, "BB": 1, "UTG": 2, "UTG+1": 3, "UTG1": 3,
    "MP": 4, "LJ": 5, "HJ": 6, "CO": 7, "BTN": 8,
}


def _relacion_posicional(state):
    hero = state.get("hero_position")
    jugadores = state.get("players") or []
    rivales = [p.get("position") for p in jugadores
               if p.get("in_hand") and not p.get("is_hero") and p.get("position")]
    if hero not in _ORDEN_POSTFLOP or not rivales:
        return None
    indices = [_ORDEN_POSTFLOP[p] for p in rivales if p in _ORDEN_POSTFLOP]
    if not indices:
        return None
    h = _ORDEN_POSTFLOP[hero]
    if h > max(indices):
        return "IP"
    if h < min(indices):
        return "OOP"
    return None                       # multiway: está entre dos rivales


def contexto_desde_estado(state, hand=None):
    """Extrae contexto observado del último frame postflop de una mano.

    El resultado es serializable y no conserva el GameState mutable. No intenta
    completar las acciones que el muestreo no vio.
    """
    if not state:
        return {}
    board = list(state.get("board") or [])
    hero = next((p for p in state.get("players") or [] if p.get("is_hero")), {})
    rivals = [p for p in state.get("players") or []
              if p.get("in_hand") and not p.get("is_hero")]
    pre = state.get("preflop_action") or action_log.estado_preflop(state)
    agresiones = pre.get("agresiones_observadas") or 0
    aggressor = pre.get("ultimo_agresor_seat")
    initiative = ("con_iniciativa" if aggressor == "HERO" else
                  "sin_iniciativa" if aggressor else None)
    # La lista es incompleta: ausencia de agresión NO demuestra bote limpeado.
    # Una o más agresiones sí son evidencia positiva y permiten clasificar.
    pot_type = (None if agresiones == 0 else
                "single_raised" if agresiones == 1 else
                "3bet" if agresiones == 2 else
                "4bet_plus")

    pot = state.get("pot")
    stacks = [p.get("stack") for p in [hero, *rivals]
              if isinstance(p.get("stack"), (int, float))]
    effective = min(stacks) if len(stacks) >= 2 else None
    spr = (effective / pot if isinstance(pot, (int, float)) and pot > 0
           and effective is not None else None)

    acciones = []
    for a in (state.get("acciones") or {}).get("acciones") or []:
        if not isinstance(a, dict):
            continue
        acciones.append({
            k: a.get(k) for k in (
                "street", "position", "seat", "accion",
                "committed_street_bb", "bet_visible_bb", "pot_bb")
            if a.get(k) is not None
        })
    agresivas_preflop = [
        index for index, action in enumerate(acciones)
        if action.get("street") == "preflop"
        and action.get("accion") in action_log.AGRESIVAS
    ]
    squeeze_observed = None
    if len(agresivas_preflop) >= 2:
        first, second = agresivas_preflop[:2]
        if any(action.get("street") == "preflop"
               and action.get("accion") == "call"
               for action in acciones[first + 1:second]):
            squeeze_observed = True

    return {
        "board": board,
        "hero_cards": list(state.get("hero_cards") or []),
        "hero_observed": len(state.get("hero_cards") or []) == 2,
        "hero_hand": (hand or {}).get("made_name"),
        "street": (hand or {}).get("street") or state.get("calle_seguida"),
        "hero_position": state.get("hero_position"),
        "position_relation": _relacion_posicional(state),
        "initiative": initiative,
        "pot_type": pot_type,
        "squeeze_observed": squeeze_observed,
        "opponents": len(rivals),
        "pot_bb": pot if isinstance(pot, (int, float)) else None,
        "to_call_bb": (state.get("to_call")
                       if isinstance(state.get("to_call"), (int, float)) else None),
        "effective_stack_bb": effective,
        "spr": round(spr, 2) if spr is not None else None,
        "actions": acciones,
        "actions_complete": bool((state.get("acciones") or {}).get("completo")),
    }


def describir(board=None, mano_ganadora=None, hero_en_showdown=None, calle=None,
              contexto=None):
    """Texto de consulta a partir de lo que se sabe de la mano terminada.

    Solo entra lo OBSERVADO. Nada de suponer iniciativa, tipo de rival ni
    intenciones: eso enriqueceria la busqueda a cambio de buscar una mano que no
    es la que se jugo."""
    contexto = contexto or {}
    partes = []
    cartas = [c for c in (contexto.get("board") or board or []) if c]
    if cartas:
        partes.append("board " + " ".join(cartas))
        partes.append(_textura(cartas))
    street = contexto.get("street") or calle
    if street:
        partes.append(street)
    if contexto.get("hero_cards"):
        partes.append("hero " + " ".join(contexto["hero_cards"]))
    if contexto.get("hero_hand"):
        partes.append("mano del hero " + str(contexto["hero_hand"]))
    if contexto.get("hero_position"):
        partes.append("hero en " + str(contexto["hero_position"]))
    relation = contexto.get("position_relation")
    if relation == "IP":
        partes.append("jugando con posicion IP")
    elif relation == "OOP":
        partes.append("jugando fuera de posicion OOP")
    if contexto.get("initiative") == "con_iniciativa":
        partes.append("con iniciativa agresor preflop")
    elif contexto.get("initiative") == "sin_iniciativa":
        partes.append("sin iniciativa defensor preflop")
    pot_type = contexto.get("pot_type")
    if pot_type == "single_raised":
        partes.append("bote subido simple")
    elif pot_type == "3bet_4bet":
        partes.append("bote 3bet o 4bet")
    elif pot_type == "3bet":
        partes.append("bote 3bet")
    elif pot_type == "4bet_plus":
        partes.append("bote 4bet o superior")
    elif pot_type == "limped":
        partes.append("bote limpeado")
    if contexto.get("spr") is not None:
        partes.append(f"SPR {contexto['spr']:g}")
    if contexto.get("opponents"):
        partes.append(f"{contexto['opponents']} rivales")
    secuencia = []
    for a in contexto.get("actions") or []:
        # Una sesión antigua no lleva calle. Incluirla como "?" mezclaría posts
        # preflop con acciones del flop; se prefiere omitir a inventar la calle.
        if a.get("street") not in ("flop", "turn", "river"):
            continue
        who = a.get("position") or a.get("seat") or "jugador"
        action = a.get("accion")
        if action:
            secuencia.append(f"{a.get('street') or '?'} {who} {action}")
    if secuencia:
        partes.append("secuencia observada " + ", ".join(secuencia))
    if mano_ganadora:
        partes.append(f"mano ganadora {mano_ganadora}")
    if hero_en_showdown is True:
        partes.append("mano que llega a showdown")
    elif hero_en_showdown is False:
        partes.append("mano que se gana sin showdown")
    return " ".join(p for p in partes if p).strip()


_PALOS = {"h": "corazones", "d": "diamantes", "c": "treboles", "s": "picas"}
_ALTAS = {"A", "K", "Q", "J", "T"}


def _textura(cartas):
    """Dos rasgos del board que sí se pueden leer de las cartas, sin suponer
    nada: si hay pareja y si hay proyecto de color."""
    rangos = [c[:-1] for c in cartas]
    palos = [c[-1].lower() for c in cartas]
    rasgos = []
    if len(set(rangos)) < len(rangos):
        rasgos.append("board emparejado")
    mas_comun = max((palos.count(p) for p in set(palos)), default=0)
    if mas_comun >= 3:
        rasgos.append("board monocolor")
    elif mas_comun == 2:
        rasgos.append("board con dos del mismo palo")
    else:
        rasgos.append("board rainbow")
    if sum(1 for r in rangos if r in _ALTAS) >= 2:
        rasgos.append("board con cartas altas")
    return " ".join(rasgos)


def _buscar_detallado(texto, k=K_POR_DEFECTO, minimo=SIMILITUD_MINIMA,
                      contexto=None):
    """Trozos de video parecidos, o [] si no hay indice o nada supera el umbral.

    Nunca lanza: si falta el indice o el modelo, el panel de estudio se queda
    vacio y la app sigue. Es una ayuda para despues, no parte del analisis."""
    if not texto:
        return [], None
    try:
        from decision.rag import query
        # Se sobre-recupera y después se deja un solo fragmento por vídeo. Sin
        # esto tres chunks contiguos de la misma lección ocupan las tres plazas.
        crudos = query.search(texto, k=max(k * 4, k), context=contexto)
    except (query.IndexUnavailableError, query.IndexIncompatibleError) as e:
        return [], str(e)
    except Exception:        # noqa: BLE001 - falta fastembed, modelo sin descargar...
        return [], "no se pudo cargar el modelo semántico"
    salida = []
    videos_vistos = set()
    for r in crudos:
        try:
            score = float(r.get("score", 0))
        except (TypeError, ValueError):
            continue
        if score < minimo:
            continue
        video = r.get("video")
        if video in videos_vistos:
            continue
        videos_vistos.add(video)
        salida.append({
            "video": video,
            "video_path": r.get("video_path"),
            "title": r.get("title"),
            "inicio_s": float(r.get("start_time") or 0),
            "fin_s": float(r.get("end_time") or 0),
            "texto": (r.get("text") or "").strip(),
            "score": score,
            "relevance_score": float(r.get("relevance_score", score)),
        })
        if len(salida) >= k:
            break
    return salida, None


def buscar(texto, k=K_POR_DEFECTO, minimo=SIMILITUD_MINIMA, contexto=None):
    """Compatibilidad: devuelve solo las referencias."""
    return _buscar_detallado(texto, k, minimo, contexto)[0]


def estudiar(board=None, mano_ganadora=None, hero_en_showdown=None, calle=None,
             k=K_POR_DEFECTO, contexto=None):
    """Une fichas verificables y referencias semánticas para el postmano."""
    from decision.rag import strategy_cards

    texto = describir(board, mano_ganadora, hero_en_showdown, calle, contexto)
    referencias, problema = _buscar_detallado(
        texto, k=k, contexto=contexto)
    fichas = strategy_cards.match(contexto) if contexto else []
    return {
        "consulta": texto,
        "fichas": fichas,
        "referencias": referencias,
        "problema": problema,
    }


def minuto(segundos):
    """72.4 -> '1:12', para poder saltar al punto del video."""
    s = int(segundos or 0)
    return f"{s // 60}:{s % 60:02d}"
