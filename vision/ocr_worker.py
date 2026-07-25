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

IDIOMA: el cliente de PokerStars esta en CASTELLANO, pero el modelo espanol NO
es mejor en todas las zonas, asi que se elige POR JOB (cada job puede pedir su
"lang"), no globalmente. Medido sobre las 111 capturas de samples_layout2/:

  - ZONAS CON PROSA CASTELLANA (chat, botones de accion) -> espanol.
    El chat lleva frases enteras ("Repartidor: ... gana el bote (2.040) con
    pareja de nueves", "Los limites suben: Ciegas 50/100 Ante 15") y con el
    modelo ingles los acentos se corrompen ("Informaci6n" por "Información"),
    lo que degrada el parseo del resultado de mano y el de ciegas del chat.

  - NAMEPLATES -> ingles. Contienen NICKS (ASCII, no palabras en castellano) y
    numeros. Con el modelo espanol la lectura de nombres EMPEORA claramente
    -404 -> 368 nameplates con nombre legible, y el nombre del hero cae del
    74.8% al 55.0% de los frames-: el modelo tiende a "corregir" un nick hacia
    una palabra con tilde, y entonces deja de encajar con el patron ASCII de
    text_extract._is_name_candidate. Los verbos de accion del nameplate
    ("Igualar"/"Pasar"/"Ausente") si son castellano, pero solo se usan para
    decidir OCUPACION, que tambien se satisface con el nick o el stack, asi que
    el nombre pesa mas. El resto de metricas (cartas, posicion, bote, ciegas,
    stacks) sale igual con los dos modelos.

  - RANGO DE CARTA (mode "text", whitelist de digitos+AKQJ) -> ingles.
    Ya ajustado y funcionando; no hay una sola palabra en castellano que ganar.

Resultado medido de repartirlo asi (spa solo en chat+botones) contra las mismas
111 capturas: TODAS las metricas del GameState quedan identicas al baseline en
ingles (nombre del hero 83/111, 404 nameplates con nombre, cartas/posicion/
bote/ciegas/stacks sin cambio) y en el chat sube lo que se buscaba -las manos
ganadoras legibles pasan de 37 a 42 de 111, y los caracteres acentuados leidos
de 26 a 100-. Es decir: se gana en el chat sin pagarlo en los nameplates.

Coste en latencia: +0.55s por frame (2.89s -> 3.44s) porque el subproceso
inicializa DOS APIs de tesseract (una por idioma) en vez de una. Sigue dentro
del margen de 5s del proyecto. Se puede recuperar cuando se paralelice el lote
de OCR en varios procesos (hoy los ~106 jobs de un frame corren en serie en un
solo nucleo), que es una mejora pendiente aparte y de mayor calado.

Degradacion limpia: si no hay spa.traineddata disponible se usa ingles para
todo, es decir el comportamiento anterior. Para tenerlo, cualquiera de las dos:
  - sudo dnf install tesseract-langpack-spa        (a nivel de sistema)
  - vision/tessdata/{spa,eng}.traineddata          (local al repo, no versionado)
tesseract exige que todos los idiomas de una misma llamada vivan en el MISMO
directorio de tessdata, de ahi que se prefiera un directorio que tenga los dos.

Entrada (stdin): JSON {"jobs": [job, ...]}
  job modo "tsv":  {"mode": "tsv", "path": "<png>", "lang": "spa" (opcional)}
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

# idioma por defecto (nicks, numeros, rangos de carta) y el que se usa cuando un
# job pide explicitamente castellano porque su zona lleva prosa (ver docstring).
DEFAULT_LANG = "eng"
LANG_SPANISH_PROSE = "spa+eng"


def _has_lang(path, lang):
    return os.path.isfile(os.path.join(path, f"{lang}.traineddata"))


def _resolve_tessdata():
    """Devuelve (path, spanish_ok). Prefiere un directorio de tessdata que tenga
    espanol E ingles (tesseract exige que los idiomas de una misma llamada esten
    en el mismo directorio); si no hay ninguno con los dos, cae al primero que
    tenga ingles y marca el espanol como no disponible."""
    for path in [_BUNDLED_TESSDATA] + _SYSTEM_TESSDATA_CANDIDATES:
        if _has_lang(path, "eng") and _has_lang(path, "spa"):
            return path, True
    for path in _SYSTEM_TESSDATA_CANDIDATES:
        if _has_lang(path, "eng"):
            return path, False
    return _BUNDLED_TESSDATA, False


TESSDATA_PATH, SPANISH_AVAILABLE = _resolve_tessdata()


def _job_lang(job):
    """Idioma efectivo de un job. Solo los que piden "spa" explicitamente (y solo
    si hay modelo espanol instalado) se salen del ingles por defecto."""
    if job.get("lang") == "spa" and SPANISH_AVAILABLE:
        return LANG_SPANISH_PROSE
    return DEFAULT_LANG


def _run_job(api, job):
    im = Image.open(job["path"]).convert("RGB")
    api.SetImage(im)
    if job["mode"] == "tsv":
        api.SetPageSegMode(tesserocr.PSM.SPARSE_TEXT)
        api.SetVariable("tessedit_char_whitelist", "")
        return api.GetTSVText(0)
    psm = getattr(tesserocr.PSM, job.get("psm", "SINGLE_LINE"))
    api.SetPageSegMode(psm)
    api.SetVariable("tessedit_char_whitelist", job.get("whitelist", ""))
    return api.GetUTF8Text().strip()


def main():
    payload = json.loads(sys.stdin.read())
    jobs = payload["jobs"]

    # se agrupa por idioma para inicializar UNA sola API por idioma (inicializar
    # tesseract es caro); los resultados se colocan por indice para devolverlos
    # en el orden original de entrada, que es el que espera OcrBatch.
    by_lang = {}
    for i, job in enumerate(jobs):
        by_lang.setdefault(_job_lang(job), []).append(i)

    results = [""] * len(jobs)
    for lang, indices in by_lang.items():
        with tesserocr.PyTessBaseAPI(path=TESSDATA_PATH, lang=lang) as api:
            for i in indices:
                results[i] = _run_job(api, jobs[i])

    sys.stdout.write(json.dumps({"results": results}))


if __name__ == "__main__":
    main()
