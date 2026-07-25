"""
Fase 3: dado un frame (recorte de la mesa), produce una estructura GameState
con las cartas propias, el board, el pot, los jugadores (nombre+stack) y las
ciegas, apoyandose en table_region.py (localizacion de la mesa),
card_detector.py (deteccion de cartas por contorno/forma), suit_classifier.py
(color+forma del palo) y text_extract.py (OCR de texto libre, sin
coordenadas fijas).

Nada se fuerza: si una carta se detecta como region pero no se puede leer
el rango con confianza, o si no aparece ningun texto que encaje con el
patron de pot/ciegas/jugador+stack, el campo queda vacio/omitido y se anota
en "warnings" en vez de adivinar.
"""
import os

import cv2

import color_card_detector
import color_rank_ocr
import dealer_button
import seat_map
from card_detector import classify_boxes, find_card_boxes
from ocr_client import OcrBatch
from rank_ocr import card_code, normalize_rank, rank_crop_variants
from suit_classifier import classify_suit
from table_region import find_table_region
from text_extract import (_clean_name, _is_name_candidate, _is_number_candidate, _is_username_token, _to_int,
                          find_blinds, find_blinds_chat, find_blinds_corner, find_players, find_pot,
                          find_pot_bb,
                          merge_line_sets, parse_tsv_lines)

# la barra de titulo de la ventana (nombre de mesa, ciegas, torneo) queda
# fuera del ovalo de la mesa y su fuente es demasiado fina para el OCR a
# tamaño completo de frame; una pasada aparte solo de esa franja, a mayor
# escala, resuelve las ciegas donde la pasada normal no llega. Fraccion de
# alto en vez de pixeles fijos: es la franja superior de la ventana
# capturada, no una coordenada de la mesa.
TITLE_BAR_HEIGHT_FRAC = 0.06

# el indicador compacto de ciegas ("17,5K/35K(4,5K)") vive en la esquina
# superior derecha, junto al reloj de mano; su fuente es mas legible que la
# barra de titulo pero sigue siendo pequeña para el OCR a tamaño de frame
# completo. Dos recortes (alto x ancho x escala) calibrados contra las 93
# capturas de vision/samples_pokerstars/: entre los dos cubren tanto las
# capturas que incluyen la barra de titulo del sistema (el indicador queda
# mas abajo) como las que no (el indicador queda mas arriba), sin necesidad
# de saber de antemano cual es cual.
CORNER_BLINDS_CROPS = [(0.12, 0.55, 4), (0.15, 0.50, 4)]

# analyze_layout (mapa de asientos): el cliente real muestra en la esquina
# superior derecha un recuadro fijo (junto al reloj de nivel y "Media: XX,XXK")
# con las ciegas en formato SB/BB(ante) -"250/500(80)", "17,5K/35K(4,5K)"-.
# Es PERSISTENTE (a diferencia del aviso del chat, que solo sale unos segundos
# al subir de nivel), asi que es la fuente automatica mas fiable. El recuadro
# esta anclado a la esquina de la VENTANA, no al ovalo del tapete, por eso se
# expresa como fraccion del FRAME (como TITLE_BAR_HEIGHT_FRAC) y no como zona
# del mapa de asientos. Margen generoso por cada lado (x desde 0.55 hasta el
# borde, y desde 0 hasta 0.17) para que aunque el encuadre baile unos pixeles
# el texto no se corte: el OCR lee bien texto rodeado de fondo, lo que no
# perdona es texto cortado por el borde. Escala x4 porque la fuente es pequeña
# a tamaño de frame completo, igual que la barra de titulo en analyze_color_deck.
# (x0, y0, x1, y1) en fracciones del frame.
CORNER_BLINDS_ZONE = (0.55, 0.0, 1.0, 0.17)
CORNER_BLINDS_SCALE = 4


def _assign_player_positions(bgr, region, players, diag, warnings):
    """Detecta el boton del dealer y, si esta lo bastante cerca de algun
    asiento conocido, anade "position" (BTN/SB/BB/CO/HJ/...) a cada jugador
    de players. Si el boton no se ve o no se puede asociar con confianza a
    ningun asiento, no se inventa nada: se anota un warning y los jugadores
    quedan sin ese campo."""
    if not players:
        return players
    button_box = dealer_button.find_dealer_button(bgr, region)
    if button_box is None:
        warnings.append("no se detecto el boton del dealer (tapado o fuera de frame); sin posiciones")
        return players
    seat_markers = dealer_button.find_occupied_seat_markers(bgr, region)
    positioned = dealer_button.assign_positions(players, button_box, diag, seat_markers)
    if positioned is None:
        warnings.append("boton del dealer detectado pero no se pudo asociar a ningun asiento con confianza; sin posiciones")
        return players
    return positioned


def _player_out(p):
    out = {"name": p["name"], "stack": p["stack"], "is_hero": p["is_hero"]}
    if "position" in p:
        out["position"] = p["position"]
    return out


def _set_hero_position(state):
    for p in state["players"]:
        if p["is_hero"] and "position" in p:
            state["hero_position"] = p["position"]
            return
    if any(p["is_hero"] for p in state["players"]):
        state["warnings"].append("hero identificado pero sin posicion asignada")


def _resolve_card(card_bgr, w, h, rank_texts):
    suit, suit_conf = classify_suit(card_bgr, w, h)
    rank = None
    for text in rank_texts:
        candidate = normalize_rank(text)
        if candidate is not None:
            rank = candidate
            break
    return rank, suit, suit_conf


def analyze(image_path):
    """Rama original (mazo blanco, capturas de YouTube): deteccion de cartas por
    contorno + OCR de texto libre sin coordenadas fijas.

    LEGADO / DIAGNOSTICO, NO APTO PARA EL MOTOR: sus stacks son ENTEROS DE FICHAS
    (find_players -> _to_int) y no declara "stack_unit", asi que engine.decide()
    RECHAZA a proposito los GameState que produce -ver el guard de stack_unit-.
    Sin ese guard, cuando la app pase a BB-only un stack de 3955 fichas se leeria
    como 3955bb y saldria una recomendacion con conviccion y falsa.
    Produccion es analyze_layout(). Se conserva porque es la unica rama que lee
    sin coordenadas fijas, util para diagnosticar capturas nuevas."""
    bgr = cv2.imread(image_path)
    state = {
        "image": os.path.basename(image_path),
        "hero_cards": [],
        "board": [],
        "pot": None,
        "blinds": None,
        "players": [],
        "warnings": [],
    }
    if bgr is None:
        state["warnings"].append("no se pudo leer la imagen")
        return state

    region = find_table_region(bgr)
    if region is None:
        state["warnings"].append("no se localizo la mesa (borde rojo no detectado); se usa el frame completo")

    boxes = find_card_boxes(bgr, region)
    hero_boxes, board_boxes, other_boxes = classify_boxes(boxes, region, bgr.shape)
    hero_boxes = sorted(hero_boxes, key=lambda b: b["x"])
    board_boxes = sorted(board_boxes, key=lambda b: b["x"])

    batch = OcrBatch()
    diag = (bgr.shape[0] ** 2 + bgr.shape[1] ** 2) ** 0.5
    tsv_idx_1 = batch.add_tsv_job(bgr, scale=1)
    tsv_idx_2 = batch.add_tsv_job(bgr, scale=2)
    tsv_idx_title = batch.add_tsv_job(bgr[0:int(bgr.shape[0] * TITLE_BAR_HEIGHT_FRAC), :], scale=4)
    tsv_idx_corners = [
        batch.add_tsv_job(bgr[0:int(bgr.shape[0] * fh), int(bgr.shape[1] * fw):], scale=sc)
        for fh, fw, sc in CORNER_BLINDS_CROPS
    ]

    all_card_boxes = hero_boxes + board_boxes
    rank_job_ranges = []
    for b in all_card_boxes:
        crop = bgr[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]]
        variants = rank_crop_variants(crop, b["w"], b["h"])
        start = batch.job_count()
        for v in variants:
            # el margen en blanco alrededor del glifo ayuda a tesseract en
            # unos casos y lo empeora en otros (recorte tan pequeño que el
            # resultado es sensible al ruido de interpolacion); se prueban
            # ambas variantes y se queda la primera que de un rango valido.
            batch.add_text_job(v, whitelist="0123456789AKQJ", psm="SINGLE_LINE", scale=6, pad=0)
            batch.add_text_job(v, whitelist="0123456789AKQJ", psm="SINGLE_LINE", scale=6, pad=20)
        rank_job_ranges.append((start, batch.job_count()))

    results = batch.run()

    tsv1, tsv2 = results[tsv_idx_1], results[tsv_idx_2]
    lines1 = parse_tsv_lines(tsv1)
    lines2 = [{**ln, "left": ln["left"] // 2, "top": ln["top"] // 2, "right": ln["right"] // 2,
               "bottom": ln["bottom"] // 2, "cx": ln["cx"] / 2, "cy": ln["cy"] / 2} for ln in parse_tsv_lines(tsv2)]
    lines = merge_line_sets(lines1, lines2)
    title_lines = parse_tsv_lines(results[tsv_idx_title])
    corner_lines = [parse_tsv_lines(results[idx]) for idx in tsv_idx_corners]

    state["pot"] = find_pot(lines)
    state["blinds"] = (find_blinds_corner(*corner_lines, lines1, lines2)
                        or find_blinds(lines) or find_blinds(title_lines))

    hero_ref_box = hero_boxes[0] if hero_boxes else None
    players = find_players(lines, diag, hero_ref_box)
    players = _assign_player_positions(bgr, region, players, diag, state["warnings"])
    state["players"] = [_player_out(p) for p in players]
    _set_hero_position(state)

    resolved = []
    for b, (start, end) in zip(all_card_boxes, rank_job_ranges):
        crop = bgr[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]]
        rank_texts = results[start:end]
        rank, suit, suit_conf = _resolve_card(crop, b["w"], b["h"], rank_texts)
        code = card_code(rank, suit)
        resolved.append({"box": b, "rank": rank, "suit": suit, "suit_conf": suit_conf, "code": code})

    n_hero = len(hero_boxes)
    hero_resolved = resolved[:n_hero]
    board_resolved = resolved[n_hero:]

    for r in hero_resolved:
        if r["code"]:
            state["hero_cards"].append(r["code"])
        else:
            state["warnings"].append(
                f"carta del hero detectada en {r['box']} pero no se pudo leer con confianza "
                f"(rank={r['rank']}, suit={r['suit']})")

    for r in board_resolved:
        if r["code"]:
            state["board"].append(r["code"])
        else:
            state["warnings"].append(
                f"carta de board detectada en {r['box']} pero no se pudo leer con confianza "
                f"(rank={r['rank']}, suit={r['suit']})")

    if not state["pot"]:
        state["warnings"].append("no se encontro texto de pot")
    if not state["blinds"]:
        state["warnings"].append("no se encontraron las ciegas")
    if not state["players"]:
        state["warnings"].append("no se emparejo ningun jugador (nombre+stack)")

    return state


def _seat_plate_name_stack(lines):
    """De las lineas OCR de la zona de un nameplate, devuelve (name, stack):
    la primera linea que parece nombre y la primera que parece numero."""
    name = None
    stack = None
    for ln in lines:
        if name is None and _is_name_candidate(ln["text"]):
            name = _clean_name(ln["text"])
        if stack is None and _is_number_candidate(ln["text"].strip()):
            stack = _to_int(ln["text"].strip())
    return name, stack


# verbos/estados que el cliente pone en el nameplate en lugar del nombre cuando
# el jugador acaba de actuar o esta sentado sin nombre visible; su presencia
# implica que el asiento esta OCUPADO aunque no se lea nombre ni stack.
SEAT_STATUS_WORDS = {
    "igualar", "iguala", "pasar", "pasa", "apostar", "apuesta", "subir", "sube",
    "resubir", "poner", "ausente", "ante", "allin", "paga", "espera", "sentado",
}


# --- unidad de los importes (fichas o big blinds), con LATCH de sesion ---
# El cliente muestra stacks/apuestas/bote en FICHAS (enteros con separador de
# miles, "5.892") o en BIG BLINDS ("123,4 BB", coma decimal + sufijo BB) segun
# la config del usuario, que NO cambia a mitad de mano.
#
# El problema de detectarlo frame a frame: el sufijo "BB" no siempre se OCR-ea
# (entre manos los nameplates se leen mal, y el "Media: N BB" de la esquina
# puede fallar), y asumir "chips" por defecto es una ADIVINANZA silenciosa. Si
# la mesa estaba en modo BB, el motor divide una profundidad YA expresada en bb
# por la ciega grande y sale una profundidad absurda: una recomendacion
# plausible pero equivocada, que es el peor modo de fallo posible en esta app
# (mucho peor que abstenerse). Medido sobre una sesion real de 34 min, la
# unidad detectada oscilaba dentro de la misma sesion (bbx30, chipsx17, bbx24,
# chipsx37) aunque la config del cliente no habia cambiado.
#
# Solucion: se late la unidad en cuanto hay EVIDENCIA y en los frames sin
# evidencia se reutiliza la latida en vez de volver a adivinar. La evidencia
# siempre manda sobre el latch, asi que si el usuario cambia la config a mitad
# de sesion se re-late solo en el primer frame legible. Sin evidencia NI latch
# se asume "chips" (como antes) pero se AVISA, para que ni el HUD ni el log
# presenten como firme algo que no se pudo determinar.
_UNIT_LATCH = {"value": None}


def reset_unit_latch():
    """Olvida la unidad latida. Para tests y para arrancar sesion limpia."""
    _UNIT_LATCH["value"] = None


def _chips_style_stack(seat_lines):
    """True si algun nameplate muestra un entero de estilo fichas ("5.892",
    "12500"). En modo BB los stacks salen como "44,5 BB", que NO encaja con
    _is_number_candidate (exige >=3 digitos o separador de miles), asi que un
    entero suelto en un nameplate es evidencia de modo fichas."""
    for lines in seat_lines.values():
        for ln in lines:
            if _is_number_candidate(ln["text"].strip()):
                return True
    return False


def _detect_stack_unit(corner_lines, seat_lines, warnings):
    """Devuelve (unit, source) con source en {"evidence", "latch", "assumed"}.
    Ver el comentario de _UNIT_LATCH para el porque del latch."""
    if (seat_map.has_bb_marker(corner_lines)
            or any(seat_map.has_bb_marker(ls) for ls in seat_lines.values())):
        _UNIT_LATCH["value"] = "bb"
        return "bb", "evidence"
    if _chips_style_stack(seat_lines):
        _UNIT_LATCH["value"] = "chips"
        return "chips", "evidence"
    if _UNIT_LATCH["value"] is not None:
        return _UNIT_LATCH["value"], "latch"
    warnings.append("no se pudo determinar si los importes estan en fichas o en BB "
                    "(sin sufijo 'BB' ni stack numerico legible); se asume fichas")
    return "chips", "assumed"


def _plate_occupied(lines):
    """True si la zona del nameplate contiene texto propio de un asiento
    ocupado: un nombre (por palabra suelta, para pillar nombres de dos
    palabras como "david sagunt"), un stack numerico, o un verbo/estado de
    accion ("Igualar"/"Pasar"/"Ausente"/"Poner CP"/"No ir"...). Un asiento
    vacio -sillas granate sobre fondo oscuro- no da ninguno de estos."""
    # Un stack en BIG BLINDS ("36,6 BB") es evidencia de asiento ocupado igual que
    # un entero de fichas, pero NINGUNA de las señales de abajo lo ve:
    # _is_number_candidate("36,6") es falso (exige >=3 digitos o separador de
    # miles) y "BB" no es ni nombre ni numero. Sin esta comprobacion un asiento con
    # stack perfectamente legible cuenta como VACIO, y como las posiciones se
    # asignan por el RECUENTO de ocupados (SEATING_BY_N), perder un asiento
    # desplaza la posicion de TODOS. Medido en vision/samples_bb/sample_bb_1.png:
    # el asiento ML lee ['makeao31', '36,6 BB'] y se juzgaba vacio -su nick lo
    # rechaza la blacklist por subcadena ("make" dentro de "makeao31") y su stack
    # no encaja en NUMBER_RE-, asi que se contaban 4 asientos en vez de 5 y el hero
    # pasaba de HJ a CO: el rango equivocado.
    # Se usa has_bb_amount y no parse_amount_bb porque aqui la pregunta es "¿hay
    # un importe en BB en esta zona?", no "¿cuanto?": parse_amount_bb devuelve
    # None a proposito cuando hay dos importes distintos (ambiguedad), y eso no
    # debe hacer que un asiento claramente ocupado cuente como vacio. Y tampoco
    # has_bb_marker, que acepta un "BB" suelto sin numero: como señal de unidad
    # vale, como señal de ocupacion es ruido de OCR de dos caracteres capaz de
    # dar por ocupado un asiento vacio y desplazar las posiciones de todos.
    if seat_map.has_bb_amount(lines):
        return True
    for ln in lines:
        low = ln["text"].lower()
        if "no ir" in low or "noir" in low:
            return True
        for word in ln["text"].split():
            wl = word.lower().strip(".,;:'\"|")
            if wl in SEAT_STATUS_WORDS:
                return True
            if _is_username_token(word) or _is_number_candidate(word.strip()):
                return True
    return False


def _resolve_zone_cards(bgr, zone_px, batch_results, card_jobs):
    """Resuelve las cartas de una zona (board o hero) usando la deteccion por
    color de color_card_detector y el OCR de rango de color_rank_ocr, ya
    encolado en el batch. card_jobs = [(box, start, end), ...]."""
    cards = []
    unresolved = 0
    for box, start, end in card_jobs:
        crop = bgr[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
        rank = color_rank_ocr.resolve_rank(batch_results[start:end], crop)
        code = card_code(rank, box["suit"])
        if code:
            cards.append(code)
        else:
            unresolved += 1
    return cards, unresolved


def analyze_layout(image_path):
    """Reconocimiento por ZONAS FIJAS (mapa de asientos), el enfoque de
    produccion para el cliente real de PokerStars capturado limpio. Ancla una
    referencia independiente del color (nucleo del tapete por contraste) y lee
    cada elemento en su zona fija: ocupacion + nombre/stack por asiento, cartas
    del hero y board (reutilizando la deteccion de palo por color y el OCR de
    rango del color-deck, ya validados), bote, ciegas (del chat) y boton del
    dealer por ancla-por-asiento -> posiciones por aritmetica horaria. Ademas
    expone "facing" ("bet"/"check"/None) segun los botones de accion del hero.

    Produce el MISMO esquema de GameState que analyze_color_deck() (mas el
    campo "facing") para que decision/engine.py y alpha.py funcionen sin
    cambios."""
    bgr = cv2.imread(image_path)
    state = {
        "image": os.path.basename(image_path),
        "hero_cards": [],
        "board": [],
        "pot": None,
        "blinds": None,
        "players": [],
        "hero_position": None,
        "facing": None,
        "vs_position": None,
        "stack_unit": None,
        "stack_unit_source": None,
        "to_call": None,
        "chat_lines": [],
        "warnings": [],
    }
    if bgr is None:
        state["warnings"].append("no se pudo leer la imagen")
        return state

    ref = seat_map.find_reference(bgr)
    if ref[4]:
        state["warnings"].append("no se detecto el ovalo del tapete por contraste; "
                                 "se usa la posicion tipica dentro del recuadro (fallback)")

    batch = OcrBatch()

    # cartas del hero y del board (deteccion por color dentro de su zona fija).
    # Se detectan ANTES de encolar los nameplates porque el del hero se ancla a
    # la posicion de sus cartas (mas robusto al encuadre que una fraccion fija
    # del ovalo, que caia en el borde inferior de la ventana y cortaba el stack).
    hero_px = seat_map.zone_to_px(ref, seat_map.HERO_CARDS_ZONE, bgr.shape)
    board_px = seat_map.zone_to_px(ref, seat_map.BOARD_ZONE, bgr.shape)
    hero_boxes = sorted(color_card_detector.find_card_boxes(bgr, hero_px), key=lambda b: b["x"])
    board_boxes = sorted(color_card_detector.find_card_boxes(bgr, board_px), key=lambda b: b["x"])
    hero_plate_px = seat_map.hero_plate_from_cards(hero_boxes, bgr.shape)

    # texto por zona (nameplates, bote, chat, botones de accion). El nameplate
    # del hero se ancla a sus cartas (hero_plate_px); si no las hay ese frame
    # (entre manos), cae a la fraccion fija del ovalo.
    seat_tsv = {}
    for name in seat_map.SEATS:
        if name == seat_map.HERO_SEAT and hero_plate_px is not None:
            x0, y0, x1, y1 = hero_plate_px
        else:
            x0, y0, x1, y1 = seat_map.zone_to_px(ref, seat_map.SEATS[name]["plate"], bgr.shape)
        seat_tsv[name] = batch.add_tsv_job(bgr[y0:y1, x0:x1], scale=3)
    # importe apostado por asiento (zona hacia el centro del tapete), para
    # inferir quien subio; se encola para todos y luego se lee solo en los
    # asientos ocupados.
    bet_tsv = {}
    for name in seat_map.SEATS:
        bx = seat_map.zone_to_px(ref, seat_map.SEAT_BET_ZONES[name], bgr.shape)
        bet_tsv[name] = batch.add_tsv_job(bgr[bx[1]:bx[3], bx[0]:bx[2]], scale=3)
    px = seat_map.zone_to_px(ref, seat_map.POT_ZONE, bgr.shape)
    pot_idx = batch.add_tsv_job(bgr[px[1]:px[3], px[0]:px[2]], scale=3)
    # chat y botones de accion en ESPANOL: son las dos unicas zonas con prosa
    # castellana ("Los limites suben: Ciegas 50/100 Ante 15", "Igualar"/"Pasar")
    # y no contienen nicks, asi que el modelo espanol solo aporta aqui. Los
    # nameplates se quedan en ingles a proposito: ahi el espanol destroza los
    # nicks. Ver el docstring de ocr_worker.py para las mediciones.
    px = seat_map.zone_to_px(ref, seat_map.CHAT_ZONE, bgr.shape)
    chat_idx = batch.add_tsv_job(bgr[px[1]:px[3], px[0]:px[2]], scale=2, lang="spa")
    px = seat_map.zone_to_px(ref, seat_map.ACTION_ZONE, bgr.shape)
    action_idx = batch.add_tsv_job(bgr[px[1]:px[3], px[0]:px[2]], scale=2, lang="spa")
    # recuadro de ciegas de la esquina superior derecha (fraccion del frame)
    fh, fw = bgr.shape[0], bgr.shape[1]
    cz = CORNER_BLINDS_ZONE
    corner_idx = batch.add_tsv_job(
        bgr[int(fh * cz[1]):int(fh * cz[3]), int(fw * cz[0]):int(fw * cz[2])],
        scale=CORNER_BLINDS_SCALE)

    # cartas del hero y del board: encolar el OCR de rango (cajas ya detectadas)
    hero_jobs = []
    for b in hero_boxes:
        crop = bgr[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]]
        s, e = color_rank_ocr.add_rank_jobs(batch, crop)
        hero_jobs.append((b, s, e))
    board_jobs = []
    for b in board_boxes:
        crop = bgr[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]]
        s, e = color_rank_ocr.add_rank_jobs(batch, crop)
        board_jobs.append((b, s, e))

    results = batch.run()

    # ocupacion por CONTENIDO del nameplate (texto), no por oscuridad: un
    # asiento vacio muestra las sillas granate sobre fondo casi-negro, tan
    # oscuras como la capsula de un asiento ocupado, asi que la fraccion de
    # pixeles oscuros NO distingue vacio de ocupado (medido sobre
    # samples_layout2/: ~0.5-0.8 en ambos casos, sin separacion). La señal
    # fiable es el texto: un asiento ocupado siempre lo tiene, uno vacio no.
    # El hero es NUESTRO propio asiento (el jugador que observa): se da por
    # ocupado siempre. En caso de bust el cliente lo reemplaza por un dialogo
    # de reentrada; esos pocos frames quedan con un hero fantasma (limitacion
    # conocida) a cambio de no perder el hero en los frames entre manos, en que
    # no tiene cartas y el OCR de su nameplate suele fallar.
    # unidad de los importes (fichas o big blinds), con latch de sesion: ver
    # _UNIT_LATCH / _detect_stack_unit. En modo BB el valor leido YA es la
    # profundidad/apuesta en bb (no hace falta dividir por la ciega).
    seat_lines = {name: parse_tsv_lines(results[seat_tsv[name]]) for name in seat_map.SEATS}
    corner_lines = parse_tsv_lines(results[corner_idx])
    unit, unit_source = _detect_stack_unit(corner_lines, seat_lines, state["warnings"])
    state["stack_unit"] = unit
    state["stack_unit_source"] = unit_source

    occupied = {}
    for name in seat_map.SEATS:
        lines = seat_lines[name]
        n, stk_chips = _seat_plate_name_stack(lines)
        stk = seat_map.parse_amount_bb(lines) if unit == "bb" else stk_chips
        occ = True if name == seat_map.HERO_SEAT else _plate_occupied(lines)
        if occ:
            bet_lines = parse_tsv_lines(results[bet_tsv[name]])
            bet = (seat_map.parse_amount_bb(bet_lines) if unit == "bb"
                   else seat_map.parse_bet_amount(bet_lines))
            occupied[name] = {"name": n, "stack": stk, "bet": bet}

    # boton -> posiciones (orden de reparto horario entre los ocupados)
    button_seat = seat_map.detect_button_seat(bgr, ref)
    positions = {}
    if button_seat is None:
        state["warnings"].append("no se detecto el boton del dealer; sin posiciones")
    else:
        if button_seat not in occupied:
            # el dealer es siempre un jugador sentado: si el boton se detecto en
            # ese asiento pero el OCR no leyo su nameplate, esta ocupado igual.
            occupied[button_seat] = {"name": None, "stack": None, "bet": None}
        order = seat_map.dealing_order(list(occupied), ref)
        n = len(order)
        if n in seat_map.SEATING_BY_N:
            bi = order.index(button_seat)
            rotated = order[bi:] + order[:bi]
            positions = dict(zip(rotated, seat_map.SEATING_BY_N[n]))
        else:
            state["warnings"].append(f"{n} asientos ocupados: fuera del rango con posiciones definidas")

    # quien sigue en la mano (dorso de carta visible). El hero se resuelve por sus
    # propias cartas, que van boca arriba. Es lo que necesita la equity postflop
    # para saber contra cuantos rivales simula.
    en_mano = seat_map.detect_in_hand_seats(bgr, ref)

    for name in seat_map.dealing_order(list(occupied), ref) if occupied else []:
        info = occupied[name]
        es_hero = name == seat_map.HERO_SEAT
        player = {
            "name": info["name"],
            "stack": info["stack"],
            "bet": info.get("bet"),
            "is_hero": es_hero,
            "in_hand": bool(state["hero_cards"]) if es_hero else (name in en_mano),
        }
        if name in positions:
            player["position"] = positions[name]
        state["players"].append(player)

    # un asiento con cartas repartidas pero que no se juzgo ocupado es una
    # contradiccion entre las dos señales (texto del nameplate vs dorso), y
    # significa que el recuento de asientos -y por tanto TODAS las posiciones-
    # puede estar mal
    fantasmas = en_mano - set(occupied)
    if fantasmas:
        state["warnings"].append(
            f"asiento(s) con cartas repartidas pero sin nameplate legible: "
            f"{sorted(fantasmas)}; el recuento de ocupados puede estar mal y con el "
            f"las posiciones")
    if seat_map.HERO_SEAT in positions:
        state["hero_position"] = positions[seat_map.HERO_SEAT]

    # cartas
    state["hero_cards"], hero_unresolved = _resolve_zone_cards(bgr, hero_px, results, hero_jobs)
    state["board"], board_unresolved = _resolve_zone_cards(bgr, board_px, results, board_jobs)
    if hero_unresolved:
        state["warnings"].append(f"{hero_unresolved} carta(s) del hero detectada(s) pero sin rango legible")
    if board_unresolved:
        state["warnings"].append(f"{board_unresolved} carta(s) de board detectada(s) pero sin rango legible")

    # bote, ciegas, facing. Ciegas: primero el recuadro persistente de la
    # esquina (SB/BB(ante), la fuente mas fiable), luego el aviso del chat
    # (transitorio) como respaldo.
    # el bote se lee segun la unidad: en modo BB lleva el sufijo y decimales
    # ("Bote: 3,75 BB"), que find_pot interpretaria como separador de miles
    # (x10/x100). Ver find_pot_bb.
    pot_lines = parse_tsv_lines(results[pot_idx])
    state["pot"] = find_pot_bb(pot_lines) if unit == "bb" else find_pot(pot_lines)
    # Las lineas del chat se EXPONEN en el GameState. Hasta ahora se OCR-eaban
    # dos veces por frame: aqui para las ciegas de respaldo, y otra vez en
    # hand_result.read_chat_lines() para el panel "Mano anterior", con un segundo
    # subproceso y un segundo arranque de tesseract. Medido sobre frames reales,
    # esa segunda pasada costaba 571 ms de un ciclo de 3,9 s (el 15%). Se guardan
    # con posicion (no solo el texto) porque parse_hand_result las necesita para
    # reconstruir el orden de lectura.
    chat_lines = parse_tsv_lines(results[chat_idx])
    state["chat_lines"] = chat_lines
    state["blinds"] = (find_blinds_corner(corner_lines, require_double=False)
                       or find_blinds_chat(chat_lines) or find_blinds(chat_lines))
    action_lines = parse_tsv_lines(results[action_idx])
    state["facing"] = seat_map.parse_facing(" ".join(ln["text"] for ln in action_lines))
    # importe que pide el boton "Igualar": evidencia INDEPENDIENTE de que hay una
    # subida que enfrentar, para poder abstenerse cuando el importe de la mesa no
    # se lee y el motor recomendaria una apertura enfrentando una subida. Solo en
    # modo BB (el boton no lleva sufijo en modo fichas). Ver parse_to_call_bb.
    state["to_call"] = seat_map.parse_to_call_bb(action_lines) if unit == "bb" else None

    # vs_position: quien subio, a partir del importe apostado por asiento. Solo
    # se rellena si el hero enfrenta una apuesta (facing="bet") y hay UNA subida
    # clara; en cualquier otro caso queda None. En modo BB la ciega grande es 1;
    # en modo fichas la detectada. El motor lo recalcula con la ciega efectiva
    # (que en fichas puede venir de blinds.local.json), pero se expone aqui para
    # el HUD/depuracion.
    bb_for_raiser = 1 if unit == "bb" else (state["blinds"]["bb"] if state["blinds"] else None)
    if state["facing"] == "bet":
        vs, _code = seat_map.detect_raiser(state["players"], bb_for_raiser)
        state["vs_position"] = vs

    if not state["hero_cards"]:
        state["warnings"].append("no se detectaron las cartas del hero")
    if not state["pot"]:
        state["warnings"].append("no se encontro texto de pot")
    if not state["blinds"]:
        state["warnings"].append("no se encontraron las ciegas (esquina/chat)")
    if not occupied:
        state["warnings"].append("ningun asiento ocupado detectado")

    return state


def analyze_color_deck(image_path):
    """LEGADO / DIAGNOSTICO, NO APTO PARA EL MOTOR: igual que analyze(), sus
    stacks son enteros de FICHAS y no declara "stack_unit", asi que
    engine.decide() rechaza sus GameState a proposito (ver el guard de
    stack_unit). Produccion es analyze_layout(). Se conserva porque tiene la
    calibracion del mazo de 4 colores contra las 93 capturas de
    samples_pokerstars/.

    Igual que analyze(), pero para el mazo de 4 colores (fondo de color
    solido + rango blanco) del cliente real de PokerStars: usa
    color_card_detector.py (palo por color de fondo, sin plantilla de
    forma) y color_rank_ocr.py (rango grande, mayoria de varias lecturas)
    en vez de card_detector.py/suit_classifier.py/rank_ocr.py. El
    reconocimiento de pot/ciegas/jugadores es identico (texto libre, no
    depende del estilo de mazo) y la forma de GameState es la misma que la
    de analyze(): a Fase 4/5 les da igual que rama de Fase 3 la produjo."""
    bgr = cv2.imread(image_path)
    state = {
        "image": os.path.basename(image_path),
        "hero_cards": [],
        "board": [],
        "pot": None,
        "blinds": None,
        "players": [],
        "warnings": [],
    }
    if bgr is None:
        state["warnings"].append("no se pudo leer la imagen")
        return state

    region = find_table_region(bgr)
    if region is None:
        state["warnings"].append("no se localizo la mesa (borde rojo no detectado); se usa el frame completo")

    boxes = color_card_detector.find_card_boxes(bgr, region)
    hero_boxes, board_boxes, _other_boxes = color_card_detector.classify_boxes(boxes, region, bgr.shape)

    batch = OcrBatch()
    diag = (bgr.shape[0] ** 2 + bgr.shape[1] ** 2) ** 0.5
    tsv_idx_1 = batch.add_tsv_job(bgr, scale=1)
    tsv_idx_2 = batch.add_tsv_job(bgr, scale=2)
    tsv_idx_title = batch.add_tsv_job(bgr[0:int(bgr.shape[0] * TITLE_BAR_HEIGHT_FRAC), :], scale=4)
    tsv_idx_corners = [
        batch.add_tsv_job(bgr[0:int(bgr.shape[0] * fh), int(bgr.shape[1] * fw):], scale=sc)
        for fh, fw, sc in CORNER_BLINDS_CROPS
    ]

    all_card_boxes = hero_boxes + board_boxes
    rank_job_ranges = []
    for b in all_card_boxes:
        crop = bgr[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]]
        start, end = color_rank_ocr.add_rank_jobs(batch, crop)
        rank_job_ranges.append((start, end))

    results = batch.run()

    tsv1, tsv2 = results[tsv_idx_1], results[tsv_idx_2]
    lines1 = parse_tsv_lines(tsv1)
    lines2 = [{**ln, "left": ln["left"] // 2, "top": ln["top"] // 2, "right": ln["right"] // 2,
               "bottom": ln["bottom"] // 2, "cx": ln["cx"] / 2, "cy": ln["cy"] / 2} for ln in parse_tsv_lines(tsv2)]
    lines = merge_line_sets(lines1, lines2)
    title_lines = parse_tsv_lines(results[tsv_idx_title])
    corner_lines = [parse_tsv_lines(results[idx]) for idx in tsv_idx_corners]

    state["pot"] = find_pot(lines)
    state["blinds"] = (find_blinds_corner(*corner_lines, lines1, lines2)
                        or find_blinds(lines) or find_blinds(title_lines))

    hero_ref_box = hero_boxes[0] if hero_boxes else None
    players = find_players(lines, diag, hero_ref_box)
    players = _assign_player_positions(bgr, region, players, diag, state["warnings"])
    state["players"] = [_player_out(p) for p in players]
    _set_hero_position(state)

    resolved = []
    for b, (start, end) in zip(all_card_boxes, rank_job_ranges):
        crop = bgr[b["y"]:b["y"] + b["h"], b["x"]:b["x"] + b["w"]]
        rank = color_rank_ocr.resolve_rank(results[start:end], crop)
        code = card_code(rank, b["suit"])
        resolved.append({"box": b, "rank": rank, "suit": b["suit"], "code": code})

    n_hero = len(hero_boxes)
    hero_resolved = resolved[:n_hero]
    board_resolved = resolved[n_hero:]

    for r in hero_resolved:
        if r["code"]:
            state["hero_cards"].append(r["code"])
        else:
            state["warnings"].append(
                f"carta del hero detectada en {r['box']} pero no se pudo leer con confianza "
                f"(rank={r['rank']}, suit={r['suit']})")

    for r in board_resolved:
        if r["code"]:
            state["board"].append(r["code"])
        else:
            state["warnings"].append(
                f"carta de board detectada en {r['box']} pero no se pudo leer con confianza "
                f"(rank={r['rank']}, suit={r['suit']})")

    if not state["pot"]:
        state["warnings"].append("no se encontro texto de pot")
    if not state["blinds"]:
        state["warnings"].append("no se encontraron las ciegas")
    if not state["players"]:
        state["warnings"].append("no se emparejo ningun jugador (nombre+stack)")

    return state
