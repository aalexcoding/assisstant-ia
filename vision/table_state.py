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
from card_detector import classify_boxes, find_card_boxes
from ocr_client import OcrBatch
from rank_ocr import card_code, normalize_rank, rank_crop_variants
from suit_classifier import classify_suit
from table_region import find_table_region
from text_extract import find_blinds, find_players, find_pot, merge_line_sets, parse_tsv_lines

# la barra de titulo de la ventana (nombre de mesa, ciegas, torneo) queda
# fuera del ovalo de la mesa y su fuente es demasiado fina para el OCR a
# tamaño completo de frame; una pasada aparte solo de esa franja, a mayor
# escala, resuelve las ciegas donde la pasada normal no llega. Fraccion de
# alto en vez de pixeles fijos: es la franja superior de la ventana
# capturada, no una coordenada de la mesa.
TITLE_BAR_HEIGHT_FRAC = 0.06


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

    state["pot"] = find_pot(lines)
    state["blinds"] = find_blinds(lines) or find_blinds(title_lines)

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

    state["pot"] = find_pot(lines)
    state["blinds"] = find_blinds(lines) or find_blinds(title_lines)

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
