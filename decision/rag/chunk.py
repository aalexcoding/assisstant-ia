"""
Agrupa los segmentos brutos de Whisper (frases de ~5-15s) en chunks de
varias frases, del tamaño adecuado para recuperacion semantica (Fase 4.3):
ni una frase suelta (poco contexto) ni el video entero (demasiado para un
embedding). Un chunk nuevo empieza cuando el chunk actual ya supera
TARGET_S de duracion, o cuando hay un hueco de silencio mayor que
MAX_GAP_S (indicio de pausa/cambio de tema entre frases de Whisper).

Uso: .venv/bin/python decision/rag/chunk.py <segments.json>
"""
import argparse
import json
import sys

TARGET_S = 60.0
MAX_GAP_S = 2.0


def chunk_segments(segments, target_s=TARGET_S, max_gap_s=MAX_GAP_S):
    chunks = []
    current = []
    for seg in segments:
        if current and (seg["start"] - current[-1]["end"] > max_gap_s or seg["end"] - current[0]["start"] > target_s):
            chunks.append(_merge(current))
            current = []
        current.append(seg)
    if current:
        chunks.append(_merge(current))
    return chunks


def _merge(segs):
    return {
        "start_time": segs[0]["start"],
        "end_time": segs[-1]["end"],
        "text": " ".join(s["text"].strip() for s in segs if s["text"].strip()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("segments_json")
    args = parser.parse_args()
    with open(args.segments_json) as f:
        segments = json.load(f)
    chunks = chunk_segments(segments)
    json.dump(chunks, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
