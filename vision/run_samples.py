"""
Corre table_state.analyze() contra todas las imagenes de vision/samples/ y
vuelca vision/results.json (una entrada por imagen) para poder revisar la
cobertura real. Uso: .venv/bin/python vision/run_samples.py
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from table_state import analyze

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "samples")
OUT_PATH = os.path.join(os.path.dirname(__file__), "results.json")


def main():
    files = sorted(glob.glob(os.path.join(SAMPLES_DIR, "*.png")))
    results = []
    for i, f in enumerate(files):
        print(f"[{i + 1}/{len(files)}] {os.path.basename(f)}")
        state = analyze(f)
        results.append(state)
    with open(OUT_PATH, "w") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"\n{len(results)} imagenes -> {OUT_PATH}")


if __name__ == "__main__":
    main()
