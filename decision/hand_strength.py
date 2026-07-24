"""
Evaluacion de mano para el HUD (NO es un motor de decision ni parte de la
Fase 4). Dado hero_cards (2 codigos tipo "9h","Ks","Td") + board (0-5 codigos)
devuelve dos cosas honestas y bien definidas:

(a) MANO FORMADA: la mejor combinacion de 5 cartas con las cartas disponibles,
    clasificada y nombrada en espanol ("Pareja de Reyes", "Color de corazones",
    "Doble pareja (Ases y Reyes)"...). En preflop (board vacio) devuelve la mano
    inicial ("AK suited", "Pareja de Ochos").

(b) PROYECTOS (draws) y probabilidad de COMPLETARLOS: proyecto de color (4 al
    color -> 9 outs), escalera abierta (OESD -> 8 outs), gutshot (4 outs),
    sobrecartas y doble proyecto (color+escalera). Los outs se convierten a % con
    dos metodos: el calculo combinatorio exacto (pct_next / pct_river) y la regla
    del 2 y el 4 (pct_next_rule = outs*2, pct_river_rule = outs*4).

HONESTIDAD: esto NO es equity contra el rango del rival (eso exigiria Monte
Carlo vs rangos). Es "mano formada ahora mismo" + "probabilidad de COMPLETAR un
proyecto si llegan las cartas que faltan". Un "35% al river" significa 35% de
ligar el proyecto, no 35% de ganar la mano. La regla del 2 y 4 es una
aproximacion que se desvia al alza con muchos outs (p.ej. 15 outs -> 60% por la
regla vs ~54% exacto); por eso se exponen ambos valores y el HUD muestra el
exacto.

Pure Python, sin dependencias nuevas.
"""
import math
from collections import Counter, defaultdict

RANK_VAL = {"2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
            "T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
VAL_RANK = {v: r for r, v in RANK_VAL.items()}

PLURAL = {14: "Ases", 13: "Reyes", 12: "Damas", 11: "Jotas", 10: "Dieces",
          9: "Nueves", 8: "Ochos", 7: "Sietes", 6: "Seises", 5: "Cincos",
          4: "Cuatros", 3: "Treses", 2: "Doses"}
SINGULAR = {14: "As", 13: "Rey", 12: "Dama", 11: "Jota", 10: "Diez", 9: "Nueve",
            8: "Ocho", 7: "Siete", 6: "Seis", 5: "Cinco", 4: "Cuatro",
            3: "Tres", 2: "Dos"}
SUIT_ES = {"h": "corazones", "d": "diamantes", "c": "treboles", "s": "picas"}
SUITS = "hdcs"


def _parse(code):
    if not code or len(str(code)) < 2:
        return None
    code = str(code)
    rank = code[:-1].upper()
    if rank == "10":
        rank = "T"
    suit = code[-1].lower()
    if rank not in RANK_VAL or suit not in SUIT_ES:
        return None
    return (RANK_VAL[rank], suit)


def _parse_cards(codes):
    out = []
    for c in codes:
        p = _parse(c)
        if p is None:
            return None
        out.append(p)
    return out


def _best_straight_high(vals):
    s = set(vals)
    if 14 in s:
        s.add(1)
    for high in range(14, 4, -1):
        if all((high - i) in s for i in range(5)):
            return high
    return None


def _classify(cards):
    """cards: lista de (val, suit). Devuelve (rank_int 1..9, detalle)."""
    vals = [v for v, _ in cards]
    cnt = Counter(vals)
    by_suit = defaultdict(list)
    for v, s in cards:
        by_suit[s].append(v)

    flush_suit = None
    for s, vs in by_suit.items():
        if len(vs) >= 5:
            flush_suit = s

    sf_high = _best_straight_high(by_suit[flush_suit]) if flush_suit else None
    straight_high = _best_straight_high(vals)

    quads = [v for v, c in cnt.items() if c == 4]
    trips = sorted((v for v, c in cnt.items() if c == 3), reverse=True)
    pairs = sorted((v for v, c in cnt.items() if c == 2), reverse=True)

    if sf_high:
        return 9, ("sf", sf_high, flush_suit)
    if quads:
        return 8, ("quads", max(quads))
    if trips and (len(trips) >= 2 or pairs):
        pair = max(list(trips[1:]) + pairs)
        return 7, ("full", trips[0], pair)
    if flush_suit:
        return 6, ("flush", flush_suit, max(by_suit[flush_suit]))
    if straight_high:
        return 5, ("straight", straight_high)
    if trips:
        return 4, ("trips", trips[0])
    if len(pairs) >= 2:
        return 3, ("twopair", pairs[0], pairs[1])
    if len(pairs) == 1:
        return 2, ("pair", pairs[0])
    return 1, ("high", max(vals))


def _describe(rank, det):
    t = det[0]
    if t == "sf":
        _, high, suit = det
        if high == 14:
            return "Escalera de color", f"Escalera de color (real) de {SUIT_ES[suit]}"
        return "Escalera de color", f"Escalera de color de {SUIT_ES[suit]}, al {SINGULAR[high]}"
    if t == "quads":
        return "Poker", f"Poker de {PLURAL[det[1]]}"
    if t == "full":
        return "Full", f"Full de {PLURAL[det[1]]} con {PLURAL[det[2]]}"
    if t == "flush":
        return "Color", f"Color de {SUIT_ES[det[1]]}, {SINGULAR[det[2]]} alto"
    if t == "straight":
        return "Escalera", f"Escalera al {SINGULAR[det[1]]}"
    if t == "trips":
        return "Trio", f"Trio de {PLURAL[det[1]]}"
    if t == "twopair":
        return "Doble pareja", f"Doble pareja ({PLURAL[det[1]]} y {PLURAL[det[2]]})"
    if t == "pair":
        return "Pareja", f"Pareja de {PLURAL[det[1]]}"
    return "Carta alta", f"Carta alta: {SINGULAR[det[1]]}"


def _preflop_name(hero):
    (v1, s1), (v2, s2) = hero
    if v1 == v2:
        name = f"Pareja de {PLURAL[v1]}"
        explain = f"dos {PLURAL[v1]} servidos (pareja de mano)"
        return "Preflop", name, explain
    hi, lo = (v1, v2) if v1 > v2 else (v2, v1)
    if s1 == s2:
        name = f"{VAL_RANK[hi]}{VAL_RANK[lo]} suited"
        explain = f"{SINGULAR[hi]} y {SINGULAR[lo]} del mismo palo (suited)"
    else:
        name = f"{VAL_RANK[hi]}{VAL_RANK[lo]} offsuit"
        explain = f"{SINGULAR[hi]} y {SINGULAR[lo]} de distinto palo (offsuit)"
    return "Preflop", name, explain


def _mk_draw(name, out_cards, unseen, cards_to_come, speculative=False, combined=False):
    outs = len(out_cards)
    d = {"name": name, "outs": outs, "speculative": speculative, "combined": combined,
         "pct_next": round(100 * outs / unseen), "pct_next_rule": outs * 2}
    if cards_to_come >= 2:
        rem = unseen - outs
        exact = 1 - (math.comb(rem, 2) / math.comb(unseen, 2))
        d["pct_river"] = round(100 * exact)
        d["pct_river_rule"] = outs * 4
    else:
        d["pct_river"] = None
        d["pct_river_rule"] = None
    return d


def _detect_draws(hero, board, made_rank):
    cards = hero + board
    known = set(cards)
    vals_set = {v for v, _ in cards}
    by_suit = defaultdict(set)
    for v, s in cards:
        by_suit[s].add(v)
    remaining = {(v, s) for v in range(2, 15) for s in SUITS} - known
    unseen = 50 - len(board)
    cards_to_come = 5 - len(board)
    draws = []

    flush_suit = None
    if made_rank < 6:
        for s, vs in by_suit.items():
            if len(vs) == 4:
                flush_suit = s
    flush_cards = set()
    if flush_suit:
        flush_cards = {c for c in remaining if c[1] == flush_suit}
        draws.append(_mk_draw(f"Proyecto de color de {SUIT_ES[flush_suit]}",
                              flush_cards, unseen, cards_to_come))

    straight_cards = set()
    if made_rank < 5:
        sset = set(vals_set)
        if 14 in sset:
            sset.add(1)
        missing = set()
        for high in range(5, 15):
            window = {high - i for i in range(5)}
            if len(window & sset) == 4:
                missing |= (window - sset)
        for r in missing:
            val = 14 if r == 1 else r
            for s in SUITS:
                if (val, s) in remaining:
                    straight_cards.add((val, s))
        if straight_cards:
            name = ("Proyecto de escalera abierta" if len(missing) >= 2
                    else "Proyecto de escalera (gutshot)")
            draws.append(_mk_draw(name, straight_cards, unseen, cards_to_come))

    if made_rank == 1:
        max_board = max(v for v, _ in board)
        oc_ranks = {v for v, _ in hero if v > max_board}
        oc_cards = {(r, s) for r in oc_ranks for s in SUITS if (r, s) in remaining}
        if oc_cards:
            draws.append(_mk_draw(f"Sobrecartas ({len(oc_ranks)}) a pareja superior",
                                  oc_cards, unseen, cards_to_come, speculative=True))

    if flush_cards and straight_cards:
        draws.append(_mk_draw("Doble proyecto (color + escalera)",
                              flush_cards | straight_cards, unseen, cards_to_come,
                              combined=True))

    return draws


def evaluate_hand(hero_codes, board_codes):
    """hero_codes: 2 codigos; board_codes: 0-5 codigos. Devuelve dict con
    street, made_category, made_name, draws (lista); o None si hero invalido."""
    hero = _parse_cards(hero_codes or [])
    if hero is None or len(hero) != 2:
        return None
    board = [p for p in (_parse(c) for c in (board_codes or [])) if p]
    n = len(board)

    if n == 0:
        cat, name, explain = _preflop_name(hero)
        return {"street": "preflop", "cards_to_come": 5,
                "made_category": cat, "made_name": name, "made_explain": explain,
                "draws": []}

    made_rank, det = _classify(hero + board)
    cat, name = _describe(made_rank, det)
    street = {3: "flop", 4: "turn", 5: "river"}.get(n, "flop")
    draws = _detect_draws(hero, board, made_rank) if n in (3, 4) else []
    return {"street": street, "cards_to_come": 5 - n,
            "made_category": cat, "made_name": name, "made_explain": None,
            "draws": draws}
