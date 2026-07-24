"""
Lanza la tanda completa de transcripcion (corpus prioritario) repartida en
N procesos pipeline.py en paralelo, para bajar el tiempo de reloj (cada
proceso de faster-whisper ya usa varios nucleos, pero no todos los
disponibles).

Uso: .venv/bin/python decision/rag/run_batch.py [--workers 4]
"""
import argparse
import os
import subprocess
import sys

import video_index as vi

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    videos = vi.list_priority_videos()
    chunks = [videos[i::args.workers] for i in range(args.workers)]

    procs = []
    for i, chunk in enumerate(chunks):
        if not chunk:
            continue
        cmd = [sys.executable, "pipeline.py", "--videos", *chunk]
        log_path = os.path.join(HERE, f"batch_worker_{i}.log")
        log = open(log_path, "w")
        print(f"worker {i}: {len(chunk)} videos -> {log_path}")
        procs.append((subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=HERE), log))

    for p, log in procs:
        p.wait()
        log.close()

    print("Tanda completa.")


if __name__ == "__main__":
    main()
