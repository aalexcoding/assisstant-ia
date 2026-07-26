"""
Fase E, primera pieza: LA OPCION DE LA BB.

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
from lookup import recommend

# La posicion cuya fila se usa como donante, y por que ella (ver el docstring).
DONANTE_POSICION = "SB"

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
