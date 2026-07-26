"""
OCR del rango de los dos mazos de 4 colores, que solo se diferencian en la
POLARIDAD de la tinta y por eso comparten todo lo demas (deck="..."):

  "solid"  color_card_detector: rango en blanco sobre fondo de color solido.
  "glyph"  glyph_card_detector: rango en el color del palo sobre cara blanca.

Distinto del OCR de rank_ocr.py (mazo blanco, rango pequeño en la esquina junto
al icono de palo, texto de color sobre fondo blanco).

Dos mejoras validadas contra 543 recortes reales etiquetados a mano
(hero+board de samples_pokerstars/samples_layout/samples_layout2):

1. Deteccion del '10' por ancho (is_ten). El '10' es el UNICO rango de dos
   glifos y el OCR falla a menudo al leer los dos digitos ("1", "0", "1O",
   "40"...), dejando al hero con <2 cartas. En vez de fiarlo al OCR se mide la
   geometria del texto blanco: el '10' lleva un '1' -una barra vertical fina-
   pegado a la izquierda del '0'. La relacion ancho/alto de ese '1' es
   0.12-0.15 en los 79 dieces reales y >=0.81 en cualquier otro rango, asi que
   el umbral 0.4 los separa con un margen enorme (0 falsos positivos, 0 dieces
   perdidos en el conjunto). Cuando la señal dispara se devuelve "10" con
   prioridad sobre el OCR.

2. Voto ponderado sobre DOS vistas. Ni una sola combinacion fija de psm/escala
   acierta siempre, asi que se prueban varias y se vota por mayoria. Una vista
   hace de ANCLA (cuenta doble) y la otra solo DESEMPATA. Empate a maximo de
   votos -> None (mejor omitir que arriesgar una carta equivocada con la misma
   confianza que una correcta).

   Cual es cual depende del mazo, porque el ruido de cada uno es distinto:

   solid: ancla = mascara de carta completa (el metodo probado); desempate =
   vista "close", el rango aislado con un cierre morfologico que reconecta los
   trazos que la mascara parte en los glifos redondos (2, 9, Q). Reduce
   confusiones sistematicas (2 36->48, 9 28->35, Q 51->53, elimina el 3->K) sin
   engrosar el glifo -a diferencia de dilatar, que fusionaba los lobulos del 3-.
   El acierto por carta pasa de ~82% a ~88%.

   glyph: al reves. Esta carta trae el rango DOS veces (grande y en la esquina)
   y el pip mide casi lo mismo que el rango, asi que la mascara completa se lee
   mal: 32 de 40 cartas etiquetadas. El ancla es el rango aislado por POSICION
   (_fila_de_arriba), que en esas 40 no se equivoca ni una vez, y la mascara
   completa solo desempata las que la aislada deja en blanco: 40 de 40.
"""
from collections import Counter

import cv2
import hashlib

import numpy as np

import glyph_card_detector
from rank_ocr import normalize_rank

WHITE_MAX_SATURATION = 60
WHITE_MIN_VALUE = 170

PSM_SCALE_VARIANTS = [
    ("SINGLE_WORD", 4),
    ("SINGLE_WORD", 6),
    ("SINGLE_WORD", 10),
    ("RAW_LINE", 6),
    ("RAW_LINE", 10),
    ("SINGLE_BLOCK", 6),
    ("SINGLE_BLOCK", 10),
    ("SINGLE_BLOCK", 12),
    ("SINGLE_BLOCK", 14),
]

# la mascara de carta completa (metodo probado) se ancla con doble voto; la
# vista "close" solo desempata/corrige confusiones de glifos redondos.
FULL_VOTE_WEIGHT = 2

# deteccion geometrica del '10'
RANK_MIN_AREA_FRAC = 0.015   # area minima (fraccion de la carta) para contar como glifo
RANK_TALL_FRAC = 0.6         # alto minimo (fraccion del mas alto) para ser glifo de rango
ONE_MAX_ASPECT = 0.4         # el '1' es una barra fina: ancho/alto < esto
ONE_MAX_OVERLAP = 0.2        # '1' y '0' van lado a lado: solape horizontal pequeño


def _white_mask(card_bgr):
    hsv = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    return ((s < WHITE_MAX_SATURATION) & (v > WHITE_MIN_VALUE)).astype(np.uint8) * 255


def _glyph_deck_mask(card_bgr):
    """Tinta del mazo de cara blanca (glyph_card_detector): el rango va en el
    color del palo sobre una cara clara, o sea justo la polaridad contraria a la
    del mazo de fondo solido. La tinta es todo lo que NO es cara."""
    hsv = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1].astype(int), hsv[:, :, 2].astype(int)
    cara = (s < glyph_card_detector.CARA_S_MAX) & (v > glyph_card_detector.CARA_V_MIN)
    return (~cara).astype(np.uint8) * 255


def rank_mask(card_bgr, deck="solid"):
    """Mascara del rango (255 = tinta) del mazo que toque. Todo lo de abajo
    trabaja sobre esto, asi que los dos mazos comparten voto, deteccion del
    '10' y cache: lo unico que cambia es de donde sale la tinta."""
    if deck == "glyph":
        return _glyph_deck_mask(card_bgr)
    return _white_mask(card_bgr)


def white_text_mask(card_bgr, deck="solid"):
    inverted = 255 - rank_mask(card_bgr, deck)
    return cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)


def _fila_de_arriba(mask):
    """Aisla el RANGO GRANDE del mazo de cara blanca: de los componentes altos,
    los que empiezan mas arriba.

    Por que por POSICION y no por tamaño, que es como se hace en el mazo de
    fondo solido: aqui el pip mide casi lo mismo que el rango, asi que el filtro
    de altura no lo quita. Medido sobre 40 cartas de board etiquetadas, votando
    igual que en produccion:

        vista cruda x2 + close (lo que habia)     32 bien,  8 mal, 0 sin resolver
        alto >= 0.55 del maximo x2 + close        27 bien, 10 mal, 3 sin resolver
        solo esta vista                           36 bien,  0 mal, 4 sin resolver
        esta vista x2 + cruda                     40 bien,  0 mal, 0 sin resolver

    Lo que la hace valiosa es la fila de en medio: aislada NO SE EQUIVOCA NUNCA,
    solo se calla. Por eso vota doble y la vista cruda solo desempata."""
    h, w = mask.shape
    n, lab, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [(i, stats[i]) for i in range(1, n) if stats[i][4] >= 0.01 * h * w]
    if not comps:
        return mask
    max_h = max(st[3] for _, st in comps)
    altos = [(i, st) for i, st in comps if st[3] >= 0.55 * max_h]
    if not altos:
        return mask
    y0 = min(st[1] for _, st in altos)
    keep = np.zeros_like(mask)
    for i, st in altos:
        if st[1] <= y0 + 0.25 * max_h:
            keep[lab == i] = 255
    return keep


def rango_grande_mask(card_bgr, deck="solid"):
    """Mascara del rango solo (sin pip ni rango pequeño de la esquina). En el
    mazo de fondo solido el rango ya domina la mascara, asi que no hay nada que
    aislar."""
    mask = rank_mask(card_bgr, deck)
    return _fila_de_arriba(mask) if deck == "glyph" else mask


def _recortar(mask):
    ys, xs = np.where(mask > 0)
    if not len(xs):
        return mask
    h, w = mask.shape
    return mask[max(0, ys.min() - 2):min(h, ys.max() + 3),
                max(0, xs.min() - 2):min(w, xs.max() + 3)]


def _rank_components(mask):
    """Componentes conexos que son glifos de rango (los mas altos), ordenados
    por x. Descarta ruido pequeño y el pip de palo (mas bajo que el rango)."""
    h, w = mask.shape
    n, _lab, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [stats[i] for i in range(1, n) if stats[i][4] >= RANK_MIN_AREA_FRAC * h * w]
    if not comps:
        return []
    max_h = max(c[3] for c in comps)
    rank = [c for c in comps if c[3] >= RANK_TALL_FRAC * max_h]
    return sorted(rank, key=lambda c: c[0])


def is_ten(card_bgr, deck="solid"):
    """True si el rango es '10': un '1' fino (barra vertical alta y estrecha)
    pegado a la izquierda de otro glifo. Señal independiente del OCR."""
    rank = _rank_components(rango_grande_mask(card_bgr, deck))
    if len(rank) < 2:
        return False
    left, right = rank[0], rank[1]
    lw, lh = int(left[2]), int(left[3])
    if lh == 0 or lw / lh >= ONE_MAX_ASPECT:
        return False
    overlap = (int(left[0]) + lw) - int(right[0])
    return overlap <= ONE_MAX_OVERLAP * lw


def _rank_only_close_img(card_bgr, deck="solid"):
    """Rango aislado (sin pip de palo), reescalado a alto fijo y con cierre
    morfologico (reconecta trazos finos partidos). Texto negro sobre blanco,
    listo para add_text_job. Cae a la mascara completa si no hay glifos."""
    mask = rank_mask(card_bgr, deck)
    h, w = mask.shape
    n, lab, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [(i, stats[i]) for i in range(1, n) if stats[i][4] >= 0.01 * h * w]
    if comps:
        max_h = max(st[3] for _, st in comps)
        keep = np.zeros_like(mask)
        for i, st in comps:
            if st[3] >= 0.55 * max_h:
                keep[lab == i] = 255
    else:
        keep = mask
    ys, xs = np.where(keep > 0)
    if len(xs):
        pad = 2
        keep = keep[max(0, ys.min() - pad):min(h, ys.max() + 1 + pad),
                    max(0, xs.min() - pad):min(w, xs.max() + 1 + pad)]
    if keep.shape[0]:
        sc = 64 / keep.shape[0]
        keep = cv2.resize(keep, (max(1, int(keep.shape[1] * sc)), 64), interpolation=cv2.INTER_CUBIC)
        keep = (keep > 127).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, k, iterations=1)
    inverted = 255 - keep
    return cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)


# --- CACHE DE RANGOS (Fase 2: no volver a OCR-ear una carta ya resuelta) ---
#
# El OCR de rango es el 86% del trabajo de un frame: 90 de los 105 jobs, porque
# cada carta se lee con 18 variantes de recorte/escala/psm para votar. Y una
# carta del board es LA MISMA IMAGEN durante todos los frames de esa calle, asi
# que se estaba pagando ese 86% una y otra vez por la misma respuesta.
#
# LA CLAVE es (palo, hash del INTERIOR del recorte). El interior -se descarta un
# CACHE_MARGEN por cada lado- porque el borde del recorte trae tapete y fichas
# que se ANIMAN: hasheando el recorte entero solo coincide el 52% de las veces,
# y quitando los margenes el 81%. Medido sobre 728 recortes de una sesion real:
#
#     margen   0%   728 recortes, 348 distintos -> 52% de ahorro
#     margen  15%   728 recortes, 141 distintos -> 81% de ahorro
#     margen  25%   728 recortes, 131 distintos -> 82% de ahorro
#
# Se queda en 15%: de ahi para arriba casi no gana y se empieza a comer el
# glifo, que es justo lo que tiene que distinguir una carta de otra.
#
# POR QUE ES SEGURO: el glifo del rango vive en el centro del recorte, asi que
# dos rangos distintos dan pixeles distintos ahi. Una colision exigiria el mismo
# interior Y el mismo palo, o sea la misma carta. El palo no se cachea: lo
# resuelve color_card_detector por color, que es barato.
CACHE_MARGEN = 0.15
CACHE_MAX = 512

_RANK_CACHE = {}


def cache_key(card_bgr, suit, deck="solid"):
    """Clave de cache de una carta, o None si el recorte no sirve. El mazo entra
    en la clave porque el mismo recorte se lee distinto en cada polaridad."""
    if card_bgr is None or card_bgr.size == 0:
        return None
    h, w = card_bgr.shape[:2]
    dy, dx = int(h * CACHE_MARGEN), int(w * CACHE_MARGEN)
    interior = card_bgr[dy:h - dy, dx:w - dx]
    if interior.size == 0:
        return None
    return (deck, suit, hashlib.blake2b(interior.tobytes(), digest_size=8).digest())


def cached_rank(key):
    """(hay_entrada, rango). Se cachea TAMBIEN el fallo (rango None): el OCR es
    determinista, asi que reintentar la misma imagen daria el mismo None y es
    justo el caso mas caro (las 18 variantes sin acuerdo)."""
    if key is None or key not in _RANK_CACHE:
        return False, None
    return True, _RANK_CACHE[key]


def store_rank(key, rank):
    if key is None:
        return
    if len(_RANK_CACHE) >= CACHE_MAX:
        # se vacia entera en vez de llevar un LRU: son cartas, el conjunto vivo
        # de una sesion es pequeño, y un dict de 512 entradas ya cubre de sobra
        # una mano larga. Vaciar cuesta un frame lento cada muchisimos.
        _RANK_CACHE.clear()
    _RANK_CACHE[key] = rank


def reset_rank_cache():
    """Para tests y para empezar sesion limpia."""
    _RANK_CACHE.clear()


def add_rank_jobs(batch, card_bgr, whitelist="0123456789AKQJ", deck="solid"):
    """Encola DOS vistas del rango, cada una con sus variantes psm/escala, y
    devuelve (start, end) para recortar sus resultados de batch.run().
    resolve_rank interpreta ese tramo: la primera mitad es el ANCLA (doble
    peso) y la segunda el DESEMPATE.

    Que vista hace de ancla depende del mazo, porque el ruido es distinto:

      solid  ancla = mascara de carta completa, desempate = rango aislado con
             cierre morfologico (reconecta trazos de 2, 9, Q). 88% por carta.
      glyph  al reves: la carta trae el rango DOS veces y el pip mide casi lo
             mismo, asi que la mascara completa se lee mal (32/40). El ancla es
             el rango aislado por posicion, que no se equivoca nunca, y la
             mascara completa solo desempata: 40/40."""
    if deck == "glyph":
        # el rango aislado ancla (nunca se equivoca, solo se calla) y la mascara
        # completa desempata. Ver _fila_de_arriba para la medicion.
        ancla = cv2.cvtColor(255 - _recortar(rango_grande_mask(card_bgr, deck)),
                             cv2.COLOR_GRAY2BGR)
        desempate = white_text_mask(card_bgr, deck)
    else:
        ancla = white_text_mask(card_bgr, deck)
        desempate = _rank_only_close_img(card_bgr, deck)
    start = batch.job_count()
    for psm, scale in PSM_SCALE_VARIANTS:
        batch.add_text_job(ancla, whitelist=whitelist, psm=psm, scale=scale, pad=20)
    for psm, scale in PSM_SCALE_VARIANTS:
        batch.add_text_job(desempate, whitelist=whitelist, psm=psm, scale=scale, pad=20)
    return start, batch.job_count()


def resolve_rank(texts, card_bgr=None, deck="solid"):
    """Rango por voto mayoritario ponderado sobre las lecturas validas.

    - Si card_bgr trae la señal de ancho de un '10' (is_ten), se devuelve "10"
      con prioridad: es el fallo mas costoso (deja al hero con <2 cartas) y la
      señal geometrica es mas fiable que el OCR de dos digitos pequeños.
    - Las lecturas de la mascara completa (primera mitad, metodo probado)
      cuentan doble; las de la vista close (segunda mitad) corrigen glifos
      redondos. Empate a maximo -> None (mejor omitir que inventar una carta)."""
    if card_bgr is not None and is_ten(card_bgr, deck):
        return "10"
    n_full = len(PSM_SCALE_VARIANTS)
    weighted = []
    for i, t in enumerate(texts):
        c = normalize_rank(t)
        if c is None:
            continue
        weighted.extend([c] * (FULL_VOTE_WEIGHT if i < n_full else 1))
    if not weighted:
        return None
    counts = Counter(weighted)
    max_count = max(counts.values())
    winners = [c for c in counts if counts[c] == max_count]
    return winners[0] if len(winners) == 1 else None
