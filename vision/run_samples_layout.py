"""
Corre table_state.analyze_layout() (reconocimiento por zonas fijas / mapa de
asientos) contra un directorio de capturas y vuelca los resultados a JSON,
igual que run_samples_pokerstars.py hace para la rama color-deck dinamica.

Uso:
  .venv/bin/python vision/run_samples_layout.py [DIR] [OUT_JSON]

Sin argumentos usa vision/samples_layout/ -> vision/results_layout.json.
Con DIR (nombre de subcarpeta de vision/ o ruta) vuelca a
vision/results_<nombre>.json salvo que se pase OUT_JSON explicito.
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from table_state import analyze_layout

VISION_DIR = os.path.dirname(__file__)


def main():
    samples_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VISION_DIR, "samples_layout")
    if not os.path.isdir(samples_dir):
        samples_dir = os.path.join(VISION_DIR, samples_dir)
    name = os.path.basename(os.path.normpath(samples_dir))
    default_out = "results_layout.json" if name == "samples_layout" else f"results_{name}.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(VISION_DIR, default_out)

    files = sorted(glob.glob(os.path.join(samples_dir, "*.png")))
    results = []
    for i, f in enumerate(files):
        print(f"[{i + 1}/{len(files)}] {os.path.basename(f)}")
        results.append(analyze_layout(f))
    with open(out_path, "w") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    print(f"\n{len(results)} imagenes -> {out_path}")


if __name__ == "__main__":
    main()
