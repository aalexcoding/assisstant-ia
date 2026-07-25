"""
Verificacion de la deteccion de "quien sigue en la mano" por dorso de carta
(seat_map.card_back_fractions / detect_in_hand_seats).

No hay ground truth etiquetado de quien se retiro, asi que la validacion se
apoya en tres propiedades que TIENEN que cumplirse si la señal es real, mas un
puñado de frames comprobados a ojo:

  1. BIMODALIDAD CON MARGEN. Si la metrica separa de verdad, no debe haber
     observaciones en la banda intermedia. Cero de 705 es una afirmacion fuerte;
     una sola en la banda ya seria motivo para revisar los umbrales.
  2. MONOTONIA DENTRO DE UNA MANO. El conjunto de jugadores vivos solo puede
     ENCOGERSE segun avanza una mano. Las fronteras entre manos se detectan por
     discontinuidad del board, no por tiempo.
  3. SUBCONJUNTO. Quien tiene cartas esta sentado, asi que in_hand ⊆ ocupados.

Es lento (procesa 141 capturas, ~1 min) porque no usa OCR: solo pixeles.
Uso: .venv/bin/python vision/test_in_hand.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import seat_map

VISION = os.path.dirname(os.path.abspath(__file__))
checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def medir(carpeta):
    """[(nombre_fichero, {asiento: fraccion}), ...] en orden de captura."""
    out = []
    for f in sorted(glob.glob(os.path.join(VISION, carpeta, "*.png"))):
        bgr = cv2.imread(f)
        if bgr is None:
            continue
        ref = seat_map.find_reference(bgr)
        out.append((os.path.basename(f), seat_map.card_back_fractions(bgr, ref)))
    return out


datos = {c: medir(c) for c in ("samples_layout2", "samples_layout")}
total = sum(len(v) for v in datos.values())
if total == 0:
    print("no hay capturas en vision/samples_layout*/ ; nada que verificar")
    raise SystemExit(0)

# --- 1. bimodalidad con margen ------------------------------------------------
print("--- 1. bimodalidad ---")
BANDA = (0.02, 0.10)
for carpeta, filas in datos.items():
    if not filas:
        continue
    vals = np.array([v for _, fr in filas for v in fr.values()])
    bajos = vals[vals < BANDA[0]]
    altos = vals[vals > BANDA[1]]
    medio = vals[(vals >= BANDA[0]) & (vals <= BANDA[1])]
    print(f"     {carpeta}: {len(filas)} frames x 5 asientos = {len(vals)} observaciones")
    print(f"       sin cartas: {len(bajos):4d} (max {bajos.max() if len(bajos) else 0:.4f})   "
          f"con cartas: {len(altos):4d} (min {altos.min() if len(altos) else 0:.4f})")
    check(f"{carpeta}: nada en la banda prohibida [{BANDA[0]}, {BANDA[1]}] "
          f"({len(medio)} observaciones)", len(medio) == 0)
    if len(bajos) and len(altos):
        check(f"{carpeta}: el margen entre poblaciones es de al menos 5x",
              altos.min() > bajos.max() * 5)

# --- 2. monotonia dentro de una mano -----------------------------------------
# Las manos se separan por discontinuidad del board: si el board deja de ser
# prefijo del anterior (o se vacia y vuelve), empezo una mano nueva. El board se
# lee del snapshot ya calculado, para no tener que correr el OCR aqui.
print("\n--- 2. monotonia dentro de una mano ---")
SNAP = os.path.join(VISION, "results_samples_layout2.json")
if os.path.exists(SNAP):
    with open(SNAP) as fh:
        snap = {r["image"]: r for r in json.load(fh)}
    filas = datos["samples_layout2"]
    violaciones = []
    previo_set, previo_board, previo_img = None, None, None
    for img, fr in filas:
        board = tuple(snap.get(img, {}).get("board") or [])
        vivos = {n for n, v in fr.items() if v >= seat_map.CARD_BACK_MIN_AREA_FRAC}
        # Frontera entre manos: el board deja de crecer como prefijo del anterior,
        # O el frame anterior no tenia a NADIE con cartas -si nadie sostiene
        # cartas la mano ya termino, asi que lo siguiente es un reparto nuevo-.
        # Sin esta segunda condicion el criterio del board no basta: entre dos
        # manos el board esta vacio en los dos frames y parecerian la misma.
        misma_mano = (previo_board is not None
                      and bool(previo_set)
                      and (board[:len(previo_board)] == previo_board
                           or previo_board[:len(board)] == board)
                      and len(board) >= len(previo_board))
        if misma_mano and previo_set is not None and not vivos <= previo_set:
            violaciones.append((previo_img, img, sorted(previo_set), sorted(vivos)))
        previo_set, previo_board, previo_img = vivos, board, img
    check(f"el conjunto de vivos nunca crece dentro de una mano "
          f"({len(violaciones)} violaciones)", not violaciones)
    for v in violaciones[:3]:
        print(f"       {v[0]} {v[2]} -> {v[1]} {v[3]}")
else:
    print("     (sin snapshot results_samples_layout2.json, se omite)")

# --- 3. invariante de subconjunto --------------------------------------------
print("\n--- 3. in_hand subset ocupados ---")
if os.path.exists(SNAP):
    malos = 0
    for img, fr in datos["samples_layout2"]:
        r = snap.get(img)
        if not r:
            continue
        n_vivos = sum(1 for v in fr.values() if v >= seat_map.CARD_BACK_MIN_AREA_FRAC)
        # los vivos son rivales; el hero va aparte, de ahi el +1
        if n_vivos + 1 > len(r["players"]):
            malos += 1
    check(f"nunca hay mas rivales con cartas que asientos ocupados ({malos} casos)",
          malos == 0)

# --- 4. frames comprobados a ojo ---------------------------------------------
# sample_1784909873584: david sagunt (UL) y Amsterdam974 (UR) tienen dos cartas
# granate cada uno; rubydog77 (ML) no, y Parfisal58 (MR) esta "Ausente".
print("\n--- 4. frames verificados a ojo ---")
ETIQUETAS = {
    "sample_1784909873584.png": {"UL", "UR"},
}
por_nombre = dict(datos["samples_layout2"])
for img, esperado in ETIQUETAS.items():
    if img not in por_nombre:
        continue
    obtenido = {n for n, v in por_nombre[img].items()
                if v >= seat_map.CARD_BACK_MIN_AREA_FRAC}
    check(f"{img}: {sorted(obtenido)} == {sorted(esperado)}", obtenido == esperado)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
