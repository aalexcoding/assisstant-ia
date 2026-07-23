"""
Proceso aislado para las llamadas a tesserocr.

Motivo: llamar a tesserocr en el mismo proceso que hace la clasificacion de
pixeles con opencv/pillow provoca corrupcion de memoria intermitente (los
tres wheels empaquetan sus propias copias de libjpeg/libpng/libtiff, con
riesgo de colision de simbolos). Se detecto porque, en tandas grandes,
process_threebet_image asignaba de vez en cuando la MISMA posicion de rival
a dos imagenes distintas de forma no determinista (variaba de una ejecucion
a otra); al quitar las llamadas a tesserocr del proceso el problema
desaparecio en varias ejecuciones de control. Aislar el OCR en un
subproceso corto evita que una corrupcion en tesserocr pueda afectar los
arrays numpy del proceso principal.

Entrada (stdin): JSON {"image": "<path>", "boxes": [[x0,y0,x1,y1,scale], ...]}
Salida (stdout): JSON con la lista de textos OCR, en el mismo orden.
"""
import json
import os
import sys

from PIL import Image
import tesserocr

_BUNDLED_TESSDATA = os.path.join(os.path.dirname(__file__), "tessdata") + "/"
_SYSTEM_TESSDATA_CANDIDATES = [
    "/usr/share/tesseract/tessdata/",
    "/usr/share/tessdata/",
    "/usr/share/tesseract-ocr/5/tessdata/",
    "/usr/share/tesseract-ocr/4.00/tessdata/",
]


def _resolve_tessdata_path():
    for path in _SYSTEM_TESSDATA_CANDIDATES:
        if os.path.isfile(os.path.join(path, "eng.traineddata")):
            return path
    return _BUNDLED_TESSDATA


TESSDATA_PATH = _resolve_tessdata_path()


def main():
    payload = json.loads(sys.stdin.read())
    im = Image.open(payload["image"]).convert("RGB")
    results = []
    with tesserocr.PyTessBaseAPI(path=TESSDATA_PATH) as api:
        for x0, y0, x1, y1, scale in payload["boxes"]:
            crop = im.crop((x0, y0, x1, y1))
            if scale != 1:
                crop = crop.resize((int(crop.width * scale), int(crop.height * scale)), Image.LANCZOS)
            api.SetImage(crop)
            results.append(api.GetUTF8Text())
    sys.stdout.write(json.dumps(results))


if __name__ == "__main__":
    main()
