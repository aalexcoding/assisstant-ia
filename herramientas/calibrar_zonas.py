#!/usr/bin/env python3
"""
¿Alguna zona esta cortando lo que tiene que leer? Se pasa sobre una sesion grabada.

Convierte en instrumento el diagnostico que se hizo A MANO tres veces: el borde
izquierdo del board (536 de 3.241 cajas mordidas), el borde superior del board (el
127% de las cartas tocandolo) y la zona de mano revelada (el asiento UR perdiendo
sus dos cartas siempre). Las tres tenian la misma firma y las tres se encontraron
mirando frames uno a uno.

SE APOYA EN LO QUE HAY: no cambia zonas ni referencias, las mide. La correccion
que sugiere es para decidir a mano, con el numero delante.

Uso:
    herramientas/calibrar_zonas.py                     # la ultima sesion
    herramientas/calibrar_zonas.py testing/sesion-XXX
    herramientas/calibrar_zonas.py --paso 1            # todos los frames
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2                                    # noqa: E402

from vision import calibracion, seat_map      # noqa: E402
from vision import table_state as ts          # noqa: E402


def _cajas(bgr, zona_px, esperadas=None, mazo=None):
    return [(b["x"], b["y"], b["w"], b["h"])
            for b in ts._cajas_de_carta(bgr, zona_px, esperadas=esperadas, mazo=mazo)]


def revisar(carpeta, paso=5):
    meta = {}
    try:
        with open(os.path.join(carpeta, "_sesion.json")) as f:
            meta = json.load(f) or {}
    except (OSError, ValueError):
        pass
    Z = seat_map.zonas(meta.get("max_players"))
    mazo = meta.get("mazo")
    refc = seat_map.ReferenciaFijada()
    lados = {}
    correcciones = {}
    escalas = Counter()
    n = 0
    for r in sorted(glob.glob(os.path.join(carpeta, "[0-9]*.png")),
                    key=lambda p: int(os.path.basename(p)[:-4]))[::paso]:
        img = cv2.imread(r)
        if img is None:
            continue
        ref = refc.de(img)
        if refc.fijada is None or ref[4]:
            continue
        n += 1
        # las zonas que contienen CARTAS, que son las que se pueden juzgar por
        # ancho: el board, la mano del hero y las manos reveladas de cada asiento
        objetivos = [("board", seat_map.BOARD_ZONE, None, seat_map.BOARD_ZONE),
                     ("hero_cards", seat_map.HERO_CARDS_ZONE, 2,
                      seat_map.HERO_CARDS_ZONE)]
        for asiento in Z["dorsos"]:
            objetivos.append((f"revelada.{asiento}", None, 2, Z["dorsos"][asiento]))
        for nombre, frac, esperadas, frac_ref in objetivos:
            if frac is None:
                px = seat_map.revealed_zone_px(ref, nombre.split(".")[1],
                                               img.shape, Z["dorsos"])
            else:
                px = seat_map.zone_to_px(ref, frac, img.shape)
            cajas = _cajas(img, px, esperadas, mazo)
            esc = calibracion.escala_de_carta(cajas)
            if esc:
                escalas[esc] += 1
            v = calibracion.recorte_de_zona(cajas, px)
            if not v["recorta"]:
                continue
            for lado, veces in v["lados"].items():
                lados[(nombre, lado)] = lados.get((nombre, lado), 0) + veces
            for lado, d in calibracion.correccion_sugerida(v, frac_ref, ref).items():
                correcciones.setdefault((nombre, lado), []).append(d)
    return n, lados, correcciones, escalas


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.strip().split("\n")[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("carpeta", nargs="?")
    p.add_argument("--paso", type=int, default=5,
                   help="1 = todos los frames; por defecto uno de cada 5")
    a = p.parse_args(argv)
    carpeta = a.carpeta
    if not carpeta:
        ses = sorted(glob.glob(os.path.join("testing", "sesion-*")))
        if not ses:
            print("no hay sesiones en testing/", file=sys.stderr)
            return 1
        carpeta = ses[-1]
    n, lados, correcciones, escalas = revisar(carpeta, a.paso)
    print(f"{os.path.basename(carpeta)}: {n} frames con mesa\n")
    if not lados:
        print("  ninguna zona corta su contenido")
    else:
        print(f"  {'zona':22} {'lado':>5} {'veces':>7} {'correccion sugerida':>21}")
        for (zona, lado), veces in sorted(lados.items(), key=lambda kv: -kv[1]):
            ds = correcciones.get((zona, lado), [])
            med = sorted(ds)[len(ds) // 2] if ds else 0
            print(f"  {zona:22} {lado:>5} {veces:7} {med:+20.4f}")
        print()
        print("  La correccion se suma a esa fraccion de la zona en seat_map.")
        print("  Conviene pasarse: el temblor de la referencia puede pedir mas")
        print("  margen del que un frame concreto delata.")
    if escalas:
        tot = sum(escalas.values())
        top = escalas.most_common(4)
        print("\n  escala (ancho de carta): "
              + "  ".join(f"{w} px x{c}" for w, c in top)
              + f"   [{tot} medidas]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
