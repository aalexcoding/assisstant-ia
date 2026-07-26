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
                          find_blinds, find_blinds_corner, find_players, find_pot,
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

# RETIRADO EN EL PASO A BB-ONLY: el recuadro de ciegas de la esquina superior
# derecha (CORNER_BLINDS_ZONE = (0.55, 0.0, 1.0, 0.17), escala x4). Leia las
# ciegas en formato SB/BB(ante) -"250/500(80)", "17,5K/35K(4,5K)"- y era la
# fuente automatica mas fiable que habia, porque es PERSISTENTE (el aviso del
# chat solo sale unos segundos al subir de nivel).
#
# Ya no hace falta: con el cliente configurado en BIG BLINDS el stack leido YA
# ES la profundidad en bb, asi que no hay nada que dividir y las ciegas dejan de
# ser un dato necesario. Quitarlo ahorra un job de OCR por frame.
#
# Se conserva la medicion por si alguna vez se vuelve: el recuadro esta anclado
# a la esquina de la VENTANA, no al ovalo del tapete, asi que iba en fracciones
# del FRAME (como TITLE_BAR_HEIGHT_FRAC) y no como zona del mapa de asientos.
# analyze_color_deck() sigue usando CORNER_BLINDS_CROPS, que es su equivalente.


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
    """De las lineas OCR de un nameplate, devuelve (name, stack, action).

    EL VERBO NO ES UN NOMBRE. Cuando un jugador actua, el cliente le SUSTITUYE el
    nick por lo que ha hecho ("Pasar", "Igualar", "Apostar", "Subir"), asi que
    leerlo como nombre hace que el jugador cambie de nombre justo en el momento
    en que hace algo -que es cuando mas falta hace saber quien es-. Medido sobre
    una sesion real: 362 de 6264 nombres leidos (6%) eran un verbo, con "Pasar"
    (153), "Igualar" (123), "Apostar" (50) y "Subir" (34) a la cabeza.

    Asi que el verbo se devuelve APARTE, como `action`. Ademas de dejar de
    ensuciar el nombre, es informacion util que hasta ahora se tiraba: dice QUE
    hizo ese asiento, que es justo lo que falta para reconstruir el historial de
    la mano (ver docs §2.2)."""
    name = None
    stack = None
    action = None
    for ln in lines:
        texto = ln["text"].strip()
        # el verbo puede venir SOLO ("All-in") o ACOMPAÑADO ("All-in 12,3 BB"),
        # segun lo que el OCR pegue en la misma linea. Se mira la linea entera y
        # tambien palabra a palabra: comprobando solo la linea, un "All-in 12,3
        # BB" se colaba como si fuera el nick del jugador.
        verbo = texto if es_verbo_de_accion(texto) else next(
            (w for w in texto.split() if es_verbo_de_accion(w)), None)
        if verbo is not None:
            if action is None:
                action = verbo
            continue                      # esta linea no es el nombre
        if name is None and _is_name_candidate(texto):
            name = _clean_name(texto)
        if stack is None and _is_number_candidate(texto):
            stack = _to_int(texto)
    return name, stack, action


# verbos/estados que el cliente pone en el nameplate en lugar del nombre cuando
# el jugador acaba de actuar o esta sentado sin nombre visible; su presencia
# implica que el asiento esta OCUPADO aunque no se lea nombre ni stack.
SEAT_STATUS_WORDS = {
    "igualar", "iguala", "pasar", "pasa", "apostar", "apuesta", "subir", "sube",
    "resubir", "poner", "ausente", "ante", "allin", "paga", "espera", "sentado",
    "noir",          # "No ir" (fold), que el cliente escribe en dos palabras
}


# --- LA APP ES BB-ONLY: por que se retiro la deteccion de unidad ---
#
# El cliente puede mostrar los importes en FICHAS (enteros con separador de
# miles, "5.892") o en BIG BLINDS ("123,4 BB", coma decimal + sufijo BB) segun la
# config del usuario. Se intento DETECTARLO frame a frame y no funciono: el
# sufijo "BB" no siempre se OCR-ea (entre manos los nameplates se leen mal) y
# asumir "chips" por defecto es una adivinanza silenciosa. Medido sobre una
# sesion real de 34 min, la unidad detectada oscilaba DENTRO de la misma sesion
# (bbx30, chipsx17, bbx24, chipsx37) aunque la config del cliente no habia
# cambiado. Se añadio un latch de sesion, que lo mitigaba pero no lo resolvia.
#
# El fallo que esto puede producir es el peor posible en esta app: si la mesa
# estaba en modo BB y se lee como fichas, el motor divide una profundidad YA
# expresada en bb por la ciega grande y sale una profundidad absurda -o al reves,
# un stack de 3955 fichas leido como 3955bb-. En los dos casos, una recomendacion
# con conviccion y falsa, que es mucho peor que abstenerse.
#
# La salida no es detectar mejor, es NO TENER QUE DETECTAR: se pide configurar el
# cliente en big blinds y punto. Entonces el stack leido YA ES la profundidad en
# bb, no hacen falta ciegas (ni detectadas ni manuales), y una subida es
# simplemente cualquier importe > 1.
#
# LA GARANTIA DE SEGURIDAD del diseño es que parse_amount_bb EXIGE el sufijo "BB"
# literal. Si el cliente no esta en modo BB, no se lee stack -> el motor se
# abstiene por falta de profundidad. Nunca lee mal. Por eso el parseo no se puede
# aflojar a "el mayor entero de la zona": eso leeria la denominacion impresa en
# una ficha (25, 100) como un importe.
#
# Las rutas de diagnostico analyze() y analyze_color_deck() siguen produciendo
# FICHAS y siguen sin declarar stack_unit; engine.decide() las rechaza a
# proposito (ver su guard).


def es_verbo_de_accion(texto):
    """True si el texto es lo que el cliente pone EN VEZ del nick cuando ese
    asiento acaba de actuar. Se normaliza quitando puntuacion, guiones y espacios
    porque el cliente escribe "All-in" y "No ir" con separadores que el OCR ademas
    cambia a capricho; sin eso, "All-in" se colaba como si fuera un nombre."""
    limpio = "".join(c for c in texto.lower() if c.isalnum())
    return bool(limpio) and limpio in SEAT_STATUS_WORDS


def _plate_occupied(lines):
    """True si la zona del nameplate contiene texto propio de un asiento
    ocupado: un importe en BB, un nombre (por palabra suelta, para pillar
    nombres de dos palabras como "david sagunt"), o un verbo/estado de accion
    ("Igualar"/"Pasar"/"Ausente"/"Poner CP"/"No ir"...). Un asiento vacio
    -sillas granate sobre fondo oscuro- no da ninguno de estos.

    ESTA FUNCION DECIDE LAS POSICIONES DE TODOS. El recuento de ocupados es lo
    que elige la fila de SEATING_BY_N, asi que un asiento de mas o de menos
    desplaza la posicion de TODOS los jugadores y con ella el rango. Es la via
    mas directa que hay a una recomendacion convincente y equivocada, de ahi que
    cada señal tenga que ser evidencia de verdad y no "algo que parece texto".

    Se usa has_bb_amount y no parse_amount_bb porque aqui la pregunta es "¿hay un
    importe en BB en esta zona?", no "¿cuanto?": parse_amount_bb devuelve None a
    proposito cuando hay dos importes distintos (ambiguedad), y eso no debe hacer
    que un asiento claramente ocupado cuente como vacio. El caso que lo motivo
    (vision/samples_bb/sample_bb_1.png): el asiento ML lee ['makeao31', '36,6 BB']
    y se juzgaba VACIO -su nick lo rechaza la blacklist por subcadena ("make"
    dentro de "makeao31") y su stack no encajaba en ninguna señal-, asi que se
    contaban 4 asientos en vez de 5 y el hero pasaba de HJ a CO.

    RETIRADO: "un entero suelto tambien vale como stack" (_is_number_candidate).
    Era de la epoca en que los importes podian estar en FICHAS; con la app ya
    BB-only un entero desnudo no es un stack, porque los stacks llevan el sufijo
    BB y los coge has_bb_amount aqui arriba. Y era un falso positivo grave: la
    TEXTURA DE PUNTOS DEL TAPETE se OCR-ea como un numero. Medido sobre una
    sesion real de un torneo 3-Max, la zona del asiento MR -tapete vacio, ni un
    caracter de verdad- leia '60668' en los 60 frames muestreados y contaba como
    ocupado, asi que la app veia 4 jugadores en el 34% de los frames y llego a
    asignarle al hero la posicion CO, que en una mesa de 3 NO EXISTE."""
    if seat_map.has_bb_amount(lines):
        return True
    for ln in lines:
        if es_verbo_de_accion(ln["text"]):
            return True
        for word in ln["text"].split():
            if es_verbo_de_accion(word) or _is_username_token(word):
                return True
    return False


def _fuerza_ocupacion(seat, info, en_mano, button_seat):
    """Cuanta confianza hay en que ese asiento este ocupado de verdad. Solo se usa
    para decidir cual soltar cuando se detectan mas asientos de los que caben en
    la mesa; el orden va de la evidencia mas dura a la mas blanda."""
    if seat == seat_map.HERO_SEAT or seat == button_seat:
        return 4          # el hero somos nosotros; el dealer es un jugador sentado
    if seat in en_mano:
        return 3          # dorso de carta: la señal mejor medida que hay (13,6x)
    if info.get("stack") is not None:
        return 3          # un importe con sufijo BB no lo produce el tapete
    if info.get("name"):
        return 2
    return 1              # solo un verbo de accion, o texto que parecia un nick


def _encolar_cartas(batch, bgr, boxes):
    """Encola el OCR de rango de cada carta, SALTANDOSE las que ya estan en la
    cache de color_rank_ocr (ver alli el porque y la medicion). Devuelve
    [(box, start, end, rango_cacheado), ...]; con rango_cacheado != NO_CACHE no
    se ha encolado nada."""
    jobs = []
    for box in boxes:
        crop = bgr[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
        key = color_rank_ocr.cache_key(crop, box["suit"])
        hay, rango = color_rank_ocr.cached_rank(key)
        if hay:
            jobs.append((box, None, None, rango))
        else:
            start, end = color_rank_ocr.add_rank_jobs(batch, crop)
            jobs.append((box, start, end, _SIN_CACHE))
    return jobs


_SIN_CACHE = object()


def _resolve_zone_cards(bgr, zone_px, batch_results, card_jobs):
    """Resuelve las cartas de una zona (board o hero) usando la deteccion por
    color de color_card_detector y el OCR de rango de color_rank_ocr.
    card_jobs = [(box, start, end, rango_cacheado), ...] de _encolar_cartas."""
    cards = []
    unresolved = 0
    for box, start, end, cacheado in card_jobs:
        if cacheado is not _SIN_CACHE:
            rank = cacheado
        else:
            crop = bgr[box["y"]:box["y"] + box["h"], box["x"]:box["x"] + box["w"]]
            rank = color_rank_ocr.resolve_rank(batch_results[start:end], crop)
            color_rank_ocr.store_rank(color_rank_ocr.cache_key(crop, box["suit"]), rank)
        code = card_code(rank, box["suit"])
        if code:
            cards.append(code)
        else:
            unresolved += 1
    return cards, unresolved


def analyze_layout(image_path, max_players=None):
    """Reconocimiento por ZONAS FIJAS (mapa de asientos), el enfoque de
    produccion para el cliente real de PokerStars capturado limpio. Ancla una
    referencia independiente del color (nucleo del tapete por contraste) y lee
    cada elemento en su zona fija: ocupacion + nombre/stack por asiento, cartas
    del hero y board (reutilizando la deteccion de palo por color y el OCR de
    rango del color-deck, ya validados), bote y boton del dealer por
    ancla-por-asiento -> posiciones por aritmetica horaria. Ademas expone
    "facing" ("bet"/"check"/None) segun los botones de accion del hero.

    max_players: cuantos jugadores caben en la mesa (3 en un 3-Max, 6 en un
    6-Max...). Opcional pero MUY recomendable, porque las posiciones se derivan
    del RECUENTO de asientos ocupados y un asiento fantasma las desplaza todas.
    Con este dato, detectar de mas es una contradiccion demostrable y se puede
    corregir o, si no esta claro cual sobra, callarse.

    TODOS LOS IMPORTES EN BIG BLINDS. Requiere el cliente de PokerStars
    configurado para mostrarlos asi; si no lo esta, no se leen y la app se
    abstiene (ver el bloque "LA APP ES BB-ONLY" mas arriba). Por eso ya no hay
    campo "blinds": con los stacks en bb, el nivel de ciegas no hace falta para
    nada. Las rutas de diagnostico analyze()/analyze_color_deck() si lo tienen,
    porque sus importes estan en fichas."""
    bgr = cv2.imread(image_path)
    state = {
        "image": os.path.basename(image_path),
        "hero_cards": [],
        "board": [],
        "pot": None,
        "players": [],
        "hero_position": None,
        "facing": None,
        "vs_position": None,
        # literal, no detectado: la app es BB-only (ver el bloque de arriba).
        # Lo declara para que engine.decide() pueda RECHAZAR los GameState de las
        # rutas de diagnostico, cuyos importes estan en fichas.
        "stack_unit": "bb",
        "to_call": None,
        "chat_lines": [],
        "warnings": [],
    }
    if bgr is None:
        state["warnings"].append("no se pudo leer la imagen")
        return state

    # SIN REFERENCIA NO SE ANALIZA NADA. Todas las zonas (nameplates, cartas,
    # bote, botones, chat) son fracciones del nucleo del tapete, asi que si el
    # ovalo no se detecta y se cae al fallback, TODAS quedan desplazadas y lo que
    # salga son lecturas de sitios equivocados: el peor tipo de salida, porque
    # parece un resultado.
    #
    # Antes se seguia adelante con el fallback. Medido sobre 999 frames de una
    # sesion real: de los 21 que cayeron en fallback, CERO dieron cartas del hero,
    # cero el boton del dealer, cero posicion, cero stack y cero recomendaciones
    # (frente a 52%/95%/95%/48%/26% en los 978 con ovalo detectado). O sea que el
    # fallback no aporta ni un frame util, y cortar aqui ademas ahorra ~1,1 s de
    # OCR por frame.
    #
    # La causa tipica es el TEMA DEL TAPETE: find_reference busca pixeles
    # saturados y con brillo (S>=45, V>=60), asi que un tapete verde (S=200,
    # V=115) se detecta en el 98% de los frames y uno gris oscuro (S=0, V=34) en
    # el 0%. Por eso el aviso nombra las dos cosas que el usuario puede arreglar.
    ref = seat_map.find_reference(bgr)
    if ref[4]:
        state["warnings"].append(
            "no se encuentra la mesa: no se detecto el ovalo del tapete. Sin esa "
            "referencia TODAS las zonas quedan desplazadas, asi que no se analiza el "
            "frame en vez de dar lecturas de sitios equivocados. Dos causas tipicas: "
            "el tapete es de un tema OSCURO o gris (hace falta uno con color, p.ej. "
            "el verde) o el recuadro de captura no encuadra la mesa (recalibra)")
        return state

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

    # cartas del hero y del board: encolar el OCR de rango (cajas ya detectadas)
    hero_jobs = _encolar_cartas(batch, bgr, hero_boxes)
    board_jobs = _encolar_cartas(batch, bgr, board_boxes)

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
    # Los importes se leen SIEMPRE en big blinds: parse_amount_bb exige el sufijo
    # "BB" literal, asi que si el cliente no esta en ese modo no se lee nada y el
    # motor se abstiene. Nunca lee un numero en la unidad equivocada.
    seat_lines = {name: parse_tsv_lines(results[seat_tsv[name]]) for name in seat_map.SEATS}

    occupied = {}
    for name in seat_map.SEATS:
        lines = seat_lines[name]
        n, _stk_chips, accion = _seat_plate_name_stack(lines)
        stk = seat_map.parse_amount_bb(lines)
        occ = True if name == seat_map.HERO_SEAT else _plate_occupied(lines)
        if occ:
            bet_lines = parse_tsv_lines(results[bet_tsv[name]])
            occupied[name] = {"name": n, "stack": stk, "action": accion,
                              "bet": seat_map.parse_amount_bb(bet_lines)}

    # quien sigue en la mano (dorso de carta visible). Se resuelve AQUI, antes de
    # cerrar la ocupacion, porque un dorso es la evidencia mas fuerte que hay de
    # que un asiento esta ocupado (medido: separacion 13,6x sobre 705
    # observaciones) y sirve para desempatar si sobran asientos.
    en_mano = seat_map.detect_in_hand_seats(bgr, ref)

    button_seat = seat_map.detect_button_seat(bgr, ref)
    if button_seat is not None and button_seat not in occupied:
        # el dealer es siempre un jugador sentado: si el boton se detecto en ese
        # asiento pero el OCR no leyo su nameplate, esta ocupado igual.
        occupied[button_seat] = {"name": None, "stack": None, "bet": None, "action": None}

    # TAMAÑO DE MESA. Si el usuario dice cuantos jugadores caben (3-max, 6-max...)
    # y se detectan MAS asientos ocupados, sobra alguno: es una contradiccion
    # demostrable, no una sospecha. Y es cara, porque las posiciones salen del
    # RECUENTO de ocupados, asi que un asiento de mas las desplaza TODAS.
    # Se sueltan los mas debiles, y solo si el corte es inequivoco: si el ultimo
    # que se soltaria tiene la misma evidencia que el primero que se queda, no
    # hay forma de elegir sin adivinar y se prefiere no dar posiciones.
    exceso = None
    if max_players and len(occupied) > max_players:
        fuerza = {s: _fuerza_ocupacion(s, occupied[s], en_mano, button_seat)
                  for s in occupied}
        orden = sorted(occupied, key=lambda s: (fuerza[s], s))
        sobran = len(occupied) - max_players
        if fuerza[orden[sobran - 1]] < fuerza[orden[sobran]]:
            soltados = orden[:sobran]
            for s in soltados:
                del occupied[s]
            state["warnings"].append(
                f"se detectaron {len(soltados) + max_players} asientos ocupados en una mesa "
                f"de {max_players}: se descarta(n) {sorted(soltados)} por ser la lectura mas "
                f"debil (sin cartas, sin importe en BB y sin nombre)")
        else:
            exceso = len(occupied)
            state["warnings"].append(
                f"se detectaron {len(occupied)} asientos ocupados en una mesa de "
                f"{max_players} y no se puede saber cual sobra: sin posiciones, porque "
                f"un asiento de mas las desplaza todas")

    # boton -> posiciones (orden de reparto horario entre los ocupados)
    positions = {}
    if exceso is not None:
        pass                                   # ya avisado arriba
    elif button_seat is None:
        state["warnings"].append("no se detecto el boton del dealer; sin posiciones")
    else:
        order = seat_map.dealing_order(list(occupied), ref)
        n = len(order)
        if n in seat_map.SEATING_BY_N:
            bi = order.index(button_seat)
            rotated = order[bi:] + order[:bi]
            positions = dict(zip(rotated, seat_map.SEATING_BY_N[n]))
        else:
            state["warnings"].append(f"{n} asientos ocupados: fuera del rango con posiciones definidas")

    # Las cartas se resuelven AQUI, ANTES de construir la lista de jugadores,
    # porque el in_hand del hero depende de ellas. Estaban despues, asi que al
    # construir los jugadores state["hero_cards"] todavia era [] y el hero salia
    # SIEMPRE con in_hand=False: 883 de 883 registros en las sesiones grabadas,
    # incluidos los 484 frames en que si tenia cartas.
    state["hero_cards"], hero_unresolved = _resolve_zone_cards(bgr, hero_px, results, hero_jobs)
    state["board"], board_unresolved = _resolve_zone_cards(bgr, board_px, results, board_jobs)
    if hero_unresolved:
        state["warnings"].append(f"{hero_unresolved} carta(s) del hero detectada(s) pero sin rango legible")
    if board_unresolved:
        state["warnings"].append(f"{board_unresolved} carta(s) de board detectada(s) pero sin rango legible")

    for name in seat_map.dealing_order(list(occupied), ref) if occupied else []:
        info = occupied[name]
        es_hero = name == seat_map.HERO_SEAT
        player = {
            # El ASIENTO ("UL", "MR"...) es la unica clave ESTABLE de un jugador
            # entre frames: la posicion rota en cada mano, el nombre lo lee el OCR
            # (y el cliente lo sustituye por el verbo de la accion justo cuando el
            # jugador actua, que es el peor momento para perderle la pista) y el
            # stack es justo lo que se quiere seguir. Sin esto no se puede
            # comparar el stack de un jugador entre dos frames, que es de lo que
            # sale lo que ha apostado (ver decision/hand_tracker.py).
            "seat": name,
            "name": info["name"],
            # lo que el cliente muestra en vez del nick cuando este asiento acaba
            # de actuar ("Pasar", "Igualar", "Subir"...). Ver _seat_plate_name_stack.
            "action": info.get("action"),
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

    # el bote lleva sufijo y decimales ("Bote: 3,75 BB"), que find_pot
    # interpretaria como separador de miles (x10/x100). Ver find_pot_bb.
    pot_lines = parse_tsv_lines(results[pot_idx])
    state["pot"] = find_pot_bb(pot_lines)
    # Las lineas del chat se EXPONEN en el GameState, y ahora son la unica razon
    # por la que se OCR-ea esa zona: alimentan el panel "Mano anterior" y, sobre
    # todo, el NUMERO DE MANO, que es la señal de frontera mas fiable que tiene
    # el rastreador (decision/hand_tracker.py). Antes se OCR-eaba dos veces por
    # frame -aqui para las ciegas y otra vez en hand_result.read_chat_lines()-,
    # con un segundo subproceso y un segundo arranque de tesseract: 571 ms de un
    # ciclo de 3,9 s. Se guardan con posicion (no solo el texto) porque
    # parse_hand_result las necesita para reconstruir el orden de lectura.
    state["chat_lines"] = parse_tsv_lines(results[chat_idx])
    action_lines = parse_tsv_lines(results[action_idx])
    state["facing"] = seat_map.parse_facing(" ".join(ln["text"] for ln in action_lines))
    # importe que pide el boton "Igualar": evidencia INDEPENDIENTE de que hay una
    # subida que enfrentar. Sirve para dos cosas: abstenerse cuando nadie la
    # explica, y autorizar al rastreador a ATRIBUIRLA por la bajada de stack.
    # Ver parse_to_call_bb y hand_tracker.atribuir_subida.
    state["to_call"] = seat_map.parse_to_call_bb(action_lines)

    # vs_position: quien subio, a partir del importe apostado por asiento. Solo
    # se rellena si el hero enfrenta una apuesta (facing="bet") y hay UNA subida
    # clara; en cualquier otro caso queda None. La ciega grande es 1 por
    # definicion (los importes estan en big blinds). El motor lo recalcula por su
    # cuenta, pero se expone aqui para el HUD y para depurar.
    if state["facing"] == "bet":
        vs, _code = seat_map.detect_raiser(state["players"], 1)
        state["vs_position"] = vs

    if not state["hero_cards"]:
        state["warnings"].append("no se detectaron las cartas del hero")
    if not state["pot"]:
        state["warnings"].append("no se encontro texto de pot")
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
