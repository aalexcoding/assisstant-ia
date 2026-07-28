"""
Lo que NO PUEDE PASAR en una mano de verdad.

Estas comprobaciones existian ya, dentro de vigilar_sesion.py, pero alli solo
IMPRIMIAN un aviso mientras la partida corria. Son afirmaciones sobre las reglas
del poker y sobre el contrato del motor, asi que valen igual como aserciones: se
extraen aqui para que las use el vigilante EN VIVO y la suite SOBRE LO GRABADO,
sin dos copias que puedan discrepar.

Todo lo de aqui es puro: entra un GameState (mas su recomendacion) y sale una
lista de violaciones. Lista vacia = nada que objetar.

DOS FAMILIAS, porque se comprueban distinto:

  - DE FRAME: se ven en una sola imagen (una carta repetida en el board, una
    recomendacion sobre cartas apagadas).
  - DE SERIE: solo se ven mirando frames consecutivos de la MISMA mano (que el
    numero de jugadores cambie, que al hero le cambie la posicion). Nadie se
    levanta a mitad de mano y el boton no se mueve hasta que la mano acaba, asi
    que si eso cambia es que se ha leido mal.
"""

# Orden de habla preflop, de la posicion mas temprana a la mas tardia.
ORDEN_PREFLOP = ("EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB")

# Un board legal tiene 0 (preflop), 3 (flop), 4 (turn) o 5 (river) cartas.
BOARD_LEGAL = (0, 3, 4, 5)

# Caben nueve en la mesa mas grande que digitaliza el proyecto.
MAX_JUGADORES = 9


def _sin_mesa(state):
    """Si no se encontro el ovalo, todas las zonas estan desplazadas y no hay
    nada que juzgar: los campos vienen vacios a proposito."""
    return any("encuentra la mesa" in w or "ovalo" in w
               for w in state.get("warnings") or [])


def de_frame(state, recommendation=None):
    """Contradicciones visibles en UN frame. Devuelve [(clave, detalle), ...]."""
    if _sin_mesa(state):
        return []

    fallos = []
    board = state.get("board") or []
    hero = state.get("hero_cards") or []
    jugadores = state.get("players") or []

    # --- las reglas del juego ------------------------------------------------
    if len(set(board)) < len(board):
        fallos.append(("board_repetido", f"board con carta repetida: {board}"))
    if set(board) & set(hero):
        fallos.append(("carta_en_dos_sitios",
                       f"carta tuya tambien en el board: {sorted(set(board) & set(hero))}"))
    if len(set(hero)) < len(hero):
        fallos.append(("hero_repetida", f"tus dos cartas son la misma: {hero}"))
    if len(board) not in BOARD_LEGAL:
        fallos.append(("board_ilegal", f"un board no puede tener {len(board)} cartas"))
    if len(jugadores) > MAX_JUGADORES:
        fallos.append(("demasiados_jugadores", f"{len(jugadores)} jugadores en la mesa"))
    if sum(1 for p in jugadores if p.get("is_hero")) > 1:
        fallos.append(("dos_heroes", "mas de un jugador marcado como hero"))

    posiciones = [p.get("position") for p in jugadores if p.get("position")]
    if len(set(posiciones)) < len(posiciones):
        fallos.append(("posicion_duplicada", f"dos asientos con la misma posicion: {posiciones}"))

    # Un rival que ENSEÑA sus cartas esta en la mano por definicion. Darlo por
    # retirado es el fallo que dejaba la equity inflada: en el all-in el cliente
    # gira las cartas, el dorso desaparece y el recuento de rivales BAJA justo
    # cuando el hero mas necesita saber contra cuantos va (ver
    # seat_map.revealed_pair_seats). Los frames grabados antes de que existiera
    # el campo no traen "revealed" y no disparan esto, que es lo que se quiere:
    # el invariante vigila de aqui en adelante, no reprocha el pasado.
    fantasmas = [p.get("seat") for p in jugadores
                 if p.get("revealed") and not p.get("in_hand")]
    if fantasmas:
        fallos.append(("revelado_pero_retirado",
                       f"asiento(s) que enseñan la mano pero no cuentan como en "
                       f"juego: {fantasmas}"))

    # El raiser al que uno DEFIENDE tiene que hablar antes: si habla despues, lo
    # de delante no es una subida que defender sino una resubida a la apertura
    # del propio hero, y las tablas no cubren eso.
    hp, vs = state.get("hero_position"), state.get("vs_position")
    if hp in ORDEN_PREFLOP and vs in ORDEN_PREFLOP \
            and ORDEN_PREFLOP.index(vs) >= ORDEN_PREFLOP.index(hp):
        fallos.append(("raiser_habla_despues",
                       f"la subida se atribuye a {vs}, que habla DESPUES que {hp}"))

    # --- el contrato del motor -----------------------------------------------
    if recommendation:
        if state.get("hero_cards_dimmed"):
            fallos.append(("recomienda_sobre_mano_abandonada",
                           "hay recomendacion con las cartas del hero APAGADAS"))
        if state.get("stack_unit") != "bb":
            fallos.append(("recomienda_sin_unidad",
                           f"hay recomendacion con stack_unit={state.get('stack_unit')!r}: "
                           f"los importes podrian estar en fichas"))
        if board:
            fallos.append(("accion_postflop",
                           "hay recomendacion de ACCION con board en la mesa"))
        if recommendation.get("stack_bb") is None:
            fallos.append(("recomienda_sin_profundidad",
                           "una recomendacion sin stack_bb no se puede justificar"))
        if not recommendation.get("action"):
            fallos.append(("recomienda_sin_accion", "recomendacion sin accion"))
        if not (recommendation.get("reasoning") or "").strip():
            fallos.append(("recomienda_sin_motivo", "recomendacion sin reasoning"))
    elif not (state.get("warnings") or []):
        fallos.append(("abstiene_sin_motivo",
                       "no hay recomendacion y tampoco ningun warning que lo explique"))

    return fallos


def de_serie(previo, actual):
    """Contradicciones entre dos frames CONSECUTIVOS de la misma mano.

    `previo` y `actual` son (state, recommendation). Si no son de la misma mano
    no se compara nada: entre manos todo puede cambiar legitimamente."""
    st_p, st_a = previo[0], actual[0]
    if _sin_mesa(st_p) or _sin_mesa(st_a):
        return []
    mano_p, mano_a = st_p.get("mano_seguida"), st_a.get("mano_seguida")
    if mano_p is None or mano_p != mano_a:
        return []

    fallos = []
    n_p, n_a = len(st_p.get("players") or []), len(st_a.get("players") or [])
    if n_p != n_a:
        fallos.append(("jugadores_cambian",
                       f"el numero de jugadores cambia dentro de la mano: {n_p} -> {n_a}"))

    hp_p, hp_a = st_p.get("hero_position"), st_a.get("hero_position")
    if hp_p and hp_a and hp_p != hp_a:
        fallos.append(("posicion_cambia",
                       f"tu posicion cambia dentro de la mano: {hp_p} -> {hp_a}"))
    return fallos
