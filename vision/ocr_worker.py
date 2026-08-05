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
  - sudo dnf install tesseract-langpack-spa        (Fedora, a nivel de sistema)
    sudo apt-get install tesseract-ocr-spa         (Debian/Ubuntu, idem)
    brew install tesseract-lang                    (macOS, trae TODOS los idiomas)
  - vision/tessdata/{spa,eng}.traineddata          (local al repo, no versionado)
    curl -sL -o vision/tessdata/spa.traineddata \
      https://github.com/tesseract-ocr/tessdata_fast/raw/main/spa.traineddata
    Es la via ligera y la que se usa en Mac: 6 MB los dos modelos, y ademas la
    rueda de tesserocr ya trae su propia libtesseract, asi que con esto el OCR
    funciona sin instalar tesseract en el sistema.
tesseract exige que todos los idiomas de una misma llamada vivan en el MISMO
directorio de tessdata, de ahi que se prefiera un directorio que tenga los dos.

Entrada (stdin): JSON {"jobs": [job, ...]}
  job modo "tsv":  {"mode": "tsv", "png_b64": "<png en base64>", "lang": "spa" (opcional)}
  job modo "text": {"mode": "text", "png_b64": "<png en base64>", "whitelist": "AKQJ0123456789" (opcional), "psm": "SINGLE_LINE"}
  (se acepta tambien "path": "<fichero png>" en vez de "png_b64", para diagnostico)
Salida (stdout): JSON {"results": [resultado, ...]} en el mismo orden.

MODO SERVIDOR (--serve): en vez de resolver un lote y salir, el proceso se queda
vivo leyendo una linea JSON de peticion por stdin y escribiendo una de respuesta
por stdout. Asi las APIs de tesseract se cargan UNA vez por sesion y no una por
lote. Importa porque el suelo de un lote es ~0,15 s de arranque + carga del
modelo, mas que el propio OCR de un recorte pequeño; con el vigilante rapido
(seat_watch) haciendo lotes de una sola capsula, ese suelo era todo el coste.
"""
import base64
import io
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
    # macOS con Homebrew: arm64 instala en /opt/homebrew, Intel en /usr/local.
    # La rueda de tesserocr trae SU PROPIA libtesseract, asi que en un Mac no
    # hace falta `brew install tesseract` para nada mas que estos modelos; el
    # camino ligero es dejarlos en vision/tessdata/ (_BUNDLED_TESSDATA), que son
    # 6 MB frente al giga largo de tesseract-lang.
    "/opt/homebrew/share/tessdata/",
    "/usr/local/share/tessdata/",
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


def _abrir(job):
    """Imagen del job. Puede venir por RUTA (un PNG temporal, como siempre) o
    EN MEMORIA -"png_b64": el PNG codificado en base64 dentro del propio JSON-.

    En memoria porque escribir los PNG al disco era 0,12 s del ciclo, el segundo
    coste despues del OCR: ~105 recortes por frame, cada uno un fichero. Se
    codifica en PNG y no en crudo para no multiplicar por 3 el tamaño del JSON
    (los recortes ya vienen en escala de grises)."""
    b64 = job.get("png_b64")
    if b64 is not None:
        return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    return Image.open(job["path"]).convert("RGB")


def _run_job(api, job):
    im = _abrir(job)
    api.SetImage(im)
    if job["mode"] == "tsv":
        # SPARSE_TEXT por defecto (texto suelto repartido por la zona, que es lo
        # que hay en el tapete y en el chat). Un job puede pedir otro: la capsula
        # de un nameplate NO es texto suelto, es una columna de dos lineas, y en
        # SPARSE_TEXT tesseract se deja una de las dos. Ver PSM_NAMEPLATE en
        # vision/table_state.py, donde esta la medicion.
        api.SetPageSegMode(getattr(tesserocr.PSM, job.get("psm", "SPARSE_TEXT")))
        api.SetVariable("tessedit_char_whitelist", "")
        return api.GetTSVText(0)
    psm = getattr(tesserocr.PSM, job.get("psm", "SINGLE_LINE"))
    api.SetPageSegMode(psm)
    api.SetVariable("tessedit_char_whitelist", job.get("whitelist", ""))
    return api.GetUTF8Text().strip()


# APIs ya inicializadas, por idioma. En modo servidor el proceso vive entre
# lotes, asi que la de cada idioma se carga UNA vez en toda la sesion en vez de
# una vez por lote. Es la razon de ser del modo servidor: arrancar el proceso y
# cargar tesseract cuesta ~0,15 s, mas que el OCR de un recorte pequeño.
_APIS = {}


def _api(lang):
    api = _APIS.get(lang)
    if api is None:
        api = _APIS[lang] = tesserocr.PyTessBaseAPI(path=TESSDATA_PATH, lang=lang)
    return api


def resolver(jobs):
    """Resuelve una lista de jobs y devuelve los resultados EN EL MISMO ORDEN.

    Se agrupa por idioma para no ir alternando de modelo dentro del lote. Un job
    que falla devuelve "" en vez de tumbar el lote entero: en modo servidor el
    proceso sigue vivo para los siguientes, y perder un recorte es mucho menos
    grave que perder el proceso."""
    by_lang = {}
    for i, job in enumerate(jobs):
        by_lang.setdefault(_job_lang(job), []).append(i)

    results = [""] * len(jobs)
    for lang, indices in by_lang.items():
        api = _api(lang)
        for i in indices:
            try:
                results[i] = _run_job(api, jobs[i])
            except Exception:  # noqa: BLE001
                results[i] = ""
    return results


def _servir():
    """Modo SERVIDOR: una linea JSON de peticion por stdin, una de respuesta por
    stdout, hasta que se cierre stdin. Sin esto habria que arrancar un proceso
    -y cargar tesseract- por cada lote."""
    for linea in sys.stdin:
        linea = linea.strip()
        if not linea:
            continue
        try:
            jobs = json.loads(linea)["jobs"]
            salida = {"results": resolver(jobs)}
        except Exception as e:  # noqa: BLE001
            salida = {"error": str(e)}
        sys.stdout.write(json.dumps(salida) + "\n")
        sys.stdout.flush()


def main():
    if "--serve" in sys.argv:
        _servir()
        return
    jobs = json.loads(sys.stdin.read())["jobs"]
    sys.stdout.write(json.dumps({"results": resolver(jobs)}))


if __name__ == "__main__":
    main()
