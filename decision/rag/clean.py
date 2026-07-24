"""Limpieza de jerga de las transcripciones antes de indexar.

Las transcripciones (Whisper sobre audio en español del curso Zeros Poker)
arrastran errores sistematicos de ASR en la jerga de poker. Este modulo aplica
un glosario de sustituciones (regex) al texto de cada chunk para que la
recuperacion por termino funcione ("3bet pot", "board seco"...).

No pretende ser exhaustivo: cubre los casos claros y frecuentes observados en
el corpus. Es ampliable: basta anadir tuplas a GLOSSARY (se aplican EN ORDEN,
asi que las reglas de frase van antes que las de palabra suelta).

Glosario aplicado (motivo entre parentesis):

  3bet / 4bet (la jerga "three-bet"/"four-bet pots" se degrada de varias formas)
    "Thrived Pods" / "Thrive Pods"      -> "3bet pots"
    "tribut pots"                       -> "3bet pots"
    "Forbid Pods"                       -> "4bet pots"
    "forbet pots"                       -> "4bet pots"
    "tribet" / "tri bet" / "three bet"  -> "3bet"
    "forbet" / "for bet" / "four bet"   -> "4bet"
    "3 bet" / "4 bet"  (con espacio)    -> "3bet" / "4bet"

  pots (el ingles "pots" cae como "pods": "multiway pods", "3 way pods"...)
    "pods"                              -> "pots"

  board (se transcribe como "boars"/"boar": "board seco", "boards conectados")
    "boars"                             -> "boards"
    "boar"                              -> "board"

  overbet (unificar la variante con espacio)
    "over bet"                          -> "overbet"

  check-raise (unificar variantes de separacion)
    "check raise" / "checkraise"        -> "check-raise"

  marca Zeros Poker (aparece de varias formas; NO se toca el handle suelto
  "ceros" porque colisiona con la palabra espanola y suele ser ruido de intro)
    "zeros poker"/"zero poker"/"ceros poker"/"cerospoker"... -> "ZerosPoker"
"""

import re

_RULES = [
    # --- reglas de frase 3bet/4bet (antes que pods->pots y que las de palabra) ---
    (r"thriv\w*\s+pods?", "3bet pots"),
    (r"forbid\s+pods?", "4bet pots"),
    (r"tribut\s+pots?", "3bet pots"),
    (r"forbet\s+pots?", "4bet pots"),
    # --- 3bet/4bet palabra suelta ---
    (r"\btribet\b", "3bet"),
    (r"\btri\s+bet\b", "3bet"),
    (r"\bthree\s?bet\b", "3bet"),
    (r"\bforbet\b", "4bet"),
    (r"\bfor\s+bet\b", "4bet"),
    (r"\bfour\s?bet\b", "4bet"),
    (r"\b3\s+bet\b", "3bet"),
    (r"\b4\s+bet\b", "4bet"),
    # --- pots (resto de "pods") ---
    (r"\bpods\b", "pots"),
    # --- board ---
    (r"\bboars\b", "boards"),
    (r"\bboar\b", "board"),
    # --- unificaciones ---
    (r"\bover\s+bet\b", "overbet"),
    (r"\bcheck\s*raise\b", "check-raise"),
    # --- marca ---
    (r"\b(?:zeros?|ceros?)\s*poker\b", "ZerosPoker"),
]

GLOSSARY = [(re.compile(p, re.IGNORECASE), r) for p, r in _RULES]


def clean_text(text):
    if not text:
        return text
    for rx, repl in GLOSSARY:
        text = rx.sub(repl, text)
    return text


def _report():
    import glob
    import json
    import os

    here = os.path.dirname(os.path.abspath(__file__))
    tdir = os.path.join(here, "transcripts")
    files = [f for f in sorted(glob.glob(os.path.join(tdir, "*.json")))
             if os.path.basename(f) != "_benchmark.json"]
    total = 0
    fired = {r.pattern: 0 for r, _ in GLOSSARY}
    for f in files:
        with open(f) as fh:
            data = json.load(fh)
        for ch in data:
            total += 1
            t = ch["text"]
            for rx, _ in GLOSSARY:
                n = len(rx.findall(t))
                if n:
                    fired[rx.pattern] += n
    print(f"chunks escaneados: {total}")
    print("sustituciones por regla:")
    for pat, n in sorted(fired.items(), key=lambda x: -x[1]):
        print(f"  {n:5d}  {pat}")


if __name__ == "__main__":
    _report()
