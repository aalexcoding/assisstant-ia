"""Metadatos verificables del corpus postflop.

No interpreta la estrategia de la transcripción. Solo extrae etiquetas que ya
están escritas en la ruta del vídeo: nivel, tipo de bote, iniciativa y si el
curso está planteado IP/OOP. Estas etiquetas permiten que el buscador no trate
como equivalentes dos fragmentos semánticamente parecidos pero pertenecientes a
spots opuestos.
"""

import os
import re
import unicodedata


# Son vídeos informativos sobre contenido futuro, no lecciones de estrategia.
# Se excluyen del índice para que una consulta de 3bet pot o juego con iniciativa
# no recupere un anuncio con gran similitud solo porque repite esas palabras.
NON_STRATEGY_MARKERS = (
    "cuando_estara_disponible_el_contenido_de_este_curso_en_3bet_pots_y_4bet",
    "como_aprender_juego_con_iniciativa_actualmente_en_zerospoker_com",
)


def _normalizar(texto):
    ascii_text = unicodedata.normalize("NFKD", str(texto)).encode(
        "ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")


def metadata(video, video_path=None):
    """Etiquetas derivadas únicamente del identificador/ruta del vídeo."""
    raw = _normalizar(video_path or video or "")
    vid = _normalizar(video or os.path.splitext(os.path.basename(video_path or ""))[0])
    is_strategy = not any(marker in raw or marker in vid
                          for marker in NON_STRATEGY_MARKERS)

    if "intermedio" in raw:
        level = "intermedio"
    elif "avanzado" in raw:
        level = "avanzado"
    else:
        level = None

    if "3bet_pots_y_4bet_pots" in raw:
        pot_type = "3bet_4bet"
    elif "botes_raiseados" in raw or "defensa_de_ciegas" in raw or "calls_con_posicion" in raw:
        pot_type = "single_raised"
    else:
        pot_type = None

    if "juego_sin_iniciativa" in raw:
        initiative = "sin_iniciativa"
    elif "juego_con_iniciativa" in raw:
        initiative = "con_iniciativa"
    else:
        initiative = None

    has_ip = bool(re.search(r"(?:^|_)ip(?:_|$)", raw))
    has_oop = bool(re.search(r"(?:^|_)oop(?:_|$)", raw))
    relation = ("IP_OOP" if has_ip and has_oop else
                "IP" if has_ip else
                "OOP" if has_oop else None)

    title = os.path.splitext(os.path.basename(video_path or ""))[0]
    if not title:
        title = str(video or "").replace("_", " ")

    return {
        "title": title,
        "level": level,
        "pot_type": pot_type,
        "initiative": initiative,
        "position_relation": relation,
        "is_strategy": is_strategy,
    }


def embedding_prefix(meta):
    """Texto corto que hace visibles las etiquetas al modelo semántico."""
    labels = [
        meta.get("title"),
        {"IP": "juego con posición IP",
         "OOP": "juego fuera de posición OOP",
         "IP_OOP": "juego IP y OOP"}.get(meta.get("position_relation")),
        {"con_iniciativa": "con iniciativa agresor preflop",
         "sin_iniciativa": "sin iniciativa defensor preflop"}.get(meta.get("initiative")),
        {"single_raised": "bote subido simple single raised pot",
         "3bet_4bet": "bote 3bet o 4bet"}.get(meta.get("pot_type")),
    ]
    return ". ".join(str(x) for x in labels if x)
