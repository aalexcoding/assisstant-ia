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
from importlib.metadata import PackageNotFoundError, version

import numpy as np

from decision.rag.clean import clean_text

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_DIR = os.path.join(HERE, "index")
EMB_PATH = os.path.join(INDEX_DIR, "embeddings.npy")
META_PATH = os.path.join(INDEX_DIR, "meta.jsonl")
MANIFEST_PATH = os.path.join(INDEX_DIR, "manifest.json")

_STATE = {"emb": None, "meta": None, "model": None, "model_name": None}


class IndexUnavailableError(RuntimeError):
    """No hay un indice local utilizable para consultar."""


class IndexIncompatibleError(RuntimeError):
    """El indice se construyo con una configuracion distinta a la actual."""


def _fastembed_version():
    try:
        return version("fastembed")
    except PackageNotFoundError as e:
        raise IndexUnavailableError("fastembed no esta instalado") from e


def _load_index():
    if _STATE["emb"] is not None:
        return
    if not os.path.exists(EMB_PATH):
        raise IndexUnavailableError(
            f"no hay indice en {INDEX_DIR}; ejecuta primero: "
            "python -m decision.rag.build_index")
    try:
        with open(MANIFEST_PATH) as fh:
            manifest = json.load(fh)
        model_name = manifest["model"]
        version_indice = manifest["fastembed_version"]
        if version_indice != _fastembed_version():
            raise IndexIncompatibleError(
                "el indice se construyo con fastembed " + version_indice +
                f" y el entorno usa {_fastembed_version()}; reconstruyelo")
        emb = np.load(EMB_PATH)
        with open(META_PATH) as fh:
            meta = [json.loads(line) for line in fh]
    except KeyError as e:
        raise IndexIncompatibleError(
            "el manifiesto del indice no registra su version de fastembed; reconstruyelo") from e
    except (OSError, ValueError, json.JSONDecodeError) as e:
        raise IndexUnavailableError(f"no se pudo abrir el indice: {e}") from e
    if emb.ndim != 2 or len(emb) != len(meta) or manifest.get("count") != len(meta):
        raise IndexIncompatibleError("los ficheros del indice no concuerdan; reconstruyelo")
    _STATE.update(emb=emb, meta=meta, model_name=model_name)


def reset_state():
    """Descarga el índice/modelo cacheados; útil tras reconstruir y en tests."""
    _STATE.update(emb=None, meta=None, model=None, model_name=None)


def index_status():
    """Estado legible del índice sin ocultar la causa de una avería."""
    try:
        _load_index()
    except (IndexUnavailableError, IndexIncompatibleError) as e:
        return {"available": False, "reason": str(e), "count": 0}
    return {
        "available": True,
        "reason": None,
        "count": len(_STATE["meta"] or []),
        "model": _STATE["model_name"],
    }


def _get_model():
    if _STATE["model"] is None:
        from fastembed import TextEmbedding
        _STATE["model"] = TextEmbedding(_STATE["model_name"])
    return _STATE["model"]


def embed_query(text):
    vec = np.array(next(_get_model().embed([text])), dtype=np.float32)
    n = np.linalg.norm(vec)
    return vec / n if n else vec


def search(texto_situacion, k=8, context=None):
    if isinstance(k, bool) or not isinstance(k, int) or k < 1:
        raise ValueError("k debe ser un entero positivo")
    _load_index()
    q = embed_query(clean_text(texto_situacion))
    sims = _STATE["emb"] @ q
    ranked = sims.copy()
    # Las etiquetas no sustituyen la similitud semántica: solo desempatan spots
    # parecidos favoreciendo el contexto observado. Se conserva ``score`` puro
    # para que el umbral siga teniendo un significado estable.
    boosts = {
        "position_relation": 0.04,
        "initiative": 0.04,
        "pot_type": 0.03,
    }
    for key, bonus in boosts.items():
        wanted = (context or {}).get(key)
        if not wanted:
            continue
        for i, meta in enumerate(_STATE["meta"]):
            actual = meta.get(key)
            same_raised_pot = (
                key == "pot_type"
                and actual == "3bet_4bet"
                and wanted in ("3bet", "4bet_plus")
            )
            if actual == wanted or actual == "IP_OOP" or same_raised_pot:
                ranked[i] += bonus
            elif actual:
                ranked[i] -= bonus
    k = min(k, len(sims))
    idx = np.argpartition(-ranked, k - 1)[:k]
    idx = idx[np.argsort(-ranked[idx])]
    out = []
    for i in idx:
        r = dict(_STATE["meta"][int(i)])
        r["score"] = float(sims[int(i)])
        r["relevance_score"] = float(ranked[int(i)])
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
    try:
        resultados = search(query, k=args.k)
    except (IndexUnavailableError, IndexIncompatibleError, ValueError) as e:
        raise SystemExit(str(e)) from e
    for rank, r in enumerate(resultados, 1):
        print(f"{rank}. {_fmt(r)}\n")
