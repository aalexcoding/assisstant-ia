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

WORKER_PATH = os.path.join(os.path.dirname(__file__), "ocr_worker.py")


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

    def run(self):
        """Resuelve todos los jobs en una invocacion del subproceso y devuelve
        una lista alineada con el orden de encolado (los jobs vacios -recorte de
        tamaño 0- devuelven "").

        El directorio temporal se borra en un finally: si el worker falla o se
        pasa del timeout, el tmpdir se limpia igual. Sin el finally cada fallo
        de OCR dejaba un /tmp/vision_ocr_* huerfano con sus PNGs dentro, y en un
        lazo de analisis en vivo eso se acumula durante toda la sesion."""
        try:
            real_jobs = [j for j in self._jobs if j is not None]
            # sin ningun job real no hace falta arrancar el subproceso (inicializar
            # tesseract cuesta mas que el propio OCR de un recorte pequeño)
            if not real_jobs:
                return ["" for _ in self._jobs]

            payload = json.dumps({"jobs": real_jobs})
            proc = subprocess.run([sys.executable, WORKER_PATH], input=payload,
                                   capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                raise RuntimeError(f"ocr_worker fallo: {proc.stderr}")
            real_results = json.loads(proc.stdout)["results"]
            results = []
            real_iter = iter(real_results)
            for j in self._jobs:
                results.append(next(real_iter) if j is not None else "")
            return results
        finally:
            shutil.rmtree(self._tmpdir, ignore_errors=True)
