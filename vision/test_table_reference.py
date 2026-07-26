"""
Verificacion de la GUARDA DE REFERENCIA de table_state.analyze_layout().

Todas las zonas del reconocimiento (nameplates, cartas, bote, botones, chat) son
fracciones del nucleo del tapete. Si el ovalo no se detecta, TODAS quedan
desplazadas y lo que salga son lecturas de sitios equivocados: el peor tipo de
salida, porque parece un resultado. Antes se seguia adelante con la "posicion
tipica" como fallback; medido sobre 999 frames de una sesion real, de los 21 que
cayeron en fallback CERO dieron cartas, boton, posicion, stack o recomendacion.

Aqui se fija que analyze_layout CORTA en ese caso, y que el aviso nombra las dos
cosas que el usuario puede arreglar (el tema del tapete y la calibracion). El
caso real que lo motivo: cambiar a un tapete gris oscuro (S=0, V=34) hizo fallar
la deteccion en el 100% de los frames, frente al 98% de acierto con el verde
(S=200, V=115), porque find_reference exige S>=45 y V>=60.

Sin depender de capturas: las imagenes se generan aqui, porque testing/ y
samples*/ estan fuera del repo.

Uso: .venv/bin/python vision/test_table_reference.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import seat_map
import table_state as ts

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def frame(color_tapete):
    """Un frame 1200x800 con un ovalo grande del color dado sobre fondo casi
    negro, que es la forma del cliente real."""
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    if color_tapete is not None:
        cv2.ellipse(img, (600, 400), (460, 230), 0, 0, 360, color_tapete, -1)
    return img


def analizar(img):
    ruta = os.path.join(tempfile.mkdtemp(prefix="test_ref_"), "f.png")
    cv2.imwrite(ruta, img)
    try:
        return ts.analyze_layout(ruta)
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


# --- un tapete CON COLOR se detecta ---------------------------------------
print("# --- tapete con color ---")
verde = frame((40, 120, 40))            # BGR: verde saturado, como el tema por defecto
ref = seat_map.find_reference(verde)
check("un tapete verde da referencia real, no fallback", ref[4] is False)
check("y el ovalo detectado ocupa la mayor parte del frame",
      ref[2] > 0.5 * verde.shape[1] and ref[3] > 0.3 * verde.shape[0])

# --- un tapete GRIS/OSCURO no, y ahi esta el fallo real --------------------
print("\n# --- tapete gris oscuro (el caso que rompio la app) ---")
gris = frame((45, 45, 45))               # BGR gris: saturacion CERO
ref_gris = seat_map.find_reference(gris)
check("un tapete gris no se detecta: saturacion cero, no pasa S>=45",
      ref_gris[4] is True)

st = analizar(gris)
check("analyze_layout CORTA en vez de analizar con las zonas desplazadas",
      st["players"] == [] and st["hero_cards"] == [] and st["board"] == [])
check("y no llega ni a hacer OCR (no hay lineas de chat)", st["chat_lines"] == [])
aviso = " ".join(st["warnings"])
check("el aviso dice que no se encuentra la mesa", "no se encuentra la mesa" in aviso)
check("y nombra el tapete oscuro como causa", "OSCURO" in aviso or "oscuro" in aviso)
check("y la recalibracion como la otra causa", "recalibra" in aviso)
check("el esquema sigue siendo un GameState valido",
      st["stack_unit"] == "bb" and "pot" in st and "to_call" in st)

# --- sin tapete de ninguna clase ------------------------------------------
print("\n# --- frame sin mesa (lobby, escritorio) ---")
st = analizar(frame(None))
check("un frame sin mesa tampoco inventa nada",
      st["players"] == [] and any("no se encuentra la mesa" in w for w in st["warnings"]))

# --- una imagen ilegible sigue avisando de lo suyo -------------------------
print("\n# --- imagen ilegible ---")
st = ts.analyze_layout("/no/existe/ninguna.png")
check("una ruta que no existe da su propio aviso, no el de la mesa",
      any("no se pudo leer la imagen" in w for w in st["warnings"]))

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
