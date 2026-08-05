"""
El OCR con modelo de vision, sin modelo delante.

Lo que se prueba es la COSTURA, que es lo unico que puede romper el pipeline: que
lo que devuelve este backend lo sepa leer text_extract.parse_tsv_lines igual que
lo que devuelve tesseract. Si eso falla, el frame no da error: da un GameState
vacio, y el sintoma aparece como "no se leen los nameplates" a dos capas de
distancia.

Las llamadas al servidor se sustituyen. Medir al modelo es otra cosa y tiene su
propia herramienta (herramientas/comparar_ocr.py), que necesita el corpus.
"""
import base64

import cv2
import numpy as np
import pytest

from vision import ocr_vlm
from vision import text_extract


def png_b64(ancho, alto):
    img = np.full((alto, ancho, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


# --- el TSV sintetico y su unico cliente -------------------------------------

def test_el_tsv_sintetico_lo_lee_parse_tsv_lines():
    """LA PRUEBA QUE IMPORTA: el formato es un contrato con text_extract, no una
    cadena cualquiera. parse_tsv_lines exige 12 columnas, nivel 5 y confianza
    >= 25; cualquier descuido ahi devuelve cero lineas en silencio."""
    tsv = ocr_vlm.tsv_sintetico(["alex_delg", "196,8 BB"], ancho=300, alto=100)
    lineas = text_extract.parse_tsv_lines(tsv)
    assert [l["text"] for l in lineas] == ["alex_delg", "196,8 BB"]


def test_el_nombre_queda_ENCIMA_del_stack():
    """De lo que se lee en una capsula, lo unico geometrico que se pregunta es
    quien esta arriba: _seat_plate_name_stack empareja el nombre con el numero de
    debajo. Si el reparto vertical no conservara el orden, el stack se asignaria
    al reves."""
    tsv = ocr_vlm.tsv_sintetico(["PaquidermeMS", "166,6 BB"], ancho=300, alto=100)
    nombre, stack = text_extract.parse_tsv_lines(tsv)
    assert nombre["cy"] < stack["cy"]


def test_las_palabras_de_una_linea_van_de_izquierda_a_derecha():
    tsv = ocr_vlm.tsv_sintetico(["Bote: 2,1 BB"], ancho=300, alto=40)
    (linea,) = text_extract.parse_tsv_lines(tsv)
    assert linea["text"] == "Bote: 2,1 BB"
    assert linea["left"] < linea["right"] <= 300


def test_sin_lineas_no_hay_tsv():
    """Cadena vacia es lo que devuelve tesseract cuando no lee nada, y es lo que
    el pipeline sabe tratar."""
    assert ocr_vlm.tsv_sintetico([], 100, 50) == ""


def test_un_recorte_de_una_sola_linea_no_divide_por_cero():
    tsv = ocr_vlm.tsv_sintetico(["A"], ancho=10, alto=1)
    assert text_extract.parse_tsv_lines(tsv)[0]["text"] == "A"


# --- lo que el modelo dice cuando no ve nada ---------------------------------

@pytest.mark.parametrize("respuesta", [
    "No text is visible in this image.",
    "nothing",
    "```\n```",
    "   \n  \n",
    "N/A",
])
def test_las_formas_de_decir_nada_no_entran_como_texto_de_la_mesa(respuesta):
    """UN MODELO NO SE CALLA: donde tesseract devuelve "", el escribe una frase.
    Si esa frase entrara en el TSV, text_extract la trataria como texto leido de
    la mesa y podria colarse como nombre de jugador."""
    assert ocr_vlm.lineas_limpias(respuesta) == []


def test_el_texto_de_verdad_si_pasa():
    assert ocr_vlm.lineas_limpias("alex_delg\n196,8 BB\n") == ["alex_delg", "196,8 BB"]


# --- el tamaño del recorte ---------------------------------------------------

def test_el_tamano_sale_de_la_cabecera_del_png():
    """Se lee del IHDR para no meter PIL ni cv2 en la ruta del backend."""
    assert ocr_vlm._tamano_png(png_b64(320, 96)) == (320, 96)


# --- leer la mesa de una llamada ---------------------------------------------

def test_leer_mesa_parsea_nombre_e_importe(monkeypatch):
    monkeypatch.setattr(ocr_vlm, "_pedir", lambda *a, **k:
                        "maru341|207,7 BB\nalex_delg|196,8 BB\n\nPOT|2,1 BB")
    r = ocr_vlm.leer_mesa(np.zeros((100, 200, 3), np.uint8))
    assert r["jugadores"] == {"maru341": "207,7 BB", "alex_delg": "196,8 BB"}
    assert r["bote"] == "2,1 BB"


def test_leer_mesa_aguanta_una_linea_sin_barra(monkeypatch):
    """El modelo mete de vez en cuando una linea suelta. Tirarla es lo correcto:
    no hay forma de saber si era un nombre o un importe."""
    monkeypatch.setattr(ocr_vlm, "_pedir", lambda *a, **k:
                        "Aqui van los jugadores:\nmaru341|207,7 BB")
    assert ocr_vlm.leer_mesa(np.zeros((10, 10, 3), np.uint8))["jugadores"] == {
        "maru341": "207,7 BB"}


def test_un_nameplate_sin_importe_no_inventa_stack(monkeypatch):
    monkeypatch.setattr(ocr_vlm, "_pedir", lambda *a, **k: "NORMANDISC|")
    assert ocr_vlm.leer_mesa(np.zeros((10, 10, 3), np.uint8))["jugadores"] == {
        "NORMANDISC": None}


# --- el backend como resolvedor de lotes -------------------------------------

def test_el_backend_devuelve_un_resultado_por_job(monkeypatch):
    monkeypatch.setattr(ocr_vlm, "_pedir", lambda *a, **k: "K")
    jobs = [{"mode": "text", "png_b64": png_b64(20, 30)},
            {"mode": "tsv", "png_b64": png_b64(200, 60)}]
    res = ocr_vlm.backend(jobs)
    assert len(res) == 2
    assert res[0] == "K"
    assert text_extract.parse_tsv_lines(res[1])[0]["text"] == "K"


def test_un_job_que_falla_no_se_lleva_el_lote(monkeypatch):
    """Igual que en el worker de tesseract: perder un recorte es mucho menos
    grave que perder el frame entero."""
    def revienta(png_b64_, prompt, **k):
        if prompt is ocr_vlm.PROMPT_TEXT:
            raise ValueError("respuesta rara")
        return "hola"
    monkeypatch.setattr(ocr_vlm, "_pedir", revienta)
    res = ocr_vlm.backend([{"mode": "text", "png_b64": png_b64(20, 30)},
                           {"mode": "tsv", "png_b64": png_b64(200, 60)}])
    assert res[0] == ""
    assert "hola" in res[1]


def test_si_el_servidor_no_esta_se_dice_y_no_se_devuelve_basura(monkeypatch):
    """Un servidor caido no es "el recorte no se leia": son TODOS los recortes, y
    devolver "" en ese caso seria un frame que parece analizado y no lo esta."""
    def caido(*_a, **_k):
        raise ocr_vlm.ServidorVlmCaido("nadie escucha")
    monkeypatch.setattr(ocr_vlm, "_pedir", caido)
    with pytest.raises(ocr_vlm.ServidorVlmCaido):
        ocr_vlm.backend([{"mode": "tsv", "png_b64": png_b64(200, 60)}])


def test_un_job_vacio_devuelve_vacio():
    assert ocr_vlm.resolver_job({"mode": "tsv"}) == ""
