"""
OCR con un modelo de vision (olmOCR) en lugar de tesseract.

Se enchufa en la costura que ya existe, `ocr_client.usar_backend`: recibe los
MISMOS jobs que el worker de tesseract y devuelve resultados en el MISMO formato,
asi que ni table_state ni text_extract se enteran. Es lo que permite medir uno
contra otro sobre el corpus sin tocar el pipeline (ver herramientas/comparar_ocr.py).

POR QUE HAY QUE FABRICAR UN TSV. Los jobs "tsv" no devuelven texto: devuelven las
COLUMNAS de tesseract (bloque, parrafo, linea, x, y, ancho, alto, confianza,
palabra), y text_extract.parse_tsv_lines agrupa por esas columnas y luego empareja
nombre y stack por PROXIMIDAD (cx/cy). Un modelo de vision devuelve texto, no
cajas. Aqui se sintetizan: las lineas se reparten de arriba abajo por el alto del
recorte y las palabras de izquierda a derecha por su longitud.

ESO ES UNA APROXIMACION Y SOLO VALE PORQUE LOS RECORTES SON PEQUEÑOS. En el
camino en vivo (table_state.analyze_layout) todos los jobs "tsv" son zonas de
geometria ya conocida -la capsula de UN asiento, el bote, el chat, los botones-,
y lo que se pregunta dentro de ellas es "que linea va encima de cual", que el
reparto vertical conserva. Los jobs de FRAME ENTERO (table_state.analyze, la ruta
de diagnostico) piden coordenadas de verdad y con esto NO funcionarian; no se
usan en produccion.

EL SERVIDOR. Se habla la API de OpenAI, que es la que sirven Ollama, vLLM y LM
Studio, y es tambien por donde olmOCR upstream acepta un servidor externo
(`olmocr --server`). Aqui no se usa el paquete `olmocr`: ese es un arnes de lotes
de PDF (rasteriza paginas, ancla con pdftotext, escribe dolma) y lo que hace
falta es el modelo. Por defecto apunta a Ollama en local.

    POKER_OCR_VLM_URL     http://localhost:11434/v1/chat/completions
    POKER_OCR_VLM_MODELO  hf.co/bartowski/allenai_olmOCR-2-7B-1025-GGUF:Q4_K_M

TEMPERATURA 0 Y NADA MAS QUE LO QUE SE VE. Toda la app esta construida sobre
abstenerse antes que inventar, y un modelo generativo hace justo lo contrario:
donde tesseract devolvia cadena vacia, el devuelve algo plausible. El prompt se
lo prohibe explicitamente y ademas se mide (ver comparar_ocr.py), porque una
recomendacion sobre un stack inventado es peor que no dar recomendacion.
"""
import base64
import json
import os
import time
import urllib.error
import urllib.request

URL = os.environ.get("POKER_OCR_VLM_URL", "http://localhost:11434/v1/chat/completions")
MODELO = os.environ.get("POKER_OCR_VLM_MODELO",
                        "hf.co/bartowski/allenai_olmOCR-2-7B-1025-GGUF:Q4_K_M")
TIMEOUT_S = float(os.environ.get("POKER_OCR_VLM_TIMEOUT", "120"))

# Confianza que se le pone a cada palabra del TSV sintetico. parse_tsv_lines
# descarta por debajo de 25; el modelo no da confianza por palabra, asi que o se
# acepta todo lo que dice o no se acepta nada. Se acepta, y el filtro de basura
# lo siguen haciendo las regex de text_extract, igual que con tesseract.
CONF = 96

PROMPT_TSV = (
    "Transcribe the visible text in this cropped screenshot of a poker table, "
    "exactly as it appears, one line of output per visual line, top to bottom. "
    "Keep the original characters, including commas as decimal separators and "
    "suffixes like BB. Do not translate. Do not explain. Do not add anything "
    "that is not clearly legible: if a line is unreadable, skip it. If there is "
    "no legible text at all, answer with nothing."
)

PROMPT_TEXT = (
    "This is a cropped playing card rank. Answer with the single rank character "
    "and nothing else, one of: A K Q J 10 9 8 7 6 5 4 3 2. "
    "If it is not clearly legible, answer with nothing."
)


class ServidorVlmCaido(RuntimeError):
    """No hay servidor de inferencia escuchando, o no responde."""


def _pedir(png_b64, prompt, temperatura=0.0, max_tokens=256):
    """Una llamada al modelo. Devuelve el texto de la respuesta, ya limpio."""
    cuerpo = json.dumps({
        "model": MODELO,
        "temperature": temperatura,
        "max_tokens": max_tokens,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64," + png_b64}},
            ],
        }],
    }).encode()
    peticion = urllib.request.Request(
        URL, data=cuerpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as r:
            datos = json.loads(r.read())
    except urllib.error.URLError as e:
        raise ServidorVlmCaido(f"no responde {URL}: {e}") from e
    return datos["choices"][0]["message"]["content"].strip()


def lineas_limpias(respuesta):
    """Las lineas utiles de una respuesta del modelo.

    Se tiran las vacias y las que son la forma que tiene un modelo de decir "no
    hay nada" -y que un OCR devolveria como cadena vacia-. Sin esto, un recorte
    ilegible mete la frase entera en el TSV y text_extract la trata como texto de
    la mesa."""
    fuera = ("no text", "no legible", "nothing", "n/a", "unreadable", "```")
    out = []
    for linea in respuesta.splitlines():
        linea = linea.strip().strip("`")
        if not linea:
            continue
        if linea.lower().startswith(fuera):
            continue
        out.append(linea)
    return out


def tsv_sintetico(lineas, ancho, alto):
    """Fabrica el TSV que espera text_extract.parse_tsv_lines.

    Solo se emiten filas de nivel 5 (palabra), que son las unicas que ese parser
    mira. Las lineas se reparten a lo alto y las palabras a lo ancho en
    proporcion a su longitud: dentro de una capsula de nameplate eso basta para
    que el nombre quede ENCIMA del stack, que es lo que se pregunta ahi.
    """
    if not lineas:
        return ""
    filas = []
    alto_linea = max(1, alto // len(lineas))
    for i, texto in enumerate(lineas):
        palabras = texto.split()
        if not palabras:
            continue
        total = sum(len(p) for p in palabras) or 1
        x = 0
        for j, palabra in enumerate(palabras):
            w = max(1, int(ancho * len(palabra) / total))
            filas.append("\t".join([
                "5", "1", "1", "1", str(i + 1), str(j + 1),
                str(x), str(i * alto_linea), str(w), str(alto_linea),
                str(CONF), palabra,
            ]))
            x += w
    # la cabecera va porque el TSV de tesseract la lleva; el parser la ignora
    # sola (su primera columna no es "5")
    cabecera = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
                "left\ttop\twidth\theight\tconf\ttext")
    return "\n".join([cabecera] + filas)


def _tamano_png(png_b64):
    """(ancho, alto) de un PNG sin descomprimirlo: la cabecera IHDR los lleva en
    los bytes 16-24. Se evita asi meter PIL o cv2 en este modulo."""
    crudo = base64.b64decode(png_b64)
    ancho = int.from_bytes(crudo[16:20], "big")
    alto = int.from_bytes(crudo[20:24], "big")
    return ancho, alto


def resolver_job(job):
    """Un job en el formato de ocr_client, resuelto por el modelo."""
    png_b64 = job.get("png_b64")
    if png_b64 is None:
        return ""
    if job.get("mode") == "tsv":
        lineas = lineas_limpias(_pedir(png_b64, PROMPT_TSV))
        ancho, alto = _tamano_png(png_b64)
        return tsv_sintetico(lineas, ancho, alto)
    respuesta = _pedir(png_b64, PROMPT_TEXT, max_tokens=8)
    lineas = lineas_limpias(respuesta)
    return lineas[0] if lineas else ""


def backend(jobs):
    """El resolvedor que espera ocr_client.usar_backend.

    EN SERIE Y A PROPOSITO: el servidor de inferencia tiene UN modelo cargado y
    lo sirve de uno en uno, asi que lanzar hilos aqui solo cambiaria donde se
    hace la cola. Un job que falla devuelve "" -igual que en el worker de
    tesseract- porque perder un recorte es mucho menos grave que perder el frame.
    """
    salida = []
    for job in jobs:
        try:
            salida.append(resolver_job(job))
        except ServidorVlmCaido:
            raise
        except Exception:  # noqa: BLE001
            salida.append("")
    return salida


def usar_para_estudio(log=print):
    """Pone ESTE backend como OCR del pipeline. Devuelve el anterior.

    SOLO PARA ESTUDIAR CASOS EN FRIO, y no hay ni un camino en vivo que llame a
    esto a proposito: son ~5 s por recorte y ~35 recortes por frame, o sea
    minutos por frame contra los ~0,3 s del ciclo entero con tesseract (la
    medicion completa, en docs/OCR-OLMOCR-MEDICION.md). Que no se pueda encender
    por variable de entorno es la idea: una app de jugar que se vuelve mil veces
    mas lenta porque alguien exporto algo no es un modo, es un accidente.

    Para mirar UN frame hay algo mucho mas barato: ver_frame.py --olmocr, que
    hace una sola llamada (leer_mesa) en vez de una por recorte.
    """
    from vision import ocr_client
    ok, motivo = disponible()
    if not ok:
        raise ServidorVlmCaido(
            f"{motivo}\n  arrancalo con:  ollama serve  &&  ollama pull {MODELO}")
    log(f"OCR del pipeline: {MODELO} (estudio en frio; esto va a tardar)")
    return ocr_client.usar_backend(backend)


def disponible():
    """(True, modelo) si hay servidor y el modelo esta cargado; (False, motivo)."""
    raiz = URL.split("/v1/")[0]
    try:
        with urllib.request.urlopen(raiz + "/v1/models", timeout=5) as r:
            modelos = [m["id"] for m in json.loads(r.read()).get("data", [])]
    except Exception as e:  # noqa: BLE001
        return False, f"no hay servidor en {raiz}: {e}"
    if MODELO not in modelos:
        return False, f"el servidor no sirve {MODELO} (tiene: {', '.join(modelos) or 'nada'})"
    return True, MODELO


# --- LEER LA MESA DE UNA SOLA LLAMADA ---------------------------------------
#
# Es la unica forma que cabe en el presupuesto. Medido en este Mac (M-series,
# olmOCR-2-7B Q4_K_M en Ollama), sobre un frame real de 1595x971:
#
#     por recorte, 17 zonas tsv          ~5,5 s cada una      ~93 s por frame
#     una llamada al frame entero        prefill 2050 tok      11,3 s
#     una llamada al frame a la MITAD    prefill 1105 tok       6,6 s
#
# El coste es casi todo PREFILL de la imagen (9,2 s de los 11,3 en el frame
# entero, a ~223 tok/s); la respuesta son 90 tokens a ~46 tok/s. Por eso bajar la
# imagen a la mitad casi lo divide por dos y no cambia ni una letra de la
# lectura. Por debajo de la mitad NO se gana nada -el modelo reescala a un
# presupuesto fijo de tokens: 1105 con 1/2, 1/3 y 1/4- y en cambio se empieza a
# perder texto ("DannySann1D1", "silvagamer0", el bote "2.1" por "2,1").
ESCALA_MESA = 0.5

PROMPT_MESA = (
    "Poker table screenshot. List each player nameplate you can read, one per "
    "line, as: nickname|amount. Then a last line: POT|amount. "
    "Copy the characters exactly as shown, including commas and the BB suffix. "
    "Only what is clearly legible. No other text."
)


def leer_mesa(bgr, escala=ESCALA_MESA):
    """Lee los nameplates y el bote de un frame de mesa en UNA llamada.

    Devuelve {"jugadores": {nombre: importe}, "bote": importe|None,
              "segundos": float, "crudo": str}.

    No sintetiza TSV ni pasa por el pipeline: es la lectura en bruto, que es lo
    que hace falta para MEDIR el modelo contra tesseract (ver
    herramientas/comparar_ocr.py) antes de decidir si se cablea.
    """
    import cv2
    if escala != 1.0:
        bgr = cv2.resize(bgr, (int(bgr.shape[1] * escala), int(bgr.shape[0] * escala)),
                         interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("no se pudo codificar el frame")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")

    t0 = time.perf_counter()
    crudo = _pedir(b64, PROMPT_MESA, max_tokens=256)
    segundos = time.perf_counter() - t0

    jugadores, bote = {}, None
    for linea in lineas_limpias(crudo):
        if "|" not in linea:
            continue
        izq, der = linea.split("|", 1)
        izq, der = izq.strip(), der.strip()
        if izq.upper() == "POT":
            bote = der or None
        elif izq:
            jugadores[izq] = der or None
    return {"jugadores": jugadores, "bote": bote, "segundos": segundos, "crudo": crudo}


def medir(png_b64, prompt=PROMPT_TSV, veces=1):
    """Latencia por llamada, para el spike de presupuesto. Devuelve
    (segundos_por_llamada, ultima_respuesta)."""
    tiempos, respuesta = [], ""
    for _ in range(veces):
        t0 = time.perf_counter()
        respuesta = _pedir(png_b64, prompt)
        tiempos.append(time.perf_counter() - t0)
    return sum(tiempos) / len(tiempos), respuesta
