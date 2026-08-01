"""
Las dos piezas por las que pasa TODA carta que la app lee, y que no tenian ni un
test: elegir entre los dos mazos (_cajas_de_carta) y decidir como se resuelve el
rango de cada carta (_encolar_cartas).

docs/PENDIENTE.md lo señalaba como el hueco a tapar antes de tocar detectores, y
tenia razon: los arreglos del mazo de figuras ilustradas (commits 9166b3a y
0dbb427) entraron justo por aqui.

Las dos se prueban con los detectores sustituidos por dobles. No es por comodidad:
lo que hay que blindar es la REGLA DE DECISION -quien gana, en que orden se
intenta cada camino-, y con imagenes reales esa regla queda escondida detras de
si el detector acerto o no, que es otra cosa y ya se prueba en otro sitio.
"""
import pytest

from vision import table_state as ts

pytestmark = pytest.mark.vision

ZONA = (100, 100, 500, 250)


def caja(x, deck):
    return {"x": x, "y": 0, "w": 87, "h": 122, "suit": "spade", "deck": deck}


@pytest.fixture
def dos_mazos(monkeypatch):
    """Deja fijar cuantas cartas encuentra cada detector."""
    estado = {"glifo": [], "solido": []}

    def pon(n_glifo, n_solido):
        estado["glifo"] = [caja(i * 90, "glyph") for i in range(n_glifo)]
        estado["solido"] = [{"x": i * 90, "y": 0, "w": 87, "h": 122, "suit": "heart"}
                            for i in range(n_solido)]

    monkeypatch.setattr(ts.glyph_card_detector, "find_card_boxes",
                        lambda *a, **k: list(estado["glifo"]))
    monkeypatch.setattr(ts.color_card_detector, "find_card_boxes",
                        lambda *a, **k: list(estado["solido"]))
    return pon


# --- elegir mazo: gana el que encuentra MAS cartas --------------------------

def test_gana_el_que_encuentra_mas_cartas(dos_mazos):
    """No el que responda primero. Antes bastaba con que el de cara blanca
    devolviera algo y con el mazo de fondo solido eso costaba caro: devolvia 1 o
    2 cajas basura -que nunca resuelven un rango- mientras el otro encontraba el
    board entero."""
    dos_mazos(2, 5)
    cajas = ts._cajas_de_carta(None, ZONA)
    assert len(cajas) == 5
    assert all(c.get("deck", "solid") == "solid" for c in cajas)


def test_si_el_de_cara_blanca_encuentra_mas_gana_el(dos_mazos):
    dos_mazos(5, 0)
    cajas = ts._cajas_de_carta(None, ZONA)
    assert len(cajas) == 5
    assert all(c["deck"] == "glyph" for c in cajas)


def test_en_empate_gana_el_de_cara_blanca(dos_mazos):
    """El desempate importa de verdad: el 26-07 el usuario cambio de mazo y la
    app se quedo ciega 267 frames. Con empate se prefiere el de cara blanca, que
    es el mazo configurado."""
    dos_mazos(3, 3)
    assert all(c["deck"] == "glyph" for c in ts._cajas_de_carta(None, ZONA))


def test_NUNCA_se_mezclan_cartas_de_los_dos_mazos(dos_mazos):
    """Un board mitad de un mazo y mitad del otro no existe: seria leer la misma
    mesa con dos polaridades a la vez."""
    for g, s in ((4, 3), (3, 4), (1, 5), (5, 1)):
        dos_mazos(g, s)
        decks = {c.get("deck", "solid") for c in ts._cajas_de_carta(None, ZONA)}
        assert len(decks) <= 1, f"glifo={g} solido={s} devolvio {decks}"


def test_las_cajas_salen_ordenadas_por_x(dos_mazos):
    """El board se lee de izquierda a derecha; sin orden, las cartas saldrian
    barajadas y el invariante de que el board solo crece dejaria de significar
    nada."""
    dos_mazos(0, 4)
    xs = [c["x"] for c in ts._cajas_de_carta(None, ZONA)]
    assert xs == sorted(xs)


def test_sin_cartas_en_ninguno_no_hay_cajas(dos_mazos):
    dos_mazos(0, 0)
    assert ts._cajas_de_carta(None, ZONA) == []


def test_las_cartas_principales_eligen_un_solo_mazo_con_las_dos_zonas(monkeypatch):
    """Una falsa quinta caja del detector contrario no puede partir la mano en
    dos polaridades: las dos cartas del hero pesan más que ese ruido."""
    hero, board = (10, 10, 20, 20), (30, 30, 40, 40)

    def glyph(_img, zona, esperadas=None):
        return [caja(i * 90, "glyph") for i in range(2 if zona == hero else 0)]

    def solid(_img, zona):
        return [caja(i * 90, "solid") for i in range(1 if zona == hero else 5)]

    monkeypatch.setattr(ts.glyph_card_detector, "find_card_boxes", glyph)
    monkeypatch.setattr(ts.color_card_detector, "find_card_boxes", solid)
    hero_boxes, board_boxes, deck = ts._cajas_principales(None, hero, board)
    assert deck == "glyph"
    assert len(hero_boxes) == 2
    assert board_boxes == []


def test_las_cartas_principales_respetan_el_mazo_elegido_por_el_usuario(dos_mazos):
    dos_mazos(2, 5)
    hero, board, deck = ts._cajas_principales(None, ZONA, ZONA, mazo="glyph")
    assert deck == "glyph"
    assert all(c["deck"] == "glyph" for c in hero + board)


def test_solo_se_ocr_ean_apuestas_de_asientos_confirmados():
    todos = {"UL", "UR", "HERO"}
    assert ts._asientos_para_apuestas(None, todos) == todos
    assert ts._asientos_para_apuestas({"UL"}, todos) == {"UL", "HERO"}


# --- resolver el rango: calco, luego cache, y solo entonces OCR -------------

@pytest.fixture
def caminos(monkeypatch):
    """Sustituye los tres caminos del rango y APUNTA EL ORDEN en que se llaman.
    El orden es lo que se prueba: el calco evita el 86% del coste de un frame,
    asi que intentarlo despues del OCR seria tenerlo y no usarlo."""
    llamadas = []
    cfg = {"calco": None, "cache": (False, None)}

    def rango_por_calco(crop, deck):
        llamadas.append("calco")
        return cfg["calco"], 1.0

    def cached_rank(key):
        llamadas.append("cache")
        return cfg["cache"]

    def add_rank_jobs(batch, crop, deck="solid"):
        llamadas.append("ocr")
        return 0, 3

    monkeypatch.setattr(ts.color_rank_ocr, "rango_por_calco", rango_por_calco)
    monkeypatch.setattr(ts.color_rank_ocr, "cached_rank", cached_rank)
    monkeypatch.setattr(ts.color_rank_ocr, "add_rank_jobs", add_rank_jobs)
    monkeypatch.setattr(ts.color_rank_ocr, "cache_key", lambda *a, **k: "k")
    return llamadas, cfg


def _una_caja():
    import numpy as np
    return np.zeros((300, 300, 3), np.uint8), [caja(0, "glyph")]


def test_con_calco_no_se_toca_ni_la_cache_ni_el_OCR(caminos):
    llamadas, cfg = caminos
    cfg["calco"] = "K"
    bgr, boxes = _una_caja()
    jobs = ts._encolar_cartas(object(), bgr, boxes)
    assert llamadas == ["calco"]
    assert [j[3] for j in jobs] == ["K"]
    assert [j[4] for j in jobs] == [1.0]
    assert jobs[0][1] is None and jobs[0][2] is None, "no se encolo trabajo de OCR"


def test_sin_calco_pero_con_cache_tampoco_se_encola_OCR(caminos):
    llamadas, cfg = caminos
    cfg["cache"] = (True, "9")
    bgr, boxes = _una_caja()
    jobs = ts._encolar_cartas(object(), bgr, boxes)
    assert llamadas == ["calco", "cache"]
    assert [j[3] for j in jobs] == ["9"]
    assert jobs[0][4] is None
    assert jobs[0][1] is None


def test_solo_cuando_fallan_los_dos_se_paga_el_OCR(caminos):
    llamadas, _cfg = caminos
    bgr, boxes = _una_caja()
    jobs = ts._encolar_cartas(object(), bgr, boxes)
    assert llamadas == ["calco", "cache", "ocr"]
    assert jobs[0][1] == 0 and jobs[0][2] == 3, "hay tramo de trabajos encolado"
    assert jobs[0][3] is ts._SIN_CACHE
    assert jobs[0][4] is None


def test_un_rango_de_board_obstruido_no_se_fuerza_por_OCR(caminos, monkeypatch):
    llamadas, _cfg = caminos
    monkeypatch.setattr(
        ts.color_rank_ocr,
        "rango_por_calco",
        lambda crop, deck: (None, ts.color_rank_ocr.SOLID_BOARD_RANK_SHAPE_MIN - 0.01),
    )
    bgr, boxes = _una_caja()
    boxes[0]["deck"] = "solid"

    jobs = ts._encolar_cartas(
        object(), bgr, boxes, rechazar_obstruidas=True)

    assert llamadas == []
    assert jobs[0][3] is None
    assert jobs[0][4] == 0.0


def test_el_mismo_recorte_no_se_rechaza_fuera_del_board(caminos, monkeypatch):
    llamadas, _cfg = caminos
    monkeypatch.setattr(
        ts.color_rank_ocr,
        "rango_por_calco",
        lambda crop, deck: (None, ts.color_rank_ocr.SOLID_BOARD_RANK_SHAPE_MIN - 0.01),
    )
    bgr, boxes = _una_caja()
    boxes[0]["deck"] = "solid"

    jobs = ts._encolar_cartas(object(), bgr, boxes)

    assert llamadas == ["cache", "ocr"]
    assert jobs[0][3] is ts._SIN_CACHE


def test_el_mazo_de_cada_caja_viaja_hasta_el_OCR(caminos, monkeypatch):
    """color_rank_ocr lee el rango con una polaridad u otra segun el mazo. Si el
    `deck` de la caja no llegara hasta aqui, se leeria el mazo nuevo con la
    polaridad del viejo y no saldria ni una carta."""
    vistos = []
    monkeypatch.setattr(ts.color_rank_ocr, "add_rank_jobs",
                        lambda batch, crop, deck="solid": (vistos.append(deck), (0, 1))[1])
    import numpy as np
    bgr = np.zeros((300, 300, 3), np.uint8)
    ts._encolar_cartas(object(), bgr, [caja(0, "glyph"), caja(90, "solid")])
    assert vistos == ["glyph", "solid"]


def test_los_huecos_de_rango_conservan_su_slot(monkeypatch):
    """Una carta ilegible no desplaza las cartas que están a su derecha."""
    import numpy as np

    boxes = [caja(i * 90, "solid") for i in range(5)]
    for box, suit in zip(boxes, ("heart", "spade", "club", "diamond", "heart")):
        box["suit"] = suit
    jobs = [
        (box, None, None, rank)
        for box, rank in zip(boxes, ("A", "K", None, "2", "7"))
    ]

    slots = ts._resolve_zone_card_slots(
        np.zeros((200, 500, 3), np.uint8), [], jobs)

    assert slots == ["Ah", "Ks", None, "2d", "7h"]


def test_la_confianza_conserva_el_slot_y_el_origen():
    import numpy as np

    boxes = [caja(0, "solid"), caja(90, "solid")]
    boxes[0]["suit"] = "heart"
    boxes[1]["suit"] = "club"
    slots, confianzas = ts._resolve_zone_card_slots_with_confidence(
        np.zeros((200, 300, 3), np.uint8),
        [],
        [
            (boxes[0], None, None, "A", 0.97),
            (boxes[1], None, None, None, 0.88),
        ],
    )

    assert slots == ["Ah", None]
    assert confianzas == [0.97, 0.0]


def test_el_fallback_de_board_exige_una_fila_contigua():
    contiguas = [caja(i * 90, "solid") for i in range(3)]
    resaltadas = [caja(i * 190, "solid") for i in range(3)]

    assert ts._fila_board_coherente(contiguas)
    assert not ts._fila_board_coherente(resaltadas)


def test_el_fallback_de_board_exige_alineacion_vertical():
    boxes = [caja(i * 90, "solid") for i in range(3)]
    boxes[-1]["y"] = 40

    assert not ts._fila_board_coherente(boxes)


def test_la_confianza_ocr_cuenta_tambien_los_votos_vacios():
    textos = ["A"] + [""] * 17

    rango, confianza = ts.color_rank_ocr.resolve_rank_with_confidence(textos)

    assert rango == "A"
    assert confianza == pytest.approx(2 / 27)


def test_un_empate_ocr_se_abstiene_tambien_en_la_salida_puntuada():
    rango, confianza = ts.color_rank_ocr.resolve_rank_with_confidence(
        ["A", "K"] + [""] * 16)

    assert rango is None
    assert confianza == 0.0
