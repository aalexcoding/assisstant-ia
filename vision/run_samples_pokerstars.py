"""
Corre table_state.analyze_color_deck() (mazo de 4 colores) contra todas las
imagenes de vision/samples_pokerstars/ y vuelca vision/results_pokerstars.json,
igual que run_samples.py hace para el mazo blanco de vision/samples/.
Uso: .venv/bin/python vision/run_samples_pokerstars.py
"""
import glob
import json
import os

from vision.table_state import analyze_color_deck

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples_pokerstars")
OUT_PATH = os.path.join(os.path.dirname(__file__), "results_pokerstars.json")


def main():
    files = sorted(glob.glob(os.path.join(SAMPLES_DIR, "*.png")))
    results = []
    for i, f in enumerate(files):
        print(f"[{i + 1}/{len(files)}] {os.path.basename(f)}")
        state = analyze_color_deck(f)
        results.append(state)
    with open(OUT_PATH, "w") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"\n{len(results)} imagenes -> {OUT_PATH}")


if __name__ == "__main__":
    main()
