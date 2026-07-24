"""
OCR del rango para el mazo de 4 colores (color_card_detector.py): el rango
va en blanco, grande, sobre el fondo de color solido de la carta (el palo ya
se resolvio por color de fondo, no hace falta leerlo). Distinto del OCR de
rank_ocr.py (mazo blanco, rango pequeño en la esquina junto al icono de
palo, texto de color sobre fondo blanco).

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

2. Voto ponderado sobre dos vistas. Ni una sola combinacion fija de psm/escala
   acierta siempre, asi que se prueban varias y se vota por mayoria. Ademas de
   la mascara de carta completa (el metodo probado) se añade una vista "close":
   el rango aislado (sin pip de palo) con un cierre morfologico que reconecta
   los trazos finos que la mascara parte en los glifos redondos (2, 9, Q). Esto
   reduce confusiones sistematicas (2 36->48, 9 28->35, Q 51->53 y elimina el
   3->K) sin engrosar el glifo -a diferencia de dilatar, que fusionaba los
   lobulos del 3-. La mascara completa cuenta doble (ancla) y la vista close
   desempata/corrige; en conjunto el acierto por carta pasa de ~82% a ~88%.
   Empate a maximo de votos -> None (mejor omitir que arriesgar una carta
   equivocada con la misma confianza que una correcta).
"""
from collections import Counter

import cv2
import numpy as np

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


def white_text_mask(card_bgr):
    inverted = 255 - _white_mask(card_bgr)
    return cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)


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


def is_ten(card_bgr):
    """True si el rango es '10': un '1' fino (barra vertical alta y estrecha)
    pegado a la izquierda de otro glifo. Señal independiente del OCR."""
    rank = _rank_components(_white_mask(card_bgr))
    if len(rank) < 2:
        return False
    left, right = rank[0], rank[1]
    lw, lh = int(left[2]), int(left[3])
    if lh == 0 or lw / lh >= ONE_MAX_ASPECT:
        return False
    overlap = (int(left[0]) + lw) - int(right[0])
    return overlap <= ONE_MAX_OVERLAP * lw


def _rank_only_close_img(card_bgr):
    """Rango aislado (sin pip de palo), reescalado a alto fijo y con cierre
    morfologico (reconecta trazos finos partidos). Texto negro sobre blanco,
    listo para add_text_job. Cae a la mascara completa si no hay glifos."""
    mask = _white_mask(card_bgr)
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


def add_rank_jobs(batch, card_bgr, whitelist="0123456789AKQJ"):
    """Encola dos vistas del rango -mascara de carta completa y rango aislado
    con cierre morfologico-, cada una con las variantes psm/escala, y devuelve
    (start, end) para recortar sus resultados de batch.run(). resolve_rank
    interpreta ese tramo: la primera mitad es la mascara completa (doble peso),
    la segunda la vista close."""
    full = white_text_mask(card_bgr)
    close = _rank_only_close_img(card_bgr)
    start = batch.job_count()
    for psm, scale in PSM_SCALE_VARIANTS:
        batch.add_text_job(full, whitelist=whitelist, psm=psm, scale=scale, pad=20)
    for psm, scale in PSM_SCALE_VARIANTS:
        batch.add_text_job(close, whitelist=whitelist, psm=psm, scale=scale, pad=20)
    return start, batch.job_count()


def resolve_rank(texts, card_bgr=None):
    """Rango por voto mayoritario ponderado sobre las lecturas validas.

    - Si card_bgr trae la señal de ancho de un '10' (is_ten), se devuelve "10"
      con prioridad: es el fallo mas costoso (deja al hero con <2 cartas) y la
      señal geometrica es mas fiable que el OCR de dos digitos pequeños.
    - Las lecturas de la mascara completa (primera mitad, metodo probado)
      cuentan doble; las de la vista close (segunda mitad) corrigen glifos
      redondos. Empate a maximo -> None (mejor omitir que inventar una carta)."""
    if card_bgr is not None and is_ten(card_bgr):
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
