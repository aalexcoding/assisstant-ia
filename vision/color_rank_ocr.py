"""
OCR del rango para el mazo de 4 colores (color_card_detector.py): el rango
va en blanco, grande, sobre el fondo de color solido de la carta (el palo ya
se resolvio por color de fondo, no hace falta leerlo). Distinto del OCR de
rank_ocr.py (mazo blanco, rango pequeño en la esquina junto al icono de
palo, texto de color sobre fondo blanco).

Probado contra 25 recortes reales de vision/samples_pokerstars/ con rango
conocido a mano (~90% de acierto por caracter): ni una sola combinacion fija
de psm/escala acierta siempre (distintos recortes fallan con distintas
combinaciones, a veces en direcciones opuestas: lo que arregla un "2" mal
leido rompe una "Q" que antes salia bien), asi que se prueban varias y se
vota por mayoria en vez de quedarse con la primera valida (a diferencia de
rank_ocr.py, aqui las lecturas erroneas son bastante mas frecuentes que en
el mazo blanco). Empate a mas votos -> se descarta en vez de arriesgar una
carta equivocada; en la practica esto pasa poco (la mayoria gana casi
siempre, para bien o para mal), asi que un acierto de ~90% por caracter
todavia deja lecturas confiadas pero equivocadas ocasionales, no solo
omisiones.
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


def white_text_mask(card_bgr):
    hsv = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    text = ((s < WHITE_MAX_SATURATION) & (v > WHITE_MIN_VALUE)).astype(np.uint8) * 255
    inverted = 255 - text
    return cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR)


def add_rank_jobs(batch, card_bgr, whitelist="0123456789AKQJ"):
    """Encola las variantes psm/escala para una carta y devuelve (start, end)
    para recortar sus resultados de batch.run()."""
    mask = white_text_mask(card_bgr)
    start = batch.job_count()
    for psm, scale in PSM_SCALE_VARIANTS:
        batch.add_text_job(mask, whitelist=whitelist, psm=psm, scale=scale, pad=20)
    return start, batch.job_count()


def resolve_rank(texts):
    """Mayoria simple entre las lecturas validas; empate a mas votos -> None
    (mejor omitir que arriesgar una carta equivocada con la misma confianza
    que una correcta)."""
    candidates = [normalize_rank(t) for t in texts]
    candidates = [c for c in candidates if c is not None]
    if not candidates:
        return None
    counts = Counter(candidates)
    max_count = max(counts.values())
    winners = [c for c in counts if counts[c] == max_count]
    return winners[0] if len(winners) == 1 else None
