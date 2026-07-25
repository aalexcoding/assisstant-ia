"""
Parser del resultado de la ULTIMA mano terminada a partir de las lineas OCR del
panel de chat de PokerStars (cliente en castellano), mas una utilidad para
OCR-ear la zona del chat por su cuenta.

analyze_layout() ya OCR-ea la zona del chat (seat_map.CHAT_ZONE) para leer las
ciegas de respaldo, pero NO expone esas lineas en el GameState y no se toca
table_state.py; asi que read_chat_lines() repite ese mismo recorte+OCR (mismas
utilidades: seat_map + OcrBatch + parse_tsv_lines) para obtener las lineas del
chat de forma independiente. Es un segundo paso de OCR por frame sobre un
recorte pequeño (barato dentro del margen de 5s del proyecto).

El cliente imprime en el chat el resultado de cada mano, p.ej.:
  "Repartidor: Mano n.o 261531764294: fabiocs98 gana el bote (2.040) con pareja de nueves"
  "Repartidor: fortu2010 tiene pareja de nueves"   (revelacion de showdown)
  "Repartidor: alex_delg, es tu turno..."          (linea de turno; se ignora)
De ahi se extrae ganador, importe, mano ganadora, numero de mano (para saber
cuando la mano es NUEVA) y, como extra, los jugadores que llegaron a showdown.

El OCR del chat es ruidoso: los patrones son tolerantes (regex flexible) pero
NO inventan; si un campo no se lee, queda vacio (None / lista vacia).
"""
import re

# clase de caracteres de una palabra de mano ganadora en castellano (con
# acentos y ñ): "pareja de nueves", "trio de reyes", "color", "full", ...
_W = r"A-Za-zÁÉÍÓÚÜÑáéíóúüñ"
_HAND_PHRASE = rf"[{_W}]+(?:\s+[{_W}]+){{0,5}}"

# nick de PokerStars: letras/digitos/_/-/. (3-20 chars)
_NICK = r"[\w\-.]{3,20}"

# "Mano n.o 261531764294:" -> el numero identifica la mano. El "n.º" sale mal
# por OCR (n.o, n°, n9, ...), asi que se ancla en "Mano" + hasta 8 no-digitos +
# una tirada larga de digitos (con posibles espacios/puntos espurios del OCR).
HAND_NUM_RE = re.compile(r"[Mm]ano\b[^\d]{0,8}([\d][\d .]{3,}[\d])")

# "X gana el bote (2.040)" / "X gana el bote principal (N)" / "X gana el bote".
# El importe va entre parentesis y es opcional (por si el OCR pierde el parentesis).
WINNER_RE = re.compile(
    rf"({_NICK})\s+gana\b[^()\n]*?bote\w*[^()\n]{{0,20}}(?:\(\s*([\d.,][\d.,\s]*?)\s*\))?",
    re.IGNORECASE)

# "... con pareja de nueves" (la mano ganadora, tras el importe)
WIN_HAND_RE = re.compile(rf"\bcon\s+({_HAND_PHRASE})", re.IGNORECASE)

# "X tiene pareja de nueves" / "X muestra full de ases" (revelaciones de showdown)
SHOWDOWN_RE = re.compile(rf"({_NICK})\s+(?:tiene|muestra)\s+({_HAND_PHRASE})", re.IGNORECASE)


def _clean_token(text):
    return text.strip().strip("/.,;:'\"|") if text else None


def _clean_amount(text):
    if not text:
        return None
    a = re.sub(r"\s+", "", text)
    return a or None


def _clean_hand(text):
    return re.sub(r"\s+", " ", text).strip() if text else None


def _line_texts(chat_lines):
    """Acepta una lista de str o de dicts {'text': ...} (lo que devuelve
    parse_tsv_lines) y devuelve una lista de strings no vacios, en orden."""
    out = []
    for ln in chat_lines or []:
        text = ln.get("text", "") if isinstance(ln, dict) else str(ln)
        if text and text.strip():
            out.append(text.strip())
    return out


def parse_hand_result(chat_lines):
    """Extrae el resultado de la ultima mano terminada de las lineas OCR del
    chat. Devuelve un dict o None si no hay ninguna linea de resultado legible.

    dict = {
      "hand_number": str|None,   # digitos del "Mano n.o XXXX" (para detectar mano nueva)
      "winner":      str|None,   # nick del ganador
      "amount":      str|None,   # importe del bote tal cual se leyo ("2.040")
      "winning_hand":str|None,   # "pareja de nueves"
      "showdown":    [ {"player": str, "hand": str}, ... ],  # extra; puede estar vacio
    }
    Las lineas se unen en un blob (una misma linea de chat larga puede partirse
    en varias lineas visuales por el OCR); la ULTIMA coincidencia de ganador en
    orden de lectura es la mas reciente (el chat va de arriba-viejo a abajo-nuevo).
    """
    lines = _line_texts(chat_lines)
    if not lines:
        return None
    blob = " ".join(lines)

    winners = list(WINNER_RE.finditer(blob))
    if not winners:
        return None
    m = winners[-1]
    winner = _clean_token(m.group(1))
    amount = _clean_amount(m.group(2))

    # mano ganadora: primer "con ..." tras el importe (ventana corta para no
    # colarse en un mensaje posterior si el ganador no fuese la ultima linea)
    winning_hand = None
    hm = WIN_HAND_RE.search(blob, m.end(), m.end() + 80)
    if hm:
        winning_hand = _clean_hand(hm.group(1))

    # numero de mano: el "Mano n.o XXXX" mas cercano ANTES del ganador (suele ir
    # en la misma linea, "Mano n.o XXXX: winner gana ..."); si no hay ninguno
    # antes, el ultimo que aparezca; si no hay ninguno, None.
    hand_number = None
    hnums = list(HAND_NUM_RE.finditer(blob))
    if hnums:
        before = [h for h in hnums if h.end() <= m.start()]
        chosen = before[-1] if before else hnums[-1]
        digits = re.sub(r"\D", "", chosen.group(1))
        if len(digits) >= 6:
            hand_number = digits

    # showdown (extra): "X tiene/muestra {mano}"; ultima lectura por jugador
    showdown = {}
    for sm in SHOWDOWN_RE.finditer(blob):
        player = _clean_token(sm.group(1))
        hand = _clean_hand(sm.group(2))
        if player and hand:
            showdown[player] = hand
    showdown_list = [{"player": p, "hand": h} for p, h in showdown.items()]

    # si el ganador no traia "con {mano}" pero se revelo su mano en showdown, se
    # rellena desde ahi (no se inventa: es la misma fuente del chat)
    if not winning_hand and winner:
        for sd in showdown_list:
            if _names_match(sd["player"], winner):
                winning_hand = sd["hand"]
                break

    return {
        "hand_number": hand_number,
        "winner": winner,
        "amount": amount,
        "winning_hand": winning_hand,
        "showdown": showdown_list,
    }


def _norm_name(name):
    return re.sub(r"[^a-z0-9]", "", name.lower()) if name else ""


def _names_match(a, b):
    """Comparacion tolerante de nicks (OCR ruidoso): igualdad normalizada, o uno
    prefijo del otro (truncamiento) con al menos 5 caracteres en comun."""
    na, nb = _norm_name(a), _norm_name(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return min(len(na), len(nb)) >= 5 and (na.startswith(nb) or nb.startswith(na))


def hero_outcome(result, hero_name):
    """Determina el desenlace del hero en la mano anterior a partir del resultado
    del chat y el nombre cacheado del hero.

    Limitacion honesta: desde el chat NO siempre se sabe si el hero jugo la mano
    (no se listan todos los jugadores). Solo se afirma algo cuando hay evidencia
    directa: si el ganador ES el hero -> "won"; si el hero aparece revelando su
    mano en showdown y no es el ganador -> "lost"; en cualquier otro caso
    "unknown" (no se afirma que perdio ni que gano).

    Devuelve {"status": "won"|"lost"|"unknown", "hero_hand": str|None}.
    """
    out = {"status": "unknown", "hero_hand": None}
    if not result or not hero_name:
        return out
    if result.get("winner") and _names_match(result["winner"], hero_name):
        out["status"] = "won"
        out["hero_hand"] = result.get("winning_hand")
        return out
    for sd in result.get("showdown", []):
        if _names_match(sd.get("player"), hero_name):
            out["status"] = "lost"
            out["hero_hand"] = sd.get("hand")
            return out
    return out


# el importe conviene mostrarlo tal cual se leyo (el separador de miles varia
# entre "." y "," segun el idioma del cliente), asi que no se convierte a int.


def read_chat_lines(image_path):
    """OCR-ea la zona del chat del frame (seat_map.CHAT_ZONE) de forma
    independiente y devuelve la lista de textos de linea (str). Repite el mismo
    recorte+escala que table_state.analyze_layout usa para el chat (scale=2),
    reutilizando seat_map + OcrBatch + parse_tsv_lines. Imports perezosos para
    que parse_hand_result/hero_outcome sean usables sin opencv/OCR."""
    import cv2

    import seat_map
    from ocr_client import OcrBatch
    from text_extract import parse_tsv_lines

    bgr = cv2.imread(image_path)
    if bgr is None:
        return []
    ref = seat_map.find_reference(bgr)
    x0, y0, x1, y1 = seat_map.zone_to_px(ref, seat_map.CHAT_ZONE, bgr.shape)
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return []
    batch = OcrBatch()
    # castellano: el chat es prosa ("gana el bote (2.040) con pareja de nueves"),
    # y con el modelo ingles los acentos se corrompen. Mismo lang que usa
    # table_state.analyze_layout para esta misma zona.
    idx = batch.add_tsv_job(crop, scale=2, lang="spa")
    results = batch.run()
    return [ln["text"] for ln in parse_tsv_lines(results[idx])]


def read_hand_result(image_path):
    """Conveniencia: OCR-ea el chat y parsea el resultado. Devuelve dict|None."""
    return parse_hand_result(read_chat_lines(image_path))
