"""
Punto de entrada del proceso principal (opencv) hacia el subproceso aislado
de OCR (ocr_worker.py, PIL+tesserocr). El preprocesado que mejora el OCR
(CLAHE, reescalado) se hace aqui con opencv y se vuelca a PNG temporal; el
subproceso solo abre esos PNG, nunca toca opencv.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import cv2
from concurrent.futures import ThreadPoolExecutor

WORKER_PATH = os.path.join(os.path.dirname(__file__), "ocr_worker.py")

# Procesos de OCR en paralelo. Se deja la mayor parte de la maquina libre a
# proposito: ver el docstring de OcrBatch.run. ThreadPoolExecutor y no
# ProcessPool porque cada hilo solo espera en subprocess.run, que suelta el GIL.
MAX_PROCS = max(1, min(6, (os.cpu_count() or 2) - 2))


def _clahe_enhance(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


class OcrBatch:
    """Acumula jobs de OCR (paths de imagenes ya preprocesadas por el
    llamador) y los resuelve en una unica invocacion del subproceso."""

    def __init__(self):
        self._tmpdir = tempfile.mkdtemp(prefix="vision_ocr_")
        self._jobs = []
        self._counter = 0

    def _new_path(self, suffix=".png"):
        self._counter += 1
        return os.path.join(self._tmpdir, f"{self._counter}{suffix}")

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
        path = self._new_path()
        cv2.imwrite(path, enhanced)
        idx = len(self._jobs)
        job = {"mode": "tsv", "path": path, "scale": scale}
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
        path = self._new_path()
        cv2.imwrite(path, gray)
        idx = len(self._jobs)
        self._jobs.append({"mode": "text", "path": path, "whitelist": whitelist, "psm": psm})
        return idx

    def _run_chunk(self, jobs):
        """Resuelve un trozo del lote en un subproceso. Devuelve sus resultados
        en el mismo orden en que se le pasaron."""
        proc = subprocess.run([sys.executable, WORKER_PATH],
                              input=json.dumps({"jobs": jobs}),
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise RuntimeError(f"ocr_worker fallo: {proc.stderr}")
        return json.loads(proc.stdout)["results"]

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

        El directorio temporal se borra en un finally: si un worker falla o se
        pasa del timeout, el tmpdir se limpia igual. Sin el finally cada fallo
        dejaba un /tmp/vision_ocr_* huerfano, y en un lazo en vivo se acumulan."""
        try:
            real = [(i, j) for i, j in enumerate(self._jobs) if j is not None]
            # sin ningun job real no hace falta arrancar el subproceso (inicializar
            # tesseract cuesta mas que el propio OCR de un recorte pequeño)
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
        finally:
            shutil.rmtree(self._tmpdir, ignore_errors=True)

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
