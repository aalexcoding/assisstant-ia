"""
Digitaliza las capturas de rango preflop de ZEROSPOKER.COM en
/mnt/qnap/Poker/CAPTURAS HERRAMIENTAS PREFLOP/ y genera ranges.json.

Fuente de datos: solo lectura, no se modifica nada en /mnt/qnap/Poker/.

Esquema de salida (ver README del proyecto para el detalle):
{
  "open_raise": {"<stack_bb>": {"<hero_pos>": {"<accion>": ["AA", "AKs", ...]}}},
  "threebet_call": {"<stack_bb>": {"<hero_pos>": {"<vs_pos>": {"<accion>": [...]}}}}
}

Las celdas cuyo color dominante no coincide con ninguna caja de la leyenda se
consideran "fold" implicito (no hay caja "FOLD" en la leyenda de la web).

Las etiquetas de accion son el texto tal cual lo lee el OCR de cada imagen
(ej. "OPEN RAISE ALL IN", "3BET (5 BB)", "MARGINAL CALL"...): no se
normalizan entre imagenes, asi que el tamano de 3bet/open-raise en BB queda
literalmente incluido en la clave cuando la web lo muestra distinto por
stack/posicion.

Limitaciones conocidas (ver aviso "N celdas con mezcla de color >15%" en la
salida de stderr para el detalle por imagen):
- Celdas con frecuencia mixta (dos colores en la misma casilla) se
  clasifican por el color dominante; la fraccion minoritaria se pierde.
  Esto es lo que explica la mayoria de los avisos de "combos OCR vs
  derivados" (el recuento de combos de la web es fraccionario, el nuestro
  no).
- El grid de 3BET-CALL/10BB/1BB (My position)/ no existe en el material
  fuente (carpeta vacia): a 10BB efectivos no hay rango de BB vs apertura.

Uso:
    .venv/bin/python -m decision.preflop.parse_ranges
    .venv/bin/python -m decision.preflop.parse_ranges --refresh <imagen> [...]

``--refresh`` redigitaliza solo las celdas indicadas y actualiza sus spots en
el JSON existente. Sirve para reparar una captura concreta sin volver a lanzar
los cientos de procesos OCR del corpus entero.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter

from PIL import Image

from decision.preflop import zerospoker_layout as zl

DATA_ROOT = "/mnt/qnap/Poker/CAPTURAS HERRAMIENTAS PREFLOP"
OPEN_RAISE_DIR = os.path.join(DATA_ROOT, "OPEN RAISE")
THREEBET_DIR = os.path.join(DATA_ROOT, "3BET-CALL")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "ranges.json")
# Como en vision/ocr_client.py: por MODULO, no por ruta, porque hay dos
# ocr_worker.py en el proyecto y el nombre suelto es ambiguo.
OCR_WORKER_MODULE = "decision.preflop.ocr_worker"
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MONTAGE_MIN_WIDTH = 3000
COMBOS_BY_KIND = {"pair": 6, "suited": 4, "offsuit": 12}


def hand_combos(hand):
    if len(hand) == 2:
        return COMBOS_BY_KIND["pair"]
    return COMBOS_BY_KIND["suited"] if hand.endswith("s") else COMBOS_BY_KIND["offsuit"]


def is_individual_image(path):
    with Image.open(path) as im:
        w, h = im.size
    return w < MONTAGE_MIN_WIDTH


def list_stack_dirs(root):
    return sorted(
        (d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))),
        key=lambda d: float(d.replace("BB", "")),
    )


class Digitizer:
    """
    Nota: el OCR de la leyenda se delega a ocr_worker.py en un subproceso
    aparte (ver docstring de ese fichero) en vez de llamar a tesserocr desde
    este proceso: mezclar tesserocr con opencv/pillow en el mismo proceso
    provocaba corrupcion de memoria intermitente que hacia que, muy de vez
    en cuando, dos imagenes distintas terminaran clasificadas con la misma
    posicion de rival (bug no determinista, confirmado comparando varias
    ejecuciones con y sin las llamadas a tesserocr en el mismo proceso).
    """

    def __init__(self):
        self.failures = []
        self.warnings = []

    def ocr_boxes(self, image_path, boxes):
        if not boxes:
            return []
        payload = json.dumps({"image": image_path, "boxes": boxes})
        proc = subprocess.run(
            [sys.executable, "-m", OCR_WORKER_MODULE], cwd=RAIZ,
            input=payload, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            self.warnings.append(f"{image_path}: fallo el subproceso OCR ({proc.stderr.strip()[-300:]})")
            return ["" for _ in boxes]
        return json.loads(proc.stdout)

    def close(self):
        pass

    def read_legend(self, im, image_path):
        boxes = zl.find_legend_swatches(im)
        if not boxes:
            return []
        ocr_boxes = []
        for box in boxes:
            ocr_boxes.append(zl.legend_label_box(box))
            ocr_boxes.append(zl.legend_meta_box(box))
        texts = self.ocr_boxes(image_path, ocr_boxes)
        legend = []
        for i, box in enumerate(boxes):
            label = zl.parse_legend_label(texts[2 * i])
            pct, combos = zl.parse_legend_meta(texts[2 * i + 1])
            color = zl.legend_swatch_color(im, box)
            legend.append({"label": label, "color": color, "pct": pct, "combos": combos, "box": box})
        return legend

    def digitize_grid(self, im, grid_top, legend):
        legend_colors = [(entry["label"], entry["color"]) for entry in legend if entry["label"]]
        ranges = {}
        mixed_cells = []
        unmatched_colors = Counter()
        for i in range(13):
            for j in range(13):
                color, second_frac = zl.classify_cell(im, grid_top, i, j)
                hand = zl.hand_at(i, j)
                label = zl.nearest_legend_label(color, legend_colors)
                if label is None:
                    label = "fold"
                    unmatched_colors[color] += 1
                ranges.setdefault(label, []).append(hand)
                if second_frac > 0.15:
                    mixed_cells.append(hand)
        total = sum(len(v) for v in ranges.values())
        return ranges, mixed_cells, unmatched_colors, total

    def validate_combos(self, path, ranges, legend):
        for entry in legend:
            label, combos = entry["label"], entry["combos"]
            if not label or combos is None or label not in ranges:
                continue
            derived = sum(hand_combos(h) for h in ranges[label])
            if abs(derived - combos) > max(6, combos * 0.1):
                self.warnings.append(
                    f"{path}: combos OCR={combos} vs derivados={derived} para accion '{label}'"
                )

    def process_open_raise_image(self, path, stack_label):
        im = zl.load_rgb(path)
        rows = zl.find_position_rows(im)
        if not rows:
            self.failures.append((path, "no se detecto boton de posicion activo"))
            return None
        hero_idx, _n = zl.row_button_index(im, rows[0])
        if hero_idx is None or hero_idx >= len(zl.OPEN_RAISE_ROW_LABELS):
            self.failures.append((path, f"indice de posicion invalido ({hero_idx})"))
            return None
        hero_label = zl.OPEN_RAISE_ROW_LABELS[hero_idx]

        legend = self.read_legend(im, path)
        if not legend:
            self.failures.append((path, "no se detecto leyenda"))
            return None
        grid_top = min(e["box"][1] for e in legend)

        ranges, mixed, unmatched, total = self.digitize_grid(im, grid_top, legend)
        if total != 169:
            self.failures.append((path, f"grid incompleto: {total}/169 celdas clasificadas"))
            return None
        self.validate_combos(path, ranges, legend)
        if mixed:
            self.warnings.append(f"{path}: {len(mixed)} celdas con mezcla de color >15% ({mixed})")

        return hero_label, ranges

    def process_threebet_image(self, path, stack_label):
        im = zl.load_rgb(path)
        rows = zl.find_position_rows(im)
        if len(rows) < 2:
            self.failures.append((path, f"se esperaban 2 filas de posicion (hero+rival), se detectaron {len(rows)}"))
            return None
        hero_idx, _n = zl.row_button_index(im, rows[0])
        if hero_idx is None or hero_idx >= len(zl.THREEBET_HERO_ROW_LABELS):
            self.failures.append((path, f"indice de posicion (hero) invalido ({hero_idx})"))
            return None
        hero_label = zl.THREEBET_HERO_ROW_LABELS[hero_idx]
        hero_canon_idx = zl.CANON9.index(hero_label)
        opp_labels_expected = zl.CANON9[hero_canon_idx + 1:]

        opp_idx, _n2 = zl.row_button_index(im, rows[1])
        if opp_idx is None or opp_idx >= len(opp_labels_expected):
            self.failures.append((path, f"indice de posicion (rival) invalido ({opp_idx})"))
            return None
        opp_label = opp_labels_expected[opp_idx]

        legend = self.read_legend(im, path)
        if not legend:
            self.failures.append((path, "no se detecto leyenda"))
            return None
        grid_top = min(e["box"][1] for e in legend)

        ranges, mixed, unmatched, total = self.digitize_grid(im, grid_top, legend)
        if total != 169:
            self.failures.append((path, f"grid incompleto: {total}/169 celdas clasificadas"))
            return None
        self.validate_combos(path, ranges, legend)
        if mixed:
            self.warnings.append(f"{path}: {len(mixed)} celdas con mezcla de color >15% ({mixed})")

        return hero_label, opp_label, ranges


def build_open_raise(dig, result):
    result["open_raise"] = {}
    stacks = list_stack_dirs(OPEN_RAISE_DIR)
    for stack in stacks:
        stack_dir = os.path.join(OPEN_RAISE_DIR, stack)
        stack_key = stack.replace("BB", "")
        result["open_raise"][stack_key] = {}
        images = sorted(f for f in os.listdir(stack_dir) if f.lower().endswith(".png"))
        for fname in images:
            path = os.path.join(stack_dir, fname)
            if not is_individual_image(path):
                continue
            out = dig.process_open_raise_image(path, stack_key)
            if out is None:
                continue
            hero_label, ranges = out
            result["open_raise"][stack_key][hero_label] = ranges


def store_threebet_spot(dig, result, stack_key, hero_label, opp_label,
                        ranges, path):
    """Guarda un spot sin permitir que una etiqueta OCR repetida borre otra."""
    result["threebet_call"][stack_key].setdefault(hero_label, {})
    spots = result["threebet_call"][stack_key][hero_label]
    if opp_label in spots:
        dig.failures.append((
            path,
            f"posición duplicada {hero_label} vs {opp_label}; "
            "se conserva la primera y no se sobrescribe",
        ))
        return False
    spots[opp_label] = ranges
    return True


def build_threebet(dig, result):
    result["threebet_call"] = {}
    stacks = list_stack_dirs(THREEBET_DIR)
    for stack in stacks:
        stack_dir = os.path.join(THREEBET_DIR, stack)
        stack_key = stack.replace("BB", "")
        result["threebet_call"][stack_key] = {}
        hero_dirs = sorted(
            (d for d in os.listdir(stack_dir) if os.path.isdir(os.path.join(stack_dir, d))),
            key=lambda d: int(re.match(r"\d+", d).group()),
        )
        for hero_dir in hero_dirs:
            hero_dir_path = os.path.join(stack_dir, hero_dir)
            images = sorted(f for f in os.listdir(hero_dir_path) if f.lower().endswith(".png"))
            for fname in images:
                path = os.path.join(hero_dir_path, fname)
                if not is_individual_image(path):
                    continue
                out = dig.process_threebet_image(path, stack_key)
                if out is None:
                    continue
                hero_label, opp_label, ranges = out
                # Una lectura errónea del botón de rival podía producir la
                # misma etiqueta que una imagen anterior. El dict la
                # sobrescribía en silencio: el total de imágenes seguía
                # cuadrando aproximadamente, pero desaparecía otra posición
                # (así quedó fuera BB vs MP1 a 20 BB en ranges.json).
                store_threebet_spot(
                    dig, result, stack_key, hero_label, opp_label, ranges, path)


def refresh_threebet_images(paths):
    """Redigitaliza imágenes 3BET-CALL concretas sobre el JSON existente."""
    with open(OUTPUT_PATH, encoding="utf-8") as f:
        result = json.load(f)
    dig = Digitizer()
    updated = []
    for path in paths:
        path = os.path.abspath(path)
        stack_dir = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if not re.fullmatch(r"\d+(?:\.\d+)?BB", stack_dir):
            raise ValueError(
                f"{path}: no está bajo 3BET-CALL/<stack>BB/<hero>/imagen.png")
        stack_key = stack_dir[:-2]
        out = dig.process_threebet_image(path, stack_key)
        if out is None:
            continue
        hero_label, opp_label, ranges = out
        result.setdefault("threebet_call", {}).setdefault(
            stack_key, {}).setdefault(hero_label, {})[opp_label] = ranges
        updated.append((stack_key, hero_label, opp_label, path))

    if dig.failures:
        detalle = "; ".join(f"{p}: {reason}" for p, reason in dig.failures)
        raise RuntimeError(f"no se actualiza ranges.json: {detalle}")
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")
    for stack, hero, opp, path in updated:
        print(f"REFRESH {stack}BB {hero} vs {opp} <- {path}", file=sys.stderr)
    for warning in dig.warnings:
        print(f"WARN {warning}", file=sys.stderr)
    return updated


def main(refresh=None):
    if refresh:
        refresh_threebet_images(refresh)
        return
    dig = Digitizer()
    result = {}
    n_open_files = sum(
        1 for stack in list_stack_dirs(OPEN_RAISE_DIR)
        for f in os.listdir(os.path.join(OPEN_RAISE_DIR, stack)) if f.lower().endswith(".png")
    )
    n_3bet_files = sum(
        1 for stack in list_stack_dirs(THREEBET_DIR)
        for hero_dir in os.listdir(os.path.join(THREEBET_DIR, stack))
        if os.path.isdir(os.path.join(THREEBET_DIR, stack, hero_dir))
        for f in os.listdir(os.path.join(THREEBET_DIR, stack, hero_dir)) if f.lower().endswith(".png")
    )
    print(f"OPEN RAISE: {n_open_files} imagenes individuales candidatas", file=sys.stderr)
    print(f"3BET-CALL: {n_3bet_files} imagenes individuales candidatas", file=sys.stderr)

    build_open_raise(dig, result)
    build_threebet(dig, result)
    dig.close()

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    n_open_ok = sum(len(v) for v in result["open_raise"].values())
    n_3bet_ok = sum(len(opp) for stack in result["threebet_call"].values() for opp in stack.values())

    print(f"\nOK open_raise: {n_open_ok}/{n_open_files} imagenes digitalizadas", file=sys.stderr)
    print(f"OK threebet_call: {n_3bet_ok}/{n_3bet_files} imagenes digitalizadas", file=sys.stderr)
    print(f"Fallos: {len(dig.failures)}", file=sys.stderr)
    for path, reason in dig.failures:
        print(f"  FAIL {path}: {reason}", file=sys.stderr)
    print(f"Avisos: {len(dig.warnings)}", file=sys.stderr)
    for w in dig.warnings:
        print(f"  WARN {w}", file=sys.stderr)
    print(f"\nEscrito {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument(
        "--refresh", nargs="+", metavar="PNG",
        help="redigitaliza solo estas capturas 3BET-CALL sobre ranges.json")
    args = parser.parse_args()
    main(refresh=args.refresh)
