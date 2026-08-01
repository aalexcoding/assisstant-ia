"""Banco de prueba visual del board sobre una sesión real.

Las etiquetas de ``VERDAD_BOARD`` se transcribieron mirando los PNG, no sus
JSON: esos JSON contienen la salida de una versión anterior de la propia app y
por tanto no son una fuente independiente. El benchmark compara ``board_slots``
(percepción cruda del frame) en vez de ``board`` (resultado del estabilizador
temporal).

La sesión no se versiona porque ``testing/`` es el corpus local. Si no está
presente, pytest omite este módulo; en la máquina de desarrollo se ejecuta con:

    pytest -q tests/test_board_benchmark.py
"""
from pathlib import Path

import cv2
import pytest

from core import Analizador
from replay import configuracion_sesion, frames
from vision import seat_map
from vision.table_state import analyze_layout


pytestmark = [pytest.mark.corpus, pytest.mark.lento, pytest.mark.vision]

RAIZ = Path(__file__).resolve().parents[1]
SESION = RAIZ / "testing" / "sesion-2026-07-31_003011"
SESION_RECIENTE = RAIZ / "testing" / "sesion-2026-07-31_011143"

# Etiquetas manuales de las cartas físicamente visibles, de izquierda a derecha.
# Cubren cinco manos, las tres calles, dos runouts que cambian en frames
# consecutivos y la transición a una mesa vacía.
VERDAD_BOARD = {
    1: ["Qd", "Ad", "9h", "4c", "7d"],
    17: ["3s", "8d", "Ad"],
    45: ["7s", "Ac", "9h"],
    64: ["9d", "7s", "Js"],
    65: ["9d", "7s", "Js", "5s"],
    66: ["9d", "7s", "Js", "5s", "4s"],
    67: ["9d", "7s", "Js", "5s", "4s"],
    85: ["Ac", "9d", "Ks"],
    86: ["Ac", "9d", "Ks", "Kc"],
    87: ["Ac", "9d", "Ks", "Kc", "9s"],
    88: ["Ac", "9d", "Ks", "Kc", "9s"],
    89: ["Ac", "9d", "Ks", "Kc", "9s"],
    69: [],
}

# Segunda tanda manual. El frame 271 conoce el board por continuidad, pero dos
# índices están físicamente tapados por fichas: la salida correcta de percepción
# es conservar sus posiciones como ``None``, no adivinar el rango.
VERDAD_BOARD_RECIENTE = {
    9: ["Td", "5h", "4s"],
    12: ["Td", "5h", "4s", "9h"],
    15: ["Td", "5h", "4s", "9h", "Ac"],
    64: ["7s", "2h", "6h"],
    71: ["7s", "2h", "6h", "Kd"],
    108: ["Kh", "2s", "6d"],
    109: ["Kh", "2s", "6d", "Qh"],
    110: ["Kh", "2s", "6d", "Qh", "3h"],
    126: ["Kc", "Ks", "Qs"],
    130: ["Kc", "Ks", "Qs", "8s"],
    133: ["Kc", "Ks", "Qs", "8s", "2c"],
    159: ["9c", "Kh", "5d"],
    166: ["9c", "Kh", "5d", "4h"],
    246: ["Ah", "6d", "8d"],
    253: ["Ah", "6d", "8d", "4s"],
    270: ["Ah", "6d", "8d", "4s"],
    271: ["Ah", "6d", None, None],
    272: ["Ah", "6d", "8d", "4s"],
    273: ["Ah", "6d", "8d", "4s", "7s"],
}


@pytest.fixture(scope="module")
def lecturas():
    if not SESION.is_dir():
        pytest.skip(f"no está disponible el corpus local: {SESION}")

    max_players, mazo = configuracion_sesion(str(SESION))
    analizador = Analizador(
        max_players=max_players,
        mazo=mazo,
        seed_equity=1,
    )
    salida = {}
    try:
        for numero, png, _grabado in frames(str(SESION)):
            resultado = analizador.analizar(png)
            if numero in VERDAD_BOARD or numero == 68:
                salida[numero] = resultado.state.get("board_slots")
            if numero >= max(max(VERDAD_BOARD), 68):
                break
    finally:
        analizador.cerrar()
    return salida


def test_reconoce_las_etiquetas_manuales_del_board(lecturas):
    diferencias = {
        numero: {"esperado": esperado, "leido": lecturas.get(numero)}
        for numero, esperado in VERDAD_BOARD.items()
        if lecturas.get(numero) != esperado
    }
    assert not diferencias, diferencias


def test_conserva_la_percepcion_cruda_durante_la_animacion(lecturas):
    assert lecturas[68] == ["9d", "7s", "Js", "5s", "4s"]


@pytest.fixture(scope="module")
def lecturas_recientes():
    if not SESION_RECIENTE.is_dir():
        pytest.skip(f"no está disponible el corpus local: {SESION_RECIENTE}")
    salida = {}
    for numero, esperado in VERDAD_BOARD_RECIENTE.items():
        ruta = SESION_RECIENTE / f"{numero:04d}.png"
        state = analyze_layout(
            str(ruta),
            max_players=6,
            mazo="solid",
            leer_chat=False,
        )
        salida[numero] = state.get("board_slots")
    return salida


def test_reconoce_los_boards_manuales_de_la_sesion_reciente(
        lecturas_recientes):
    diferencias = {
        numero: {"esperado": esperado, "leido": lecturas_recientes.get(numero)}
        for numero, esperado in VERDAD_BOARD_RECIENTE.items()
        if lecturas_recientes.get(numero) != esperado
    }
    assert not diferencias, diferencias


def test_el_fallback_limitado_recupera_solo_la_fila_completa():
    if not SESION_RECIENTE.is_dir():
        pytest.skip(f"no está disponible el corpus local: {SESION_RECIENTE}")

    referencia = seat_map.ReferenciaFijada()
    for numero in range(1, 274):
        image = cv2.imread(str(SESION_RECIENTE / f"{numero:04d}.png"))
        referencia.de(image)

    estados = {
        numero: analyze_layout(
            str(SESION_RECIENTE / f"{numero:04d}.png"),
            max_players=6,
            mazo="solid",
            referencia=referencia,
            leer_chat=False,
        )
        for numero in (274, 275, 276)
    }

    assert estados[274]["table_reference_valid"] is False
    assert estados[274]["board_slots"] == ["Ah", "6d", "8d", "4s", "7s"]
    assert estados[274]["players"] == []
    assert estados[275]["board_slots"] == []
    assert estados[276]["board_slots"] == []
