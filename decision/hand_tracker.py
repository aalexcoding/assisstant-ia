"""
Rastreador de mano: reconstruye lo que cada jugador ha COMPROMETIDO en el bote
comparando su STACK entre frames, en vez de intentar leer las fichas apostadas
sobre el tapete.

    comprometido[asiento] = stack_al_empezar_la_mano - stack_actual

POR QUE. Leer el importe apostado en la mesa es lo que esta fallando: de 101
frames con el boton "Igualar" pidiendo mas de 1 BB, 81 no tenian NINGUN asiento
cuyo importe lo explicara, y una pasada de OCR sobre el tapete entero tampoco
encuentra la cifra (0 de 22). Los stacks, en cambio, si se leen. Y no depende de
donde dibuje el cliente las fichas, asi que sobrevive a recalibrar un recuadro:
esa clase de fallo ya ha mordido dos veces en este proyecto (el area del boton
del dealer en pixeles absolutos, las zonas de apuesta).

LO QUE MIDE ESTE MODULO, re-analizando una sesion real entera (1.173 frames) con
el codigo actual, en los 98 frames PREFLOP donde el boton pide mas de 1 BB (que
son exactamente los que hoy hacen abstenerse al motor):

    lo explica el importe leido en la mesa      35%
    lo explica el comprometido derivado         59%
    lo explica alguno de los dos                81%
    sin explicar (el motor se abstiene)         19%   <- antes 65%

Y cuando disparan las dos señales apuntan al MISMO asiento 12 de 13 veces, que es
la corroboracion que hace fiable la atribucion (son fuentes independientes: OCR
del nameplate vs OCR de la zona de apuesta).

De punta a punta, con el motor entero sobre esa sesion: las defensas
(threebet_call) pasan de 13 a 33 y las recomendaciones de 278 a 298, y el cambio
es PURAMENTE ADITIVO -20 nuevas, 0 cambiadas, 0 perdidas-, que es la propiedad
que lo hace seguro de meter (fijada en test_hand_tracker.py).

EL COMPROMETIDO ES UNA COTA INFERIOR, y de ahi sale todo el cuidado del modulo.
Si la mano ya habia empezado cuando se vio al asiento por primera vez, la base
YA esta rebajada por lo que puso, asi que se devuelve de menos. Medido: en la
mitad de las manos la SB sale con 0 comprometido en vez de 0,5, porque la
frontera de mano se detecta unos frames tarde y para entonces las ciegas ya
estan puestas.

Quedarse corto es la direccion PELIGROSA: no ver una subida lleva a recomendar el
rango de APERTURA enfrentando una subida, el peor fallo posible en esta app. Por
eso la regla de uso es estricta y esta en el motor:

    el comprometido NUNCA crea una subida, solo ATRIBUYE una que el boton
    "Igualar" ya ha demostrado que existe.

Asi, un comprometido inflado (por una frontera de mano que se paso por alto) no
puede inventarse un raiser: si el boton no pide nada, no se mira. Y si lo pide,
se exige ademas un unico candidato, igual que ya hace detect_raiser.

FRONTERAS DE MANO. La base hay que olvidarla al empezar mano nueva, o el
comprometido se dispara en cuanto alguien gana un bote. Se cortan por dos
señales, elegidas midiendo (ver motivos_de_frontera); el board y las subidas de
stack se descartaron con datos.

Vive en decision/ y no en vision/ porque no mira pixeles: consume GameStates ya
resueltos y lo que produce -cuanto ha metido cada jugador- es una entrada de la
DECISION. vision/ es puro por frame a proposito; el estado entre frames vive aqui.

Necesita player["seat"], que expone table_state.analyze_layout(): es la unica
clave estable de un jugador entre frames (la posicion rota en cada mano, y el
nombre lo lee el OCR y el cliente lo sustituye por el verbo de la accion JUSTO
cuando el jugador actua, que es el peor momento para perderle la pista).
"""

# Margen para considerar que dos lecturas de stack son "el mismo numero". El OCR
# de un importe en BB da una decimal, asi que basta con absorber el redondeo.
IGUAL_TOL_BB = 0.05

# Cartas que dos boards tienen que compartir para ser el mismo board. Solo se
# usa para exponer la señal; NO corta (ver MOTIVOS_DE_CORTE).
BOARD_COMUNES_MIN = 2

# Longitudes legales de un board. Una lectura de 1, 2 o 6 cartas es basura de
# OCR y no puede juzgar nada: medido, 9 de 403 frames traen un board ilegal, y
# uno de ellos ("7cAc" en medio de un QcQs8sKsTc) partia la mano en dos.
BOARD_LONGITUDES = (3, 4, 5)


_NOMBRE_CALLE = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}


def _mas_visto(cuentas):
    """El nombre mas visto de ese asiento en esta mano, o None. Empate -> el
    alfabeticamente primero, solo para que la respuesta sea estable entre frames
    (un nombre que baila es justo lo que se quiere evitar)."""
    if not cuentas:
        return None
    return max(sorted(cuentas), key=lambda n: cuentas[n])


def _board_legal(cartas):
    return list(cartas) if len(cartas) in BOARD_LONGITUDES else None


def _vista(state, hand_number=None):
    """Lo unico que hace falta de un GameState para juzgar fronteras.

    hand_number llega por parametro y no del state porque lo produce
    vision/hand_result.parse_hand_result() a partir de state["chat_lines"], y
    este modulo no importa vision/ (que arrastra cv2). El llamador ya lo tiene:
    la GUI parsea el chat en cada frame para el panel "Mano anterior"."""
    stacks = {}
    for p in state.get("players") or []:
        seat = p.get("seat")
        if seat and isinstance(p.get("stack"), (int, float)):
            stacks[seat] = float(p["stack"])
    return {
        "board": _board_legal(state.get("board") or []),
        "hero_cards": list(state.get("hero_cards") or []),
        "hand_number": hand_number,
        "boton": next((p.get("seat") for p in state.get("players") or []
                       if p.get("position") == "BTN"), None),
        "stacks": stacks,
    }


def motivos_de_frontera(previo, actual):
    """Conjunto de señales que dicen que `actual` es de una mano DISTINTA de
    `previo`. Los dos son vistas de _vista(). Pura a proposito: es lo que permite
    medir cada señal por separado contra las sesiones grabadas.

      "cartas_aparecen"  el hero pasa de no tener cartas a tener dos: le acaban
                    de repartir, o sea que empieza una mano. NO se puede
                    encadenar con la mano anterior porque entre manos las cartas
                    siempre se recogen. Medido: 35 de 52 cortes reales, CERO
                    disparos sin respaldo.
      "cartas"      las cartas del hero son otras de un frame al siguiente.
                    PARECIA la señal mas fuerte -que salgan las mismas dos en dos
                    manos seguidas es 1 entre 1326- y medida es de las peores: en
                    tres sesiones acerto 3 de 52 cortes, y en una de ellas los 4
                    disparos fueron TODOS falsos. El motivo es que el OCR lee mal
                    una carta del hero el 2,4% de los frames, y ahi la señal ve
                    una mano nueva donde solo hay una lectura floja. NO CORTA, y
                    ademas es redundante: "cartas_aparecen" cubre el mismo caso
                    sin el ruido.
      "boton"       el boton del dealer esta en otro asiento. Es ESTRUCTURAL y no
                    estadistico: el boton se mueve exactamente UNA vez por mano,
                    ni mas ni menos. Medido sobre tres sesiones: 72 de 92 cortes
                    reales y CERO disparos sin respaldo. Aparecio revisando una
                    partida EN VIVO: el vigilante marcaba "tu posicion cambia
                    dentro de la mano", y al mirar el frame se veia que no era la
                    posicion la que fallaba sino que TODO el mapa habia rotado un
                    asiento, que es lo que pasa al empezar una mano.
      "mano_chat"   cambio el numero de mano del chat. Es el numero de la ultima
                    mano TERMINADA, o sea una etiqueta estable de la mano en
                    curso, y se lee en el 70% de los frames (13 cortes en 267).
                    Llega con unos frames de retraso, que es justo por lo que las
                    ciegas suelen quedar fuera de la base.
      "board"       los dos boards (de longitud legal) comparten menos de
                    BOARD_COMUNES_MIN cartas. NO CORTA: medido, 3 de 3 de sus
                    cortes no tenian respaldo ni del chat ni de las cartas.
      "board_vacio" habia board (de longitud legal) y ahora no hay ninguna carta.
                    Se descarto en la primera medicion, sobre 267 frames, por
                    miedo a que el OCR perdiera el board un frame. Con 3.300
                    frames de tres sesiones resulta ser de las mejores: 35 de 52
                    cortes reales y CERO disparos sin respaldo. Se probo exigir 3
                    frames vacios seguidos y no mejora (67 aciertos frente a 68) y
                    obliga a mirar al futuro, asi que se deja causal.
      "stack_sube"  algun stack subio mas de lo que absorbe el redondeo. Parecia
                    la señal ideal -en poker solo se ganan fichas al acabar la
                    mano- pero NO CORTA: mirando las 12 subidas dentro de manos
                    ya etiquetadas por el chat, son errores gordos de OCR
                    (106.5 -> 1065.0, o sea el punto decimal perdido; 30.3 ->
                    130.3, un "1" fantasma), no manos nuevas. Se expone porque
                    delata un asiento cuya lectura no es de fiar.
    """
    motivos = set()

    hp, ha = previo["hero_cards"], actual["hero_cards"]
    if len(hp) == 0 and len(ha) == 2:
        motivos.add("cartas_aparecen")
    if len(hp) == 2 and len(ha) == 2 and set(hp) != set(ha):
        motivos.add("cartas")

    if previo["hand_number"] and actual["hand_number"] and \
            previo["hand_number"] != actual["hand_number"]:
        motivos.add("mano_chat")

    bp, ba = previo["board"], actual["board"]
    if bp and ba and len(set(bp) & set(ba)) < min(BOARD_COMUNES_MIN, len(bp), len(ba)):
        motivos.add("board")
    if bp and not ba:
        motivos.add("board_vacio")

    if previo["boton"] and actual["boton"] and previo["boton"] != actual["boton"]:
        motivos.add("boton")

    for seat, s in actual["stacks"].items():
        anterior = previo["stacks"].get(seat)
        if anterior is not None and s > anterior + IGUAL_TOL_BB:
            motivos.add("stack_sube")
            break

    return motivos


# Las señales que CORTAN de verdad. Las otras se calculan y se exponen, pero no
# resetean el seguimiento: ver motivos_de_frontera para la medicion que descarto
# a cada una.
#
# Elegidas midiendo contra el numero de mano del chat sobre 3.300 frames de tres
# sesiones. Comparando juegos de señales por cuantos cortes REALES detectan:
#
#     chat + cartas distintas   (lo de antes)      44/75  = 59%
#     chat + cartas_aparecen                       58/75  = 77%
#     chat + cartas_aparecen + board_vacio         68/75  = 91%
#     ...y añadir "cartas distintas" a eso         68/75  = 91%, +1 falso
#
# Y despues, revisando una partida en vivo, aparecio "boton": 72 de 92 cortes
# reales y CERO falsos por si sola.
#
# O sea que "cartas distintas" no aporta un solo corte que las otras no vean, y
# si aporta ruido. Fuera.
MOTIVOS_DE_CORTE = frozenset({"mano_chat", "cartas_aparecen", "board_vacio", "boton"})

# Frames minimos que tiene que durar una mano antes de poder cortarla otra vez.
#
# Las señales de frontera se solapan a proposito -el board se vacia, se reparten
# cartas y el chat cambia el numero, todo en un par de segundos- asi que UNA
# frontera real dispara varias veces seguidas. Sin este minimo, cada disparo abre
# una mano: medido, el rastreador veia 110 manos donde el chat contaba 53. Una
# mano de verdad no dura dos frames, asi que ignorar los cortes inmediatos no
# pierde ninguna.
MIN_FRAMES_POR_MANO = 4


class _Asiento:
    """Seguimiento de un asiento dentro de UNA mano.

    La base es la PRIMERA lectura de la mano y no se sube nunca: dentro de una
    mano el stack solo puede bajar, asi que una lectura mayor es imposible y se
    descarta por ruido. Se probo exigir que un valor se confirmara 2 o 3 veces
    antes de aceptarlo -parecia lo prudente- y MEDIDO era peor en todo: la
    cobertura bajaba del 91% al 79% y al 68%, y el acuerdo con el bote leido del
    37% al 15% y al 8%. El motivo es que el preflop se resuelve en pocos frames y
    esperar confirmacion se lo pierde entero."""

    def __init__(self):
        self.base = None
        self.actual = None
        self.base_calle = None    # stack al empezar la CALLE en curso
        self.observaciones = 0
        self.descartadas = 0      # lecturas por encima de la base: OCR sospechoso

    def leer(self, valor):
        if valor is None:
            return
        valor = float(valor)
        self.observaciones += 1
        if self.base is None:
            self.base = self.actual = self.base_calle = valor
        elif valor <= self.base + IGUAL_TOL_BB:
            self.actual = valor
            if self.base_calle is None:
                self.base_calle = valor
        else:
            self.descartadas += 1

    def abrir_calle(self):
        """Empieza una calle nueva: lo puesto hasta ahora ya esta recogido en el
        bote, asi que la cuenta de la calle arranca de cero desde el stack de
        este momento. Si el asiento aun no se ha leido en esta mano, se deja a
        None y la primera lectura de la calle hara de base."""
        self.base_calle = self.actual

    def comprometido(self):
        if self.base is None or self.actual is None:
            return None
        return round(max(0.0, self.base - self.actual), 2)

    def comprometido_calle(self):
        if self.base_calle is None or self.actual is None:
            return None
        return round(max(0.0, self.base_calle - self.actual), 2)


class HandTracker:
    """Estado entre frames. Un objeto por sesion de analisis.

        tr = HandTracker()
        for state in frames:
            info = tr.update(state, hand_number)
            hand_tracker.aplicar(state, info)
    """

    def __init__(self):
        self.mano = 0
        self._previo = None
        self._asientos = {}
        self._meta = {}
        self._frames = 0
        self._motivos = frozenset()
        self._abrir(frozenset())

    def _abrir(self, motivos):
        self.mano += 1
        self._asientos = {}
        self._meta = {}
        # Nombres vistos en cada asiento durante ESTA mano, CON SU CUENTA. Se
        # muestra el mas visto, no el ultimo.
        #
        # Por que por mayoria y no "el ultimo bueno": el problema no era solo que
        # el cliente tapa el nick con el verbo de la accion, sino que el OCR lee
        # el mismo nick de formas distintas casi cada frame. Medido en una sesion
        # real, un asiento dio ocho variantes en UNA mano -"juanpalla",
        # "Juanpalia", "juanpaila", "jJuanpalia", "juanpalila"...- con 40 cambios,
        # y en el HUD eso se ve como un nombre que no para de bailar. La mayoria
        # lo fija: 152 lecturas de "babette62" no las tumba una de "Bn2ie".
        #
        # SE OLVIDA EN CADA MANO, y eso no es un descuido: en Zoom el cliente te
        # cambia de mesa entre manos, asi que el ocupante de un asiento puede ser
        # otra persona. Dentro de una mano el asiento no cambia de dueño, que es
        # justo el alcance en el que fijar el nombre es seguro.
        self._nombres = {}
        self._veces = {}           # en cuantos frames de la mano se vio cada asiento
        self._calle = 0            # cartas de board de la calle en curso
        self._frames = 0
        self._motivos = frozenset(motivos)

    def update(self, state, hand_number=None):
        """Incorpora un GameState y devuelve el resumen de la mano en curso. No
        modifica el state (para eso esta aplicar())."""
        actual = _vista(state, hand_number)
        motivos = motivos_de_frontera(self._previo, actual) if self._previo else frozenset()
        if motivos & MOTIVOS_DE_CORTE and self._frames >= MIN_FRAMES_POR_MANO:
            self._abrir(motivos)
        self._previo = actual
        self._frames += 1

        # CALLE. Se mide por el numero de cartas de board, y SOLO PUEDE AVANZAR:
        # el board no encoge en una mano de verdad, asi que un board mas corto (o
        # ausente) es una lectura perdida, no una calle anterior. Ignorarlo es lo
        # que evita que una lectura floja reinicie la cuenta de la calle y borre
        # lo que un rival lleva puesto en ella.
        board = actual["board"]
        if board is not None and len(board) > self._calle:
            self._calle = len(board)
            for a in self._asientos.values():
                a.abrir_calle()

        for p in state.get("players") or []:
            seat = p.get("seat")
            if not seat:
                continue
            a = self._asientos.get(seat)
            if a is None:
                a = self._asientos[seat] = _Asiento()
                self._veces[seat] = 0
                # si el asiento aparece en el PRIMER frame de la mano hay al menos
                # la posibilidad de haberle visto el stack intacto; si aparece mas
                # tarde, seguro que se perdio algo de lo que ya habia puesto
                self._meta[seat] = {"desde_el_principio": self._frames == 1}
            self._veces[seat] = self._veces.get(seat, 0) + 1
            a.leer(p.get("stack") if isinstance(p.get("stack"), (int, float)) else None)
            if p.get("name"):
                self._nombres.setdefault(seat, {})
                self._nombres[seat][p["name"]] = self._nombres[seat].get(p["name"], 0) + 1
            self._meta[seat].update(
                position=p.get("position"),
                is_hero=bool(p.get("is_hero")),
                in_hand=p.get("in_hand"),
                nombre=_mas_visto(self._nombres.get(seat)),
                action=p.get("action"),
                bet_leido=p.get("bet") if isinstance(p.get("bet"), (int, float)) else None)

        return self.resumen()

    def asientos_estables(self):
        """Asientos que se han visto ocupados en al menos la MITAD de los frames
        de esta mano. Es lo que hay que usar para contar jugadores, porque las
        posiciones salen de ese recuento y un asiento que parpadea las desplaza
        todas.

        Por que la mitad y no la union de todo lo visto: medido sobre 2.811
        frames, comparando contra el conjunto de asientos MODAL de cada mano, la
        UNION acierta el 72,5% -acumula cada falso positivo y ya no lo suelta- y
        la mayoria el 89,2%, frente al 85,7% de la lectura cruda. Y en lo que de
        verdad importa, la estabilidad de la posicion del hero dentro de la mano,
        baja los cambios del 3,9% al 1,8%.

        Nadie se levanta a mitad de mano, asi que dentro de una mano el conjunto
        es constante por las reglas del juego: lo que se mide aqui es ruido de
        lectura, no gente entrando y saliendo."""
        if not self._veces:
            return set()
        return {s for s, v in self._veces.items() if v * 2 >= self._frames}

    def resumen(self):
        asientos = {}
        for seat, a in self._asientos.items():
            m = self._meta[seat]
            comprometido = a.comprometido()
            asientos[seat] = {
                # lo puesto en LA CALLE en curso, que es lo que decide si hay una
                # apuesta que igualar AHORA. Preflop coincide con el de la mano,
                # asi que no cambia nada de lo que ya funcionaba.
                "comprometido_calle": a.comprometido_calle(),
                "position": m.get("position"),
                "nombre": m.get("nombre"),
                "action": m.get("action"),
                "is_hero": m.get("is_hero", False),
                "in_hand": m.get("in_hand"),
                "stack": a.actual,
                "stack_inicial": a.base,
                "comprometido": comprometido,
                "observaciones": a.observaciones,
                "lecturas_descartadas": a.descartadas,
                "desde_el_principio": m.get("desde_el_principio", False),
                "bet_leido": m.get("bet_leido"),
                "acuerdo": acuerdo(comprometido, m.get("bet_leido")),
            }
        return {
            "mano": self.mano,
            "frames": self._frames,
            "calle": _NOMBRE_CALLE.get(self._calle, "?"),
            "motivos_apertura": sorted(self._motivos),
            "asientos": asientos,
        }


# tolerancia para decir que el comprometido derivado y el importe leido en la
# mesa son el mismo numero
ACUERDO_TOL_BB = 0.15


def acuerdo(derivado, leido):
    """Como se llevan las dos señales para un asiento. Sirve para dos cosas: dar
    confianza cuando coinciden, y dejar rastro cuando no (el derivado manda -en
    las discrepancias suele acertar el- pero una discrepancia merece anotarse)."""
    if derivado is None and leido is None:
        return "ninguno"
    if leido is None:
        return "solo_derivado"
    if derivado is None:
        return "solo_leido"
    if abs(derivado - leido) <= ACUERDO_TOL_BB:
        return "coinciden"
    return "discrepan"


def aplicar(state, info):
    """Cuelga el comprometido de cada jugador del GameState, junto a su "bet"
    leido de la mesa, para que el motor pueda usar las dos señales. Devuelve el
    state (modificado in situ)."""
    asientos = info.get("asientos") or {}
    for p in state.get("players") or []:
        d = asientos.get(p.get("seat"))
        if d is not None:
            p["committed"] = d["comprometido"]
            p["committed_calle"] = d["comprometido_calle"]
            p["committed_acuerdo"] = d["acuerdo"]
            # Fija el nick al mas visto de esta mano. NO se limita a rellenar
            # cuando falta: el OCR lee el mismo nombre de formas distintas casi
            # cada frame, y dejar pasar la lectura del momento hace que el nombre
            # baile en el HUD. Una lectura suelta no tumba a la que se ha visto
            # cien veces.
            if d.get("nombre") and p.get("name") != d["nombre"]:
                p["name"] = d["nombre"]
                p["name_repuesto"] = True
    state["mano_seguida"] = info.get("mano")
    state["calle_seguida"] = info.get("calle")
    return state


# Margen al comparar el comprometido de un asiento con lo que pide el boton
# "Igualar". El comprometido es una COTA INFERIOR (la base puede estar ya
# rebajada), asi que se permite quedarse algo corto; pasarse no hace falta
# permitirlo porque el que subio siempre tiene puesto al menos lo que te piden.
TO_CALL_MARGEN_BB = 0.3


def atribuir_subida(players, to_call):
    """Quien subio, segun el comprometido derivado, cuando el boton "Igualar"
    pide `to_call`. Devuelve (position, seat) o (None, motivo).

    NO decide si hay subida: eso ya lo dice `to_call`, que es evidencia
    independiente (el propio cliente pidiendo un importe). Aqui solo se atribuye
    a un asiento. Esa asimetria es la que hace seguro usar un numero que puede
    venir inflado si se paso por alto una frontera de mano: sin boton que pida
    nada, no se mira.

    Conservador igual que engine._detect_raiser: si hay mas de un candidato o el
    candidato no tiene posicion, no se adivina."""
    if not isinstance(to_call, (int, float)) or to_call <= 0:
        return None, "sin_to_call"
    umbral = to_call - TO_CALL_MARGEN_BB
    cands = [p for p in players
             if not p.get("is_hero")
             and isinstance(p.get("committed"), (int, float))
             and p["committed"] >= umbral]
    if not cands:
        return None, "nadie_lo_explica"
    if len(cands) > 1:
        return None, "varios_candidatos"
    pos = cands[0].get("position")
    if pos is None:
        return None, "candidato_sin_posicion"
    return pos, cands[0].get("seat")
