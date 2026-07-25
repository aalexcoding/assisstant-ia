"""
Estimacion de equity POSTFLOP por simulacion de Monte Carlo contra los rangos
reales del usuario (decision/opponent_ranges.py), evaluando con el evaluador
vectorizado (decision/hand_eval.py).

QUE ES Y QUE NO ES
------------------
Devuelve una PROBABILIDAD, no una decision. En concreto, equity "de all-in":
supone que se ven todas las cartas que faltan sin mas apuestas. No mira el bote,
no modela fold equity, no sabe de implied odds ni de ICM. Un 14% puede ser un
call correcto con el precio adecuado y un 60% puede ser un fold con reverse
implied odds. Por eso este modulo NO devuelve ninguna accion y engine.decide()
sigue sin recomendar nada postflop: lo unico que aporta es el numero, y el numero
va acompañado de sus supuestos.

DOS NUMEROS QUE SE PARECEN Y NO SON LO MISMO
--------------------------------------------
hand_strength.evaluate_hand() ya da "probabilidad de COMPLETAR un proyecto"
(9 outs de color -> ~35% al river). Eso NO es la probabilidad de ganar la mano:
se puede ligar el color y perder contra uno mayor, o no ligarlo y ganar igual con
pareja. La equity de aqui es la de ganar. Como las dos cifras van a acabar a
centimetros en el mismo panel, hand_potential incluye los proyectos TAL CUAL los
calcula hand_strength (sin recalcularlos) y una nota que dice la diferencia.

EL SUPUESTO QUE MAS PESA
------------------------
Los rangos de rival son de ENTRADA al bote (preflop). Un rival vivo en el turn
ademas ha pagado una apuesta en el flop, asi que su rango real es mas fuerte. Como
estrechar el rango del rival casi siempre baja la equity del hero, el numero es
TIPICAMENTE UN TECHO. "Tipicamente" y no "siempre": una mano floja preflop puede
ser un monstruo en un board concreto (72o en 772). Va dicho en "assumptions".

Se abstiene (devuelve None) antes que responder sobre datos imposibles: cartas
repetidas -el OCR produce boards imposibles en el 6% de los frames-, board de
longitud invalida, o un numero de rivales que no cabe en la mesa.
"""
import numpy as np

import hand_eval
import hand_strength
import opponent_ranges

DEFAULT_ITERATIONS = 10000
MAX_OPPONENTS = 5          # mesa de 6 plazas


def _cards_or_none(codes):
    try:
        return hand_eval.card_ids(codes)
    except ValueError:
        return None


def _abstain(warnings, motivo):
    if warnings is not None:
        warnings.append(motivo)
    return None


def _sin_conflicto(combos, prohibidas):
    """Quita de un array (M,2) los combos que usan alguna carta ya vista."""
    prohibidas = np.asarray(prohibidas, dtype=np.int32)
    usa = np.isin(combos, prohibidas).any(axis=1)
    return combos[~usa]


def _simular(hero, board, mazo, rangos, iteraciones, rng):
    """Nucleo de la simulacion.

    hero: (2,)  board: (k,)  mazo: cartas disponibles  rangos: lista de arrays
    (M,2) ya filtrados, uno por rival.

    Reparte el board que falta y una mano por rival, RECHAZANDO las repeticiones
    en conjunto (no secuencialmente): repartir al rival 1 y luego al 2 evitando al
    1 daria una distribucion dependiente del orden y sesgada. Devuelve
    (win, tie, loss, categorias_finales_del_hero, n_validas)."""
    faltan = 5 - len(board)
    win = tie = loss = 0
    cats = np.zeros(9, dtype=np.int64)
    hechas = 0
    intentos = 0

    while hechas < iteraciones and intentos < 40:
        intentos += 1
        lote = min(iteraciones - hechas, iteraciones) * 2

        # board que falta: se barajan indices del mazo por fila
        if faltan:
            orden = np.argsort(rng.random((lote, len(mazo))), axis=1)[:, :faltan]
            extra = mazo[orden]
        else:
            extra = np.empty((lote, 0), dtype=np.int32)

        manos = [r[rng.integers(0, len(r), lote)] for r in rangos]

        repartidas = np.concatenate([extra] + manos, axis=1)
        ordenadas = np.sort(repartidas, axis=1)
        validas = (np.diff(ordenadas, axis=1) != 0).all(axis=1)
        if not validas.any():
            continue
        extra, manos = extra[validas], [m[validas] for m in manos]
        k = min(extra.shape[0], iteraciones - hechas)
        extra, manos = extra[:k], [m[:k] for m in manos]

        board_full = np.concatenate(
            [np.tile(board, (k, 1)), extra], axis=1) if faltan else np.tile(board, (k, 1))
        s_hero = hand_eval.score(np.concatenate([np.tile(hero, (k, 1)), board_full], axis=1))
        mejor_rival = None
        for m in manos:
            s = hand_eval.score(np.concatenate([m, board_full], axis=1))
            mejor_rival = s if mejor_rival is None else np.maximum(mejor_rival, s)

        win += int((s_hero > mejor_rival).sum())
        tie += int((s_hero == mejor_rival).sum())
        loss += int((s_hero < mejor_rival).sum())
        cats += np.bincount(hand_eval.category(s_hero), minlength=9).astype(np.int64)
        hechas += k
    return win, tie, loss, cats, hechas


def estimate_equity(player_hand, community_cards, player_position, remaining_players,
                    *, opponent_positions=None, stack_bb=None,
                    iterations=DEFAULT_ITERATIONS, seed=None,
                    include_baselines=True, warnings=None):
    """Equity del hero postflop. Devuelve un dict, o None si no se puede
    responder honestamente (el motivo se añade a `warnings` si se pasa una lista).

    player_hand: 2 codigos ('Ah','Kd'). community_cards: 3, 4 o 5.
    player_position: posicion del hero ('BTN', 'SB'...), solo informativa aqui.
    remaining_players: numero de RIVALES vivos (no incluye al hero).
    opponent_positions: lista opcional de posiciones de esos rivales; sin ella se
        usa un rango generico derivado igualmente de las tablas del usuario.
    """
    hero = _cards_or_none(player_hand or [])
    if hero is None or len(hero) != 2:
        return _abstain(warnings, "equity: hacen falta las 2 cartas del hero")
    board = _cards_or_none(community_cards or [])
    if board is None or len(board) not in (3, 4, 5):
        return _abstain(warnings, "equity: el board debe tener 3, 4 o 5 cartas "
                                  f"(tiene {len(community_cards or [])})")

    conocidas = np.concatenate([hero, board])
    if len(np.unique(conocidas)) != len(conocidas):
        # el OCR produce boards imposibles: medido, 4 de 64 frames con board
        return _abstain(warnings, "equity: hay cartas repetidas entre tu mano y el board "
                                  "(lectura erronea); no se simula sobre un mazo imposible")
    if not isinstance(remaining_players, int) or remaining_players < 1:
        return _abstain(warnings, "equity: hace falta al menos 1 rival vivo")
    if remaining_players > MAX_OPPONENTS:
        return _abstain(warnings, f"equity: {remaining_players} rivales excede la mesa "
                                  f"de {MAX_OPPONENTS + 1} plazas")
    if 2 + len(board) + 2 * remaining_players > 52:
        return _abstain(warnings, "equity: no hay cartas suficientes en el mazo")

    avisos = []
    rng = np.random.default_rng(seed)
    mazo = np.setdiff1d(np.arange(52, dtype=np.int32), conocidas)

    # --- rangos de los rivales ---
    posiciones = list(opponent_positions or [])
    posiciones += [None] * (remaining_players - len(posiciones))
    posiciones = posiciones[:remaining_players]

    rangos, metas = [], []
    for pos in posiciones:
        if pos is None and stack_bb is not None:
            combos, meta = opponent_ranges.generic_combos(stack_bb)
        else:
            combos, meta = opponent_ranges.entering_combos(pos, stack_bb if stack_bb else 20.0)
        if combos is None or len(combos) == 0:
            combos = opponent_ranges.random_combos()
            meta = dict(meta or {}, role="unknown", pct_of_all=1.0, combos=len(combos),
                        source="aleatorio (sin rango aplicable)")
            meta.setdefault("warnings", []).append(
                f"sin rango aplicable para {pos}; se le supone cualquier mano")
        libres = _sin_conflicto(combos, conocidas)
        if len(libres) == 0:
            return _abstain(warnings, f"equity: el rango de {pos} queda vacio al quitar "
                                      f"las cartas ya vistas")
        rangos.append(libres)
        metas.append(meta)
        avisos.extend(meta.get("warnings", []))

    # --- simulacion principal ---
    win, tie, loss, cats, n = _simular(hero, board, mazo, rangos, iterations, rng)
    if n == 0:
        return _abstain(warnings, "equity: no se pudo generar ninguna reparticion valida")

    p_win, p_tie, p_loss = win / n, tie / n, loss / n
    equity = p_win + p_tie / 2.0
    err_pp = float(np.sqrt(max(equity * (1 - equity), 0) / n) * 100)

    # --- proyectos: se toman TAL CUAL de hand_strength, sin recalcular ---
    made = hand_strength.evaluate_hand(list(player_hand), list(community_cards))
    draws = (made or {}).get("draws") or []
    no_espec = [d for d in draws if not d.get("speculative")]
    mejor = max(no_espec, key=lambda d: d.get("pct_river") or d.get("pct_next") or 0,
                default=None)
    # distribucion de la categoria FINAL del hero sobre las reparticiones
    # simuladas. Es informacion que los proyectos de hand_strength no pueden dar
    # (ellos responden "¿ligo el color?", esto responde "¿con que acabo?").
    dist = {hand_eval.CATEGORY_ES[i]: round(float(c) / n, 4) for i, c in enumerate(cats) if c}

    hand_potential = {
        "made_now": (made or {}).get("made_name"),
        "made_category_now": (made or {}).get("made_category"),
        "draws": draws,
        "best_draw": mejor,
        "final_categories": dist,
        "note": ("los % de 'draws' son de COMPLETAR el proyecto, no de ganar la mano; "
                 "la de ganar es win_probability"),
    }

    # --- factores medibles de posicion y numero de rivales ---
    positional = {
        "hero_position": player_position,
        "opponents": remaining_players,
        "opponent_ranges": metas,
        "win_probability_vs_random": None,
        "range_effect_pp": None,
        "opponent_count_effect_pp": None,
        "explanation": "",
    }
    if include_baselines:
        aleatorios = [_sin_conflicto(opponent_ranges.random_combos(), conocidas)
                      for _ in range(remaining_players)]
        w2, t2, _l2, _c2, n2 = _simular(hero, board, mazo, aleatorios, iterations, rng)
        if n2:
            eq_rnd = (w2 + t2 / 2.0) / n2
            positional["win_probability_vs_random"] = round(w2 / n2, 4)
            positional["range_effect_pp"] = round((equity - eq_rnd) * 100, 1)
        if remaining_players > 1:
            w1, t1, _l1, _c1, n1 = _simular(hero, board, mazo, rangos[:1], iterations, rng)
            if n1:
                eq1 = (w1 + t1 / 2.0) / n1
                positional["opponent_count_effect_pp"] = round((equity - eq1) * 100, 1)

    partes = []
    if positional["range_effect_pp"] is not None:
        partes.append(f"que los rivales tengan un rango (y no una mano cualquiera) te "
                      f"{'quita' if positional['range_effect_pp'] < 0 else 'da'} "
                      f"{abs(positional['range_effect_pp']):.1f} puntos")
    if positional["opponent_count_effect_pp"] is not None:
        partes.append(f"pasar de 1 a {remaining_players} rivales te "
                      f"{'quita' if positional['opponent_count_effect_pp'] < 0 else 'da'} "
                      f"{abs(positional['opponent_count_effect_pp']):.1f} puntos")
    partes.append("la POSICION no cambia esta equity: cambia lo que consigues realizar de "
                  "ella apostando, y para eso este proyecto no tiene datos con los que "
                  "calibrar nada, asi que no se inventa un factor")
    positional["explanation"] = ". ".join(partes).capitalize() + "."

    assumptions = [
        'equity "de all-in": supone que se ven todas las cartas sin mas apuestas; '
        "no mira el bote ni las apuestas por venir",
        "cada rival tiene el rango con el que ENTRO al bote (preflop); ya han pasado "
        "el flop, asi que su rango real es mas fuerte y este numero es tipicamente un TECHO",
        "los rangos son los TUYOS (ranges.json): se supone que los rivales juegan como tu",
        "las celdas de frecuencia mixta de ranges.json estan colapsadas a su accion "
        "dominante, asi que los rangos son conjuntos duros, sin frecuencias",
    ]

    street = {3: "flop", 4: "turn", 5: "river"}[len(board)]
    return {
        "win_probability": round(p_win, 4),
        "tie_probability": round(p_tie, 4),
        "loss_probability": round(p_loss, 4),
        "equity": round(equity, 4),
        "std_error_pp": round(err_pp, 2),
        "iterations": iterations,
        "iterations_valid": n,
        "street": street,
        "cards_to_come": 5 - len(board),
        "hand_potential": hand_potential,
        "positional_adjustment": positional,
        "assumptions": assumptions,
        "warnings": avisos,
    }
