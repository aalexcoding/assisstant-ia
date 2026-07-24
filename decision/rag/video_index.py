"""
Localiza y ordena los videos del curso ZEROS POKER que alimentan el RAG
postflop (Fase 4.2-3), priorizando las dos carpetas de estrategia postflop
segun prompt.md: primero el curso absoluto avanzado (101 videos), luego la
teoria intermedia (23 videos). El resto de TORNEOS/ (iniciacion, escalando
niveles, productividad, software) queda fuera por ahora.

Fuente: solo lectura, no se modifica nada en /mnt/qnap/Poker/.
"""
import os
import re
import unicodedata

TORNEOS_ROOT = "/mnt/qnap/Poker/VIDEOS ZEROS POKER/TORNEOS"

PRIORITY_DIRS = [
    "6. EL CURSO ABSOLUTO DE JUEGO POSTFLOP (Avanzado)",
    "5. CONTENIDO DE TEORÍA POSTFLOP (Intermedio)",
]

VIDEO_EXTS = (".mp4", ".mkv", ".flv")


def _sort_key(name):
    m = re.match(r"(\d+)", name)
    return (int(m.group(1)) if m else 10**9, name)


def list_videos_in(dir_path):
    videos = []
    for root, dirs, files in os.walk(dir_path):
        dirs.sort(key=_sort_key)
        for fname in sorted(files, key=_sort_key):
            if fname.lower().endswith(VIDEO_EXTS):
                videos.append(os.path.join(root, fname))
    return videos


def list_priority_videos():
    videos = []
    for d in PRIORITY_DIRS:
        videos.extend(list_videos_in(os.path.join(TORNEOS_ROOT, d)))
    return videos


def video_id(video_path):
    """Identificador estable y legible para un video: su ruta relativa a
    TORNEOS_ROOT, normalizada a ascii/snake_case. Se usa como nombre de
    fichero para el audio/transcript intermedios, y como valor del campo
    "video" en los chunks (permite volver al video original sin ambiguedad)."""
    rel = os.path.relpath(video_path, TORNEOS_ROOT)
    rel = os.path.splitext(rel)[0]
    ascii_rel = unicodedata.normalize("NFKD", rel).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "_", ascii_rel).strip("_").lower()


def main():
    videos = list_priority_videos()
    print(f"{len(videos)} videos en las carpetas prioritarias:")
    for v in videos:
        print(f"  {os.path.relpath(v, TORNEOS_ROOT)}")


if __name__ == "__main__":
    main()
