"""
Verificacion del pool de workers de OCR persistentes (vision/ocr_client.py).

Por que existe el pool: el suelo de un lote era ~0,15 s aunque solo llevara UN
recorte, porque eso es arrancar python, importar PIL/tesserocr y cargar el modelo
-no el OCR-. Con 6 trozos por frame se pagaba ese arranque 6 veces por frame, y
con el vigilante rapido (seat_watch) haciendo lotes de una sola capsula el
arranque ERA todo el coste. Medido tras el cambio: 6 jobs pasan de 0,145 s a
0,005 s, y el OCR de una capsula de nameplate de ~250 ms a 39 ms.

Lo que de verdad protege este test:

  1. Que los resultados sigan saliendo BIEN y EN ORDEN. Un pool que reordena
     resultados es peor que no tener pool: cada recorte acabaria interpretado
     como otra cosa.
  2. Que un worker muerto no tumbe el frame (se reemplaza y se reintenta).
  3. Que no queden procesos sueltos, ni por sesion larga ni al cerrar.

Uso: .venv/bin/python vision/test_ocr_pool.py
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import ocr_client as oc

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def texto(t):
    """Imagen negra sobre blanco con un texto, para que el OCR tenga algo real."""
    img = np.full((70, 260, 3), 255, dtype=np.uint8)
    cv2.putText(img, t, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3)
    return img


def procesos_vivos():
    out = subprocess.run(["pgrep", "-f", "ocr_worker.py --serve"],
                         capture_output=True, text=True)
    return [p for p in out.stdout.split() if p]


# --- resultados correctos y EN ORDEN ---------------------------------------
print("# --- resultados y orden ---")
oc.cerrar_workers()
b = oc.OcrBatch()
palabras = ["ABC", "123", "XYZ"]
for p in palabras:
    b.add_text_job(texto(p), whitelist="ABCXYZ0123456789")
res = b.run()
check("devuelve un resultado por job", len(res) == 3)
aciertos = sum(1 for p, r in zip(palabras, res) if p in r.replace(" ", ""))
check(f"y cada uno corresponde a SU recorte ({aciertos}/3 leidos)", aciertos >= 2)

# los recortes vacios siguen devolviendo "" y sin descolocar al resto
b = oc.OcrBatch()
b.add_text_job(texto("ABC"), whitelist="ABC")
b.add_text_job(np.zeros((0, 0, 3), dtype=np.uint8))
b.add_text_job(texto("XYZ"), whitelist="XYZ")
res = b.run()
check("un recorte vacio devuelve '' sin descolocar los demas",
      len(res) == 3 and res[1] == "" and "ABC" in res[0].replace(" ", ""))

# --- los workers se REUTILIZAN ---------------------------------------------
print("\n# --- persistencia ---")
oc.cerrar_workers()
oc.OcrBatch().run()                       # lote vacio: no arranca nada
b = oc.OcrBatch()
b.add_text_job(texto("A"), whitelist="A")
b.run()
libres_1 = list(oc._POOL._libres)
check("tras un lote queda un worker VIVO en el pool",
      len(libres_1) == 1 and libres_1[0].vivo())
b = oc.OcrBatch()
b.add_text_job(texto("A"), whitelist="A")
b.run()
check("y el siguiente lote REUTILIZA ese mismo worker, no arranca otro",
      list(oc._POOL._libres) == libres_1)

# --- un worker muerto no tumba el frame ------------------------------------
print("\n# --- resiliencia ---")
libres_1[0].proc.kill()
libres_1[0].proc.wait(timeout=5)
b = oc.OcrBatch()
b.add_text_job(texto("XYZ"), whitelist="XYZ")
res = b.run()
check("si el worker del pool ha muerto, se arranca otro y el lote sale igual",
      len(res) == 1 and res[0] is not None)
check("y el pool queda con un worker sano",
      len(oc._POOL._libres) == 1 and oc._POOL._libres[0].vivo())

# --- el pool esta acotado y se cierra --------------------------------------
print("\n# --- limpieza ---")
for _ in range(oc.MAX_PROCS + 4):
    w = oc._Worker()
    oc._POOL._soltar(w)
check("el pool no crece por encima de MAX_PROCS en una sesion larga",
      len(oc._POOL._libres) <= oc.MAX_PROCS)

oc.cerrar_workers()
check("cerrar_workers() vacia el pool", oc._POOL._libres == [])
check("y no deja procesos sueltos", procesos_vivos() == [])

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
