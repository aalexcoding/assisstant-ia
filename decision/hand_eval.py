"""
Evaluador de manos de 7 cartas (mejor combinacion de 5), vectorizado con numpy.
Es la pieza de la que depende la simulacion de equity (decision/equity.py): una
Monte Carlo de 10.000 iteraciones contra varios rivales hace decenas de miles de
evaluaciones por frame, asi que tiene que ser rapido Y dar un ORDEN TOTAL.

POR QUE NO SE REUTILIZA hand_strength._classify
-----------------------------------------------
hand_strength.py ya clasifica manos, pero su salida NO sirve para comparar dos
manos en un showdown, por tres motivos:
  - se come todos los kickers: ("pair", 9) no distingue 99+AKQ de 99+432, y
    ("twopair", 9, 5) pierde la quinta carta;
  - ("flush", suit, high) pone el PALO antes que la carta alta, asi que comparar
    dos colores compara 'c' < 'd' < 'h' < 's' primero: orden falso;
  - solo sigue un palo para el color y solo busca escalera de color dentro de el.
Sirve para NOMBRAR una mano en castellano (y para eso se sigue usando), no para
decidir quien gana. De ahi este modulo.

POR QUE NO SE USA treys (u otra libreria)
-----------------------------------------
treys es Python puro y evalua mano a mano; a decenas de miles de manos por frame
eso se come el presupuesto de latencia entero. numpy ya es dependencia del
proyecto y permite evaluar el lote completo sin bucle en Python. Ademas la
puntuacion de treys es "menor es mejor", invertida respecto a todo lo demas de
aqui, que es una fuente facil de errores de signo. El oraculo de fuerza bruta
que valida este modulo vive en test_hand_eval.py, asi que la correccion no
depende de una tercera libreria.

REPRESENTACION
--------------
  carta  = indice_de_rango * 4 + indice_de_palo
  rangos = "23456789TJQKA" -> 0..12   (12 = as)
  palos  = "shdc"          -> 0..3    (el palo NO influye en la puntuacion)

PUNTUACION (orden total, mayor es mejor)
----------------------------------------
  score = categoria * 13^5 + d1*13^4 + d2*13^3 + d3*13^2 + d4*13 + d5
con las categorias 0..8 (carta alta .. escalera de color) y d1..d5 los indices de
rango de desempate, de mas a menos significativo. Base 13 porque los indices van
de 0 a 12. El maximo cabe de sobra en int32.

Desempates por categoria:
  escalera de color  d1 = rango alto de la escalera
  poker              d1 = rango del poker, d2 = kicker
  full               d1 = rango del trio, d2 = rango de la pareja
  color              d1..d5 = los 5 rangos mas altos del palo del color
  escalera           d1 = rango alto
  trio               d1 = rango del trio, d2..d3 = kickers
  doble pareja       d1 = pareja alta, d2 = pareja baja, d3 = kicker
  pareja             d1 = rango de la pareja, d2..d4 = kickers
  carta alta         d1..d5 = los 5 rangos mas altos
"""
import numpy as np

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_INDEX = {r: i for i, r in enumerate(RANKS)}
SUIT_INDEX = {s: i for i, s in enumerate(SUITS)}

# nombres en castellano por categoria, en el MISMO orden que la puntuacion, para
# poder describir la mano final de una simulacion sin volver a hand_strength.
CATEGORY_ES = ("Carta alta", "Pareja", "Doble pareja", "Trio", "Escalera",
               "Color", "Full", "Poker", "Escalera de color")

BASE = 13
_P = (BASE ** 4, BASE ** 3, BASE ** 2, BASE, 1)   # pesos de d1..d5
CAT_WEIGHT = BASE ** 5

_NMASK = 1 << 13   # 8192 mascaras posibles de 13 rangos


def _build_tables():
    """Tablas indexadas por mascara de 13 bits (bit r = rango r presente).

    straight_hi[m] = indice de rango mas alto de una escalera de 5 en m, o -1.
    top[k][m]      = los k rangos mas altos de m, ya empaquetados en base 13 con
                     d1 en el peso 13^4 (para poder sumarlos directamente).
    """
    straight_hi = np.full(_NMASK, -1, dtype=np.int8)
    top = [np.zeros(_NMASK, dtype=np.int32) for _ in range(6)]   # top[0] sin usar

    # Patrones de escalera: 5 rangos consecutivos, mas la rueda (A-2-3-4-5), en
    # la que el as vale por debajo del 2 y la escalera es "al cinco" (indice 3).
    # EN ORDEN DESCENDENTE de carta alta, porque el bucle de abajo corta en la
    # primera coincidencia: con la lista ascendente se quedaba con la escalera
    # mas BAJA de la mano (7 cartas pueden contener dos escaleras solapadas), y
    # entonces dos escaleras distintas empataban o ganaba la peor. Lo cazo el
    # oraculo de fuerza bruta: 6 comparaciones mal de 20.000, todas escaleras.
    patrones = [(0b11111 << (hi - 4), hi) for hi in range(12, 3, -1)]
    patrones.append(((1 << 12) | 0b1111, 3))   # A,2,3,4,5 -> alta = 5

    for m in range(_NMASK):
        for patron, hi in patrones:            # de mayor a menor: el primero gana
            if m & patron == patron:
                straight_hi[m] = hi
                break
        altos = [r for r in range(12, -1, -1) if m & (1 << r)]
        acc = 0
        for k in range(1, 6):
            if k <= len(altos):
                acc += altos[k - 1] * _P[k - 1]
            top[k][m] = acc
    return straight_hi, top


_STRAIGHT_HI, _TOP = _build_tables()
_POPCOUNT = np.array([bin(m).count("1") for m in range(_NMASK)], dtype=np.int8)
# Rango mas alto presente en la mascara (indice), o -1 si esta vacia.
# int32 A PROPOSITO, no int8: estos valores se usan como desplazamiento
# (1 << _HIGH[...]) para tachar un rango de una mascara, y con int8 numpy hace la
# operacion en int8, asi que 1 << 12 DESBORDA y da 0 en vez de 4096. El sintoma
# no es un error sino mascaras de kicker corruptas: la categoria y el desempate
# salen mal en silencio. Lo cazo el oraculo de fuerza bruta de test_hand_eval.py
# (83 categorias y 107 ordenes mal de 4000 manos).
_HIGH = np.array([max((r for r in range(12, -1, -1) if m & (1 << r)), default=-1)
                  for m in range(_NMASK)], dtype=np.int32)


def card_id(code):
    """'Ah' -> int. Acepta '10s' ademas de 'Ts', y minusculas, igual que
    hand_strength._parse. None si el codigo no es valido."""
    if not code:
        return None
    code = str(code).strip()
    if len(code) < 2:
        return None
    rank, suit = code[:-1].upper(), code[-1].lower()
    if rank == "10":
        rank = "T"
    if rank not in RANK_INDEX or suit not in SUIT_INDEX:
        return None
    return RANK_INDEX[rank] * 4 + SUIT_INDEX[suit]


def card_ids(codes):
    """Lista de codigos -> np.int32. Lanza ValueError si alguno es invalido: en
    una simulacion, una carta mal leida no puede pasar en silencio."""
    out = []
    for c in codes:
        i = card_id(c)
        if i is None:
            raise ValueError(f"carta invalida: {c!r}")
        out.append(i)
    return np.array(out, dtype=np.int32)


def score(cards7):
    """(N,7) de ids de carta -> (N,) int32. Mayor es mejor, orden TOTAL (los
    empates reales dan puntuaciones identicas). El palo nunca desempata."""
    cards7 = np.asarray(cards7, dtype=np.int32)
    if cards7.ndim == 1:
        cards7 = cards7[None, :]
    n = cards7.shape[0]

    rangos = cards7 >> 2          # // 4
    palos = cards7 & 3            # % 4
    bits = (1 << rangos).astype(np.int32)

    # cuentas por rango y mascaras por palo
    idx = (np.arange(n, dtype=np.int64)[:, None] * BASE + rangos).ravel()
    cuentas = np.bincount(idx, minlength=n * BASE).reshape(n, BASE)

    mask_all = np.bitwise_or.reduce(bits, axis=1)
    mask_palo = np.empty((n, 4), dtype=np.int32)
    for s in range(4):
        mask_palo[:, s] = np.bitwise_or.reduce(np.where(palos == s, bits, 0), axis=1)

    # mascaras de rangos por multiplicidad
    m_quads = np.bitwise_or.reduce(np.where(cuentas == 4, 1 << np.arange(BASE), 0), axis=1)
    m_trips = np.bitwise_or.reduce(np.where(cuentas == 3, 1 << np.arange(BASE), 0), axis=1)
    m_pairs = np.bitwise_or.reduce(np.where(cuentas == 2, 1 << np.arange(BASE), 0), axis=1)

    # --- color y escalera de color ---
    cuentas_palo = np.empty((n, 4), dtype=np.int32)
    for s in range(4):
        cuentas_palo[:, s] = (palos == s).sum(axis=1)
    palo_color = np.argmax(cuentas_palo, axis=1)
    hay_color = cuentas_palo.max(axis=1) >= 5
    mask_color = np.where(hay_color, mask_palo[np.arange(n), palo_color], 0)

    sf_hi = _STRAIGHT_HI[mask_color]
    hay_sf = hay_color & (sf_hi >= 0)

    # --- escalera ---
    st_hi = _STRAIGHT_HI[mask_all]
    hay_st = st_hi >= 0

    # --- poker ---
    hay_quads = m_quads != 0
    r_quads = _HIGH[m_quads]
    kicker_quads = _TOP[1][mask_all & ~(1 << np.maximum(r_quads, 0))] // BASE

    # --- full: un trio y (otro trio o una pareja) ---
    n_trips = _POPCOUNT[m_trips]
    r_trips = _HIGH[m_trips]
    # el trio sobrante (si hay dos) tambien puede hacer de pareja
    m_pareja_full = m_pairs | (m_trips & ~(1 << np.maximum(r_trips, 0)))
    hay_full = (n_trips >= 1) & (m_pareja_full != 0)
    r_pareja_full = _HIGH[m_pareja_full]

    # --- trio (sin full) ---
    hay_trio = n_trips >= 1
    kickers_trio = _TOP[2][mask_all & ~(1 << np.maximum(r_trips, 0))] // BASE

    # --- doble pareja ---
    n_pairs = _POPCOUNT[m_pairs]
    hay_2p = n_pairs >= 2
    dos_altas = _TOP[2][m_pairs]                    # p1*13^4 + p2*13^3
    # las dos parejas usadas, para excluirlas del kicker
    p1 = _HIGH[m_pairs]
    m_sin_p1 = m_pairs & ~(1 << np.maximum(p1, 0))
    p2 = _HIGH[m_sin_p1]
    usados_2p = (1 << np.maximum(p1, 0)) | (1 << np.maximum(p2, 0))
    kicker_2p = _TOP[1][mask_all & ~usados_2p] // (BASE * BASE)

    # --- pareja simple ---
    hay_par = n_pairs >= 1
    kickers_par = _TOP[3][mask_all & ~(1 << np.maximum(p1, 0))] // BASE

    cero = np.zeros(n, dtype=np.int32)
    candidatos = [
        (hay_sf,    8, np.maximum(sf_hi, 0).astype(np.int32) * _P[0]),
        (hay_quads, 7, np.maximum(r_quads, 0).astype(np.int32) * _P[0] + kicker_quads),
        (hay_full,  6, np.maximum(r_trips, 0).astype(np.int32) * _P[0]
                       + np.maximum(r_pareja_full, 0).astype(np.int32) * _P[1]),
        (hay_color, 5, _TOP[5][mask_color]),
        (hay_st,    4, np.maximum(st_hi, 0).astype(np.int32) * _P[0]),
        (hay_trio,  3, np.maximum(r_trips, 0).astype(np.int32) * _P[0] + kickers_trio),
        (hay_2p,    2, dos_altas + kicker_2p),
        (hay_par,   1, np.maximum(p1, 0).astype(np.int32) * _P[0] + kickers_par),
    ]
    condiciones = [c for c, _, _ in candidatos]
    valores = [cat * CAT_WEIGHT + tb for _, cat, tb in candidatos]
    return np.select(condiciones, valores, default=_TOP[5][mask_all] + cero).astype(np.int32)


def category(scores):
    """(N,) de puntuaciones -> (N,) int8 con la categoria 0..8, indexable en
    CATEGORY_ES."""
    return (np.asarray(scores) // CAT_WEIGHT).astype(np.int8)
