"""
Punto de entrada del proceso principal (opencv) hacia el subproceso aislado
de OCR (ocr_worker.py, PIL+tesserocr). El preprocesado que mejora el OCR
(CLAHE, reescalado) se hace aqui con opencv y se vuelca a PNG temporal; el
subproceso solo abre esos PNG, nunca toca opencv.
"""
import json
import os
import atexit
import base64
import subprocess
import sys
import threading

import cv2
from concurrent.futures import ThreadPoolExecutor

# El worker se lanza como MODULO, no por ruta: `vision` es un paquete y hay otro
# ocr_worker.py en decision/preflop/, asi que el nombre solo es ambiguo. Con -m la
# resolucion la hace el import system y no el azar del sys.path del proceso hijo.
# Necesita la raiz del proyecto como cwd, de ahi RAIZ.
WORKER_MODULE = "vision.ocr_worker"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Procesos de OCR en paralelo. Se deja la mayor parte de la maquina libre a
# proposito: ver el docstring de OcrBatch.run. ThreadPoolExecutor y no
# ProcessPool porque cada hilo solo espera en subprocess.run, que suelta el GIL.
MAX_PROCS = max(1, min(6, (os.cpu_count() or 2) - 2))


def _png_b64(img):
    """Codifica un recorte a PNG en base64, para mandarlo al worker DENTRO del
    JSON en vez de por un fichero temporal.

    Escribir los PNG al disco era 0,12 s del ciclo -el segundo coste despues del
    propio OCR-, porque son ~105 ficheros por frame. PNG y no crudo para no
    multiplicar por 3 el tamaño del mensaje: los recortes ya van en escala de
    grises y comprimen mucho."""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("no se pudo codificar el recorte a PNG")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def _clahe_enhance(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


class OcrBatch:
    """Acumula jobs de OCR (paths de imagenes ya preprocesadas por el
    llamador) y los resuelve en una unica invocacion del subproceso."""

    def __init__(self):
        self._jobs = []

    def job_count(self):
        return len(self._jobs)

    def add_tsv_job(self, bgr_full_frame, scale=1, lang=None):
        """Encola un OCR de texto libre. lang=None usa el idioma por defecto del
        worker (ingles); lang="spa" pide el modelo espanol para las zonas que
        contienen PROSA en castellano (ver LANG_SPANISH_PROSE en ocr_worker.py:
        el espanol ayuda con los acentos pero perjudica a los nicks de jugador,
        que son ASCII y el modelo tiende a "corregir" hacia palabras con tilde)."""
        if bgr_full_frame is None or bgr_full_frame.size == 0:
            idx = len(self._jobs)
            self._jobs.append(None)
            return idx
        enhanced = _clahe_enhance(bgr_full_frame)
        if scale != 1:
            enhanced = cv2.resize(enhanced, (enhanced.shape[1] * scale, enhanced.shape[0] * scale),
                                   interpolation=cv2.INTER_LANCZOS4)
        idx = len(self._jobs)
        job = {"mode": "tsv", "png_b64": _png_b64(enhanced), "scale": scale}
        if lang:
            job["lang"] = lang
        self._jobs.append(job)
        return idx

    def add_text_job(self, bgr_crop, whitelist="", psm="SINGLE_LINE", scale=3, pad=20):
        if bgr_crop.size == 0:
            idx = len(self._jobs)
            self._jobs.append(None)
            return idx
        gray = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
        if scale != 1:
            gray = cv2.resize(gray, (gray.shape[1] * scale, gray.shape[0] * scale),
                               interpolation=cv2.INTER_CUBIC)
        # tesseract necesita margen en blanco alrededor del texto: un
        # recorte muy ajustado (el glifo tocando el borde de la imagen)
        # le hace fallar por completo aunque el contraste sea bueno.
        if pad:
            gray = cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        idx = len(self._jobs)
        self._jobs.append({"mode": "text", "png_b64": _png_b64(gray),
                           "whitelist": whitelist, "psm": psm})
        return idx

    def _run_chunk(self, jobs):
        """Resuelve un trozo del lote. Devuelve sus resultados en el mismo orden
        en que se le pasaron. Por defecto usa un worker PERSISTENTE del pool
        (ver _Pool); _BACKEND es la costura para sustituirlo (ver usar_backend)."""
        return _BACKEND(jobs)

    def run(self):
        """Resuelve todos los jobs y devuelve una lista alineada con el orden de
        encolado (los jobs vacios -recorte de tamaño 0- devuelven "").

        EN PARALELO. Un frame encola ~106 recortes y antes se resolvian todos en
        serie dentro de un unico subproceso, o sea en 1 nucleo de los 16 de la
        maquina: 3,85 s, el 83% del ciclo de analisis. Repartidos:
            1 proceso  3,85 s      8 procesos  1,18 s  (3,3x)
            4 procesos 1,30 s     12 procesos  1,00 s  (3,8x)
        Se usan como mucho MAX_PROCS. NO se cogen todos los nucleos a proposito:
        de 8 a 12 procesos solo se ganan 0,18 s y el resto de la maquina -la
        propia ventana GTK, la VM con el cliente de poker- se queda sin aire, que
        es justo el sintoma de lag que se queria arreglar.

        Dentro de cada idioma el reparto es INTERCALADO (jobs[i::n]) y no por
        bloques porque los jobs tienen costes muy distintos: primero van las zonas
        grandes de texto (nameplates, chat, botones) y luego decenas de recortes
        minusculos de rango de carta. Por bloques, el primer proceso se comeria
        todo lo caro.

        LOS JOBS EN ESPAÑOL VAN TODOS AL MISMO PROCESO, y esto vale mas que
        cualquier reparto fino. Cargar el modelo espanol cuesta ~0,26 s, y solo
        dos jobs del frame lo necesitan (chat y botones: son las unicas zonas con
        prosa castellana). Con el reparto intercalado esos dos caian en procesos
        DISTINTOS, asi que el modelo se cargaba DOS VECES y ademas alargaba dos de
        los seis trozos. Juntandolos en un trozo propio se carga una sola vez y
        los otros procesos se quedan solo con lo barato. Medido sobre un frame
        real, 3 corridas:

            intercalado (antes)   1,202 s   trozos [18,18,18,17,17,17]
            espanol aislado       0,888 s   trozos [2,21,21,21,20,20]   -26%

        SIN FICHEROS TEMPORALES: los recortes viajan dentro del JSON (ver
        _png_b64). Antes cada job escribia un PNG a un tmpdir que habia que
        limpiar en un finally, y cuando ese finally no estaba cada fallo dejaba un
        /tmp/vision_ocr_* huerfano que en un lazo en vivo se acumulaba. En
        velocidad da igual -codificar 105 recortes en memoria son 39 ms frente a
        54 ms de escribirlos-, pero quita esa clase de fallo entera."""
        real = [(i, j) for i, j in enumerate(self._jobs) if j is not None]
        # sin ningun job real no hace falta molestar a un worker
        if not real:
            return ["" for _ in self._jobs]

        trozos = self._repartir(real)
        if len(trozos) == 1:
            partes = [self._run_chunk([j for _i, j in trozos[0]])]
        else:
            with ThreadPoolExecutor(max_workers=len(trozos)) as ex:
                partes = list(ex.map(lambda t: self._run_chunk([j for _i, j in t]), trozos))

        por_indice = {}
        for trozo, parte in zip(trozos, partes):
            for (idx, _j), r in zip(trozo, parte):
                por_indice[idx] = r

        return [por_indice.get(i, "") if j is not None else ""
                for i, j in enumerate(self._jobs)]

    @staticmethod
    def _repartir(real):
        """Reparte [(indice, job)] en trozos, uno por proceso. Los jobs que piden
        un idioma no-por-defecto van todos juntos en su propio trozo: ver run()."""
        con_idioma = [p for p in real if p[1].get("lang")]
        sin_idioma = [p for p in real if not p[1].get("lang")]
        trozos = [con_idioma] if con_idioma else []
        n = min(MAX_PROCS - len(trozos), len(sin_idioma))
        if n <= 1:
            if sin_idioma:
                trozos.append(sin_idioma)
        else:
            trozos.extend(sin_idioma[i::n] for i in range(n))
        return [t for t in trozos if t]


# --- POOL DE WORKERS PERSISTENTES -------------------------------------------
#
# Antes se arrancaba un subproceso por trozo y por frame. Medido, el suelo de un
# lote es ~0,15 s aunque solo lleve UN recorte: eso es arrancar python, importar
# PIL/tesserocr y cargar el modelo, no el OCR. Con 6 trozos por frame y ~1 frame
# por segundo se estaba pagando ese arranque 6 veces por segundo, y con el
# vigilante rapido (seat_watch) haciendo lotes de una sola capsula el arranque
# ERA todo el coste.
#
# Ahora los procesos viven entre lotes (ocr_worker --serve) y las APIs de
# tesseract se cargan una vez por sesion.
#
# Un worker que muere -o que devuelve basura- se reemplaza y el trozo se
# reintenta UNA vez. Reintentar mas seria arriesgarse a un bucle con un job que
# mata al worker siempre; a la segunda se propaga el fallo, que OcrBatch.run ya
# convierte en un frame perdido y no en una sesion caida.


class _Worker:
    def __init__(self):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", WORKER_MODULE, "--serve"], cwd=RAIZ,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)

    def vivo(self):
        return self.proc.poll() is None

    def resolver(self, jobs):
        self.proc.stdin.write(json.dumps({"jobs": jobs}) + "\n")
        self.proc.stdin.flush()
        linea = self.proc.stdout.readline()
        if not linea:
            raise RuntimeError("el worker de OCR se cerro")
        datos = json.loads(linea)
        if "error" in datos:
            raise RuntimeError(f"ocr_worker fallo: {datos['error']}")
        return datos["results"]

    def matar(self):
        try:
            self.proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass


class _Pool:
    """Workers persistentes, uno por hilo que los pida. El candado solo protege
    la lista de libres: el OCR en si corre fuera de el, que es lo que permite que
    los trozos vayan de verdad en paralelo."""

    def __init__(self):
        self._libres = []
        self._lock = threading.Lock()

    def _coger(self):
        with self._lock:
            while self._libres:
                w = self._libres.pop()
                if w.vivo():
                    return w
        return _Worker()

    def _soltar(self, w):
        with self._lock:
            if w.vivo() and len(self._libres) < MAX_PROCS:
                self._libres.append(w)
                return
        w.matar()

    def resolver(self, jobs):
        w = self._coger()
        try:
            r = w.resolver(jobs)
            self._soltar(w)
            return r
        except Exception:
            w.matar()
            # un reintento con un worker nuevo: el anterior pudo morir por
            # cualquier cosa (OOM, un PNG corrupto) y no vale la pena perder el
            # frame por eso
            w2 = _Worker()
            try:
                r = w2.resolver(jobs)
                self._soltar(w2)
                return r
            except Exception:
                w2.matar()
                raise

    def cerrar(self):
        with self._lock:
            libres, self._libres = self._libres, []
        for w in libres:
            w.matar()


_POOL = _Pool()
atexit.register(_POOL.cerrar)


def _backend_real(jobs):
    return _POOL.resolver(jobs)


# QUIEN resuelve de verdad un trozo del lote. En produccion es el pool de
# subprocesos; en un test se sustituye por una funcion que devuelve texto fijo,
# y entonces table_state.analyze_layout() se puede ejercitar sin tesseract, sin
# subprocesos y en milisegundos en vez de segundos. Es la unica dependencia
# externa del pipeline de vision, asi que es el unico sitio donde hace falta.
_BACKEND = _backend_real


def usar_backend(fn):
    """Sustituye el resolvedor de OCR y devuelve el anterior, para poder
    restaurarlo. `fn(jobs) -> lista de resultados alineada con jobs`."""
    global _BACKEND
    anterior, _BACKEND = _BACKEND, fn
    return anterior


def restaurar_backend():
    """Vuelve al pool de subprocesos real."""
    global _BACKEND
    _BACKEND = _backend_real


def cerrar_workers():
    """Cierra los workers persistentes. Para tests y para cerrar sesion limpia."""
    _POOL.cerrar()
