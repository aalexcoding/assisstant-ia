"""
Traduccion de las etiquetas de accion a (ingles, castellano), para que el HUD
pueda mostrar la orden en ingles grande con el castellano debajo:

    FOLD
    no ir

Las etiquetas vienen tal cual de decision/preflop/ranges.json, que es la
digitalizacion de las capturas del usuario, asi que NO se pueden renombrar en
origen: llegan como "OPEN RAISE (2 BB)", "3BET (6.5 BB)", "MARGINAL CALL",
"fold"... Esta capa las traduce sin tocar el dato.

El SIZING no se enumera. Doce de las diecinueve etiquetas solo se diferencian en
el importe entre parentesis (4 de OPEN RAISE y 8 de 3BET), asi que se separa con
UNA regex, se traduce solo la frase base y se vuelve a pegar. Consecuencia
practica: si el usuario redigitaliza sus rangos y aparece un "3BET (7.5 BB)" que
hoy no existe, se traduce solo, sin tocar este fichero.

Decimales: el ingles conserva el importe tal cual salio del dato (punto), el
castellano lo pasa a coma, que es lo que muestra el cliente en español.

Etiqueta desconocida -> (label.upper(), None), nunca una excepcion. La capa
probabilistica del preflop (Fase E) va a introducir etiquetas nuevas, y el HUD
debe seguir mostrando la linea grande aunque todavia no tenga traduccion, en vez
de romperse o quedarse mudo. El test test_actions.py recorre ranges.json y exige
que TODA etiqueta presente en los datos tenga castellano, asi que el hueco se
detecta en el test y no en la mesa.
"""
import re

# "OPEN RAISE (3.5 BB)" -> base="OPEN RAISE", size="3.5"
SIZING_RE = re.compile(r"^(?P<base>.*?)\s*\(\s*(?P<size>\d+(?:[.,]\d+)?)\s*BB\s*\)\s*$",
                       re.IGNORECASE)

# Etiqueta sintetica del motor (no sale de ranges.json): la BB nunca ABRE el
# bote, asi que cuando nadie ha subido su decision es pasar y ver el flop gratis.
CHECK_BB_OPTION = "CHECK (BB option)"

# Frases base. La busqueda es por coincidencia EXACTA de la base, no por prefijo,
# para que "OPEN RAISE ALL IN" no lo capture la entrada de "OPEN RAISE".
_BASE = {
    "OPEN RAISE":          ("OPEN RAISE", "abrir subiendo"),
    "OPEN RAISE ALL IN":   ("OPEN RAISE ALL IN", "abrir con todo (all in)"),
    "MARGINAL OPEN RAISE": ("MARGINAL OPEN RAISE", "abrir subiendo, justo"),
    "LIMP":                ("LIMP", "pagar la ciega sin subir"),
    "FOLD":                ("FOLD", "no ir"),
    "3BET":                ("3BET", "resubir"),
    "ALL IN":              ("ALL IN", "con todo (all in)"),
    "CALL":                ("CALL", "pagar"),
    "MARGINAL CALL":       ("MARGINAL CALL", "pagar, justo"),
    "CHECK (BB OPTION)":   ("CHECK", "pasar (opcion de la BB)"),
}


def translate_action(label):
    """'OPEN RAISE (3.5 BB)' -> ('OPEN RAISE (3.5 BB)', 'abrir subiendo a 3,5 BB').

    Devuelve (english, spanish). spanish es None si la etiqueta no se conoce; en
    ese caso english es la etiqueta en mayusculas, para que el HUD siempre tenga
    algo que enseñar."""
    if not label:
        return "", None
    texto = " ".join(str(label).split())

    m = SIZING_RE.match(texto)
    base, size = (m.group("base"), m.group("size")) if m else (texto, None)

    par = _BASE.get(base.upper())
    if par is None:
        return texto.upper(), None
    en, es = par

    if size is not None:
        en = f"{en} ({size} BB)"
        # el cliente en español usa coma decimal
        es = f"{es} a {size.replace('.', ',')} BB"
    return en, es


def translate_into(recommendation):
    """Añade action_en / action_es a un dict de recomendacion, in place, y lo
    devuelve. La etiqueta cruda se conserva en "action": es la que enlaza con
    ranges.json y la que se registra en el log de decisiones, asi que el
    historial sigue siendo comparable."""
    if recommendation and recommendation.get("action"):
        en, es = translate_action(recommendation["action"])
        recommendation["action_en"] = en
        recommendation["action_es"] = es
    return recommendation
