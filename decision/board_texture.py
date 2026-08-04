"""
Textura del board: emparejamiento, conexión, palos y carta alta.

Es una descripción de las cartas comunitarias, no una recomendación. La usa
decision/postflop_gto.py para elegir frecuencia y tamaño de c-bet siguiendo las
heurísticas publicadas de GTO Wizard, que están enunciadas justo sobre estos
tres ejes:

    https://blog.gtowizard.com/flop-heuristics-ip-c-betting-in-cash-games/

POR QUÉ NO SE REUTILIZA hand_strength._classify. Aquel clasifica la MANO de 5
del hero (par, color, escalera...). Aquí no hay mano: se mira qué escaleras y
colores permite el board a CUALQUIERA, que es una pregunta distinta y no
necesita las cartas del hero.

EL AS SE CUENTA DOS VECES para la conexión (14 y 1), porque A-2-3-4-5 es una
escalera y con el as solo alto un board A23 saldría "desconectado" teniendo tres
cartas a un solo hueco de escalera.
"""

_ORDEN = "23456789TJQKA"
_VALOR = {r: i + 2 for i, r in enumerate(_ORDEN)}     # "2"->2 ... "A"->14

_CALLE_POR_CARTAS = {3: "flop", 4: "turn", 5: "river"}

# Las etiquetas de palo del artículo son de FLOP (3 cartas). En turn y river se
# nombra por el máximo de cartas de un mismo palo, que es lo que decide si hay
# color hecho o proyecto.
_PALOS_FLOP = {3: "arcoiris", 2: "dos_palos", 1: "monocolor"}

FUENTE = "GTO Wizard — Flop Heuristics: IP C-Betting in Cash Games"
FUENTE_URL = "https://blog.gtowizard.com/flop-heuristics-ip-c-betting-in-cash-games/"


def _valores(codigos):
    """Valores de rango de las cartas, o None si alguna no se puede leer."""
    valores = []
    for codigo in codigos:
        if not isinstance(codigo, str) or len(codigo) < 2:
            return None
        rango = codigo[0].upper()
        if rango not in _VALOR:
            return None
        valores.append(_VALOR[rango])
    return valores


def _palos(codigos):
    """Palos de las cartas, o None si alguna no se puede leer.

    Repite la comprobación de longitud de _valores en vez de darla por hecha:
    las dos se llaman sobre la misma lista, pero clasificar() evalúa los dos
    resultados DESPUÉS, así que fiarse de la otra convierte un código de una
    sola letra en un IndexError en vez de en una abstención.
    """
    palos = []
    for codigo in codigos:
        if not isinstance(codigo, str) or len(codigo) < 2:
            return None
        palo = codigo[1].lower()
        if palo not in "hdcs":
            return None
        palos.append(palo)
    return palos


def _con_as_bajo(valores):
    """Los valores distintos, añadiendo el 1 si hay algún as (rueda A2345)."""
    distintos = set(valores)
    if 14 in distintos:
        distintos.add(1)
    return distintos


def _conexion(valores):
    """'conectado' | 'proyecto_escalera' | 'desconectado'.

    Se razona por VENTANAS de escalera reales, no por la distancia entre dos
    cartas, porque la distancia miente en los extremos del mazo. Con A y K en el
    board la única escalera que las contiene es TJQKA, así que con dos cartas
    propias (QJ) queda un proyecto a UN solo extremo -falta el T- y no un OESD;
    la regla ingenua "dos rangos a distancia <= 3" lo daba por proyecto abierto y
    subía la frecuencia de c-bet en un board que en realidad es seco.

    conectado          existe una ventana de 5 rangos consecutivos con TRES o
                       más cartas del board: la escalera ya está servida para
                       quien tenga las dos que faltan.
    proyecto_escalera  existe una ventana de 4 consecutivos con DOS o más del
                       board y los dos extremos abiertos, o sea desde 2345 hasta
                       TJQK. JQKA no cuenta (solo completa por abajo) y A234
                       tampoco (solo por arriba).
    desconectado       ni una cosa ni otra.
    """
    distintos = _con_as_bajo(valores)
    for inicio in range(1, 11):                  # A2345 ... TJQKA
        if len(distintos & set(range(inicio, inicio + 5))) >= 3:
            return "conectado"
    for inicio in range(2, 11):                  # 2345 ... TJQK
        if len(distintos & set(range(inicio, inicio + 4))) >= 2:
            return "proyecto_escalera"
    return "desconectado"


def _categoria_carta_alta(alta):
    if alta == 14:
        return "as"
    if alta >= 12:
        return "broadway_alto"          # K o Q
    if alta >= 10:
        return "broadway_bajo"          # J o T
    if alta >= 7:
        return "medio"
    return "bajo"


def _emparejamiento(valores):
    cuentas = {}
    for v in valores:
        cuentas[v] = cuentas.get(v, 0) + 1
    maximo = max(cuentas.values())
    if maximo >= 4:
        return "poker_en_board", maximo
    if maximo == 3:
        return "trio_en_board", maximo
    if maximo == 2:
        doble = sum(1 for c in cuentas.values() if c == 2) >= 2
        return ("doble_pareja_en_board" if doble else "emparejado"), maximo
    return "sin_emparejar", 1


def clasificar(board):
    """Textura del board, o None si no hay 3-5 cartas legibles.

    Devuelve None y no una textura "neutra" a propósito: una textura inventada
    se propagaría a una recomendación de tamaño con toda la apariencia de estar
    fundada.
    """
    if not isinstance(board, (list, tuple)) or len(board) not in _CALLE_POR_CARTAS:
        return None
    valores = _valores(board)
    palos = _palos(board)
    if valores is None or palos is None:
        return None
    if len(set(board)) != len(board):
        return None                       # una carta repetida: lectura imposible

    emparejamiento, repeticion_max = _emparejamiento(valores)
    cuentas_palo = {p: palos.count(p) for p in set(palos)}
    max_palo = max(cuentas_palo.values())
    if len(board) == 3:
        palos_label = _PALOS_FLOP[len(cuentas_palo)]
    elif max_palo >= 5:
        palos_label = "color_en_board"
    elif max_palo == 4:
        palos_label = "cuatro_del_palo"
    elif max_palo == 3:
        palos_label = "tres_del_palo"
    else:
        palos_label = "arcoiris"

    alta = max(valores)
    conexion = _conexion(valores)
    return {
        "calle": _CALLE_POR_CARTAS[len(board)],
        "cartas": len(board),
        "carta_alta": _ORDEN[alta - 2],
        "carta_alta_categoria": _categoria_carta_alta(alta),
        "hay_as": 14 in valores,
        "emparejamiento": emparejamiento,
        "emparejado": emparejamiento != "sin_emparejar",
        "repeticion_maxima": repeticion_max,
        "conexion": conexion,
        "palos": palos_label,
        "max_cartas_mismo_palo": max_palo,
        "color_posible": max_palo >= 3,
        "humedad": _humedad(conexion, palos_label, emparejamiento),
        "fuente": FUENTE,
        "fuente_url": FUENTE_URL,
    }


def _humedad(conexion, palos_label, emparejamiento):
    """0 (seco) a 1 (muy húmedo). Es un RESUMEN para mostrar, no un parámetro.

    Ningún tamaño se elige a partir de este número: postflop_gto trabaja con los
    tres ejes por separado, tal y como están enunciados en la fuente. Colapsarlos
    en un escalar perdería, por ejemplo, que un board emparejado se apuesta MÁS
    a menudo y a la vez más pequeño.
    """
    puntos = 0.0
    puntos += {"desconectado": 0.0, "proyecto_escalera": 0.30, "conectado": 0.50}[conexion]
    puntos += {
        "arcoiris": 0.0, "dos_palos": 0.25, "monocolor": 0.45,
        "tres_del_palo": 0.25, "cuatro_del_palo": 0.40, "color_en_board": 0.50,
    }[palos_label]
    if emparejamiento != "sin_emparejar":
        puntos += 0.05
    return round(min(puntos, 1.0), 2)


def describir(textura):
    """Frase corta en castellano para el HUD."""
    if not textura:
        return ""
    conexion = {
        "desconectado": "desconectado",
        "proyecto_escalera": "con proyecto de escalera",
        "conectado": "conectado",
    }[textura["conexion"]]
    palos = {
        "arcoiris": "arcoíris",
        "dos_palos": "de dos palos",
        "monocolor": "monocolor",
        "tres_del_palo": "con tres del mismo palo",
        "cuatro_del_palo": "con cuatro del mismo palo",
        "color_en_board": "con color servido",
    }[textura["palos"]]
    emparejado = {
        "sin_emparejar": "",
        "emparejado": ", emparejado",
        "doble_pareja_en_board": ", con doble pareja",
        "trio_en_board": ", con trío",
        "poker_en_board": ", con póker",
    }[textura["emparejamiento"]]
    return f"{textura['carta_alta']} alta, {conexion}, {palos}{emparejado}"
