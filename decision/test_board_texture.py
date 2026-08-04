import pytest

from decision import board_texture as bt


@pytest.mark.parametrize("board, esperado", [
    # tres cartas dentro de una ventana de 5: la escalera ya está para quien
    # tenga las dos que faltan (76 sobre 985)
    (["9d", "8h", "5c"], "conectado"),
    (["Ah", "2d", "3c"], "conectado"),          # la rueda: el as vale 1
    (["Th", "9d", "4c"], "proyecto_escalera"),  # 87 o QJ dan OESD
    (["Kh", "Qd", "2c"], "proyecto_escalera"),  # JT da JTQK, abierto por 9 y A
    (["Kh", "7d", "2c"], "desconectado"),       # el board seco de manual
])
def test_conexion(board, esperado):
    assert bt.clasificar(board)["conexion"] == esperado


def test_as_y_rey_no_son_un_proyecto_abierto():
    """El fallo que motivó razonar por ventanas y no por distancia entre cartas.

    A y K están a distancia 1, pero la única escalera que las contiene es
    TJQKA: con QJ en la mano falta el T y solo el T, así que es un proyecto a un
    extremo. Tratarlo como OESD subía la frecuencia de c-bet en un board seco.
    """
    assert bt.clasificar(["Ah", "Kd", "6c"])["conexion"] == "desconectado"
    # y la simétrica de abajo SÍ es abierta: 5432 se completa con A o con 6
    assert bt.clasificar(["3h", "2d", "9c"])["conexion"] == "proyecto_escalera"


@pytest.mark.parametrize("board, esperado", [
    (["Kh", "7d", "2c"], "arcoiris"),
    (["Kh", "7h", "2c"], "dos_palos"),
    (["Kh", "7h", "2h"], "monocolor"),
    (["Kh", "7h", "2h", "9h"], "cuatro_del_palo"),
    (["Kh", "7h", "2h", "9h", "3h"], "color_en_board"),
    (["Kh", "7h", "2d", "9c", "3h"], "tres_del_palo"),
])
def test_palos(board, esperado):
    assert bt.clasificar(board)["palos"] == esperado


@pytest.mark.parametrize("board, esperado", [
    (["Kh", "7d", "2c"], "sin_emparejar"),
    (["7h", "7d", "2c"], "emparejado"),
    (["7h", "7d", "2c", "2s"], "doble_pareja_en_board"),
    (["7h", "7d", "7c"], "trio_en_board"),
    (["7h", "7d", "7c", "7s"], "poker_en_board"),
])
def test_emparejamiento(board, esperado):
    assert bt.clasificar(board)["emparejamiento"] == esperado


@pytest.mark.parametrize("board, categoria", [
    (["Ah", "7d", "2c"], "as"),
    (["Kh", "7d", "2c"], "broadway_alto"),
    (["Jh", "7d", "2c"], "broadway_bajo"),
    (["9h", "7d", "2c"], "medio"),
    (["6h", "4d", "2c"], "bajo"),
])
def test_categoria_de_carta_alta(board, categoria):
    """El as va aparte de las demás cartas altas porque la fuente lo trata
    aparte: en board de as se apuesta MENOS, no más."""
    assert bt.clasificar(board)["carta_alta_categoria"] == categoria


@pytest.mark.parametrize("board", [
    [], ["Kh"], ["Kh", "7d"],                     # menos de un flop
    ["Kh", "7d", "2c", "9s", "4h", "8d"],         # más de un river
    ["Kh", "7d", "Kh"],                           # carta repetida: OCR roto
    ["Xh", "7d", "2c"], ["K", "7d", "2c"],        # códigos ilegibles
    ["Kz", "7d", "2c"],
    "Kh7d2c", None,
])
def test_se_abstiene_en_vez_de_inventar_una_textura(board):
    """Una textura 'neutra' se propagaría a un tamaño de apuesta con toda la
    apariencia de estar fundada."""
    assert bt.clasificar(board) is None


def test_describir_es_legible_y_nombra_los_tres_ejes():
    texto = bt.describir(bt.clasificar(["Kh", "Qh", "Qd"]))
    assert "K alta" in texto
    assert "emparejado" in texto
    assert texto == bt.describir(bt.clasificar(["Kh", "Qh", "Qd"]))


def test_describir_sin_textura_no_revienta():
    assert bt.describir(None) == ""


def test_la_humedad_ordena_de_seco_a_mojado():
    seco = bt.clasificar(["Kh", "7d", "2c"])["humedad"]
    medio = bt.clasificar(["Th", "9d", "4c"])["humedad"]
    mojado = bt.clasificar(["9h", "8h", "5h"])["humedad"]
    assert seco < medio < mojado
