"""
Extrae la pista de audio de un video a WAV mono 16kHz (formato de entrada
que espera Whisper) via ffmpeg. No se toca el video original.

Uso: .venv/bin/python decision/rag/extract_audio.py <video> [--out-dir DIR]
"""
import argparse
import os
import subprocess

import video_index as vi

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "audio")
SAMPLE_RATE = 16000


def extract_audio(video_path, out_dir=AUDIO_DIR):
    os.makedirs(out_dir, exist_ok=True)
    wav_path = os.path.join(out_dir, vi.video_id(video_path) + ".wav")
    if os.path.exists(wav_path):
        return wav_path
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-loglevel", "error", wav_path,
        ],
        check=True,
    )
    return wav_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--out-dir", default=AUDIO_DIR)
    args = parser.parse_args()
    print(extract_audio(args.video, args.out_dir))


if __name__ == "__main__":
    main()
