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


def _rank_exacto(text):
    if text in ("10", "1O", "I0"):
        return "10"
    return text if text in VALID_RANKS else None


def normalize_rank(raw_text):
    """Texto de OCR -> rango ("2".."9", "10", "J", "Q", "K", "A") o None.

    LECTURAS DE VARIAS LINEAS. Tesseract devuelve dos lineas cuando ademas del
    rango grande lee el PIP DEL PALO de la esquina del recorte, y el trebol se
    parece bastante a un "4". Antes cualquier texto multilinea se descartaba
    entero, o sea que se tiraba la lectura buena junto con el artefacto.

    El orden no es casual y por eso se puede resolver: el pip esta ARRIBA del
    rango dentro del recorte, y tesseract emite de arriba abajo, asi que el rango
    real es la ULTIMA linea valida. Medido sobre 46 cartas que se quedaban sin
    resolver en una sesion real: los patrones multilinea eran '4|2' (x60), '4|8'
    (x6) y '4|Q' (x1) -siempre el mismo artefacto delante-, la ultima linea
    rescataba 27 de las 46, y en CERO casos las distintas lecturas de una misma
    carta discrepaban sobre cual era.

    Esto alimenta el voto por mayoria de color_rank_ocr.resolve_rank, no lo
    sortea: una linea rescatada tiene que ganar la votacion igual que cualquier
    otra lectura, y el empate sigue devolviendo None. Perder una carta de board
    deja la equity sin calcular; inventarla daria una equity FALSA, que es peor.
    """
    text = raw_text.strip().upper().replace("O", "0")
    directo = _rank_exacto(text)
    if directo is not None:
        return directo
    if "\n" in text:
        for linea in reversed(text.split("\n")):
            r = _rank_exacto(linea.strip())
            if r is not None:
                return r
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
