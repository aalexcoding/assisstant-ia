"""
Matemática de equilibrio: alpha, MDF y ratio valor:farol.

Es ARITMÉTICA PURA sobre dos números (lo que se apuesta y el bote). No conoce
cartas, ni rangos, ni GameState, y por eso no puede equivocarse de spot: lo que
devuelve es cierto por definición una vez fijados bote y apuesta. Quien traduce
esos números en una acción es decision/postflop_gto.py, que sí asume cosas.

    alpha = riesgo / (riesgo + recompensa)
    MDF   = 1 - alpha

Fuente de las identidades y de los ejemplos numéricos de los tests:
https://blog.gtowizard.com/mdf-alpha/

QUÉ BOTE. Es el error que más fácil se cuela aquí. Las fórmulas publicadas usan
el bote ANTES de la apuesta; PokerStars dibuja en ``Bote`` el bote YA CON la
apuesta del rival dentro (comprobado en el corpus, ver decision/postflop_math).
Los dos convenios conviven en este módulo, pero separados y nombrados:

    alpha(apuesta, bote_antes)              <- convenio de la literatura
    alpha_desde_bote_mostrado(pagar, bote)  <- convenio de la pantalla

y ``bote_antes = bote_mostrado - apuesta``. Confundirlos no da un error
escandaloso sino uno pequeño y plausible (con apuesta de bote, 33% donde toca
50%), que es justo la clase de fallo que esta app evita.

LO QUE ESTOS NÚMEROS NO SON. El MDF es una propiedad de un RANGO, no de una
mano: dice qué fracción de tu rango tiene que seguir para que el farol de bote
0% de equity del rival sea indiferente. No dice si ESTA mano paga; eso lo dicen
las pot odds (equity requerida) y la equity que tenga. Además el MDF supone que
los faroles del rival no tienen equity: cuando la tienen -y en flop y turn casi
siempre la tienen- la defensa correcta es MENOR que el MDF, porque el rival ya
gana algo cuando le pagan. Por eso el MDF es el techo de una defensa, no una
cuota que haya que cumplir en flop.
"""

FUENTE = "GTO Wizard — MDF & Alpha"
FUENTE_URL = "https://blog.gtowizard.com/mdf-alpha/"


def _positivo(valor):
    return (isinstance(valor, (int, float))
            and not isinstance(valor, bool)
            and valor > 0)


def alpha(apuesta, bote_antes):
    """Fracción de foldeos que necesita un farol de 0% de equity para no perder.

    ``bote_antes`` es el bote SIN la apuesta dentro: se arriesga ``apuesta``
    para ganar ``bote_antes``. Devuelve None si algún importe no es utilizable,
    porque un 0 silencioso aquí se leería como "no necesita foldeos nunca".
    """
    if not _positivo(apuesta) or not _positivo(bote_antes):
        return None
    return apuesta / (apuesta + bote_antes)


def mdf(apuesta, bote_antes):
    """Frecuencia mínima de defensa del que enfrenta la apuesta: 1 - alpha."""
    a = alpha(apuesta, bote_antes)
    return None if a is None else 1.0 - a


def alpha_de_subida(subida_total, bote_antes_de_la_subida):
    """Alpha de una SUBIDA, que no es la misma cuenta que la de una apuesta.

    El que sube arriesga el total de su subida (no la diferencia) para ganar un
    bote que ya incluye la apuesta que está subiendo. Ejemplo del artículo: se
    apuesta 60 en un bote de 100 y el rival sube a 200; arriesga 200 para ganar
    160, así que alpha = 200/(200+160) = 55,5% y no el 44,4% que saldría de
    tratar la subida como una apuesta de 200 en un bote de 250.
    """
    if not _positivo(subida_total) or not _positivo(bote_antes_de_la_subida):
        return None
    return subida_total / (subida_total + bote_antes_de_la_subida)


def fraccion_farol(apuesta, bote_antes):
    """Qué parte del rango que apuesta deben ser faroles, en equilibrio.

    Sale de exigir que el que paga quede indiferente: con ``apuesta`` en un bote
    ``bote_antes`` necesita ``apuesta/(2*apuesta+bote_antes)`` de faroles
    enfrente. Apuesta de bote -> 1/3 faroles (2:1 valor:farol).

    Es un resultado de RIVER, donde ya no queda carta que cambie quién gana. En
    flop y turn el rango que apuesta lleva más faroles que esto, porque muchos
    tienen equity y no son faroles puros.
    """
    if not _positivo(apuesta) or not _positivo(bote_antes):
        return None
    return apuesta / (2.0 * apuesta + bote_antes)


def ratio_valor_farol(apuesta, bote_antes):
    """Combos de valor por cada combo de farol: (bote + apuesta) / apuesta.

    33% -> 4:1 · 50% -> 3:1 · 66% -> 2,5:1 · 100% -> 2:1 · 125% -> 1,8:1.
    """
    if not _positivo(apuesta) or not _positivo(bote_antes):
        return None
    return (bote_antes + apuesta) / apuesta


def faroles_permitidos(combos_valor, apuesta, bote_antes):
    """Cuántos combos de farol admite un rango con ``combos_valor`` de valor."""
    ratio = ratio_valor_farol(apuesta, bote_antes)
    if ratio is None or not isinstance(combos_valor, (int, float)):
        return None
    return combos_valor / ratio


def equity_requerida(pagar, bote_mostrado):
    """Pot odds con el BOTE DE LA PANTALLA (la apuesta del rival ya dentro).

    Es ``pagar / (bote_mostrado + pagar)``: se paga ``pagar`` para disputar un
    bote final de ``bote_mostrado + pagar``. Misma identidad que usa
    decision/postflop_math.calcular, replicada aquí para que el módulo se pueda
    usar suelto.
    """
    if not _positivo(pagar) or not _positivo(bote_mostrado):
        return None
    return pagar / (bote_mostrado + pagar)


def bote_antes_de(bote_mostrado, apuesta):
    """Del bote que dibuja el cliente al bote de las fórmulas publicadas.

    None si la resta no deja un bote positivo: pasa cuando el OCR leyó mal uno
    de los dos importes, y seguir con un bote 0 o negativo produciría un alpha
    inventado.
    """
    if not _positivo(bote_mostrado) or not _positivo(apuesta):
        return None
    antes = bote_mostrado - apuesta
    return antes if antes > 0 else None


def alpha_desde_bote_mostrado(pagar, bote_mostrado):
    """Alpha de la apuesta del rival leyendo el bote de la pantalla.

    Se simplifica a ``pagar / bote_mostrado`` porque el bote mostrado ya es
    ``bote_antes + pagar``. Se deja escrito con bote_antes_de() de todas formas,
    para que la guarda de coherencia (bote mostrado mayor que la apuesta) actúe.
    """
    antes = bote_antes_de(bote_mostrado, pagar)
    return None if antes is None else alpha(pagar, antes)


def mdf_desde_bote_mostrado(pagar, bote_mostrado):
    a = alpha_desde_bote_mostrado(pagar, bote_mostrado)
    return None if a is None else 1.0 - a


def ev_farol(prob_fold, bote_antes, apuesta):
    """EV en fichas de un farol de 0% de equity: fold%*bote - call%*apuesta."""
    if not _positivo(bote_antes) or not _positivo(apuesta):
        return None
    if not isinstance(prob_fold, (int, float)) or not 0.0 <= prob_fold <= 1.0:
        return None
    return prob_fold * bote_antes - (1.0 - prob_fold) * apuesta


def resumen(apuesta, bote_antes):
    """Todas las cifras de un tamaño, o None si los importes no sirven.

    ``tamano_pct`` es la apuesta como porcentaje del bote previo, que es como se
    nombran los tamaños en la literatura (una "apuesta de 66%" son 66% del bote
    ANTES de apostar).
    """
    a = alpha(apuesta, bote_antes)
    if a is None:
        return None
    return {
        "apuesta_bb": round(float(apuesta), 2),
        "bote_antes_bb": round(float(bote_antes), 2),
        "tamano_pct": round(100.0 * apuesta / bote_antes, 1),
        "alpha": round(a, 4),
        "mdf": round(1.0 - a, 4),
        "fraccion_farol": round(fraccion_farol(apuesta, bote_antes), 4),
        "ratio_valor_farol": round(ratio_valor_farol(apuesta, bote_antes), 2),
        "fuente": FUENTE,
        "fuente_url": FUENTE_URL,
    }
