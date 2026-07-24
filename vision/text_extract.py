"""
Extraccion de texto (pot, ciegas, nombres+stacks de jugadores) a partir de
las lineas OCR de todo el frame. No usa coordenadas fijas: agrupa palabras en
lineas (segun la propia segmentacion de tesseract) y luego busca patrones
(regex) y proximidad espacial entre una linea "nombre" y una linea "numero"
para emparejar cada jugador con su stack, sea cual sea su posicion en la mesa.
"""
import re

NAME_BLACKLIST = {
    "pot", "fold", "call", "raise", "check", "time", "bank", "chat", "hands",
    "notes", "stats", "info", "sit", "out", "next", "hand", "blinds", "ante",
    "bounty", "adrenaline", "play", "responsibly", "winning", "tournament",
    "stream", "fastest", "poker", "mids", "cur", "balance", "account", "all",
    "in", "remaining", "bounties", "earned", "places", "paid", "my",
    "position", "pokerstars", "sthsi71", "make", "deal", "sub", "subscribe",
    "los", "the", "de", "tu", "busqueda", "this", "on", "knockout", "final",
    "table", "kos", "sit out", "any", "bet", "to", "won",
}

RANK_WORDS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_\-\.]{2,19}$")
# el cliente en ingles agrupa miles con "," (12,500); el cliente en
# castellano (vision/samples_pokerstars/) con "." (12.500). Aceptar ambos
# formatos, nunca mezclados dentro del mismo numero.
NUMBER_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$|^\d{1,3}(?:\.\d{3})+$|^\d{3,6}$")
_NUM = r"[\d][\d,\.]*"
POT_RE = re.compile(rf"(?:pot|bote)[:\.]?\s*\$?({_NUM})", re.IGNORECASE)
BLINDS_LABELED_RE = re.compile(
    rf"blinds?\s+\$?({_NUM})\s*/\s*\$?({_NUM})(?:\s*ante\s+\$?({_NUM}))?", re.IGNORECASE)
BLINDS_COMPACT_RE = re.compile(rf"\$?({_NUM})\s*/\s*\$?({_NUM})\s*\(\s*({_NUM})\s*\)")
BLINDS_ANTE_WORD_RE = re.compile(
    rf"^\$?({_NUM})\s*/\s*\$?({_NUM})\s*ante\s+\$?({_NUM})$", re.IGNORECASE)
# la barra de titulo del cliente en castellano ("15.000/30.000 ante 3.750")
# a veces pierde el valor de la ante en el OCR (fuente muy fina): se acepta
# igual sb/bb con la ante a None antes que descartar la linea entera. La
# palabra "ante" (sin valor detras) sigue exigiendose para no confundir con
# otros pares "x/y" del HUD que no son ciegas (posicion en el torneo, etc).
BLINDS_ANTE_NO_VALUE_RE = re.compile(rf"^\$?({_NUM})\s*/\s*\$?({_NUM})\s*ante\b", re.IGNORECASE)

# indicador compacto de ciegas/ante junto al reloj de mano, en la esquina
# superior derecha ("17,5K/35K(4,5K)", "12.500/25.000 ante 3.250" tambien
# aparece asi a veces, pero el formato propio de esta zona usa notacion K/M
# con coma decimal: "12,5K"=12500, "1,2M"=1200000). Verificado contra las 93
# capturas de vision/samples_pokerstars/: mucho mas legible que la barra de
# titulo (fuente mas grande, fondo solido) y por tanto con mejor cobertura.
_CORNER_NUM = r"\d+(?:[.,]\s?\d+)?[KM]?"
BLINDS_CORNER_RE = re.compile(rf"({_CORNER_NUM})\s*/\s*({_CORNER_NUM})\s*\(\s*({_CORNER_NUM})\s*\)")


def _to_int_corner(s):
    s = s.strip().replace(" ", "")
    mult = 1
    if s and s[-1] in "KkMm":
        mult = 1000 if s[-1] in "Kk" else 1_000_000
        s = s[:-1]
    try:
        return int(round(float(s.replace(",", ".")) * mult))
    except ValueError:
        return None


def _to_int(s):
    return int(re.sub(r"[,\.]", "", s))


def parse_tsv_lines(tsv_text):
    lines = {}
    for row in tsv_text.splitlines():
        parts = row.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        block, par, line_no = parts[2], parts[3], parts[4]
        left, top, w, h = int(parts[6]), int(parts[7]), int(parts[8]), int(parts[9])
        conf = float(parts[10])
        text = parts[11]
        if conf < 25 or not text.strip():
            continue
        key = (block, par, line_no)
        entry = lines.setdefault(key, {"words": [], "left": left, "top": top,
                                        "right": left + w, "bottom": top + h})
        entry["words"].append(text)
        entry["left"] = min(entry["left"], left)
        entry["top"] = min(entry["top"], top)
        entry["right"] = max(entry["right"], left + w)
        entry["bottom"] = max(entry["bottom"], top + h)

    result = []
    for entry in lines.values():
        text = " ".join(entry["words"])
        result.append({
            "text": text,
            "left": entry["left"], "top": entry["top"],
            "right": entry["right"], "bottom": entry["bottom"],
            "cx": (entry["left"] + entry["right"]) / 2,
            "cy": (entry["top"] + entry["bottom"]) / 2,
        })
    return result


def merge_line_sets(*line_sets, dedup_dist=15):
    merged = []
    for lines in line_sets:
        for ln in lines:
            dup = False
            for existing in merged:
                if abs(existing["cx"] - ln["cx"]) < dedup_dist and abs(existing["cy"] - ln["cy"]) < dedup_dist:
                    dup = True
                    break
            if not dup:
                merged.append(ln)
    return merged


def _row_texts(lines, y_tol=12):
    rows = []
    used = [False] * len(lines)
    order = sorted(range(len(lines)), key=lambda i: lines[i]["cy"])
    for i in order:
        if used[i]:
            continue
        group = [lines[i]]
        used[i] = True
        for j in order:
            if used[j]:
                continue
            if abs(lines[j]["cy"] - lines[i]["cy"]) < y_tol:
                group.append(lines[j])
                used[j] = True
        group.sort(key=lambda ln: ln["cx"])
        rows.append(" ".join(ln["text"] for ln in group))
    return rows


MIN_PLAUSIBLE_POT = 100
MIN_PLAUSIBLE_BB = 20


def find_pot(lines):
    candidates = []
    for ln in lines:
        m = POT_RE.search(ln["text"])
        if m:
            candidates.append(_to_int(m.group(1)))
    for row in _row_texts(lines):
        m = POT_RE.search(row)
        if m:
            candidates.append(_to_int(m.group(1)))
    for value in candidates:
        if value >= MIN_PLAUSIBLE_POT:
            return value
    return None


def _blinds_dict(sb, bb, ante):
    if bb < MIN_PLAUSIBLE_BB:
        return None
    if ante is not None and ante < 5:
        ante = None
    return {"sb": sb, "bb": bb, "ante": ante}


def find_blinds(lines):
    passes = [
        lambda text: BLINDS_LABELED_RE.search(text),
        lambda text: BLINDS_ANTE_WORD_RE.search(text),
        lambda text: BLINDS_COMPACT_RE.search(text),
    ]
    for check in passes:
        for ln in lines:
            m = check(ln["text"])
            if m:
                sb, bb = _to_int(m.group(1)), _to_int(m.group(2))
                ante = _to_int(m.group(3)) if m.group(3) else None
                result = _blinds_dict(sb, bb, ante)
                if result:
                    return result
    for check in (lambda text: BLINDS_LABELED_RE.search(text), lambda text: BLINDS_COMPACT_RE.search(text)):
        for row in _row_texts(lines):
            m = check(row)
            if m:
                sb, bb = _to_int(m.group(1)), _to_int(m.group(2))
                ante = _to_int(m.group(3)) if m.group(3) else None
                result = _blinds_dict(sb, bb, ante)
                if result:
                    return result
    for ln in lines:
        m = BLINDS_ANTE_NO_VALUE_RE.search(ln["text"])
        if m:
            result = _blinds_dict(_to_int(m.group(1)), _to_int(m.group(2)), None)
            if result:
                return result
    return None


def find_blinds_corner(*line_sets):
    """Busca el indicador compacto de ciegas ("17,5K/35K(4,5K)") en cada
    conjunto de lineas de line_sets, probados en orden (paradas al primer
    acierto). Se pasan varios conjuntos -no ya fusionados por
    merge_line_sets()- porque un mismo error de OCR (un caracter espurio en
    una de las pasadas) no aparece igual en todas: si la pasada de mayor
    prioridad da un numero corrupto, la siguiente puede dar el bueno, y
    fusionar antes perderia esa segunda oportunidad (merge_line_sets se
    queda con la primera lectura de cada posicion, corrupta o no).
    Verificado contra las 93 capturas: la gran mayoria de aciertos cumplen
    bb == 2*sb (estructura estandar de este torneo), asi que se exige esa
    relacion como filtro de cordura contra OCR corrupto (un caracter de mas
    o de menos en el "K"/"M" da un valor que ya no encaja)."""
    for lines in line_sets:
        for ln in lines:
            m = BLINDS_CORNER_RE.search(ln["text"])
            if not m:
                continue
            sb, bb = _to_int_corner(m.group(1)), _to_int_corner(m.group(2))
            ante = _to_int_corner(m.group(3))
            if not sb or not bb or bb != 2 * sb:
                continue
            result = _blinds_dict(sb, bb, ante)
            if result:
                return result
    return None


def _clean_name(text):
    return text.strip().strip("/.,;:'\"|")


def _is_name_candidate(text):
    cleaned = _clean_name(text)
    if len(cleaned) < 5:
        return False
    if not RANK_WORDS_RE.match(cleaned):
        return False
    low = cleaned.lower()
    if low in NAME_BLACKLIST:
        return False
    if any(len(bw) >= 4 and (bw in low or low in bw) for bw in NAME_BLACKLIST):
        return False
    if sum(1 for c in cleaned if c.isalpha() and c.islower()) < 2:
        return False
    return True


def _is_number_candidate(text):
    cleaned = text.strip()
    return bool(NUMBER_RE.match(cleaned))


def find_players(lines, image_diagonal, hero_box=None):
    names = [ln for ln in lines if _is_name_candidate(ln["text"])]
    numbers = [ln for ln in lines if _is_number_candidate(ln["text"])]

    max_dy = image_diagonal * 0.045
    max_dx = image_diagonal * 0.09
    used_numbers = set()
    players = []
    pairs = []
    for n in names:
        best_j, best_d = None, None
        for j, num in enumerate(numbers):
            if j in used_numbers:
                continue
            dx, dy = abs(n["cx"] - num["cx"]), abs(n["cy"] - num["cy"])
            if dx > max_dx or dy > max_dy:
                continue
            d = (dx ** 2 + dy ** 2) ** 0.5
            if best_d is None or d < best_d:
                best_d, best_j = d, j
        if best_j is not None:
            pairs.append((n, numbers[best_j]))
            used_numbers.add(best_j)

    hero_cx = hero_cy = None
    if hero_box:
        hero_cx = hero_box["x"] + hero_box["w"] / 2
        hero_cy = hero_box["y"] + hero_box["h"] / 2

    for name_ln, num_ln in pairs:
        players.append({
            "name": _clean_name(name_ln["text"]),
            "stack": _to_int(num_ln["text"]),
            "is_hero": False,
            "x": name_ln["cx"], "y": name_ln["cy"],
        })

    # el hero es, como mucho, un unico jugador: el de nombre+stack mas
    # cercano al asiento inferior-centro (donde estan sus cartas), y solo
    # si esta razonablemente cerca (si no, mejor ningun hero que uno erroneo)
    if hero_cx is not None and players:
        closest = min(players, key=lambda p: (p["x"] - hero_cx) ** 2 + (p["y"] - hero_cy) ** 2)
        d = ((closest["x"] - hero_cx) ** 2 + (closest["y"] - hero_cy) ** 2) ** 0.5
        if d < image_diagonal * 0.08:
            closest["is_hero"] = True

    return players
