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


def _plate_occupied(lines):
    """True si la zona del nameplate contiene texto propio de un asiento
    ocupado: un nombre (por palabra suelta, para pillar nombres de dos
    palabras como "david sagunt"), un stack numerico, o un verbo/estado de
    accion ("Igualar"/"Pasar"/"Ausente"/"Poner CP"/"No ir"...). Un asiento
    vacio -sillas granate sobre fondo oscuro- no da ninguno de estos."""
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
        rank = color_rank_ocr.resolve_rank(batch_results[start:end])
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
    px = seat_map.zone_to_px(ref, seat_map.POT_ZONE, bgr.shape)
    pot_idx = batch.add_tsv_job(bgr[px[1]:px[3], px[0]:px[2]], scale=3)
    px = seat_map.zone_to_px(ref, seat_map.CHAT_ZONE, bgr.shape)
    chat_idx = batch.add_tsv_job(bgr[px[1]:px[3], px[0]:px[2]], scale=2)
    px = seat_map.zone_to_px(ref, seat_map.ACTION_ZONE, bgr.shape)
    action_idx = batch.add_tsv_job(bgr[px[1]:px[3], px[0]:px[2]], scale=2)

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
    occupied = {}
    for name in seat_map.SEATS:
        lines = parse_tsv_lines(results[seat_tsv[name]])
        n, stk = _seat_plate_name_stack(lines)
        occ = True if name == seat_map.HERO_SEAT else _plate_occupied(lines)
        if occ:
            occupied[name] = {"name": n, "stack": stk}

    # boton -> posiciones (orden de reparto horario entre los ocupados)
    button_seat = seat_map.detect_button_seat(bgr, ref)
    positions = {}
    if button_seat is None:
        state["warnings"].append("no se detecto el boton del dealer; sin posiciones")
    else:
        if button_seat not in occupied:
            # el dealer es siempre un jugador sentado: si el boton se detecto en
            # ese asiento pero el OCR no leyo su nameplate, esta ocupado igual.
            occupied[button_seat] = {"name": None, "stack": None}
        order = seat_map.dealing_order(list(occupied), ref)
        n = len(order)
        if n in seat_map.SEATING_BY_N:
            bi = order.index(button_seat)
            rotated = order[bi:] + order[:bi]
            positions = dict(zip(rotated, seat_map.SEATING_BY_N[n]))
        else:
            state["warnings"].append(f"{n} asientos ocupados: fuera del rango con posiciones definidas")

    for name in seat_map.dealing_order(list(occupied), ref) if occupied else []:
        info = occupied[name]
        player = {
            "name": info["name"],
            "stack": info["stack"],
            "is_hero": name == seat_map.HERO_SEAT,
        }
        if name in positions:
            player["position"] = positions[name]
        state["players"].append(player)
    if seat_map.HERO_SEAT in positions:
        state["hero_position"] = positions[seat_map.HERO_SEAT]

    # cartas
    state["hero_cards"], hero_unresolved = _resolve_zone_cards(bgr, hero_px, results, hero_jobs)
    state["board"], board_unresolved = _resolve_zone_cards(bgr, board_px, results, board_jobs)
    if hero_unresolved:
        state["warnings"].append(f"{hero_unresolved} carta(s) del hero detectada(s) pero sin rango legible")
    if board_unresolved:
        state["warnings"].append(f"{board_unresolved} carta(s) de board detectada(s) pero sin rango legible")

    # bote, ciegas (del chat), facing
    state["pot"] = find_pot(parse_tsv_lines(results[pot_idx]))
    chat_lines = parse_tsv_lines(results[chat_idx])
    state["blinds"] = find_blinds_chat(chat_lines) or find_blinds(chat_lines)
    state["facing"] = seat_map.parse_facing(" ".join(ln["text"] for ln in parse_tsv_lines(results[action_idx])))

    if not state["hero_cards"]:
        state["warnings"].append("no se detectaron las cartas del hero")
    if not state["pot"]:
        state["warnings"].append("no se encontro texto de pot")
    if not state["blinds"]:
        state["warnings"].append("no se encontraron las ciegas (chat)")
    if not occupied:
        state["warnings"].append("ningun asiento ocupado detectado")

    return state


def analyze_color_deck(image_path):
    """Igual que analyze(), pero para el mazo de 4 colores (fondo de color
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
        rank = color_rank_ocr.resolve_rank(results[start:end])
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
