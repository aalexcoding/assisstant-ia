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

# --- lecturas de OCR con VARIAS LINEAS -------------------------------------
# El pip del palo de la esquina del recorte se cuela en el OCR (el trebol se
# parece a un "4") y tesseract devuelve dos lineas. Antes se descartaba el texto
# entero y la carta se perdia: el usuario lo cazo jugando ("hay un 2 trebol" en
# un board que la app leia con solo 2 cartas). Como el pip esta ARRIBA del rango
# y tesseract emite de arriba abajo, el rango real es la ultima linea valida.
print("\n# --- OCR de rango con varias lineas ---")
from rank_ocr import normalize_rank  # noqa: E402

check("una lectura limpia sigue igual", normalize_rank("K") == "K")
check("el 10 sigue teniendo su caso especial",
      normalize_rank("10") == "10" and normalize_rank("1O") == "10")
check("'4|2' (pip de trebol + rango) da 2, que era el caso real",
      normalize_rank("4\n2") == "2")
check("'4|8' y '4|Q' tambien", normalize_rank("4\n8") == "8" and normalize_rank("4\nQ") == "Q")
check("un 4 de verdad sigue siendo un 4", normalize_rank("4") == "4")
check("si la ultima linea es basura se coge la anterior valida",
      normalize_rank("4\nX") == "4")
check("y si no hay ninguna linea valida, None (no se inventa carta)",
      normalize_rank("X\nZ") is None and normalize_rank("") is None)

# --- ocupacion de asientos: lo que decide TODAS las posiciones --------------
# Las posiciones salen del RECUENTO de asientos ocupados, asi que un asiento de
# mas las desplaza todas y el rango elegido es el de otra posicion. Caso real:
# en un torneo 3-Max la app veia 4 jugadores en el 34% de los frames y llego a
# asignarle al hero la posicion CO, que en una mesa de 3 no existe.
print("\n# --- ocupacion de asientos ---")


def lineas(*textos):
    return [{"text": t, "left": 0, "top": 0, "right": 10, "bottom": 10, "cx": 5, "cy": 5}
            for t in textos]


check("un importe en BB ocupa el asiento", ts._plate_occupied(lineas("69,3 BB")))
check("un nick tambien", ts._plate_occupied(lineas("Dav6934")))
check("y un verbo de accion", ts._plate_occupied(lineas("Igualar")))
check("el 'No ir' del cliente, que va en dos palabras", ts._plate_occupied(lineas("No ir")))
check("tapete vacio -> NO ocupado", ts._plate_occupied(lineas("")) is False)
check("un ENTERO SUELTO ya no ocupa: era de la epoca de las fichas y la textura "
      "de puntos del tapete se OCR-ea como un numero ('60668' en 60 de 60 frames)",
      ts._plate_occupied(lineas("60668")) is False)
check("ni con separador de miles", ts._plate_occupied(lineas("5.892")) is False)

# la fuerza de la evidencia, que es lo que decide cual se suelta si sobran
f = ts._fuerza_ocupacion
check("el hero nunca se suelta", f("HERO", {}, set(), None) == 4)
check("ni el asiento del boton", f("MR", {}, set(), "MR") == 4)
check("un dorso de carta pesa mas que un nombre",
      f("MR", {}, {"MR"}, None) > f("MR", {"name": "pepe"}, set(), None))
check("y un importe en BB tambien",
      f("MR", {"stack": 44.5}, set(), None) > f("MR", {"name": "pepe"}, set(), None))
check("lo mas debil es un asiento sin nada de eso",
      f("MR", {}, set(), None) < f("MR", {"name": "pepe"}, set(), None))

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
