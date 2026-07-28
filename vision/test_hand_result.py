"""
Verificacion de hand_result.parse_hand_result / hero_outcome contra las lineas de
chat REALES del cliente, mas variantes con el ruido de OCR que se ha observado.

Es puro parseo de texto: no hace falta ni opencv ni tesseract.
"""
import pytest

from vision.hand_result import hero_outcome, parse_hand_result

# Linea real y completa: numero de mano + ganador + importe + mano ganadora.
COMPLETA = ["Repartidor: Mano n.º 261531764294: fabiocs98 gana el bote (2.040) "
            "con pareja de nueves"]

CON_SHOWDOWN = [
    "Repartidor: alex_delg, es tu turno...",
    "Repartidor: Mano n.º 261531764294: fabiocs98 gana el bote (2.040) con pareja de nueves",
    "Repartidor: fortu2010 tiene pareja de nueves",
]

SPLIT = [
    "Repartidor: Mano n.º 261531249025: Amsterdam974 empata por el bote",
    "Repartidor: Mano n.º 261531249025: rubydog77 empata por el bote (4.243)",
]


@pytest.fixture
def completa():
    return parse_hand_result(COMPLETA)


@pytest.fixture
def con_showdown():
    return parse_hand_result(CON_SHOWDOWN)


@pytest.fixture
def split():
    return parse_hand_result(SPLIT)


# --- la linea de resultado ---------------------------------------------------

@pytest.mark.parametrize("campo, esperado", [
    ("hand_number", "261531764294"),
    ("winner", "fabiocs98"),
    ("amount", "2.040"),
    ("winning_hand", "pareja de nueves"),
])
def test_linea_real_completa(completa, campo, esperado):
    assert completa is not None
    assert completa[campo] == esperado


def test_el_showdown_recoge_lo_que_enseño_cada_uno(con_showdown):
    assert con_showdown["winner"] == "fabiocs98"
    assert any(s["player"] == "fortu2010" and s["hand"] == "pareja de nueves"
               for s in con_showdown["showdown"])


@pytest.mark.parametrize("desc, lineas", [
    ("una linea de turno sola no es un resultado", ["Repartidor: alex_delg, es tu turno..."]),
    ("chat vacio", []),
    ("chat None", None),
])
def test_sin_resultado_devuelve_none(desc, lineas):
    assert parse_hand_result(lineas) is None, desc


# --- ruido de OCR ------------------------------------------------------------

def test_ruido_de_ocr_n_grado_leido_como_n_o_y_separadores_raros():
    r = parse_hand_result(["Repartidor Mano n.o 261531764295 SHARKOS54 gana el bote "
                           "(12.500) con trío de reyes"])
    assert r["hand_number"] == "261531764295"
    assert r["winner"] == "SHARKOS54"
    assert r["amount"] == "12.500"
    assert r["winning_hand"] == "trío de reyes"


def test_gana_sin_showdown_todos_foldearon():
    """"gana el bote (N)" sin el "con ..."."""
    r = parse_hand_result(["Repartidor: Mano n.º 261531764296: alex_delg gana el bote (500)"])
    assert r["winner"] == "alex_delg"
    assert r["amount"] == "500"
    assert r["winning_hand"] is None


def test_la_linea_partida_en_dos_por_el_ocr_se_reune():
    r = parse_hand_result(["Repartidor: Mano n.º 261531764297: fabiocs98 gana",
                           "el bote (2.040) con color de corazones"])
    assert r["winner"] == "fabiocs98"
    assert r["hand_number"] == "261531764297"
    assert r["winning_hand"] == "color de corazones"


def test_con_dos_resultados_visibles_manda_el_mas_reciente():
    r = parse_hand_result([
        "Repartidor: Mano n.º 111111111111: pepe gana el bote (100) con par de doses",
        "Repartidor: Mano n.º 222222222222: juanito gana el bote (300) con escalera"])
    assert r["winner"] == "juanito"
    assert r["hand_number"] == "222222222222"


def test_sin_numero_de_mano_legible_sigue_habiendo_resultado():
    r = parse_hand_result(["fabiocs98 gana el bote (2.040) con pareja de nueves"])
    assert r is not None
    assert r["winner"] == "fabiocs98"
    assert r["hand_number"] is None


def test_el_orden_visual_manda_sobre_el_orden_de_lectura():
    """tesseract en SPARSE_TEXT no devuelve las lineas en orden de lectura, asi
    que la continuacion de un mensaje puede llegar ANTES que su cabecera."""
    r = parse_hand_result([
        {"text": "el bote (2.040) con color de corazones", "top": 40, "left": 0},
        {"text": "Repartidor: Mano n.º 261531764297: fabiocs98 gana", "top": 20, "left": 0}])
    assert r is not None
    assert r["winner"] == "fabiocs98"
    assert r["winning_hand"] == "color de corazones"


def test_la_frase_de_mano_no_invade_el_mensaje_siguiente():
    """Se busca dentro del MISMO mensaje del chat (hasta el siguiente
    "Repartidor:"), no en una ventana fija de caracteres."""
    r = parse_hand_result([
        "Repartidor: Mano n.º 261531400000: pepe gana el bote (120) con pareja de jotas",
        "Repartidor: alex_delg, es tu turno. Tienes 7 segundos para actuar"])
    assert r["winning_hand"] == "pareja de jotas"


# --- hero_outcome ------------------------------------------------------------

def test_el_hero_gana(completa):
    o = hero_outcome(completa, "fabiocs98")
    assert o["status"] == "won"
    assert o["hero_hand"] == "pareja de nueves"


def test_el_hero_pierde_y_se_le_ve_la_mano_en_el_showdown(con_showdown):
    o = hero_outcome(con_showdown, "fortu2010")
    assert o["status"] == "lost"
    assert o["hero_hand"] == "pareja de nueves"


def test_si_el_hero_no_aparece_por_ningun_lado_es_desconocido(con_showdown):
    o = hero_outcome(con_showdown, "alex_delg")
    assert o["status"] == "unknown"
    assert o["hero_hand"] is None


def test_sin_nombre_de_hero_cacheado_es_desconocido(completa):
    assert hero_outcome(completa, None)["status"] == "unknown"


def test_el_emparejado_de_nicks_tolera_el_truncamiento_del_ocr(completa):
    assert hero_outcome(completa, "fabiocs9")["status"] == "won"


# --- BOTE DIVIDIDO -----------------------------------------------------------
# "empata por el bote", una linea por jugador con el mismo n.º de mano. Lineas
# reales de vision/samples_layout2/: antes no se reconocian (el patron exigia
# "gana") y la mano salia como "resultado no legible".

def test_el_bote_dividido_se_reconoce(split):
    assert split is not None
    assert split["split"] is True
    assert split["winners"] == ["Amsterdam974", "rubydog77"]
    assert split["winner"] == "Amsterdam974"
    assert split["amount"] == "4.243"
    assert split["hand_number"] == "261531249025"


def test_en_un_split_el_hero_empata(split):
    assert hero_outcome(split, "rubydog77")["status"] == "split"


def test_en_un_split_un_ajeno_sigue_siendo_desconocido(split):
    assert hero_outcome(split, "pepito")["status"] == "unknown"


def test_un_solo_ganador_no_se_marca_como_split(completa):
    assert completa["split"] is False
    assert completa["winners"] == ["fabiocs98"]


def test_un_split_viejo_en_el_historial_no_gana_a_la_mano_nueva():
    r = parse_hand_result([
        "Repartidor: Mano n.º 111111111111: aaa empata por el bote (100)",
        "Repartidor: Mano n.º 111111111111: bbb empata por el bote",
        "Repartidor: Mano n.º 222222222222: ccc gana el bote (300) con escalera"])
    assert r["split"] is False
    assert r["winner"] == "ccc"


# --- NICK CON ESPACIO --------------------------------------------------------
# El OCR lee el guion bajo como espacio ("david_sagunt" -> "david sagunt").
# Antes el regex capturaba solo "sagunt".

@pytest.fixture
def nick_con_espacio():
    return parse_hand_result(["Repartidor: Mano n.º 261531241628: david sagunt gana "
                              "el bote (2.197) con pareja de jotas"])


def test_un_nick_con_espacio_no_se_trunca(nick_con_espacio):
    assert nick_con_espacio["winner"] == "david sagunt"
    assert nick_con_espacio["winning_hand"] == "pareja de jotas"


def test_un_nick_con_espacio_casa_con_su_forma_con_guion_bajo(nick_con_espacio):
    assert hero_outcome(nick_con_espacio, "david_sagunt")["status"] == "won"


def test_el_nick_no_se_come_la_palabra_previa_cuando_no_es_suya():
    r = parse_hand_result(["Repartidor: El jugador pepito gana el bote (50)"])
    assert r["winner"] == "pepito"


# --- MANO CON COMA -----------------------------------------------------------
# "doble pareja, damas y sietes" (linea real de showdown). Antes se cortaba en la
# coma y quedaba solo "doble pareja".

def test_una_mano_con_coma_se_lee_entera():
    r = parse_hand_result(["Repartidor: Mano n.º 261531300000: david sagunt gana el "
                           "bote (900) con doble pareja, damas y sietes"])
    assert r["winning_hand"] == "doble pareja, damas y sietes"


def test_una_mano_con_coma_tambien_en_el_showdown():
    r = parse_hand_result(["Repartidor: rubydog77 tiene doble pareja, reyes y doses",
                           "Repartidor: Mano n.º 261531300001: pepe gana el bote (10)"])
    assert any(s["hand"] == "doble pareja, reyes y doses" for s in r["showdown"])
