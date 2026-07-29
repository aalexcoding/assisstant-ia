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
    assert jobs[0][1] is None and jobs[0][2] is None, "no se encolo trabajo de OCR"


def test_sin_calco_pero_con_cache_tampoco_se_encola_OCR(caminos):
    llamadas, cfg = caminos
    cfg["cache"] = (True, "9")
    bgr, boxes = _una_caja()
    jobs = ts._encolar_cartas(object(), bgr, boxes)
    assert llamadas == ["calco", "cache"]
    assert [j[3] for j in jobs] == ["9"]
    assert jobs[0][1] is None


def test_solo_cuando_fallan_los_dos_se_paga_el_OCR(caminos):
    llamadas, _cfg = caminos
    bgr, boxes = _una_caja()
    jobs = ts._encolar_cartas(object(), bgr, boxes)
    assert llamadas == ["calco", "cache", "ocr"]
    assert jobs[0][1] == 0 and jobs[0][2] == 3, "hay tramo de trabajos encolado"
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
