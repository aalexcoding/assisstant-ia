"""
Verificacion del pool de workers de OCR persistentes (vision/ocr_client.py).

Por que existe el pool: el suelo de un lote era ~0,15 s aunque solo llevara UN
recorte, porque eso es arrancar python, importar PIL/tesserocr y cargar el modelo
-no el OCR-. Con 6 trozos por frame se pagaba ese arranque 6 veces por frame, y
con el vigilante rapido (seat_watch) haciendo lotes de una sola capsula el
arranque ERA todo el coste. Medido tras el cambio: 6 jobs pasan de 0,145 s a
0,005 s, y el OCR de una capsula de nameplate de ~250 ms a 39 ms.

Lo que de verdad protege:

  1. Que los resultados sigan saliendo BIEN y EN ORDEN. Un pool que reordena
     resultados es peor que no tener pool: cada recorte acabaria interpretado
     como otra cosa.
  2. Que un worker muerto no tumbe el frame (se reemplaza y se reintenta).
  3. Que no queden procesos sueltos, ni por sesion larga ni al cerrar.

Estos SI arrancan tesseract de verdad: es lo unico que prueba el pool.
"""
import subprocess

import cv2
import numpy as np
import pytest

from vision import ocr_client as oc

pytestmark = [pytest.mark.vision, pytest.mark.lento]


def texto(t):
    """Imagen negra sobre blanco con un texto, para que el OCR tenga algo real."""
    img = np.full((70, 260, 3), 255, dtype=np.uint8)
    cv2.putText(img, t, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    return img


def procesos_vivos():
    out = subprocess.run(["pgrep", "-f", "vision.ocr_worker --serve"],
                         capture_output=True, text=True)
    return [p for p in out.stdout.split() if p]


@pytest.fixture(autouse=True)
def pool_limpio():
    """Cada test parte de un pool vacio y lo deja vacio: si no, el estado de los
    workers se arrastra y el orden de ejecucion decide el resultado."""
    oc.restaurar_backend()
    oc.cerrar_workers()
    yield
    oc.cerrar_workers()


# --- resultados correctos y EN ORDEN ----------------------------------------

def test_cada_resultado_corresponde_a_su_recorte():
    """Un pool que reordena resultados es peor que no tener pool."""
    palabras = ["ABC", "123", "XYZ"]
    b = oc.OcrBatch()
    for p in palabras:
        b.add_text_job(texto(p), whitelist="ABCXYZ0123456789")
    res = b.run()
    assert len(res) == 3
    aciertos = sum(1 for p, r in zip(palabras, res) if p in r.replace(" ", ""))
    assert aciertos >= 2, f"solo {aciertos}/3 leidos: {res}"


def test_un_recorte_vacio_devuelve_cadena_vacia_sin_descolocar_los_demas():
    b = oc.OcrBatch()
    b.add_text_job(texto("ABC"), whitelist="ABC")
    b.add_text_job(np.zeros((0, 0, 3), dtype=np.uint8))
    b.add_text_job(texto("XYZ"), whitelist="XYZ")
    res = b.run()
    assert len(res) == 3
    assert res[1] == ""
    assert "ABC" in res[0].replace(" ", "")


# --- los workers se REUTILIZAN ----------------------------------------------

def test_un_lote_vacio_no_arranca_ningun_worker():
    oc.OcrBatch().run()
    assert oc._POOL._libres == []


def test_tras_un_lote_queda_un_worker_vivo_y_el_siguiente_lo_reutiliza():
    b = oc.OcrBatch()
    b.add_text_job(texto("A"), whitelist="A")
    b.run()
    libres = list(oc._POOL._libres)
    assert len(libres) == 1 and libres[0].vivo()

    b = oc.OcrBatch()
    b.add_text_job(texto("A"), whitelist="A")
    b.run()
    assert list(oc._POOL._libres) == libres, "no arranca otro"


# --- un worker muerto no tumba el frame -------------------------------------

def test_si_el_worker_del_pool_ha_muerto_el_lote_sale_igual():
    b = oc.OcrBatch()
    b.add_text_job(texto("A"), whitelist="A")
    b.run()
    muerto = oc._POOL._libres[0]
    muerto.proc.kill()
    muerto.proc.wait(timeout=5)

    b = oc.OcrBatch()
    b.add_text_job(texto("XYZ"), whitelist="XYZ")
    res = b.run()
    assert len(res) == 1 and res[0] is not None
    assert len(oc._POOL._libres) == 1 and oc._POOL._libres[0].vivo()


# --- el pool esta acotado y se cierra ---------------------------------------

def test_el_pool_no_crece_por_encima_de_max_procs():
    """En una sesion larga se sueltan muchos workers y no pueden acumularse."""
    for _ in range(oc.MAX_PROCS + 4):
        oc._POOL._soltar(oc._Worker())
    assert len(oc._POOL._libres) <= oc.MAX_PROCS


def test_cerrar_workers_vacia_el_pool_y_no_deja_procesos_sueltos():
    b = oc.OcrBatch()
    b.add_text_job(texto("A"), whitelist="A")
    b.run()
    oc.cerrar_workers()
    assert oc._POOL._libres == []
    assert procesos_vivos() == []


# --- la costura para los tests que NO quieren tesseract ---------------------

def test_el_backend_de_ocr_se_puede_sustituir():
    """Es lo que permite ejercitar table_state.analyze_layout sin tesseract, sin
    subprocesos y en milisegundos."""
    anterior = oc.usar_backend(lambda jobs: ["FALSO"] * len(jobs))
    try:
        b = oc.OcrBatch()
        b.add_text_job(texto("ABC"), whitelist="ABC")
        b.add_text_job(texto("XYZ"), whitelist="XYZ")
        assert b.run() == ["FALSO", "FALSO"]
        assert oc._POOL._libres == [], "no se arranco ningun proceso"
    finally:
        oc.usar_backend(anterior)


def test_restaurar_backend_vuelve_al_pool_real():
    oc.usar_backend(lambda jobs: ["FALSO"] * len(jobs))
    oc.restaurar_backend()
    assert oc._BACKEND is oc._backend_real
