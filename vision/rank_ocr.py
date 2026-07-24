"""
OCR del rango (parte 2 del enfoque recomendado) sobre el recorte de una
carta ya localizada. Tesseract falla con facilidad en recortes tan pequeños
(<40px) si el glifo toca el borde de la imagen o si el recorte no encaja
justo con el ancho real del caracter (mas notorio en la mitad derecha de un
par de cartas fusionadas, donde el punto de corte no cae siempre exacto en
la costura). En vez de ajustar a mano un unico recorte "perfecto", se
generan varias variantes de recorte y se O CR-ean todas; la primera que
produzca un rango valido gana. Si ninguna produce un rango valido, se
devuelve None: mejor no adivinar que inventar una carta.
"""
VALID_RANKS = {"A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"}

CROP_VARIANTS = [
    (0.0, 0.40, 0.42),
    (0.0, 0.52, 0.45),
    (0.06, 0.46, 0.42),
    (0.0, 0.36, 0.50),
    (0.10, 0.50, 0.42),
    (0.0, 0.70, 0.60),
]


def rank_crop_variants(card_bgr, w, h):
    crops = []
    for x0f, x1f, yf in CROP_VARIANTS:
        y1 = max(int(h * yf), 24)
        x0, x1 = int(w * x0f), int(w * x1f)
        crops.append(card_bgr[0:y1, x0:x1])
    return crops


def normalize_rank(raw_text):
    text = raw_text.strip().upper()
    text = text.replace("O", "0")
    if text == "10" or text == "1O" or text == "I0":
        return "10"
    if text in VALID_RANKS:
        return text
    return None


CODE_TO_NOTATION = {
    "10": "T", "J": "J", "Q": "Q", "K": "K", "A": "A",
    "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
}

SUIT_TO_LETTER = {"spade": "s", "heart": "h", "club": "c", "diamond": "d"}


def card_code(rank, suit):
    if rank is None or suit is None:
        return None
    return CODE_TO_NOTATION[rank] + SUIT_TO_LETTER[suit]
