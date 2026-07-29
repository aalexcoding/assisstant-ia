"""
Regresion de los bugs de la Fase 0 (los que se arreglaron antes de pasar la app a
BB-only) y de los endurecidos que vinieron despues.

Cada bloque documenta el fallo REAL que cubria, con el dato medido que lo
destapo, para que si alguien revierte el arreglo el test diga exactamente que se
rompe y por que importaba.
"""
import json
import os

import pytest

from decision import engine
from decision import hand_strength as hs
from vision import seat_map
from vision.seat_map import detect_raiser, parse_amount_bb
from vision.table_state import _plate_occupied
from vision.text_extract import find_pot, find_pot_bb


def L(text):
    """Una linea OCR con la forma que devuelve parse_tsv_lines."""
    return {"text": text, "cx": 0, "cy": 0, "left": 0, "top": 0, "right": 10, "bottom": 10}


def P(position, bet, hero=False):
    return {"position": position, "bet": bet, "is_hero": hero}


# --- 0.1 parse_amount_bb: separador decimal y tope de digitos ----------------
# El OCR lee la coma decimal como punto. Antes '57.2 BB' devolvia 2: un hero a
# 57bb se leia a 2bb -> tabla de 4bb -> "OPEN RAISE ALL IN". Fallo MUDO, del tipo
# que produce una recomendacion plausible y falsa.

@pytest.mark.parametrize("texto, esperado", [
    ("57,2 BB", 57.2),
    ("57.2 BB", 57.2),          # el OCR lee la coma como punto
    ("1234,5 BB", 1234.5),      # cuatro digitos no se truncan
    ("123,45 BB", 123.45),
    ("89 BB", 89.0),
    ("Bote: 3,75 BB", 3.75),
    ("0,31 € 2,5 BB", 2.5),     # ignora la marca de bounty
])
def test_parse_amount_bb(texto, esperado):
    assert parse_amount_bb([L(texto)]) == esperado


@pytest.mark.parametrize("texto", ["1.900 BB", "12.500 BB"])
def test_el_separador_de_miles_no_casa(texto):
    """En modo BB no existe: es OCR corrupto de un importe en fichas, y aceptarlo
    reintroduciria un error de 1000x."""
    assert parse_amount_bb([L(texto)]) is None


# --- 0.2 BB-ante: la apuesta de la BB no es prueba de subida -----------------
# Con BB-ante (casi todos los torneos modernos) bet_BB = 1+ante > bb, asi que se
# detectaba a la BB como raiser y se buscaba threebet_call[stack][hero]["BB"],
# que NO EXISTE para ningun hero: la BB habla ULTIMA preflop, asi que nunca es el
# agresor al que uno defiende. Resultado: abstencion en TODAS las manos.

BB_ANTE = [P("BB", 2.0), P("SB", 0.5), P("CO", None, hero=True)]
CON_APERTURA = [P("BB", 2.0), P("SB", 0.5), P("CO", 2.5), P("BTN", None, hero=True)]


@pytest.mark.parametrize("desc, jugadores, esperado", [
    ("BB con ante no es una subida", BB_ANTE, (None, "no_raise")),
    ("con BB-ante se sigue viendo la apertura ajena", CON_APERTURA, ("CO", "single")),
    ("la BB subiendo de verdad (el hero limpeo y la BB ataca)",
     [P("BB", 4.0), P("SB", 1.0, hero=True)], (None, "bb_raised")),
    ("sin ante, BB=1.0", [P("BB", 1.0), P("SB", 0.5), P("CO", None, hero=True)],
     (None, "no_raise")),
    ("multiway", [P("BB", 1.0), P("HJ", 2.0), P("CO", 2.0), P("BTN", None, hero=True)],
     (None, "multiway")),
    ("hero_raised", [P("BB", 1.0), P("CO", 3.0, hero=True), P("BTN", 6.0)],
     (None, "hero_raised")),
])
def test_detect_raiser(desc, jugadores, esperado):
    assert detect_raiser(jugadores, 1.0) == esperado, desc


@pytest.mark.parametrize("jugadores", [BB_ANTE, CON_APERTURA])
def test_el_gemelo_del_motor_coincide_con_el_de_vision(jugadores):
    """Hay dos implementaciones de detect_raiser y tienen que decir lo mismo."""
    assert engine._detect_raiser(jugadores, 1.0) == detect_raiser(jugadores, 1.0)


def test_bb_raised_tiene_motivo_de_abstencion():
    assert "bb_raised" in engine._RAISE_ABSTAIN


# --- 0.3 la ocupacion era ciega a los nameplates en BB -----------------------
# _is_number_candidate("36,6") es falso y "BB" no es ni nombre ni numero, asi que
# un asiento con stack perfectamente legible contaba como VACIO. Y como las
# posiciones se asignan por el RECUENTO de ocupados, perder un asiento desplaza
# la posicion de TODOS. Medido en samples_bb/sample_bb_1.png: el asiento ML lee
# ['makeao31','36,6 BB'] y se juzgaba vacio -su nick lo rechaza la blacklist por
# subcadena ("make" dentro de "makeao31")-, con lo que se contaban 4 asientos en
# vez de 5 y el hero pasaba de HJ a CO.

def test_un_stack_en_bb_marca_el_asiento_como_ocupado():
    assert _plate_occupied([L("36,6 BB")]) is True


def test_el_caso_real_completo_nick_que_la_blacklist_mata_mas_stack():
    assert _plate_occupied([L("makeao31"), L("36,6 BB")]) is True


def test_un_asiento_vacio_sigue_vacio():
    assert _plate_occupied([L("* * *"), L("~—")]) is False


@pytest.mark.parametrize("texto", ["5.892", "60668"])
def test_un_entero_suelto_no_marca_ocupado(texto):
    """Lo hacia cuando los importes podian estar en fichas; con la app BB-only un
    stack lleva sufijo. Y era un falso positivo caro: la textura de puntos del
    tapete se OCR-ea como un numero. Medido en un torneo 3-Max, la zona del
    asiento MR -tapete vacio- leia '60668' en los 60 frames muestreados y contaba
    como ocupado, asi que la app veia 4 jugadores en el 34% de los frames y le
    asignaba al hero la posicion CO, que en una mesa de 3 NO EXISTE. Al quitarlo,
    sobre 160 frames: >3 jugadores 58 -> 9, y hero en CO 28 -> 1."""
    assert _plate_occupied([L(texto)]) is False


# --- 0.4 el bote estaba roto en modo BB --------------------------------------
# POT_RE + _to_int tratan la , y el . como separador de MILES, asi que el decimal
# se comia. Verificado end-to-end: el bote real de samples_bb/sample_bb_1.png es
# 3,75 BB y analyze_layout devolvia 375.

@pytest.mark.parametrize("texto, esperado", [
    ("Bote: 3,75 BB", 3.75),
    ("Bote: 12,5 BB", 12.5),
    ("Bote: 8,5 BB", 8.5),       # MIN_PLAUSIBLE_POT=100 lo descartaba
    ("Pot: 4 BB", 4.0),          # etiqueta en ingles
])
def test_find_pot_bb(texto, esperado):
    assert find_pot_bb([L(texto)]) == esperado


def test_sin_etiqueta_bote_o_pot_no_es_el_bote():
    """En modo BB todos los importes llevan el mismo sufijo, asi que sin la
    etiqueta un stack de la zona se confundiria con el bote."""
    assert find_pot_bb([L("47,8 BB")]) is None


@pytest.mark.parametrize("texto, esperado", [
    ("Bote: 3,75 BB", 375),      # el modo fichas lo daba x100
    ("Bote: 8,5 BB", None),      # y lo descartaba por debajo del minimo
])
def test_el_lector_en_fichas_sigue_comportandose_como_antes(texto, esperado):
    assert find_pot([L(texto)]) == esperado


# --- 0.5 coherencia entre la lectura de botones y la de posicion -------------

def test_facing_check_con_hero_distinto_de_bb_se_abstiene():
    """Preflop solo la BB puede PASAR (para el resto la ciega grande es una
    apuesta viva). Si los botones dicen "Pasar" y la posicion leida no es BB, una
    de las dos lecturas esta mal; si es la posicion, el rango tambien lo estara."""
    st = {"board": [], "hero_cards": ["Ah", "Kd"], "hero_position": "CO",
          "facing": "check", "stack_unit": "bb", "warnings": [],
          "players": [dict(P("CO", None, hero=True), stack=25.0)]}
    assert engine.decide(st) is None
    assert any("contradiccion" in w for w in st["warnings"])


def test_facing_none_sigue_recomendando():
    """Decision MEDIDA, no descuido: sobre el log de una sesion real, 55 de los 74
    frames decidibles tenian facing=None y de ahi salieron casi todas las
    recomendaciones. Abstenerse mataria ~75% de la utilidad para cubrir un caso
    que no es el peligroso (una apertura sin accion pendiente es un preview
    inofensivo)."""
    st = {"board": [], "hero_cards": ["Ah", "Kd"], "hero_position": "BTN",
          "facing": None, "stack_unit": "bb", "warnings": [],
          "players": [dict(P("BTN", None, hero=True), stack=40.0)]}
    assert engine.decide(st) is not None


# --- 0.6 interpolacion vs extrapolacion, contra la rejilla real --------------
# Antes habia un unico umbral fijo de 2.6bb que no distinguia "cae entre dos
# tablas tuyas" de "cae fuera de tus tablas". Y tenia un agujero: las claves de
# threebet_call son 10/15/20/..., asi que una defensa a 12,5bb queda a 2,5bb de la
# de 10 y 2,5 < 2,6 -> se servia el grafico de 10bb SIN AVISO.

def test_la_rejilla_sale_de_los_datos():
    assert engine._stack_grid("open_raise")[0] == 4.0
    assert engine._stack_grid("open_raise")[-1] == 40.0
    assert engine._stack_grid("threebet_call")[0] == 10.0, \
        "no hay defensa digitalizada por debajo de 10bb"


def test_fuera_de_la_tabla_es_extrapolacion_y_avisa():
    """100bb es todo el principio de un torneo y el maximo digitalizado son 40."""
    avisos = []
    nota = engine._stack_key_note({"stack_key": 40.0}, 100.0, "open_raise", avisos)
    assert "extrapolado" in nota
    assert len(avisos) == 1 and "FUERA" in avisos[0]


def test_entre_dos_claves_reales_es_interpolacion_y_se_nombra_la_vecina():
    """Antes, a 12,5bb: silencio total."""
    avisos = []
    nota = engine._stack_key_note({"stack_key": 10.0}, 12.5, "threebet_call", avisos)
    assert nota != ""
    assert "15bb" in nota
    assert avisos == [], "no es un error, asi que no ensucia warnings"


def test_una_profundidad_que_coincide_con_una_clave_no_lleva_nota():
    avisos = []
    assert engine._stack_key_note({"stack_key": 40.0}, 40.0, "open_raise", avisos) == ""
    assert avisos == []


# --- 0.7 cartas imposibles por OCR -------------------------------------------
# Medido: 4 de los 64 frames con board (6,2%) traen una carta repetida. Sin
# guarda, evaluate_hand devolvia una mano formada que el usuario NO tiene.

@pytest.mark.parametrize("desc, hero, board", [
    ("board con carta repetida", ["Ah", "Kd"], ["4s", "7d", "9d", "7h", "9d"]),
    ("hero con dos cartas identicas", ["Ah", "Ah"], []),
    ("una carta del hero repetida en el board", ["Ah", "Kd"], ["Ah", "7d", "2c"]),
    ("board imposiblemente largo", ["Ah", "Kd"], ["2c", "3d", "4h", "5s", "6c", "7d"]),
])
def test_una_mano_imposible_no_se_evalua(desc, hero, board):
    assert hs.evaluate_hand(hero, board) is None, desc


def test_un_board_valido_sigue_evaluandose():
    assert hs.evaluate_hand(["Ah", "Kd"], ["4s", "7d", "9d"])["made_name"] == "Carta alta: As"


# --- A-1b parse_amount_bb a prueba de ambiguedad -----------------------------
# Una zona de nameplate puede tragarse el importe del vecino o el "Media: N BB" de
# la esquina si el encuadre baila; quedarse con "el primero que salga" elige la
# profundidad equivocada -y con ella el rango- sin que nada lo delate.

def test_un_solo_importe_se_lee_normal():
    assert parse_amount_bb([L("36,6 BB")]) == 36.6


def test_dos_importes_distintos_dan_none():
    """Antes se quedaba con el primero. Sin stack el motor se abstiene o tira del
    cache; con un stack falso recomienda con conviccion."""
    assert parse_amount_bb([L("36,6 BB"), L("Media: 89 BB")]) is None


def test_el_mismo_importe_repetido_no_es_ambiguo():
    assert parse_amount_bb([L("36,6 BB"), L("36,6 BB")]) == 36.6


def test_la_ocupacion_sobrevive_a_la_ambiguedad():
    """Ahi la pregunta es "¿hay un importe en BB?", no "¿cual?"."""
    assert _plate_occupied([L("36,6 BB"), L("Media: 89 BB")]) is True


# --- A-1d el importe del boton "Igualar" -------------------------------------
# Evidencia INDEPENDIENTE de que hay una subida.

@pytest.mark.parametrize("desc, lineas, esperado", [
    ("importe en la linea del verbo", [L("Igualar 2,5 BB")], 2.5),
    ("importe en otra linea -> el menor (igualar < subir a)",
     [L("Igualar"), L("Subir a"), L("2,5 BB"), L("6 BB")], 2.5),
    ("sin importe", [L("Igualar cualquiera")], None),
    ("sin botones", [], None),
])
def test_parse_to_call_bb(desc, lineas, esperado):
    assert seat_map.parse_to_call_bb(lineas) == esperado, desc


def test_una_subida_que_el_boton_delata_pero_la_mesa_no_explica_se_abstiene():
    """Seguir por open_raise seria recomendar el rango de APERTURA enfrentando una
    subida, que es exactamente el fallo que este trabajo existe para eliminar."""
    st = {"board": [], "hero_cards": ["Ah", "Kd"], "hero_position": "BTN",
          "facing": "bet", "stack_unit": "bb", "to_call": 3.0, "warnings": [],
          "players": [dict(P("BTN", None, hero=True), stack=30.0),
                      dict(P("BB", 1.0), stack=20.0)]}
    assert engine.decide(st) is None
    assert any("igualar" in w and "ningun asiento" in w for w in st["warnings"])


def test_la_sb_completando_sigue_recomendando():
    """Pide 0,5bb, por debajo de la ciega grande: no es una subida."""
    st = {"board": [], "hero_cards": ["Ah", "Kd"], "hero_position": "SB",
          "facing": "bet", "stack_unit": "bb", "to_call": 0.5, "warnings": [],
          "players": [dict(P("SB", 0.5, hero=True), stack=30.0),
                      dict(P("BB", 1.0), stack=20.0)]}
    assert engine.decide(st) is not None


# --- A-3 LA GUARDA DE UNIDAD -------------------------------------------------
# Las rutas de diagnostico (analyze/analyze_color_deck) siguen produciendo stacks
# en FICHAS ENTERAS. Sin esta guarda, un stack de 3955 fichas se leeria como
# 3955bb -> tabla de 40bb -> una recomendacion con conviccion y falsa.

@pytest.mark.parametrize("unidad, desc", [
    (None, "sin stack_unit"),
    ("chips", 'con stack_unit="chips"'),
])
def test_un_gamestate_que_no_declara_bb_se_abstiene(unidad, desc):
    st = {"board": [], "hero_cards": ["Ah", "Kd"], "hero_position": "BTN",
          "facing": None, "warnings": [],
          "players": [dict(P("BTN", None, hero=True), stack=3955)]}
    if unidad is not None:
        st["stack_unit"] = unidad
    assert engine.decide(st) is None, desc
    assert any("BIG BLINDS" in w for w in st["warnings"]), desc


CORPUS_FICHAS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "vision", "results_samples_layout2.json")


@pytest.mark.skipif(not os.path.exists(CORPUS_FICHAS),
                    reason=f"falta {CORPUS_FICHAS} (no versionado)")
def test_el_corpus_en_fichas_es_indecidible_en_una_build_bb_only():
    """LA ASERCION DE SEGURIDAD DEL PASO A BB-ONLY. Si alguna de estas capturas
    produjera recomendacion, seria una profundidad en fichas interpretada como bb.
    Antes del cambio salian 4."""
    with open(CORPUS_FICHAS) as fh:
        estados = json.load(fh)
    assert estados, "el corpus esta vacio; el test no probaria nada"
    recomendadas = [st for st in estados if engine.decide(dict(st)) is not None]
    assert not recomendadas, f"{len(recomendadas)} de {len(estados)} capturas recomendaron"


# --- GUARDA ESTRUCTURAL: el raiser tiene que hablar ANTES que el hero --------
# Sus tablas de defensa solo cubren raisers que hablan antes. Si el "raiser" habla
# despues, lo de delante no es una subida que defender sino una RESUBIDA a la
# apertura del propio hero. Medido sobre dos sesiones: 67 de 134 atribuciones eran
# de este tipo, y 47 de ellas hero=BTN vs SB, imposible en 3-max.

def _defensa(hero_pos, vs_pos):
    st = {"board": [], "hero_cards": ["9c", "8c"], "hero_position": hero_pos,
          "facing": "bet", "stack_unit": "bb", "to_call": 5.0, "warnings": [],
          "players": [dict(P(hero_pos, None, hero=True), stack=20.0),
                      dict(P(vs_pos, 5.0), stack=30.0)]}
    return engine.decide(st), st


def test_un_raiser_que_habla_despues_que_el_hero_se_abstiene():
    r, st = _defensa("BTN", "SB")
    assert r is None
    assert any("habla" in w and "DESPUES" in w for w in st["warnings"]), \
        "el motivo dice que es una resubida, no un hueco de datos"


def test_bb_vs_sb_si_es_posible_y_no_lo_bloquea():
    r, st = _defensa("BB", "SB")
    assert r is not None or not any("DESPUES" in w for w in st["warnings"])


# --- CONTAR LIMPERS: dos reglas que parecian detalles y no lo son ------------
# Medido sobre una sesion real, sin ellas la capa derivada disparaba "subir sobre
# los limpers" en 45 frames y en LOS 45 el bote estaba en realidad SUBIDO.

def _limpers(*rivales):
    """rivales = (position, importe puesto)"""
    return engine._contar_limpers(
        [dict(P("BTN", None, hero=True), stack=20.0)]
        + [dict(P(pos, imp), stack=20.0) for pos, imp in rivales])


@pytest.mark.parametrize("desc, rivales, esperado", [
    ("un rival con una ciega grande justa es un limper", [("CO", 1.0)], 1),
    ("dos limpers son dos", [("CO", 1.0), ("HJ", 1.0)], 2),
    ("LA CIEGA GRANDE NO ES UN LIMPER: su 1bb es obligatorio, no una decision. "
     "Contarla corria la fila donante un asiento de mas SIEMPRE", [("BB", 1.0)], 0),
    ("y con un limper de verdad al lado, sigue contando uno solo",
     [("BB", 1.0), ("CO", 1.0)], 1),
    ("la BB con ciega+ante tampoco cuenta ni dispara la alarma de subida",
     [("BB", 1.8), ("CO", 1.0)], 1),
    ("SI ALGUIEN HA PUESTO MAS QUE UNA CIEGA el bote esta SUBIDO, no limpeado",
     [("CO", 1.0), ("SB", 5.0)], 0),
    ("y basta uno para invalidarlo", [("CO", 4.0)], 0),
    ("la SB completando (1bb) SI es un limper", [("SB", 1.0)], 1),
    ("la SB con solo su media ciega no cuenta", [("SB", 0.5)], 0),
])
def test_contar_limpers(desc, rivales, esperado):
    assert _limpers(*rivales) == esperado, desc


def test_sin_ningun_importe_no_es_cero_sino_none():
    """No es lo mismo 'he mirado y no hay' que 'no he podido mirar'."""
    assert _limpers(("CO", None), ("HJ", None)) is None


# --- PONER UNA CIEGA NO ES ENTRAR PAGANDO -----------------------------------
# La regla "la BB no es un limper" mira la ETIQUETA de posicion, y por eso no
# basta: si las posiciones salen corridas, la ciega grande real no se llama "BB"
# y su importe vuelve a parecer un limp.
#
# Paso de verdad y lo anoto el usuario en vivo (2026-07-27, frame 0462 de la
# sesion 220231): era BTN con Kc5s a 26,5bb, la BB real estaba etiquetada MP2,
# su 1,1bb obligatorio conto como limp y el motor sirvio el rango de CO en vez
# del de BTN. Su nota: "dice que un rival ha entrado pagando pero en realidad
# son las ciegas".
#
# El arreglo cruza con el HISTORIAL DE ACCIONES, que es evidencia INDEPENDIENTE
# de la etiqueta. Medido sobre las 14 sesiones grabadas: 301 frames preflop
# corrigen el recuento (263 de 1->0) y 72 cambian la orden.

LOG_PONER = [{"seat": "TOPC", "accion": "post", "verbo": "Poner"}]


def _limpers_log(rivales, acciones):
    return engine._contar_limpers(
        [dict(P("BTN", None, hero=True), stack=20.0, seat="HERO")]
        + [dict(P(pos, imp), stack=20.0, seat=seat) for seat, pos, imp in rivales],
        {"acciones": acciones, "completo": False})


@pytest.mark.parametrize("desc, rivales, acciones, esperado", [
    ("un asiento cuya ultima accion vista fue PONER no es un limper, aunque su "
     "etiqueta de posicion este equivocada (el bug que anoto el usuario)",
     [("TOPC", "MP2", 1.1)], LOG_PONER, 0),
    ("sin el log, ese mismo frame contaba un limper fantasma",
     [("TOPC", "MP2", 1.1)], [], 1),
    ("un limper de verdad al lado sigue contando",
     [("TOPC", "MP2", 1.1), ("MR", "CO", 1.0)], LOG_PONER, 1),
    ("si despues de PONER se le ve IGUALAR, vuelve a contar: manda lo ULTIMO",
     [("TOPC", "MP2", 1.1)], LOG_PONER + [{"seat": "TOPC", "accion": "call"}], 1),
    ("el ante tambien es 'post' y tampoco convierte a nadie en limper",
     [("TOPC", "MP2", 1.0)], [{"seat": "TOPC", "accion": "post", "verbo": "Ante"}], 0),
])
def test_el_historial_corrige_el_recuento(desc, rivales, acciones, esperado):
    assert _limpers_log(rivales, acciones) == esperado, desc


@pytest.mark.parametrize("desc, acciones", [
    ("un log vacio no borra a nadie: sin evidencia positiva se cuenta igual", []),
    ("y un 'post' de OTRO asiento no afecta a este", LOG_PONER),
])
def test_asimetria_solo_se_usa_la_presencia_de_un_post(desc, acciones):
    """Nunca la AUSENCIA de un 'call'. El historial viene siempre con
    completo=False -el verbo dura menos de 1,5 s y solo se ve lo que se
    muestrea-, asi que exigir ver el "Igualar" haria perder limpers de verdad."""
    assert _limpers_log([("MR", "CO", 1.0)], acciones) == 1, desc


# --- SIN BOTONES LEIDOS, EL BOTE PUEDE ESTAR SUBIDO IGUAL -------------------
# Toda la deteccion de subida vivia dentro de `if facing == "bet"`, incluida la
# red de to_call. Pero los botones solo se leen en ~el 10% de los frames, asi
# que en el resto un to_call de 2bb se tiraba entero y el motor seguia como si
# el bote estuviera sin abrir.
#
# Lo cazo el usuario jugando (28-07-2026, sesion 004126), dos notas que son el
# mismo fallo visto desde dos sitios:
#   frame 0181, era la BB, el boton pedia 2 BB -> la app dijo RAISE OVER LIMPERS
#               ("no entiendo porque me dice que suba sobre limpers, yo era ciega")
#   frame 0247, era la SB, el historial acababa de ver "Subir" a su derecha
#               -> la app dijo LIMP ("ha subido y a mi no me lo ha detectado rapido")

SUBE = [{"seat": "MR", "accion": "raise", "verbo": "Subir"}]


def _decide(hero_pos, cartas, to_call=None, acciones=None, rivales=()):
    st = {"board": [], "hero_cards": list(cartas), "stack_unit": "bb",
          "hero_position": hero_pos, "facing": None, "to_call": to_call,
          "acciones": {"acciones": list(acciones or []), "completo": False},
          "players": [dict(P(hero_pos, None, hero=True), stack=60.0, seat="HERO")]
                     + [dict(P(pos, bet), stack=60.0, seat=s) for s, pos, bet in rivales],
          "warnings": []}
    return engine.decide(st), st


def test_con_el_boton_pidiendo_dos_bb_no_se_recomienda_como_bote_sin_abrir():
    """Frame 0181 del usuario."""
    r, st = _decide("BB", ["Ks", "9d"], to_call=2.0)
    assert r is None
    assert any("2 BB para igualar" in w for w in st["warnings"])


def test_si_lo_ultimo_visto_fue_un_rival_subiendo_tampoco():
    """Frame 0247 del usuario."""
    r, _st = _decide("SB", ["Ah", "7c"], acciones=SUBE)
    assert r is None


@pytest.mark.parametrize("desc, kwargs", [
    ("una subida YA RESPONDIDA no bloquea: se mira la ultima accion, no toda la "
     "mano (asi se pasa de perder 485 recomendaciones a 204)",
     dict(hero_pos="SB", cartas=["Ah", "7c"],
          acciones=SUBE + [{"seat": "UL", "accion": "call"}])),
    ("la subida del PROPIO HERO no le bloquea a el mismo (de 204 a 111)",
     dict(hero_pos="BTN", cartas=["Ah", "Kd"],
          acciones=[{"seat": "HERO", "accion": "raise", "verbo": "Subir"}])),
    ("sin ninguna señal, se recomienda como siempre",
     dict(hero_pos="BTN", cartas=["Ah", "Kd"])),
    ("un to_call de media ciega (la SB completando) no es una subida",
     dict(hero_pos="BTN", cartas=["Ah", "Kd"], to_call=0.5)),
])
def test_los_recortes_que_evitan_comerse_las_recomendaciones_buenas(desc, kwargs):
    r, _st = _decide(**kwargs)
    assert r is not None, desc


# --- postflop_equity: separado de decide(), y abstenerse antes que inflar ----
# El riesgo real de este camino es contar MENOS rivales de los que hay (en
# showdown las cartas se giran y los dorsos desaparecen), porque eso INFLA la
# equity del hero, que es la direccion peligrosa.

def _post(**kw):
    d = {"board": ["Ah", "Kd", "2c"], "hero_cards": ["Qs", "Jh"], "hero_position": "BTN",
         "facing": "bet", "stack_unit": "bb", "warnings": [],
         "players": [{"is_hero": True, "in_hand": True, "position": "BTN", "stack": 30.0},
                     {"is_hero": False, "in_hand": True, "position": "BB", "stack": 25.0}]}
    d.update(kw)
    return d


def test_equity_caso_normal_devuelve_probabilidades():
    assert engine.postflop_equity(_post(), seed=1)["win_probability"] is not None


def test_equity_en_preflop_devuelve_none_sin_ensuciar_warnings():
    st = _post(board=[], warnings=[])
    assert engine.postflop_equity(st, seed=1) is None
    assert st["warnings"] == []


def test_equity_sin_las_cartas_del_hero():
    assert engine.postflop_equity(_post(hero_cards=[]), seed=1) is None


def test_equity_sin_in_hand_no_supone_el_numero_de_rivales():
    """Suponer de menos INFLA la equity, que es la direccion peligrosa."""
    st = _post(players=[{"is_hero": True}, {"is_hero": False}])
    assert engine.postflop_equity(st, seed=1) is None
    assert any("INFLA" in w for w in st["warnings"])


def test_equity_sin_nadie_con_cartas_nombra_el_showdown():
    """O la mano termino, o es un showdown con las cartas ya giradas: en los dos
    casos afirmar "ganas seguro" seria falso."""
    st = _post(players=[{"is_hero": True, "in_hand": True},
                        {"is_hero": False, "in_hand": False}])
    assert engine.postflop_equity(st, seed=1) is None
    assert any("showdown" in w for w in st["warnings"])


def test_decide_sigue_sin_dar_accion_postflop():
    """La equity es una probabilidad, no una decision: convertirla en accion
    exigiria modelar bote e implied odds."""
    assert engine.decide(_post()) is None


# --- el board tiene que cuadrar con la calle que sigue el rastreador --------
#
# Son dos lecturas INDEPENDIENTES: contar cartas en el frame, y llevar la cuenta
# a lo largo de la mano. Si se contradicen, una esta mal y no se sabe cual, asi
# que calcular igualmente da un numero sobre un board a medias.
#
# Medido sobre los 9.225 frames grabados: la discrepancia aparece en 462 (5,0%) y
# en 17 de las 826 equities (2,1%) se calculo el numero de todas formas. Caso
# real, sesion-2026-07-27_014058/0461-0465: 'river' con tres cartas leidas y la
# app imprimiendo 30,6% con dos cartas de menos.

def _post_calle(calle, board):
    return {"hero_cards": ["Ah", "Kh"], "board": list(board), "stack_unit": "bb",
            "hero_position": "BTN", "calle_seguida": calle, "warnings": [],
            "players": [{"is_hero": True, "in_hand": True, "position": "BTN", "stack": 30.0},
                        {"is_hero": False, "in_hand": True, "position": "BB", "stack": 25.0}]}


@pytest.mark.parametrize("calle, board", [
    ("river", ["3c", "7d", "Js"]),              # el caso medido
    ("river", ["3c", "7d", "Js", "2h"]),
    ("turn", ["3c", "7d", "Js"]),
    ("flop", ["3c", "7d", "Js", "2h", "5s"]),
])
def test_no_se_calcula_equity_sobre_un_board_que_no_cuadra(calle, board):
    st = _post_calle(calle, board)
    assert engine.postflop_equity(st, iterations=200, seed=1) is None
    assert any("board" in w and calle in w for w in st["warnings"]), st["warnings"]


@pytest.mark.parametrize("calle, board", [
    ("flop", ["3c", "7d", "Js"]),
    ("turn", ["3c", "7d", "Js", "2h"]),
    ("river", ["3c", "7d", "Js", "2h", "5s"]),
])
def test_cuando_cuadra_se_calcula_como_siempre(calle, board):
    assert engine.postflop_equity(_post_calle(calle, board), iterations=200, seed=1) is not None


def test_sin_calle_seguida_no_se_bloquea_nada():
    """Los GameState de las rutas de diagnostico no traen el campo, y esos frames
    no tienen por que perder la equity."""
    st = _post_calle("river", ["3c", "7d", "Js"])
    del st["calle_seguida"]
    assert engine.postflop_equity(st, iterations=200, seed=1) is not None


def test_las_cartas_vistas_del_rival_llegan_al_calculo():
    """El puente entre vision/ y decision/: table_state pone player["cards"]
    cuando el cliente enseña la mano, y postflop_equity tiene que pasarlas."""
    st = {"hero_cards": ["Kh", "6d"], "board": ["2c", "5c", "4s", "Qs", "3c"],
          "stack_unit": "bb", "hero_position": "SB", "calle_seguida": "river",
          "warnings": [],
          "players": [{"is_hero": True, "in_hand": True, "position": "SB", "stack": 20.0},
                      {"is_hero": False, "in_hand": True, "position": "BB", "stack": 16.4,
                       "revealed": True, "cards": ["6c", "4c"]}]}
    r = engine.postflop_equity(st, iterations=500, seed=1)
    assert r["win_probability"] == 0.0, "escalera de color contra escalera: iba muerto"
    assert r["positional_adjustment"]["opponent_ranges"][0]["combos"] == 1


def test_el_stack_cacheado_NO_cruza_la_frontera_de_mano():
    """Dentro de una mano el stack casi no se mueve; entre manos si -has ganado o
    perdido el bote, o han subido las ciegas-. Medido sobre las 6 sesiones
    grabadas, la cache de una mano anterior se equivoca en mas del 15% el 62,3%
    de las veces, contra el 33,6% de la cache de la misma mano. Y un 15% a 25bb
    basta para servir la tabla preflop de otra profundidad."""
    engine.reset_state()
    hero = {"stack": 25.0}
    assert engine._cached_hero_stack(hero, mano=7) == (25.0, False)
    # mismo numero de mano: la cache vale
    assert engine._cached_hero_stack({}, mano=7) == (25.0, True)
    # mano siguiente: no vale, aunque el TTL siga vivo
    assert engine._cached_hero_stack({}, mano=8) == (None, False)


def test_sin_numero_de_mano_la_cache_se_comporta_como_antes():
    """No se puede saber si se cruzo la frontera, asi que manda solo el TTL. Pasa
    en los tests que arman un GameState a mano, no en produccion, donde
    analyze_layout siempre trae mano_seguida."""
    engine.reset_state()
    assert engine._cached_hero_stack({"stack": 12.0}) == (12.0, False)
    assert engine._cached_hero_stack({}) == (12.0, True)
    assert engine._cached_hero_stack({}, mano=3) == (12.0, True)
