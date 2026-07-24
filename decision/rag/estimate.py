"""
Extrapola cuanto tardaria y ocuparia transcribir el corpus completo (o el
subconjunto prioritario) a partir de decision/rag/transcripts/_benchmark.json
(tiempos reales medidos por pipeline.py sobre el subconjunto de prueba).
Usa ffprobe para conocer la duracion real de los videos restantes, sin
tocarlos ni copiarlos.

Uso: .venv/bin/python decision/rag/estimate.py
"""
import json
import os
import subprocess

import video_index as vi

BENCHMARK_PATH = os.path.join(os.path.dirname(__file__), "transcripts", "_benchmark.json")


def ffprobe_duration(path):
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", path,
        ],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out) if out else 0.0


def load_rates():
    with open(BENCHMARK_PATH) as f:
        entries = json.load(f)
    total_audio_s = sum(e["audio_duration_s"] for e in entries)
    return {
        "n_videos": len(entries),
        "total_audio_s": total_audio_s,
        "s_per_audio_s": sum(e["extract_s"] + e["transcribe_s"] for e in entries) / total_audio_s,
        "json_bytes_per_audio_s": sum(e["json_bytes"] for e in entries) / total_audio_s,
        "wav_bytes_per_audio_s": sum(e["wav_bytes"] for e in entries) / total_audio_s,
    }


def fmt_hours(seconds):
    return f"{seconds / 3600:.1f}h"


def fmt_mb(nbytes):
    return f"{nbytes / 1e6:.1f}MB"


def report(label, videos, rates):
    duration_s = sum(ffprobe_duration(p) for p in videos)
    print(f"\n{label}: {len(videos)} videos, {fmt_hours(duration_s)} de contenido")
    print(f"  proceso (extraccion+transcripcion) estimado: {fmt_hours(duration_s * rates['s_per_audio_s'])}")
    print(f"  transcripts JSON estimado: {fmt_mb(duration_s * rates['json_bytes_per_audio_s'])}")
    print(f"  audio WAV intermedio estimado (no versionado): {fmt_mb(duration_s * rates['wav_bytes_per_audio_s'])}")


def main():
    rates = load_rates()
    print(
        f"Tasa medida sobre {rates['n_videos']} videos de prueba "
        f"({fmt_hours(rates['total_audio_s'])} de audio):"
    )
    print(
        f"  {rates['s_per_audio_s']:.3f}s de proceso por segundo de audio "
        f"(~{1 / rates['s_per_audio_s']:.1f}x tiempo real)"
    )
    print(f"  {rates['json_bytes_per_audio_s']:.1f} bytes/s de transcript JSON")
    print(f"  {rates['wav_bytes_per_audio_s']:.1f} bytes/s de audio WAV intermedio")

    report("Corpus prioritario (avanzado + intermedio)", vi.list_priority_videos(), rates)
    report("Corpus completo TORNEOS/", vi.list_videos_in(vi.TORNEOS_ROOT), rates)


if __name__ == "__main__":
    main()
