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
# Admite COMA entre palabras: el cliente escribe "doble pareja, damas y sietes"
# y sin la coma la frase se cortaba en seco ("doble pareja"). Se amplia a 6
# palabras extra por la misma razon; el desborde se recorta luego en
# _trim_hand_phrase(), que corta en el marcador del siguiente mensaje del chat.
_HAND_PHRASE = rf"[{_W}]+(?:,?\s+[{_W}]+){{0,6}}"

# nick de PokerStars: letras/digitos/_/-/. Se admite UN espacio interno porque el
# OCR lee a veces el guion bajo de un nick como espacio ("david_sagunt" ->
# "david sagunt"); sin esa tolerancia el regex solo capturaba el ultimo token
# ("sagunt") y el ganador salia truncado. _norm_name() quita los no-alfanumericos
# antes de comparar, asi que "david sagunt" y "david_sagunt" siguen casando.
_NICK_WORD = r"[\w\-.]{2,20}"
_NICK = rf"{_NICK_WORD}(?:\s{_NICK_WORD})?"

# palabras que NUNCA forman parte de un nick: al admitir un espacio interno, el
# regex podria comerse la palabra previa ("jugador pepito gana ..."); se recorta.
_NICK_LEADING_NOISE = {"jugador", "repartidor", "artidor", "partidor", "mano",
                       "el", "la", "los", "las", "a", "de", "del", "que", "y"}

# "Mano n.o 261531764294:" -> el numero identifica la mano. El "n.º" sale mal
# por OCR (n.o, n°, n9, ...), asi que se ancla en "Mano" + hasta 8 no-digitos +
# una tirada larga de digitos (con posibles espacios/puntos espurios del OCR).
HAND_NUM_RE = re.compile(r"[Mm]ano\b[^\d]{0,8}([\d][\d .]{3,}[\d])")

# Cierre de mano en el chat, en sus DOS formas:
#   - un solo ganador: "X gana el bote (2.040)" / "X gana el bote principal (N)"
#   - bote dividido:   "X empata por el bote (4.243)"  (una linea por jugador)
# El importe va entre parentesis y es opcional (por si el OCR pierde el parentesis).
WINNER_RE = re.compile(
    rf"({_NICK})\s+(gana|empata)\b[^()\n]*?bote\w*[^()\n]{{0,20}}"
    rf"(?:\(\s*([\d.,][\d.,\s]*?)\s*\))?",
    re.IGNORECASE)

# "... con pareja de nueves" (la mano ganadora, tras el importe)
WIN_HAND_RE = re.compile(rf"\bcon\s+({_HAND_PHRASE})", re.IGNORECASE)

# "X tiene pareja de nueves" / "X muestra full de ases" (revelaciones de showdown)
SHOWDOWN_RE = re.compile(rf"({_NICK})\s+(?:tiene|muestra)\s+({_HAND_PHRASE})", re.IGNORECASE)

# comienzo de un mensaje del chat. Sirve para acotar hasta donde puede llegar la
# frase de mano de UN mensaje. "Repartidor:" sale a menudo truncado por la
# izquierda ("artidor:") porque el panel de chat queda pegado al borde del frame
# capturado, asi que se acepta cualquier cola de esa palabra.
_MSG_START_RE = re.compile(r"[A-Za-z]*artidor\s*:|[Mm]ano\s+n", re.IGNORECASE)

# marcadores de que la frase de mano ya se salio a otro mensaje del chat
_HAND_STOP_WORDS = ("repartidor", "artidor", "partidor", "mano n", "es tu turno",
                    "el tiempo", "los limites", "los límites", "banco de tiempo",
                    "se le permitira", "se le permitirá", "empata", "gana el bote")

# particulas de 1-2 letras que SI pueden cerrar legitimamente una frase de mano
# (por si el OCR corta justo ahi); cualquier otro token corto al final es ruido.
_HAND_TAIL_OK = {"y", "de", "al", "en"}


def _clean_token(text):
    return text.strip().strip("/.,;:'\"|") if text else None


def _clean_amount(text):
    if not text:
        return None
    a = re.sub(r"\s+", "", text)
    return a or None


def _clean_hand(text):
    return re.sub(r"\s+", " ", text).strip() if text else None


def _clean_nick(text):
    """Limpia un nick capturado y le quita una palabra inicial que no puede ser
    parte del nick (ver _NICK_LEADING_NOISE): al admitir un espacio interno, el
    regex puede haberse comido la palabra previa."""
    nick = _clean_token(text)
    if not nick:
        return None
    parts = nick.split()
    if len(parts) == 2:
        head = parts[0].lower().strip(".,;:'\"|")
        # se descarta la primera palabra si es una de las que nunca forman nick, o
        # si no tiene ninguna letra: un nick de PokerStars empieza siempre por
        # letra, asi que un token puramente numerico delante es ruido -tipicamente
        # el numero de mano cuando el OCR se come los dos puntos ("Mano n.o
        # 2615... SHARKOS54 gana ...")-.
        if head in _NICK_LEADING_NOISE or not any(c.isalpha() for c in head):
            nick = parts[1]
    return nick or None


def _trim_hand_phrase(text):
    """Recorta la frase de mano en el primer marcador de otro mensaje del chat.
    El regex admite hasta 7 palabras y, con el mensaje envuelto en varias lineas
    visuales, puede invadir el mensaje siguiente ("... pareja de jotas Repartidor:
    alex_delg es tu turno")."""
    if not text:
        return None
    low = text.lower()
    cut = len(text)
    for w in _HAND_STOP_WORDS:
        i = low.find(w)
        if i != -1:
            cut = min(cut, i)
    limpio = _clean_hand(text[:cut])
    if not limpio:
        return None
    # basura final de 1-2 caracteres: los rangos de las cartas de la mesa se
    # cuelan a veces al final de la frase ("pareja de jotas Qa", "doble pareja,
    # reyes y doses QQ"). Ningun nombre de mano en castellano termina en un token
    # de una o dos letras salvo las particulas de _HAND_TAIL_OK, asi que se poda.
    partes = limpio.split()
    while len(partes) > 1 and len(partes[-1].strip(".,;:")) <= 2 \
            and partes[-1].lower().strip(".,;:") not in _HAND_TAIL_OK:
        partes.pop()
    return " ".join(partes).strip(" ,;:") or None


def _line_texts(chat_lines):
    """Acepta una lista de str o de dicts {'text': ..., 'top': ..., 'left': ...}
    (lo que devuelve parse_tsv_lines) y devuelve una lista de strings no vacios.

    Si TODAS las lineas traen posicion, se ordenan por posicion visual
    (arriba->abajo, izquierda->derecha) antes de unirlas: el modo SPARSE_TEXT de
    tesseract no garantiza devolverlas en orden de lectura, y con un mensaje
    envuelto en varias lineas la continuacion ("...con pareja de jotas") podia
    llegar ANTES de su cabecera, con lo que la busqueda de la mano ganadora -que
    avanza desde el ganador hacia adelante- no la encontraba nunca."""
    items = []
    for ln in chat_lines or []:
        if isinstance(ln, dict):
            text = ln.get("text", "")
            key = (ln.get("top"), ln.get("left"))
            if key[0] is None or key[1] is None:
                key = None
        else:
            text, key = str(ln), None
        if text and text.strip():
            items.append((key, text.strip()))
    if items and all(key is not None for key, _ in items):
        items.sort(key=lambda it: (it[0][0], it[0][1]))
    return [text for _, text in items]


def parse_hand_result(chat_lines):
    """Extrae el resultado de la ultima mano terminada de las lineas OCR del
    chat. Devuelve un dict o None si no hay ninguna linea de resultado legible.

    dict = {
      "hand_number": str|None,   # digitos del "Mano n.o XXXX" (para detectar mano nueva)
      "winner":      str|None,   # nick del ganador (el primero, si el bote se dividio)
      "winners":     [str, ...], # todos los que se llevan bote (1, o varios si hay split)
      "split":       bool,       # True si el bote se dividio ("empata por el bote")
      "amount":      str|None,   # importe del bote tal cual se leyo ("2.040")
      "winning_hand":str|None,   # "pareja de nueves"
      "showdown":    [ {"player": str, "hand": str}, ... ],  # extra; puede estar vacio
    }
    Las lineas se unen en un blob (una misma linea de chat larga puede partirse
    en varias lineas visuales por el OCR); la ULTIMA coincidencia de ganador en
    orden de lectura es la mas reciente (el chat va de arriba-viejo a abajo-nuevo).

    Botes divididos: el cliente los anuncia con "X empata por el bote (N)", una
    linea por jugador que empata y todas con el MISMO numero de mano. Antes no se
    reconocian en absoluto (el patron exigia "gana"), asi que una mano repartida
    se veia como "resultado no legible".
    """
    lines = _line_texts(chat_lines)
    if not lines:
        return None
    blob = " ".join(lines)

    matches = list(WINNER_RE.finditer(blob))
    if not matches:
        return None
    m = matches[-1]

    # numero de mano asociado a una posicion del blob: el "Mano n.o XXXX" mas
    # cercano ANTES de ella (suele ir en la misma linea, "Mano n.o XXXX: winner
    # gana ..."); si no hay ninguno antes, el ultimo que aparezca.
    hnums = list(HAND_NUM_RE.finditer(blob))

    def _hnum_at(pos):
        if not hnums:
            return None
        before = [h for h in hnums if h.end() <= pos]
        chosen = before[-1] if before else hnums[-1]
        digits = re.sub(r"\D", "", chosen.group(1))
        return digits if len(digits) >= 6 else None

    hand_number = _hnum_at(m.start())

    split = m.group(2).lower().startswith("empata")
    if split:
        # todos los que empatan en ESTA mano (mismo numero de mano que el match
        # elegido); si el numero no se pudo leer, se aceptan todos los "empata"
        # visibles antes que descartar la evidencia.
        winners, amount = [], None
        for mm in matches:
            if not mm.group(2).lower().startswith("empata"):
                continue
            if hand_number is not None and _hnum_at(mm.start()) != hand_number:
                continue
            nick = _clean_nick(mm.group(1))
            if nick and nick not in winners:
                winners.append(nick)
            if amount is None:
                amount = _clean_amount(mm.group(3))
    else:
        winners = [n for n in [_clean_nick(m.group(1))] if n]
        amount = _clean_amount(m.group(3))
    winner = winners[0] if winners else None

    # mano ganadora: el "con ..." del MISMO mensaje del chat. El limite es el
    # comienzo del mensaje siguiente, no una ventana fija de caracteres: con el
    # texto envuelto en varias lineas visuales el "con pareja de X" cae mas alla
    # de los 80 chars que se usaban antes y se perdia (winning_hand salia solo en
    # 37 de 111 frames reales).
    nxt = _MSG_START_RE.search(blob, m.end())
    winning_hand = None
    hm = WIN_HAND_RE.search(blob, m.end(), nxt.start() if nxt else len(blob))
    if hm:
        winning_hand = _trim_hand_phrase(hm.group(1))

    # showdown (extra): "X tiene/muestra {mano}"; ultima lectura por jugador
    showdown = {}
    for sm in SHOWDOWN_RE.finditer(blob):
        player = _clean_nick(sm.group(1))
        hand = _trim_hand_phrase(sm.group(2))
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
        "winners": winners,
        "split": split,
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
    directa: si el hero esta entre los que se llevan el bote -> "won", o "split"
    si el bote se dividio; si el hero aparece revelando su mano en showdown y no
    se lleva bote -> "lost"; en cualquier otro caso "unknown" (no se afirma que
    perdio ni que gano).

    Devuelve {"status": "won"|"split"|"lost"|"unknown", "hero_hand": str|None}.
    """
    out = {"status": "unknown", "hero_hand": None}
    if not result or not hero_name:
        return out
    ganadores = result.get("winners")
    if not ganadores:
        ganadores = [result["winner"]] if result.get("winner") else []
    for g in ganadores:
        if _names_match(g, hero_name):
            out["status"] = "split" if result.get("split") else "won"
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
    independiente y devuelve las lineas TAL CUAL las da parse_tsv_lines, es decir
    dicts con texto y posicion ({'text','left','top','right','bottom','cx','cy'}).

    Se devuelve la posicion y no solo el texto porque parse_hand_result la usa
    para reconstruir el orden de lectura: el modo SPARSE_TEXT de tesseract no
    garantiza devolver las lineas en orden visual, y sin ordenarlas la
    continuacion de un mensaje envuelto puede aparecer antes que su cabecera.
    _line_texts() acepta tanto dicts como strings, asi que quien solo quiera el
    texto puede seguir pasandole cualquiera de los dos.

    Repite el mismo recorte+escala+idioma que table_state.analyze_layout usa para
    el chat, reutilizando seat_map + OcrBatch + parse_tsv_lines. Imports perezosos
    para que parse_hand_result/hero_outcome sean usables sin opencv/OCR."""
    import cv2

    from vision import seat_map
    from vision.ocr_client import OcrBatch
    from vision.text_extract import parse_tsv_lines

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
    return parse_tsv_lines(results[idx])


def read_hand_result(image_path):
    """Conveniencia: OCR-ea el chat y parsea el resultado. Devuelve dict|None."""
    return parse_hand_result(read_chat_lines(image_path))
