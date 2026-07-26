"""
Verificacion de la vigilancia rapida de nameplates (vision/seat_watch.py).

Lo que de verdad protege:

  1. Que un cambio REAL se vea (si no, se pierde la accion del rival, que es
     justo lo que la pieza existe para captar) y que el ruido de la animacion del
     tapete NO cuente como cambio (si no, se dispara un OCR en cada frame y la
     idea deja de ser barata).
  2. Que el buffer GUARDE COPIAS y este ACOTADO: el buffer del stream se
     reescribe en la lectura siguiente, y una sesion de 40 minutos a 10 Hz son
     24.000 frames.

Sin depender de capturas: las imagenes se generan aqui.
Uso: .venv/bin/python vision/test_seat_watch.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import seat_map
import seat_watch as sw

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


ALTO, ANCHO = 800, 1200
REF = (100, 100, 1000, 500, False)          # (x, y, w, h, fallback) del nucleo


def frame(valor=60):
    return np.full((ALTO, ANCHO, 3), valor, dtype=np.uint8)


def pintar_asiento(img, seat, valor):
    """Escribe en el INTERIOR de la capsula de un asiento (lo que se hashea)."""
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, seat_map.SEATS[seat]["plate"], img.shape)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(ANCHO, x1), min(ALTO, y1)
    dy, dx = int((y1 - y0) * 0.2), int((x1 - x0) * 0.2)
    img[y0 + dy:y1 - dy, x0 + dx:x1 - dx] = valor
    return img


def pintar_borde(img, seat, valor):
    """Escribe SOLO en el borde de la capsula (lo que se descarta al hashear)."""
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, seat_map.SEATS[seat]["plate"], img.shape)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(ANCHO, x1), min(ALTO, y1)
    dy = max(1, int((y1 - y0) * 0.03))
    img[y0:y0 + dy, x0:x1] = valor
    return img


# --- deteccion de cambios ---------------------------------------------------
print("# --- que cuenta como cambio ---")
w = sw.SeatWatch()
base = pintar_asiento(frame(), "UL", 200)
check("la PRIMERA vez no hay cambios: no hay con que comparar, y darlo por "
      "cambiado haria OCR-ear los seis asientos sin razon",
      w.cambios(base, REF) == [])
check("el mismo frame otra vez tampoco cambia", w.cambios(base, REF) == [])

otro = pintar_asiento(base.copy(), "UL", 120)
cam = w.cambios(otro, REF)
check("cambiar el interior de UL se detecta", cam == ["UL"])
check("y solo ese asiento", len(cam) == 1)
check("una vez visto, deja de contar como cambio", w.cambios(otro, REF) == [])

ruido = pintar_borde(otro.copy(), "MR", 5)
check("el ruido SOLO en el borde de la capsula NO cuenta: ahi es donde se animan "
      "el tapete, el avatar y la marca de bounty",
      w.cambios(ruido, REF) == [])

dos = pintar_asiento(pintar_asiento(ruido.copy(), "UL", 30), "MR", 30)
check("dos asientos a la vez dan los dos", sorted(w.cambios(dos, REF)) == ["MR", "UL"])

w.olvidar()
check("olvidar() vuelve al estado inicial", w.cambios(dos, REF) == [])

# --- huellas ----------------------------------------------------------------
print("\n# --- huellas ---")
h = sw.huellas(base, REF)
check("hay una huella por asiento del mapa", set(h) == set(seat_map.SEATS))
check("son bytes, no objetos raros", all(isinstance(v, bytes) for v in h.values()))
check("el mismo frame da las mismas huellas", h == sw.huellas(base, REF))

# --- el buffer --------------------------------------------------------------
print("\n# --- buffer de frames ---")
b = sw.FrameBuffer(maxlen=3)
f1 = frame(10)
b.añadir(f1, t=1.0)
check("guarda una COPIA: el buffer del stream se reescribe en la lectura "
      "siguiente, asi que sin copiar lo guardado dejaria de ser lo que se vio",
      b.ultimo()["frame"] is not f1)
f1[:] = 99
check("y por eso modificar el original no toca lo guardado",
      int(b.ultimo()["frame"][0, 0, 0]) == 10)

b.añadir(frame(20), t=2.0)
b.añadir(frame(30), t=3.0)
b.añadir(frame(40), t=4.0)
check("esta ACOTADO: no crece sin limite en una sesion larga", len(b) == 3)
check("y lo que se descarta es lo mas viejo",
      [x["t"] for x in b.todos()] == [2.0, 3.0, 4.0])
check("el ultimo es el mas reciente", b.ultimo()["t"] == 4.0)
b.vaciar()
check("vaciar lo deja a cero", len(b) == 0 and b.ultimo() is None)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
