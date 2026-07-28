"""
Fase E: capa DERIVADA del preflop. Responde spots que las tablas del usuario no
cubren, y todo lo que responde sale de UNA CELDA REAL suya.

Dos situaciones cubiertas hasta ahora:

    bb_option()   la opcion de la BB en un bote limpeado
    vs_limp()     limpers delante, con el hero FUERA de las ciegas
    squeeze()     una subida Y ademas alguien que la ha pagado

--- LA OPCION DE LA BB ---

Hasta ahora, cuando el hero estaba en la BB y nadie habia subido, el motor
respondia siempre lo mismo -"pasa y ve el flop gratis"- SIN MIRAR LAS CARTAS NI
EL STACK. Medido sobre una sesion real, esa respuesta era el 36% de todas las
recomendaciones: con AA y 5bb decia exactamente lo mismo que con 72o.

Aqui se responde de verdad, y todo lo que se responde sale de UNA CELDA REAL del
usuario. No se recalcula ninguna etiqueta: el 94% de los buckets de sus tablas no
son contiguos en el orden de fuerza de las manos, asi que repartir acciones por
tramos daria un rango que no es su estilo.

EL DONANTE: SU PROPIA FILA DE LA SB, a la misma profundidad.

Es la unica fila de sus tablas con la forma que pide este spot -subida arriba,
LIMP en medio, fold minimo- porque es la unica posicion desde la que el usuario
digitalizo "entrar sin subir". Las demas solo suben o se van.

EL MAPEO, que no es una eleccion sino una consecuencia de las reglas:

    OPEN RAISE (x BB)   -> RAISE OVER LIMPERS (x BB)
    MARGINAL OPEN RAISE -> MARGINAL RAISE OVER LIMPERS
    OPEN RAISE ALL IN   -> ALL IN
    LIMP                -> CHECK
    fold                -> CHECK

Las dos ultimas son forzadas: LA BB CON LA OPCION NUNCA SE RETIRA, porque pasar
es gratis. Un "fold" del donante no puede traducirse por fold aqui; lo que
significa es "no metas mas dinero", y eso es CHECK.

El sizing se copia del donante y NO se recalcula. Sobre limpers se suele subir
mas que abriendo, pero de eso no hay dato del usuario, y preferimos decir "este
es tu sizing de apertura de la SB" a inventar un multiplicador.

LO QUE SE PROBO Y NO SE SOSTIENE: desplazar la fila un asiento por cada limper de
mas (SB -> BTN -> CO), que era la idea del plan. Medido sobre ranges.json, a
partir de 20bb la fila BTN SUBE MAS que la SB (37-56% de los combos frente a
19-29%), porque en profundo la SB mete casi todo su rango medio en LIMP. O sea
que el desplazamiento ENSANCHA en vez de apretar, que es justo lo contrario de
lo que hace falta con mas rivales. Sin un segundo donante valido, con 2 o mas
limpers no se deriva: se deja el CHECK de siempre y se dice por que.

ANCHOS DEL DONANTE (% de los 1326 combos que suben), para saber que se esta
recomendando: 4bb 78,6% · 10bb 53,4% · 15bb 31,2% · 20bb 29,1% · 30bb 18,7% ·
40bb 22,6%. A 4-6bb la fila SB es practicamente todo all-in, asi que AA a 5bb
pasa de "pasa y ve el flop" a ALL IN, que es lo que dicen sus propias tablas.

Requiere lookup.py en el mismo directorio (lo pone el caller en sys.path).
"""
from decision.preflop.lookup import recommend

# La posicion cuya fila se usa como donante para la OPCION DE LA BB, y por que
# ella (ver el docstring).
DONANTE_POSICION = "SB"

# Orden de las posiciones de mas TIGHT a mas suelta, tal y como sale de sus
# propias tablas. Es el eje sobre el que se hace el CAMBIO DE FILA: enfrentar
# limpers pide apretar, y apretar es moverse hacia EP.
#
# Medido sobre ranges.json, ratio de anchura (no-fold) entre asientos adyacentes:
# n=77, media 0.802, sd 0.114. O sea que cada asiento hacia EP aprieta ~20%, y es
# MONOTONO en las once profundidades.
#
# La SB queda FUERA a proposito, como donante y como hero. Su fila es la unica
# construida sobre LIMP -78-90% de no-fold frente al 15-56% del resto- porque es
# la unica posicion desde la que el usuario digitalizo "entrar sin subir". Meterla
# en este eje romperia la monotonia: mover de SB a BTN no aprieta, ENSANCHA lo que
# se sube. Para la BB su forma es justo la que hace falta (bb_option); para este
# spot, no.
ORDEN_TIGHT_A_SUELTA = ("EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN")

# Cuantos limpers admite esta derivacion. Con 2 o mas no hay donante valido.
MAX_LIMPERS = 1

_DIRECTO = {
    "LIMP": "CHECK",
    "fold": "CHECK",
    "FOLD": "CHECK",
    "OPEN RAISE ALL IN": "ALL IN",
    "MARGINAL OPEN RAISE": "MARGINAL RAISE OVER LIMPERS",
}


def _traducir(etiqueta_donante):
    """Etiqueta de la fila SB -> etiqueta para la opcion de la BB."""
    directo = _DIRECTO.get(etiqueta_donante)
    if directo is not None:
        return directo
    # "OPEN RAISE (3 BB)" -> "RAISE OVER LIMPERS (3 BB)", conservando el sizing
    if etiqueta_donante.upper().startswith("OPEN RAISE"):
        return "RAISE OVER LIMPERS" + etiqueta_donante[len("OPEN RAISE"):]
    # etiqueta que no estaba en los datos cuando se escribio esto: no se
    # traduce a ciegas, se renuncia. Mejor el CHECK de siempre que una accion
    # inventada.
    return None


_DIRECTO_VS_LIMP = {
    # aqui SI se puede foldear: el hero no esta en la BB, asi que entrar cuesta
    # dinero. Es la diferencia clave con la opcion de la BB.
    "fold": "fold",
    "LIMP": "LIMP",
    "OPEN RAISE ALL IN": "ALL IN",
    "MARGINAL OPEN RAISE": "MARGINAL RAISE OVER LIMPERS",
}


def vs_limp(hero_cards, hero_position, stack_bb, limpers=1):
    """Que hacer con limpers delante, estando el hero FUERA de las ciegas.

    El donante es OTRA CELDA REAL suya: su rango de apertura desde la posicion
    que esta `limpers` asientos mas temprana. La idea es que cada limper ya
    metido equivale, a efectos de cuanta gente queda por hablar y de cuanto hay
    que apretar, a estar un asiento antes. Se copia esa celda tal cual; no se
    recalcula ninguna etiqueta.

    Devuelve None -y el motor se queda con lo de siempre- cuando no hay donante
    valido: si el hero esta en las ciegas (la SB tiene otra forma de fila, ver
    ORDEN_TIGHT_A_SUELTA; la BB tiene su propia funcion), si al desplazar se cae
    por debajo de EP1 (ya no hay nada mas tight que copiar) o si `limpers` no es
    un numero util."""
    if not isinstance(limpers, int) or limpers < 1:
        return None
    if hero_position not in ORDEN_TIGHT_A_SUELTA:
        return None
    i = ORDEN_TIGHT_A_SUELTA.index(hero_position) - limpers
    if i < 0:
        return None                       # no hay fila mas tight que copiar
    donante_pos = ORDEN_TIGHT_A_SUELTA[i]

    donante = recommend(hero_cards, donante_pos, stack_bb, facing="open_raise")
    if donante is None:
        return None
    accion = _traducir_vs_limp(donante["action"])
    if accion is None:
        return None

    key = donante["stack_key"]
    plural = "" if limpers == 1 else "s"
    return {
        "action": accion,
        "source": "derived",
        # media-alta: es una celda real suya y el desplazamiento esta medido
        # (0.802 de ratio, sd 0.114). Con mas de un limper se encadena el
        # desplazamiento y la incertidumbre se acumula.
        "confidence": "media-alta" if limpers == 1 else "media",
        "donor": f"tu rango de apertura de {donante_pos} a {key:g}bb",
        "donor_action": donante["action"],
        "stack_key": key,
        "limpers": limpers,
        "assumptions": [f"se trata {limpers} limper{plural} como estar {limpers} "
                        f"asiento{plural} mas temprano ({hero_position} -> {donante_pos}); "
                        f"cada asiento aprieta el rango un 20% en tus tablas"],
    }


def _traducir_vs_limp(etiqueta_donante):
    directo = _DIRECTO_VS_LIMP.get(etiqueta_donante)
    if directo is not None:
        return directo
    if etiqueta_donante.upper().startswith("OPEN RAISE"):
        return "RAISE OVER LIMPERS" + etiqueta_donante[len("OPEN RAISE"):]
    return None


def bb_option(hero_cards, stack_bb, limpers=None):
    """Que hacer con la opcion de la BB, derivado de la fila SB del usuario.

    limpers: cuantos rivales han entrado pagando (la SB completando cuenta). None
    si no se pudo contar, que pasa a menudo porque el importe de la mesa no
    siempre se lee.

    CERO SE TRATA COMO DESCONOCIDO. Si el hero tiene de verdad la opcion, hay al
    menos un rival dentro: si no, la mano ya habria terminado y el bote seria
    suyo. Asi que contar cero significa "no lo he visto", no "no hay nadie" -o
    bien que todavia no ha actuado nadie y esto es una vista previa-. En los dos
    casos se responde suponiendo UN limper, que es el caso modal, y se DICE.

    Devuelve None cuando no se puede responder honestamente (sin cartas, sin
    stack, con 2+ limpers, o con una etiqueta que no se sabe traducir); el
    llamador se queda entonces con el CHECK de siempre.

    El dict que devuelve lleva SIEMPRE de donde sale: `donor` nombra la celda
    real usada, para que en el HUD se pueda leer "esto no es tu tabla para este
    spot, es tu rango de apertura de la SB"."""
    if isinstance(limpers, int) and limpers > MAX_LIMPERS:
        return None

    donante = recommend(hero_cards, DONANTE_POSICION, stack_bb, facing="open_raise")
    if donante is None:
        return None
    accion = _traducir(donante["action"])
    if accion is None:
        return None

    key = donante["stack_key"]
    supuestos = []
    confianza = "media"
    if not limpers:                      # None o 0: ver el docstring
        supuestos.append("no se ha visto entrar a nadie todavia; se asume UN rival "
                         "dentro (con mas, este rango se queda suelto)")
        confianza = "baja"
    return {
        "action": accion,
        "source": "derived",
        "confidence": confianza,
        "donor": f"tu rango de apertura de la {DONANTE_POSICION} a {key:g}bb",
        "donor_action": donante["action"],
        "stack_key": key,
        "limpers": limpers,
        "assumptions": supuestos,
    }


# --- SQUEEZE: una subida Y ademas quien la ha pagado ------------------------
#
# Enfrentar una subida con gente que ya la ha pagado detras no es lo mismo que
# enfrentarla heads-up: hay mas dinero muerto, pero tambien mas manos que pueden
# superarte y menos posibilidad de que la subida sea un robo. Su tabla de
# threebet_call esta digitalizada para el caso heads-up, asi que aqui hay que
# apretar.
#
# EL DONANTE es otra celda REAL suya de la MISMA familia: su defensa contra ese
# mismo raiser, pero desde la posicion que esta `callers` asientos mas temprana.
# La logica es la misma que en vs_limp -cada rival de mas equivale a estar un
# asiento antes- solo que en la tabla de defensa en vez de en la de apertura.
#
# Medido sobre ranges.json, eje del HERO en threebet_call (sin las ciegas, que son
# outliers por su forma): n=105, media 0.848, sd 0.081. Cada asiento hacia EP
# aprieta la defensa un 15%.
#
# El eje del RAISER tambien es monotono (n=188, media 0.950) pero mucho mas flojo,
# asi que apretar por ahi apenas movería el rango: se usa el del hero.

_DIRECTO_SQUEEZE = {
    "fold": "fold",
    "ALL IN": "ALL IN",
    "CALL": "CALL",
    "MARGINAL CALL": "MARGINAL CALL",
}


def _traducir_squeeze(etiqueta_donante):
    directo = _DIRECTO_SQUEEZE.get(etiqueta_donante)
    if directo is not None:
        return directo
    # "3BET (5 BB)" -> "SQUEEZE (5 BB)": resubir con gente dentro ES un squeeze,
    # y llamarlo por su nombre importa porque el sizing correcto es otro (aunque
    # aqui se copie el del donante, como en el resto de la capa derivada).
    if etiqueta_donante.upper().startswith("3BET"):
        return "SQUEEZE" + etiqueta_donante[len("3BET"):]
    return None


def squeeze(hero_cards, hero_position, vs_position, stack_bb, callers=1):
    """Que hacer con una subida delante que ademas ya ha pagado alguien.

    Devuelve None -y el motor se queda con lo que hiciera antes- cuando no hay
    donante valido: si el hero esta en las ciegas (su fila tiene otra forma), si
    al desplazar se cae por debajo de EP1, si no existe celda de defensa contra
    ese raiser desde la posicion donante, o si `callers` no es util."""
    if not isinstance(callers, int) or callers < 1:
        return None
    if hero_position not in ORDEN_TIGHT_A_SUELTA or not vs_position:
        return None
    i = ORDEN_TIGHT_A_SUELTA.index(hero_position) - callers
    if i < 0:
        return None
    donante_pos = ORDEN_TIGHT_A_SUELTA[i]

    donante = recommend(hero_cards, donante_pos, stack_bb,
                        facing="threebet_call", vs_position=vs_position)
    if donante is None:
        return None
    accion = _traducir_squeeze(donante["action"])
    if accion is None:
        return None

    key = donante["stack_key"]
    plural = "" if callers == 1 else "s"
    return {
        "action": accion,
        "source": "derived",
        # media-baja: el salto esta medido, pero es mas flojo que el de apertura
        # (15% por asiento frente al 20%) y la tabla de partida ya es la mas
        # dispersa de las suyas
        "confidence": "media-baja" if callers == 1 else "baja",
        "donor": f"tu defensa de {donante_pos} contra {vs_position} a {key:g}bb",
        "donor_action": donante["action"],
        "stack_key": key,
        "callers": callers,
        "assumptions": [f"se trata {callers} rival{plural} que ya ha pagado la subida como "
                        f"estar {callers} asiento{plural} mas temprano ({hero_position} -> "
                        f"{donante_pos}); cada asiento aprieta tu defensa un 15%"],
    }
