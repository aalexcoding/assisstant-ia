"""
Fase 4.1: lookup puro sobre decision/preflop/ranges.json (generado por
parse_ranges.py, no tocar). Dado hero_cards + posicion + stack efectivo,
devuelve la etiqueta de accion del rango digitalizado, o None si falta
algun dato o la posicion/stack no tiene rango para ese facing.
"""
import json
import os

RANKS = ["A", "K", "Q", "J", "T", "9", "8", "7", "6", "5", "4", "3", "2"]
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}

RANGES_PATH = os.path.join(os.path.dirname(__file__), "ranges.json")

# Los rangos se cargan LA PRIMERA VEZ QUE SE PIDEN, no al importar el modulo.
# Antes el json.load estaba aqui arriba, al nivel del modulo, y eso tenia dos
# consecuencias molestas: importar cualquier cosa que acabe en lookup (o sea, el
# motor entero) fallaba si el fichero no estaba o estaba corrupto, y no habia
# forma de meter unos rangos de prueba sin escribir en el fichero real.
_RANGES = None


def load_ranges(path=None, datos=None):
    """Carga (o sustituye) la tabla de rangos y la devuelve.

    Con `datos` se inyecta un diccionario ya montado, que es lo que hacen los
    tests que quieren una tabla minima y controlada. Sin argumentos recarga de
    RANGES_PATH."""
    global _RANGES
    if datos is not None:
        _RANGES = datos
    else:
        with open(path or RANGES_PATH) as f:
            _RANGES = json.load(f)
    return _RANGES


def ranges():
    """La tabla de rangos, cargandola si hace falta. Dentro del modulo se usa
    esto y no RANGES, porque el __getattr__ de abajo solo cubre el acceso desde
    FUERA (PEP 562 no intercepta los nombres globales del propio modulo)."""
    return _RANGES if _RANGES is not None else load_ranges()


def __getattr__(nombre):
    """`lookup.RANGES` sigue existiendo y se lee igual que siempre; lo unico que
    cambia es CUANDO se carga (PEP 562)."""
    if nombre == "RANGES":
        return ranges()
    raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")


def normalize_hand(hero_cards):
    """["Ks","6c"] -> "K6o" ; ["Ah","Ad"] -> "AA". None si no hay 2 cartas
    validas (rangos fuera de RANKS, cartas repetidas, etc)."""
    if len(hero_cards) != 2:
        return None
    r1, r2 = hero_cards[0][0], hero_cards[1][0]
    if r1 not in RANK_INDEX or r2 not in RANK_INDEX:
        return None
    if hero_cards[0] == hero_cards[1]:
        return None
    if r1 == r2:
        return r1 + r2
    hi, lo = (r1, r2) if RANK_INDEX[r1] < RANK_INDEX[r2] else (r2, r1)
    suited = "s" if hero_cards[0][1] == hero_cards[1][1] else "o"
    return hi + lo + suited


def _nearest_stack_key(stack_bb, stack_keys):
    return min(stack_keys, key=lambda k: abs(float(k) - stack_bb))


def recommend(hero_cards, hero_position, stack_bb, facing="open_raise", vs_position=None):
    if hero_position is None or stack_bb is None:
        return None
    hand = normalize_hand(hero_cards)
    if hand is None:
        return None
    stack_table = ranges().get(facing)
    if not stack_table:
        return None

    stack_key = _nearest_stack_key(stack_bb, stack_table.keys())
    pos_table = stack_table[stack_key].get(hero_position)
    if pos_table is None:
        return None

    if facing == "threebet_call":
        if vs_position is None:
            return None
        pos_table = pos_table.get(vs_position)
        if pos_table is None:
            return None

    for action, hands in pos_table.items():
        if hand in hands:
            # stack_key: la profundidad de la TABLA que se acabo usando. Se expone
            # porque _nearest_stack_key redondea a la clave mas cercana sin limite
            # -con 100bb devuelve el rango de 40bb como si fuera exacto-, y quien
            # llama necesita poder distinguir "esta es tu tabla" de "esto es una
            # extrapolacion fuera de lo digitalizado" para poder avisar.
            return {"action": action, "hands_bucket": hands,
                    "stack_key": float(stack_key)}
    return None
