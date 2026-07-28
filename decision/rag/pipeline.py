"""
Orquesta el pipeline completo de la Fase 4.2 para una lista de videos:
extraer audio (extract_audio.py) -> transcribir (transcribe.py) -> trocear
(chunk.py) -> escribir <video_id>.json en decision/rag/transcripts/.

Ademas registra en decision/rag/transcripts/_benchmark.json el tiempo real
que ha costado cada video (extraccion + transcripcion) y el tamaño de los
ficheros generados, para poder extrapolar cuanto tardaria/ocuparia el
corpus completo (ver estimate.py).

Es idempotente: si ya existe el JSON final de un video, se salta (usar
--force para regenerar). Pensado para tandas pequeñas de validacion, NO
para lanzar los 126 videos prioritarios de una sentada (ver prompt.md).

Uso:
  .venv/bin/python decision/rag/pipeline.py --limit 8
  .venv/bin/python decision/rag/pipeline.py --videos "/ruta/a/uno.mp4" "/ruta/a/otro.mp4"
"""
import argparse
import json
import os
import time

from decision.rag import chunk as ch
from decision.rag import extract_audio as ea
from decision.rag import transcribe as tr
from decision.rag import video_index as vi

TRANSCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "transcripts")
BENCHMARK_PATH = os.path.join(TRANSCRIPTS_DIR, "_benchmark.json")


def process_video(video_path, model, out_dir=TRANSCRIPTS_DIR, force=False):
    vid = vi.video_id(video_path)
    out_path = os.path.join(out_dir, vid + ".json")
    if os.path.exists(out_path) and not force:
        return out_path, None

    t0 = time.monotonic()
    wav_path = ea.extract_audio(video_path)
    t1 = time.monotonic()
    segments, info = tr.transcribe(wav_path, model=model)
    t2 = time.monotonic()
    chunks = ch.chunk_segments(segments)

    os.makedirs(out_dir, exist_ok=True)
    result = [
        {
            "video": vid,
            "video_path": video_path,
            "chunk_index": i,
            "start_time": c["start_time"],
            "end_time": c["end_time"],
            "text": c["text"],
        }
        for i, c in enumerate(chunks)
    ]
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    stats = {
        "video": vid,
        "video_path": video_path,
        "audio_duration_s": segments[-1]["end"] if segments else 0.0,
        "extract_s": round(t1 - t0, 2),
        "transcribe_s": round(t2 - t1, 2),
        "n_segments": len(segments),
        "n_chunks": len(chunks),
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "wav_bytes": os.path.getsize(wav_path),
        "json_bytes": os.path.getsize(out_path),
    }
    return out_path, stats


def _load_benchmark():
    if os.path.exists(BENCHMARK_PATH):
        with open(BENCHMARK_PATH) as f:
            return json.load(f)
    return []


def _save_benchmark(entries):
    os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
    with open(BENCHMARK_PATH, "w") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="numero de videos prioritarios a procesar")
    parser.add_argument("--videos", nargs="+", default=None, help="rutas explicitas de video (ignora --limit)")
    parser.add_argument("--force", action="store_true", help="re-procesa aunque ya exista el JSON de salida")
    args = parser.parse_args()

    if args.videos:
        videos = args.videos
    else:
        videos = vi.list_priority_videos()
        if args.limit:
            videos = videos[: args.limit]

    print(f"Cargando modelo Whisper ({tr.MODEL_SIZE})...")
    model = tr.get_model()

    benchmark = _load_benchmark()
    seen = {e["video"] for e in benchmark}

    for n, video_path in enumerate(videos, 1):
        vid = vi.video_id(video_path)
        print(f"[{n}/{len(videos)}] {os.path.relpath(video_path, vi.TORNEOS_ROOT)}")
        out_path, stats = process_video(video_path, model, force=args.force)
        if stats is None:
            print("  (ya existe, se salta)")
            continue
        print(
            f"  audio={stats['audio_duration_s']:.1f}s "
            f"extract={stats['extract_s']:.1f}s transcribe={stats['transcribe_s']:.1f}s "
            f"chunks={stats['n_chunks']} -> {out_path}"
        )
        if vid in seen:
            benchmark = [e for e in benchmark if e["video"] != vid]
        benchmark.append(stats)
        seen.add(vid)
        _save_benchmark(benchmark)

    print(f"\n{len(benchmark)} videos con estadisticas en {BENCHMARK_PATH}")


if __name__ == "__main__":
    main()
