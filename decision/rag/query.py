"""Interfaz de consulta sobre el indice de embeddings (Fase 4.3, solo retrieval).

search(texto_situacion, k=8) -> lista de chunks ordenados por similitud coseno,
cada uno con su video de origen, timestamp y texto (ya limpiado).

Uso por linea de comandos (para revisar la recuperacion a ojo):
    python decision/rag/query.py "flop seco J72 rainbow tengo iniciativa como agresor preflop"
    python decision/rag/query.py -k 5 "3bet pot fuera de posicion en el flop"
"""

import argparse
import json
import os
import sys

import numpy as np

from clean import clean_text

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_DIR = os.path.join(HERE, "index")
EMB_PATH = os.path.join(INDEX_DIR, "embeddings.npy")
META_PATH = os.path.join(INDEX_DIR, "meta.jsonl")
MANIFEST_PATH = os.path.join(INDEX_DIR, "manifest.json")

_STATE = {"emb": None, "meta": None, "model": None, "model_name": None}


def _load_index():
    if _STATE["emb"] is not None:
        return
    if not os.path.exists(EMB_PATH):
        sys.exit(f"no hay indice en {INDEX_DIR}; ejecuta primero: python {os.path.join(HERE, 'build_index.py')}")
    _STATE["emb"] = np.load(EMB_PATH)
    with open(META_PATH) as fh:
        _STATE["meta"] = [json.loads(line) for line in fh]
    with open(MANIFEST_PATH) as fh:
        _STATE["model_name"] = json.load(fh)["model"]


def _get_model():
    if _STATE["model"] is None:
        from fastembed import TextEmbedding
        _STATE["model"] = TextEmbedding(_STATE["model_name"])
    return _STATE["model"]


def embed_query(text):
    vec = np.array(next(_get_model().embed([text])), dtype=np.float32)
    n = np.linalg.norm(vec)
    return vec / n if n else vec


def search(texto_situacion, k=8):
    _load_index()
    q = embed_query(clean_text(texto_situacion))
    sims = _STATE["emb"] @ q
    k = min(k, len(sims))
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    out = []
    for i in idx:
        r = dict(_STATE["meta"][int(i)])
        r["score"] = float(sims[int(i)])
        out.append(r)
    return out


def _fmt(r, width=300):
    t = r["text"].strip().replace("\n", " ")
    if len(t) > width:
        t = t[:width].rsplit(" ", 1)[0] + " ..."
    return (f"[{r['score']:.3f}] {r['video']}\n"
            f"        t={r['start_time']:.0f}-{r['end_time']:.0f}s  (chunk {r['chunk_index']})\n"
            f"        {t}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="+", help="descripcion de la situacion postflop")
    ap.add_argument("-k", type=int, default=8, help="numero de resultados (def 8)")
    args = ap.parse_args()
    query = " ".join(args.query)
    print(f"consulta: {query!r}\n")
    for rank, r in enumerate(search(query, k=args.k), 1):
        print(f"{rank}. {_fmt(r)}\n")
