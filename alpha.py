"""
Bucle de diagnostico en vivo: captura la mesa cada pocos segundos, corre el
reconocimiento de Fase 3 (mazo de 4 colores, el real de produccion) y
muestra el GameState por consola para validar en directo mientras juegas.

No es el HUD final (Fase 5, panel bajo la ventana) ni dispara por cambio de
board (Fase 2, deteccion de cambios) - es un lazo de polling simple para
validar la Fase 3 contra partidas reales y que digas si acierta o no.

Uso: .venv/bin/python alpha.py [--interval SEGUNDOS]
Para: Ctrl+C.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "capture"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vision"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "decision"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "decision", "preflop"))

import cv2

import engine
import portal_capture as pc
import table_state as ts

CALIBRATION_PATH = os.path.join(os.path.dirname(__file__), "calibration", "config.local.json")
TMP_FRAME_PATH = "/tmp/poker_alpha_frame.png"


def load_region():
    with open(CALIBRATION_PATH) as f:
        region = json.load(f)["capture_region"]
    return region["x"], region["y"], region["width"], region["height"]


def format_state(state, recommendation):
    lines = []
    hero = " ".join(state["hero_cards"]) or "?"
    board = " ".join(state["board"]) or "(preflop)"
    pot = state["pot"] if state["pot"] is not None else "?"
    lines.append(f"Hero: {hero}   Board: {board}   Pot: {pot}")
    if state["blinds"]:
        b = state["blinds"]
        lines.append(f"Ciegas: {b.get('sb')}/{b.get('bb')} ante {b.get('ante')}")
    for p in state["players"]:
        marker = "  <- tu" if p["is_hero"] else ""
        lines.append(f"  {p['name']}: {p['stack']}{marker}")
    if recommendation:
        lines.append(f"Recomendacion: {recommendation['action']}")
    if state["warnings"]:
        lines.append("Avisos: " + "; ".join(state["warnings"]))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=float, default=3.0, help="segundos entre analisis")
    args = parser.parse_args()

    x, y, w, h = load_region()
    portal, session_handle, fd, stream, _props = pc.open_frame_stream()
    print(f"Analizando cada {args.interval}s (Ctrl+C para parar)...\n")
    last_printed = None
    try:
        while True:
            frame = stream.read(timeout_s=5.0)
            if frame is not None:
                crop = frame[y:y + h, x:x + w]
                cv2.imwrite(TMP_FRAME_PATH, crop)
                state = ts.analyze_color_deck(TMP_FRAME_PATH)
                recommendation = engine.decide(state)
                text = format_state(state, recommendation)
                if text != last_printed:
                    print(f"--- {time.strftime('%H:%M:%S')} ---")
                    print(text)
                    print()
                    last_printed = text
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        stream.close()
        os.close(fd)
        portal.close_session(session_handle)


if __name__ == "__main__":
    main()
