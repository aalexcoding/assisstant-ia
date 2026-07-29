"""
Verificacion de la vara de medir cartas (herramientas/score_cartas.py).

Una vara mal graduada es peor que no tener vara: da un numero, se cree, y se
toman decisiones con el. Lo que hay que blindar aqui es el CRITERIO del chequeo
contra el chat, que es la unica etiqueta de verdad que tiene el proyecto y cuya
solidez depende de ir en UNA SOLA DIRECCION.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "herramientas"))

import score_cartas as sc          # noqa: E402


# --- que rangos afirma la frase del chat ------------------------------------

@pytest.mark.parametrize("frase, esperado", [
    ("pareja de nueves", [("9", 2)]),
    ("trio de reyes", [("K", 3)]),
    ("poker de ases", [("A", 4)]),
    ("doble pareja, dieces y cuatros", [("T", 2), ("4", 2)]),
    ("Trío de Damas", [("Q", 3)]),               # mayusculas y tilde
])
def test_se_leen_los_rangos_que_nombra_el_chat(frase, esperado):
    assert sc._rangos_nombrados(frase) == esperado


@pytest.mark.parametrize("frase", [
    "color", "escalera de color, de dos a seis", "carta alta", "full", "", None,
])
def test_las_jugadas_que_no_van_por_rango_no_afirman_nada(frase):
    """Un color o una escalera no dicen cuantas cartas del mismo rango hay, asi
    que de ellas no se puede sacar ninguna comprobacion."""
    assert sc._rangos_nombrados(frase) == []


def test_una_frase_truncada_sigue_sirviendo():
    """El chat se lee por OCR y llega cortado a menudo ('doble pareja, dieces y'
    es literal de una sesion). Lo que se alcance a leer se aprovecha."""
    assert sc._rangos_nombrados("doble pareja, dieces y") == [("T", 2)]


# --- el chequeo, que va en UNA sola direccion -------------------------------

def test_el_board_no_puede_tener_MAS_del_rango_que_el_chat_nombra():
    """Si el ganador tiene doble pareja de dieces, el board no puede llevar tres
    dieces: con tres en la mesa el ganador tendria trio y el cliente lo habria
    escrito. Un tercer diez en el board solo puede venir de una carta mal leida."""
    assert sc._contradice_al_chat(["Th", "Td", "Tc", "4s", "2d"],
                                  "doble pareja, dieces y cuatros")


def test_pero_que_el_board_no_tenga_NINGUNO_es_normal():
    """Las dos cartas del rango pueden ir en la mano del ganador, que no se ve.
    Contar esto como fallo llenaria la medicion de falsos positivos y es la
    tentacion que hay que resistir."""
    assert not sc._contradice_al_chat(["9h", "8d", "2c", "3s", "5d"],
                                      "doble pareja, dieces y cuatros")


def test_el_caso_normal_no_salta():
    """Board real de una sesion: dos dieces y dos cuatros, doble pareja. Cuadra."""
    assert not sc._contradice_al_chat(["Jc", "4c", "4d", "Th", "Tc"],
                                      "doble pareja, dieces y")


def test_un_trio_admite_tres_en_el_board():
    assert not sc._contradice_al_chat(["Kh", "Kd", "Kc", "4s", "2d"], "trio de reyes")
    assert sc._contradice_al_chat(["Kh", "Kd", "Kc", "Ks", "2d"], "trio de reyes")


def test_sin_board_no_se_afirma_nada():
    assert not sc._contradice_al_chat([], "trio de reyes")


# --- el reparto de rangos se cuenta por MANO -------------------------------

def test_el_reparto_de_rangos_cuenta_una_vez_por_mano(tmp_path):
    """Un board se ve en decenas de frames seguidos. Contarlo una vez por frame
    no mide el mazo, mide cuanto duro la mano: sobre los primeros 300 frames de
    una sesion real eso daba 8,4% de figuras y por mano 20,2%, con el mismo
    codigo y los mismos datos."""
    import json
    estado = {"players": [], "hero_cards": [], "mano_seguida": 1,
              "stack_unit": "bb", "warnings": ["x"], "board": ["Kh", "Kd", "Kc"]}
    for i in range(1, 21):                      # 20 frames de LA MISMA mano
        (tmp_path / f"{i:04d}.json").write_text(json.dumps({"state": estado}))
    _n, _p, _f, rangos = sc.puntua(str(tmp_path))
    assert sum(rangos.values()) == 3, f"se contaron {sum(rangos.values())} cartas, no 3"
    assert rangos["K"] == 3


def test_de_cada_mano_se_queda_el_board_MAS_LARGO(tmp_path):
    """El board crece dentro de la mano; la muestra buena es el river, no el flop
    que se vio primero."""
    import json
    for i, board in enumerate([["Kh", "Kd", "2c"], ["Kh", "Kd", "2c", "9s"],
                               ["Kh", "Kd", "2c", "9s", "As"]], start=1):
        (tmp_path / f"{i:04d}.json").write_text(json.dumps({"state": {
            "players": [], "hero_cards": [], "mano_seguida": 7,
            "stack_unit": "bb", "warnings": ["x"], "board": board}}))
    _n, _p, _f, rangos = sc.puntua(str(tmp_path))
    assert sum(rangos.values()) == 5
    assert rangos["A"] == 1 and rangos["9"] == 1
