"""Importa los PDF públicos 8-max MTT de RangeConverter.

Los PDF no se versionan en el proyecto. Se descargan de las URL declaradas en
``SOURCES`` y este importador convierte únicamente las siete páginas
``RFI vs 3bet`` de cada profundidad en JSON reproducible.

Uso:

    python -m decision.preflop.import_rangeconverter \
        --pdf-dir /ruta/con/20.pdf,30.pdf,... \
        --output decision/preflop/rangeconverter_ranges.json

Supuestos comprobables de la publicación:

* mesa 8-max;
* ante total 1 BB (12,5 % por jugador);
* estrategia chip-EV, sin ICM;
* frecuencias simplificadas al 50 %.

El azul oscuro no es FOLD frente a la 3-bet: marca manos que no pertenecían al
RFI de partida. Se conserva como ``NOT_IN_RFI`` para que el motor se abstenga si
la línea real llegó ahí desviándose del rango de apertura.
"""
import argparse
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image

from decision.preflop.zerospoker_layout import hand_at


STACKS = (20, 30, 40, 50, 60, 100)
POSITIONS = ("EP1", "EP2", "MP1", "HJ", "CO", "BTN", "SB", "BB")
SOURCES = {
    stack: (
        f"https://rangeconverter.com/downloads/"
        f"8-max-MTT-{stack}bb-Tournament-Poker-Charts"
    )
    for stack in STACKS
}

# Render a 120 dpi: coordenadas estables de la maqueta landscape de los PDF.
_X = (28, 368, 709, 1049)
_Y = (123, 559)
_GRID_W = 329
_GRID_H = 362
_LEGEND_Y_OFFSET = 371

_COLORS = {
    "NOT_IN_RFI": (18, 38, 60),
    "FOLD": (39, 125, 161),
    "CALL": (64, 145, 108),
    "4BET": (227, 130, 20),
    "ALL IN": (164, 22, 26),
}
_COLOR_DISTANCE_MAX = 45


def _distance(a, b):
    return sum((int(x) - int(y)) ** 2 for x, y in zip(a, b)) ** 0.5


def _nearest_color(rgb):
    action, distance = min(
        ((action, _distance(rgb, color)) for action, color in _COLORS.items()),
        key=lambda item: item[1],
    )
    return action if distance <= _COLOR_DISTANCE_MAX else None


def _cell_actions(image, x0, y0, row, column):
    """Acciones visibles en una celda, ignorando texto y bordes.

    ``NOT_IN_RFI`` solo gana cuando no aparece ninguna acción condicional. Si
    media celda es oscura y media CALL, el significado al llegar al nodo es
    CALL, no «abrir/fold 50 %».
    """
    cell_w = _GRID_W / 13
    cell_h = _GRID_H / 13
    left = round(x0 + column * cell_w) + 2
    right = round(x0 + (column + 1) * cell_w) - 2
    top = round(y0 + row * cell_h) + 2
    bottom = round(y0 + (row + 1) * cell_h) - 2
    counts = Counter(
        action
        for pixel in image.crop(
            (left, top, right, bottom)).get_flattened_data()
        if (action := _nearest_color(pixel)) is not None
    )
    strategic = [(action, count) for action, count in counts.items()
                 if action != "NOT_IN_RFI"]
    strategic_total = sum(count for _action, count in strategic)
    classified_total = sum(counts.values())
    # El antialias del texto blanco deja 1-3 píxeles cercanos al azul incluso
    # en una celda oscura. No son una franja de estrategia.
    if (not strategic
            or strategic_total < 20
            or strategic_total / max(1, classified_total) < 0.10):
        return ("NOT_IN_RFI",)
    strategic.sort(key=lambda item: (-item[1], item[0]))
    total = sum(count for _action, count in strategic)
    material = {
        action for action, count in strategic
        if count / total >= 0.20
    }
    order = ("FOLD", "CALL", "4BET", "ALL IN")
    return tuple(action for action in order if action in material)[:2]


def _chart_origins(number):
    """Posiciones de N gráficos: cuatro arriba y el resto abajo."""
    return [
        (_X[index % 4], _Y[index // 4])
        for index in range(number)
    ]


def _orange_label(image_path, x0, y0):
    """Detecta si el árbol ofrece una 4-bet no all-in.

    El PDF imprime tamaños con dos decimales en una tipografía de 5 píxeles. El
    OCR confundía ``17.4`` con ``174`` y ``14.1`` con ``41``. Se conserva la
    acción fiable sin fabricar un tamaño: el importador prefiere una indicación
    incompleta y explícita a un sizing numérico falso.
    """
    image = Image.open(image_path).convert("RGB")
    legend_y = y0 + _LEGEND_Y_OFFSET
    # ¿La leyenda tiene naranja? En ese caso son cuatro cajas iguales.
    probe = image.crop((
        x0 + _GRID_W // 2,
        legend_y,
        x0 + 3 * _GRID_W // 4,
        legend_y + 30,
    ))
    orange = sum(
        _nearest_color(pixel) == "4BET"
        for pixel in probe.get_flattened_data())
    if orange < 100:
        return None
    return "4BET NON-ALL-IN"


def _render_pages(pdf_path, output_dir):
    prefix = output_dir / "page"
    subprocess.run(
        [
            "pdftoppm", "-f", "10", "-l", "16", "-png", "-r", "120",
            str(pdf_path), str(prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return [output_dir / f"page-{page}.png" for page in range(10, 17)]


def _render_rfi_page(pdf_path, output_dir):
    prefix = output_dir / "rfi"
    subprocess.run(
        [
            "pdftoppm", "-f", "3", "-l", "3", "-png", "-r", "120",
            str(pdf_path), str(prefix),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return output_dir / "rfi-03.png"


def _import_rfi(page_path):
    image = Image.open(page_path).convert("RGB")
    result = {}
    for position, (x0, y0) in zip(
            POSITIONS[:-1], _chart_origins(len(POSITIONS) - 1)):
        probe = image.crop((x0, y0, x0 + _GRID_W, y0 + _GRID_H))
        solid_strategy_pixels = sum(
            min(_distance(pixel, color) for color in _COLORS.values()) <= 10
            for pixel in probe.get_flattened_data()
        )
        if solid_strategy_pixels < 1000:
            # El PDF de 50 BB, por ejemplo, no publica gráfico de SB. La zona
            # está vacía y no puede convertirse en 169 folds por accidente.
            continue
        buckets = {}
        for row in range(13):
            for column in range(13):
                hand = hand_at(row, column)
                colors = _cell_actions(image, x0, y0, row, column)
                mapped = []
                for color in colors:
                    action = {
                        "NOT_IN_RFI": "FOLD",
                        "FOLD": "FOLD",
                        "CALL": "LIMP",
                        "4BET": "OPEN RAISE",
                        "ALL IN": "OPEN RAISE ALL IN",
                    }[color]
                    if action not in mapped:
                        mapped.append(action)
                label = (
                    mapped[0] if len(mapped) == 1 else
                    f"{mapped[0]} 50% / {mapped[1]} 50%"
                )
                buckets.setdefault(label, []).append(hand)
        assert sum(map(len, buckets.values())) == 169
        result[position] = buckets
    return result


def import_pdf(pdf_path, stack):
    response = {}
    with tempfile.TemporaryDirectory(prefix=f"rangeconverter_{stack}_") as tmp:
        tmp_path = Path(tmp)
        pages = _render_pages(pdf_path, tmp_path)
        rfi = _import_rfi(_render_rfi_page(pdf_path, tmp_path))
        for hero_index, page_path in enumerate(pages):
            hero_position = POSITIONS[hero_index]
            opponents = POSITIONS[hero_index + 1:]
            image = Image.open(page_path).convert("RGB")
            hero_table = response.setdefault(hero_position, {})
            for opponent, (x0, y0) in zip(
                    opponents, _chart_origins(len(opponents))):
                orange_label = _orange_label(page_path, x0, y0)
                buckets = {}
                for row in range(13):
                    for column in range(13):
                        hand = hand_at(row, column)
                        actions = list(_cell_actions(
                            image, x0, y0, row, column))
                        actions = [
                            orange_label if action == "4BET" else action
                            for action in actions
                        ]
                        label = (
                            actions[0] if len(actions) == 1 else
                            f"{actions[0]} 50% / {actions[1]} 50%"
                        )
                        buckets.setdefault(label, []).append(hand)
                assert sum(map(len, buckets.values())) == 169
                hero_table[opponent] = buckets
    return rfi, response


def build(pdf_dir):
    pdf_dir = Path(pdf_dir)
    open_raise = {}
    response_to_3bet = {}
    for stack in STACKS:
        path = pdf_dir / f"{stack}.pdf"
        if not path.is_file():
            raise FileNotFoundError(path)
        rfi, response = import_pdf(path, stack)
        open_raise[str(stack)] = rfi
        response_to_3bet[str(stack)] = response
    return {
        "_meta": {
            "source_name": "RangeConverter Free 8-max MTT Charts",
            "source_urls": {str(k): v for k, v in SOURCES.items()},
            "format": "MTT 8-max",
            "players": 8,
            "ante_total_bb": 1.0,
            "utility": "chip-EV",
            "frequency_resolution": 0.5,
            "families": ["RFI", "RFI response to 3bet"],
            "license_note": "Datos derivados de PDF públicos; no se incluyen los PDF.",
        },
        "open_raise": open_raise,
        "response_to_3bet": response_to_3bet,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pdf-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = build(args.pdf_dir)
    args.output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
