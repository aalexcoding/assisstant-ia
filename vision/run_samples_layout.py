"""
Corre table_state.analyze_layout() (reconocimiento por zonas fijas / mapa de
asientos) contra todas las imagenes de vision/samples_layout/ y vuelca
vision/results_layout.json, igual que run_samples_pokerstars.py hace para la
rama color-deck dinamica.
Uso: .venv/bin/python vision/run_samples_layout.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from table_state import analyze_layout

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples_layout")
OUT_PATH = os.path.join(os.path.dirname(__file__), "results_layout.json")


def main():
    files = sorted(glob.glob(os.path.join(SAMPLES_DIR, "*.png")))
    results = []
    for i, f in enumerate(files):
        print(f"[{i + 1}/{len(files)}] {os.path.basename(f)}")
        results.append(analyze_layout(f))
    with open(OUT_PATH, "w") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"\n{len(results)} imagenes -> {OUT_PATH}")


if __name__ == "__main__":
    main()
