"""
Graba capturas reales de la mesa mientras se juega, recortadas al recuadro
calibrado en calibration/config.local.json, para tener con que construir el
reconocimiento de la Fase 3 (vision/).

Uso: .venv/bin/python capture/record_samples.py [--interval SEGUNDOS]
Para: Ctrl+C.
"""
import argparse
import json
import os
import time

import cv2
import numpy as np

import portal_capture as pc

CALIBRATION_PATH = os.path.join(os.path.dirname(__file__), "..", "calibration", "config.local.json")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "vision", "samples")

FELT_HUE_RANGE = (50, 95)
FELT_MIN_SATURATION = 60
FELT_MIN_FRACTION = 0.08


def looks_like_table(crop):
    """Heuristica barata para descartar frames que no muestran el tapete
    (camara del streamer, cortes ajenos al poker insertados en el video,
    etc.): el tapete verde/turquesa deberia ocupar buena parte del centro
    de la imagen. Umbral calibrado contra muestras reales: mesa ~0.31-0.32,
    camara/cortes ajenos ~0.000-0.001."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, w = crop.shape[:2]
    region = hsv[int(h * 0.15):int(h * 0.85), int(w * 0.1):int(w * 0.9)]
    mask = (region[:, :, 0] >= FELT_HUE_RANGE[0]) & (region[:, :, 0] <= FELT_HUE_RANGE[1]) \
        & (region[:, :, 1] >= FELT_MIN_SATURATION)
    return mask.mean() >= FELT_MIN_FRACTION


def load_region():
    with open(CALIBRATION_PATH) as f:
        region = json.load(f)["capture_region"]
    return region["x"], region["y"], region["width"], region["height"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=3.0, help="segundos entre capturas")
    parser.add_argument("--duration", type=float, default=None, help="segundos totales (por defecto, indefinido hasta Ctrl+C)")
    args = parser.parse_args()

    x, y, w, h = load_region()
    os.makedirs(OUT_DIR, exist_ok=True)

    portal, session_handle, fd, stream, _props = pc.open_frame_stream()
    print(f"Grabando cada {args.interval}s en {OUT_DIR} (Ctrl+C para parar)...")
    n = 0
    start = time.monotonic()
    try:
        while args.duration is None or time.monotonic() - start < args.duration:
            frame = stream.read(timeout_s=5.0)
            if frame is not None:
                crop = frame[y:y + h, x:x + w]
                if looks_like_table(crop):
                    path = os.path.join(OUT_DIR, f"sample_{int(time.time() * 1000)}.png")
                    cv2.imwrite(path, crop)
                    n += 1
                    print(f"[{n}] {os.path.basename(path)}")
                else:
                    print("(descartado, no parece la mesa)")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        print(f"\nParado. {n} capturas guardadas en {OUT_DIR}")
        stream.close()
        os.close(fd)
        portal.close_session(session_handle)


if __name__ == "__main__":
    main()
