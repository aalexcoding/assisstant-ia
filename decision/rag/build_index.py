"""Construye el indice de embeddings de los chunks de transcripcion.

Modelo: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
        (multilingue, dim 384, ~0.22GB) servido via fastembed/onnxruntime.
        Se elige por ser multilingue (contenido en espanol), pequeno y
        CPU-friendly (ONNX, sin torch): en esta maquina no hay GPU y la RAM
        esta ajustada, asi que fastembed+onnxruntime es mas ligero que
        sentence-transformers+torch. onnxruntime ya esta en el sistema.

Indice: matriz numpy de embeddings L2-normalizados (coseno = producto escalar).
        Para ~5000 chunks numpy sobra; no hace falta FAISS.

Salida en decision/rag/index/:
  embeddings.npy  float32 [N, 384] normalizado
  meta.jsonl      una linea JSON por chunk (video, video_path, chunk_index,
                  start_time, end_time, text ya limpiado)
  manifest.json   modelo, dim, N, fingerprint del corpus, timestamp

Idempotente: si el fingerprint (modelo + textos limpios) coincide con el del
manifest existente, no reconstruye salvo --force.
"""

import argparse
import glob
import hashlib
import json
import os
import time

import numpy as np

from decision.rag.clean import clean_text

HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS_DIR = os.path.join(HERE, "transcripts")
INDEX_DIR = os.path.join(HERE, "index")
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

EMB_PATH = os.path.join(INDEX_DIR, "embeddings.npy")
META_PATH = os.path.join(INDEX_DIR, "meta.jsonl")
MANIFEST_PATH = os.path.join(INDEX_DIR, "manifest.json")


def load_chunks():
    files = [f for f in sorted(glob.glob(os.path.join(TRANSCRIPTS_DIR, "*.json")))
             if os.path.basename(f) != "_benchmark.json"]
    records = []
    empty = 0
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        if not data:
            empty += 1
            continue
        for ch in data:
            text = clean_text(ch["text"]).strip()
            if not text:
                continue
            records.append({
                "video": ch["video"],
                "video_path": ch["video_path"],
                "chunk_index": ch["chunk_index"],
                "start_time": ch["start_time"],
                "end_time": ch["end_time"],
                "text": text,
            })
    return records, len(files), empty


def fingerprint(records):
    h = hashlib.sha256()
    h.update(MODEL_NAME.encode())
    for r in records:
        h.update(r["video"].encode())
        h.update(str(r["chunk_index"]).encode())
        h.update(r["text"].encode())
    return h.hexdigest()


def already_built(fp):
    if not (os.path.exists(EMB_PATH) and os.path.exists(META_PATH)
            and os.path.exists(MANIFEST_PATH)):
        return False
    try:
        with open(MANIFEST_PATH) as fh:
            man = json.load(fh)
        return man.get("fingerprint") == fp
    except Exception:
        return False


def build(force=False):
    records, n_files, n_empty = load_chunks()
    print(f"transcripciones: {n_files} ficheros, {n_empty} vacios descartados")
    print(f"chunks a indexar (tras limpiar): {len(records)}")

    fp = fingerprint(records)
    if not force and already_built(fp):
        print("indice ya al dia (fingerprint coincide); nada que hacer. Usa --force para reconstruir.")
        return

    from fastembed import TextEmbedding
    print(f"cargando modelo {MODEL_NAME} ...")
    t0 = time.time()
    model = TextEmbedding(MODEL_NAME)
    print(f"modelo listo en {time.time() - t0:.1f}s")

    texts = [r["text"] for r in records]
    embs = np.empty((len(texts), 384), dtype=np.float32)
    t0 = time.time()
    for i, vec in enumerate(model.embed(texts, batch_size=64)):
        embs[i] = vec
        if (i + 1) % 500 == 0 or i + 1 == len(texts):
            dt = time.time() - t0
            rate = (i + 1) / dt
            eta = (len(texts) - (i + 1)) / rate if rate else 0
            print(f"  embebidos {i + 1}/{len(texts)}  ({rate:.0f}/s, ETA {eta:.0f}s)")

    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    embs /= norms

    os.makedirs(INDEX_DIR, exist_ok=True)
    np.save(EMB_PATH, embs)
    with open(META_PATH, "w") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(MANIFEST_PATH, "w") as fh:
        json.dump({
            "model": MODEL_NAME,
            "dim": 384,
            "count": len(records),
            "fingerprint": fp,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, fh, ensure_ascii=False, indent=2)
    print(f"indice escrito en {INDEX_DIR} ({len(records)} vectores, {time.time() - t0:.0f}s total embed)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="reconstruir aunque el fingerprint coincida")
    args = ap.parse_args()
    build(force=args.force)
