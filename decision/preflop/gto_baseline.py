"""
RFI de referencia a 100 BB para mesas de 6 y 9 plazas.

POR QUÉ EXISTE. Las tablas digitalizadas del usuario (ranges.json) llegan hasta
40 BB y el suplemento de RangeConverter es MTT 8-max. A 100 BB -principio de
torneo y cash- una mesa de 9 se quedaba sin nada: lookup._nearest_stack_key
devolvía el rango de 40 BB como si fuera el del spot, que es justo el fallo que
_stack_key_note avisa pero no puede arreglar. Esto tapa ese hueco con una tabla
publicada PARA esa profundidad y PARA ese formato.

Fuente: Preflop Wizard, "Preflop Charts: Free GTO Poker Range Charts for Every
Position — 6-max, 9-max, MTT", RFI a 100 BB efectivas.
https://www.preflopwizard.app/blog/preflop-charts

LAS ETIQUETAS DE POSICIÓN NO SON LAS DEL GRÁFICO. Esta app nombra las posiciones
por CUÁNTA GENTE QUEDA DETRÁS, sobre el canon de 9 plazas (ver
vision/seat_map._posiciones): el primero en hablar de una mesa de 6 tiene cinco
jugadores detrás, así que se llama MP2 y no UTG. Traducir por el nombre en vez
de por la estructura es el bug que ya se arregló en seat_map y que aquí volvería
a entrar por la puerta de atrás, así que la equivalencia está escrita explícita
en _EQUIVALENCIA y los tests la comprueban contra seat_map.

LO QUE NO CUBRE. El gráfico de 9-max solo publica UTG, HJ, CO, BTN y SB. Las
tres posiciones intermedias de una mesa de 9 (EP2, MP1, MP2) NO están, y no se
rellenan interpolando: un rango de apertura inventado para MP1 sería
indistinguible de uno publicado y se jugaría igual de convencido. Tampoco hay
mesas de 7; para 8 ya está el suplemento de RangeConverter.

LO QUE ASUME. 100 BB efectivas, sin ante, bote sin abrir (nadie ha limpeado ni
subido), y frecuencias redondeadas -el gráfico da un rango puro por posición, no
una estrategia mixta-. No trae sizing y aquí no se inventa ninguno.
"""
from decision.preflop.lookup import RANKS, RANK_INDEX, normalize_hand

FUENTE_NOMBRE = "Preflop Wizard — Free GTO Preflop Charts (RFI 100 BB)"
FUENTE_URL = "https://www.preflopwizard.app/blog/preflop-charts"

STACK_KEY_BB = 100.0

# A partir de qué profundidad esta tabla está MÁS CERCA que la digitalizada de
# 40 BB: el punto medio entre las dos. Es la misma regla de "gráfico más
# cercano" que ya usa lookup._nearest_stack_key, solo que aplicada entre dos
# familias distintas en vez de dentro de una.
USABLE_DESDE_BB = 70.0

# Etiqueta de la app -> etiqueta del gráfico, por número de plazas. Se deriva de
# vision/seat_map._posiciones(n): en una mesa de 6 el primero en hablar es MP2,
# en una de 9 es EP1. En la de 9 el gráfico publica además "MP", que es el
# TERCERO en hablar de una mesa de nueve y por tanto el MP1 de esta app.
_EQUIVALENCIA = {
    6: {"MP2": "UTG", "HJ": "HJ", "CO": "CO", "BTN": "BTN", "SB": "SB"},
    9: {"EP1": "UTG", "MP1": "MP", "HJ": "HJ", "CO": "CO", "BTN": "BTN",
        "SB": "SB"},
}

# Rangos tal y como los publica la fuente, en notación estándar. No se tocan al
# copiarlos: expandirlos a mano aquí sería una transcripción más que revisar.
#
# EL PORCENTAJE QUE ACOMPAÑA A CADA FILA ES EL DE LA FUENTE, y no siempre cuadra
# con su propia lista de manos: en 6-max SB el gráfico rotula ~36% y las manos
# que enumera son el 33,7%. Se conserva el rótulo porque es lo que el usuario ve
# si abre el gráfico, pero lo que la app APLICA es la lista, así que
# recommend() devuelve también el porcentaje recalculado (``range_pct_real``) y
# es ese el que se enseña. Un test comprueba que la distancia entre los dos no
# se dispara, que es como se detecta una transcripción a la que le faltan
# tokens: así se cazó la primera versión de esta tabla, a la que se le habían
# perdido las manos offsuit de CO, BTN y SB.
_NOTACION = {
    6: {
        "UTG": ("22+, ATs+, AJo+, KQs, KJs, QJs, JTs, T9s", 15),
        "HJ": ("22+, A9s+, ATo+, KTs+, KQo, QTs+, JTs, T9s, 98s", 19),
        "CO": ("22+, A2s+, A8o+, K9s+, KTo+, Q9s+, QTo+, J9s+, JTo, T8s+, "
               "97s+, 87s, 76s, 65s", 27),
        "BTN": ("22+, A2s+, A2o+, K2s+, K7o+, Q4s+, Q9o+, J7s+, J9o+, T7s+, "
                "T9o, 96s+, 86s+, 75s+, 65s, 54s", 43),
        "SB": ("22+, A2s+, A4o+, K4s+, K9o+, Q7s+, QTo+, J8s+, JTo, T8s+, "
               "97s+, 87s, 76s, 65s, 54s", 36),
    },
    9: {
        "UTG": ("22+, ATs+, KTs+, QTs+, JTs, AJo+, KQo", 11),
        "MP": ("22+, A9s+, KTs+, QTs+, J9s+, T9s, 98s, AJo+, KQo", 13),
        "HJ": ("22+, A7s+, K9s+, Q9s+, J9s+, T9s, 98s, ATo+, KJo+", 17),
        "CO": ("22+, A2s+, K8s+, Q9s+, J8s+, T8s+, 97s+, 87s, 76s, A9o+, "
               "KTo+, QJo", 24),
        "BTN": ("22+, A2s+, K2s+, Q5s+, J7s+, T7s+, 96s+, 86s+, 75s+, 65s, "
                "54s, A2o+, K8o+, Q9o+, J9o+, T9o", 40),
        "SB": ("22+, A2s+, K5s+, Q8s+, J8s+, T8s+, 97s+, 86s+, 76s, 65s, "
               "A2o+, K9o+, QTo+, JTo", 30),
    },
}

# 52*51/2: todos los repartos posibles de dos cartas. Es el denominador de un
# porcentaje de rango, y va nombrado porque "1326" suelto no se lee.
COMBOS_TOTALES = 1326

_CACHE = {}


def _expandir_token(token):
    """'ATs+' -> ['AKs','AQs','AJs','ATs'] · '22+' -> todas las parejas.

    El '+' significa "y mejor" sobre el eje que varía: en una pareja sube la
    pareja entera, en una no-pareja sube el KICKER hasta una carta por debajo de
    la alta. Lanza ValueError con la notación mal escrita en vez de devolver un
    conjunto a medias, porque un rango silenciosamente recortado es un rango
    demasiado tight que nadie nota.
    """
    texto = token.strip()
    if not texto:
        raise ValueError("token vacío")
    mas = texto.endswith("+")
    nucleo = texto[:-1] if mas else texto
    if len(nucleo) < 2:
        raise ValueError(f"notación no reconocida: {token!r}")
    alto, bajo, sufijo = nucleo[0].upper(), nucleo[1].upper(), nucleo[2:].lower()
    if alto not in RANK_INDEX or bajo not in RANK_INDEX:
        raise ValueError(f"rango desconocido en {token!r}")

    if alto == bajo:
        if sufijo:
            raise ValueError(f"una pareja no lleva sufijo de palo: {token!r}")
        indice = RANK_INDEX[alto]
        indices = range(indice + 1) if mas else (indice,)
        return [RANKS[i] * 2 for i in indices]

    if sufijo not in ("s", "o"):
        raise ValueError(f"falta el sufijo s/o en {token!r}")
    i_alto, i_bajo = RANK_INDEX[alto], RANK_INDEX[bajo]
    if i_alto >= i_bajo:
        raise ValueError(f"la carta alta no es la primera en {token!r}")
    indices = range(i_alto + 1, i_bajo + 1) if mas else (i_bajo,)
    return [alto + RANKS[i] + sufijo for i in indices]


def expandir(notacion):
    """'22+, ATs+, KQs' -> conjunto de manos en la notación de ranges.json.

    Un rango vacío es un error, no un resultado: significaría que no se abre
    NINGUNA mano desde esa posición, y eso no lo dice ningún gráfico.
    """
    manos = set()
    for token in (notacion or "").split(","):
        if token.strip():
            manos.update(_expandir_token(token))
    if not manos:
        raise ValueError(f"notación sin ninguna mano: {notacion!r}")
    return manos


def combos(manos):
    """Repartos concretos que cubren esas manos: 6 por pareja, 4 suited, 12 off."""
    return sum(6 if len(m) == 2 else 4 if m.endswith("s") else 12 for m in manos)


def _rango(plazas, posicion_grafico):
    clave = (plazas, posicion_grafico)
    if clave not in _CACHE:
        notacion, pct = _NOTACION[plazas][posicion_grafico]
        manos = expandir(notacion)
        real = round(100.0 * combos(manos) / COMBOS_TOTALES, 1)
        _CACHE[clave] = (manos, pct, real)
    return _CACHE[clave]


def posicion_publicada(hero_position, max_players):
    """Etiqueta del gráfico para esta posición, o None si no está publicada."""
    return (_EQUIVALENCIA.get(max_players) or {}).get(hero_position)


def recommend(hero_cards, hero_position, max_players, stack_bb,
              ante_observado=False):
    """Apertura de referencia a 100 BB, o None si el spot no está cubierto.

    Devuelve None -y no un FOLD- cuando falta el soporte: la posición no está
    publicada, la mesa no es de 6 ni de 9, o la profundidad cae más cerca de las
    tablas digitalizadas. Un FOLD por falta de datos se lee igual que un FOLD por
    estrategia y es mucho peor consejo.

    ``ante_observado`` NO cambia el rango, lo DECLARA. El gráfico es de cash sin
    ante y con ante se abre más ancho, porque hay más muerto en el bote por el
    que pelear. Se sigue sirviendo igual -medido en la sesión del 03-08-2026, el
    81% de las manos lleva ante y la alternativa era la tabla digitalizada de 40
    BB estirada hasta 113, que se equivoca MUCHO más en profundidad que esto en
    anchura- pero baja la confianza y lo dice, en vez de presentar un rango de
    otro juego como si fuera el del spot.
    """
    if max_players not in _EQUIVALENCIA:
        return None
    if not isinstance(stack_bb, (int, float)) or isinstance(stack_bb, bool):
        return None
    if stack_bb < USABLE_DESDE_BB:
        return None
    posicion_grafico = posicion_publicada(hero_position, max_players)
    if posicion_grafico is None:
        return None
    mano = normalize_hand(hero_cards or [])
    if mano is None:
        return None

    manos, pct, pct_real = _rango(max_players, posicion_grafico)
    distancia = abs(stack_bb - STACK_KEY_BB)
    return {
        "action": "OPEN RAISE" if mano in manos else "FOLD",
        "hand": mano,
        "in_range": mano in manos,
        "table_position": posicion_grafico,
        # el rótulo del gráfico y lo que de verdad abre la lista que se aplica
        "range_pct": pct,
        "range_pct_real": pct_real,
        "stack_key": STACK_KEY_BB,
        "stack_distance_bb": round(distancia, 1),
        "max_players": max_players,
        "ante_observado": bool(ante_observado),
        "source": "gto_baseline_chart",
        "source_name": FUENTE_NOMBRE,
        "source_url": FUENTE_URL,
        "confidence": _confianza(distancia, ante_observado),
        "assumptions": [
            f"gráfico RFI de {max_players}-max a 100 BB efectivas, sin ante",
            (
                "ESTA MESA PAGA ANTE y el gráfico no lo lleva: con ante se abre "
                "más ancho, así que este rango se queda CORTO, sobre todo en "
                "las posiciones tardías"
                if ante_observado else
                "no se ha observado ante en esta mano, que es el supuesto del "
                "gráfico"
            ),
            f"la posición {hero_position} de esta app equivale a "
            f"{posicion_grafico} en el gráfico (misma gente detrás)",
            "bote sin abrir: ni limpers ni subidas",
            "rango puro publicado; la fuente no da estrategia mixta ni sizing",
            "chip-EV, sin ICM",
        ],
    }


def _confianza(distancia, ante_observado):
    if ante_observado:
        return ("media-baja: gráfico de cash SIN ante aplicado a una mesa CON "
                "ante; el rango publicado se queda corto")
    if distancia <= 15:
        return "media-alta: formato y profundidad publicados para este spot"
    return (f"media: gráfico de 100 BB a {distancia:.0f} BB de la profundidad "
            "real de este spot")
