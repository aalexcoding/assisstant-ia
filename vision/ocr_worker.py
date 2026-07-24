"""
Proceso aislado para las llamadas a tesserocr, igual que en
decision/preflop/ocr_worker.py: mezclar tesserocr con opencv en el mismo
proceso arriesga corrupcion de memoria (colision de simbolos entre las
copias de libjpeg/libpng/libtiff que empaquetan sus wheels). Aqui ademas
el preprocesado (CLAHE, reescalado) que mejora bastante el OCR de los
nameplates SI necesita opencv, asi que ese trabajo lo hace el proceso
principal (que ya usa opencv para todo lo demas) y escribe PNGs temporales
ya preprocesados; este proceso solo abre esos PNG con PIL y llama a
tesserocr, sin importar cv2 en ningun momento.

Entrada (stdin): JSON {"jobs": [job, ...]}
  job modo "tsv":  {"mode": "tsv", "path": "<png>"}
  job modo "text": {"mode": "text", "path": "<png>", "whitelist": "AKQJ0123456789" (opcional), "psm": "SINGLE_LINE"}
Salida (stdout): JSON {"results": [resultado, ...]} en el mismo orden.
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
    results = []
    with tesserocr.PyTessBaseAPI(path=TESSDATA_PATH) as api:
        for job in payload["jobs"]:
            im = Image.open(job["path"]).convert("RGB")
            api.SetImage(im)
            if job["mode"] == "tsv":
                api.SetPageSegMode(tesserocr.PSM.SPARSE_TEXT)
                api.SetVariable("tessedit_char_whitelist", "")
                results.append(api.GetTSVText(0))
            else:
                psm = getattr(tesserocr.PSM, job.get("psm", "SINGLE_LINE"))
                api.SetPageSegMode(psm)
                api.SetVariable("tessedit_char_whitelist", job.get("whitelist", ""))
                results.append(api.GetUTF8Text().strip())
    sys.stdout.write(json.dumps({"results": results}))


if __name__ == "__main__":
    main()
