"""
Historial de acciones de la mano (docs §2.2), reconstruido de los VERBOS que el
cliente pone en el nameplate.

De donde sale el dato: cuando un jugador actua, PokerStars le sustituye el nick
por lo que ha hecho -"Pasar", "Igualar", "Apostar", "Subir", "No ir"-. Esa
informacion se estaba tirando (peor: se estaba leyendo como si fuera el nombre,
ver table_state.es_verbo_de_accion). Aqui se convierte en la secuencia ordenada
de lo que ha pasado en la mano, que es lo unico que faltaba para distinguir con
certeza un open de una 3bet, un squeeze de una resubida.

QUE APORTA SOBRE EL COMPROMETIDO (hand_tracker). Son complementarios:

    hand_tracker  CUANTO ha puesto cada uno   (bajada de stack)
    action_log    QUE hizo y EN QUE ORDEN     (verbo del nameplate)

El comprometido no distingue "pagar 4bb" de "subir a 4bb", y el orden no se puede
deducir de un total. El verbo si lo dice.

EL LIMITE, y es el que manda: SOLO SE VE LO QUE SE MUESTREA. El verbo esta en
pantalla menos de 1,5 s, asi que a un periodo de muestreo parecido se pierden
acciones. Medido sobre una sesion real de 53 manos con muestreo de 1,48 s: se
captan 5,7 verbos distintos por mano, y una mano de 3-max tiene tipicamente 4-8
acciones. O sea que se ve la mayor parte, pero NO se puede afirmar que la lista
este completa, y por eso `acciones()` viene siempre con `completo=False`: quien
lo consuma tiene que tratarlo como "esto es lo que se ha visto", no como "esto es
todo lo que paso".

DEDUPLICACION. La misma acción visible en varios frames seguidos es UNA, aunque
el OCR cambie la puntuación ("Pasar" / "Pasar ~>"). Se compara la forma
CANÓNICA en cada asiento, así que "Subir, Subir, (nick), Subir" son dos subidas:
volver a ver el nick cierra el evento. Si el cliente revela después la segunda
línea "All-in", el evento existente se actualiza en vez de crear otra decisión.

Vive en decision/ por lo mismo que hand_tracker: no mira pixeles, consume
GameStates ya resueltos, y lo que produce es una entrada de la decision.
"""

# Verbo del cliente -> accion canonica. Las claves son la forma normalizada
# (minusculas y sin nada que no sea alfanumerico), igual que
# table_state.es_verbo_de_accion, porque el cliente escribe "All-in" y "No ir"
# con separadores que el OCR cambia a capricho.
_VERBO_A_ACCION = {
    "pasar": "check", "pasa": "check",
    "igualar": "call", "iguala": "call", "paga": "call",
    "apostar": "bet", "apuesta": "bet",
    "subir": "raise", "sube": "raise", "resubir": "raise",
    "noir": "fold",
    "allin": "allin",
    "poner": "post",          # "Poner CP" / poner la ciega
    "ante": "post",
}

# Verbos que NO son una accion sino un ESTADO del asiento. Se reconocen para no
# tomarlos por nombre, pero no entran en el historial: "Ausente" no es una
# decision de poker, y meterlo desordenaria la secuencia.
_NO_SON_ACCION = {"ausente", "sentado", "espera"}

# Acciones que meten dinero de forma voluntaria y agresiva. Es lo que hay que
# mirar para saber si el bote esta abierto o subido.
AGRESIVAS = ("bet", "raise", "allin")

# Acciones que consumen una decisión del jugador. ``post`` queda fuera porque
# ciegas y antes no significan que el jugador haya respondido a una subida.
VOLUNTARIAS = frozenset({"check", "call", "bet", "raise", "allin", "fold"})

# PokerStars puede pintar una acción en dos líneas y el OCR devolver primero la
# línea principal y después "All-in". No son dos decisiones: "Subir" ->
# "All-in" e "Igualar" -> "All-in" describen el mismo movimiento.
_ACTUALIZABLES_A_ALLIN = frozenset({"call", "bet", "raise"})


def normalizar(verbo):
    """Texto del nameplate -> accion canonica, o None si no es una accion.

    None cubre dos casos distintos a proposito: que no sea un verbo (es el nick)
    y que sea un estado ("Ausente"). Ninguno de los dos entra en el historial."""
    if not verbo:
        return None
    limpio = "".join(c for c in str(verbo).lower() if c.isalnum())
    if limpio in _NO_SON_ACCION:
        return None
    return _VERBO_A_ACCION.get(limpio)


def estado_preflop(state):
    """Resume la agresión observada en la mano, conservando su ORDEN.

    No intenta completar acciones que el muestreo no vio. Solo transforma
    evidencia positiva del historial:

    * completa ``position`` mediante el asiento estable del GameState;
    * colapsa repeticiones agresivas consecutivas del mismo jugador;
    * distingue una primera subida de una resubida observada;
    * detecta si un rival volvió a agredir después de que actuase el hero.

    El último punto no significa que exista una tabla estratégica para ese
    spot. Significa que el motor ya no puede decir erróneamente "el hero actuó
    y no ha pasado nada después" cuando sí vio la resubida.
    """
    contenedor = state.get("acciones") or {}
    acciones = (contenedor.get("acciones") or []
                if isinstance(contenedor, dict) else contenedor)

    posiciones = {
        p.get("seat"): p.get("position")
        for p in state.get("players") or []
        if p.get("seat") and p.get("position")
    }
    # Una posición capturada antes en la misma mano sigue siendo útil mientras
    # el nameplate muestra el verbo y el frame actual trae position=None.
    for r in acciones:
        if isinstance(r, dict) and r.get("seat") and r.get("position"):
            posiciones.setdefault(r["seat"], r["position"])

    resueltas = []
    for indice, r in enumerate(acciones):
        if not isinstance(r, dict):
            continue
        # Los registros actuales llevan calle. Un bet de flop no puede
        # convertir retrospectivamente un single-raised pot en una "resubida
        # preflop". ``None`` se conserva por compatibilidad con sesiones viejas.
        if r.get("street") not in (None, "preflop"):
            continue
        resueltas.append({
            "indice": indice,
            "orden": r.get("orden"),
            "seat": r.get("seat"),
            "position": r.get("position") or posiciones.get(r.get("seat")),
            "accion": r.get("accion"),
            "t": r.get("t"),
            "street": r.get("street"),
        })

    # FRONTERA DE MANO DENTRO DEL PROPIO LOG. En una transición rápida el
    # tracker puede abrir la mano nueva cuando aún queda un cartel de la
    # anterior. Caso real, sesión 2026-07-31_022832, frame 0311: se registró un
    # "all-in" residual y, dos segundos después, la ciega del HERO. Ese all-in
    # no puede pertenecer al preflop actual porque ocurrió antes de terminar de
    # colocar las ciegas.
    #
    # Si hay timestamps se exige que la acción sea POSTERIOR al último post. Las
    # que tienen exactamente el mismo instante son ambiguas (un frame recorre
    # los asientos en orden espacial, no cronológico) y no se convierten en una
    # agresión cierta. En sesiones antiguas sin ``t`` se usa el orden del log.
    ultimo_post = next(
        (r for r in reversed(resueltas) if r["accion"] == "post"), None)
    ambiguas_arranque = []
    if ultimo_post is None:
        activas = resueltas
    else:
        t_post = ultimo_post.get("t")

        def posterior_al_post(r):
            if isinstance(t_post, (int, float)) and isinstance(r.get("t"), (int, float)):
                return r["t"] > t_post
            return r["indice"] > ultimo_post["indice"]

        activas = [r for r in resueltas if posterior_al_post(r)]
        if isinstance(t_post, (int, float)):
            ambiguas_arranque = [
                r for r in resueltas
                if r["accion"] in AGRESIVAS
                and isinstance(r.get("t"), (int, float))
                and r["t"] == t_post
            ]

    # ActionLog ya deduplica en vivo. Esta segunda barrera hace al consumidor
    # robusto frente a sesiones antiguas: un mismo jugador no puede volver a
    # subir hasta que OTRO haya agredido entre medias. Los folds/calls que haya
    # entre dos lecturas suyas no convierten un cartel repetido en otra subida.
    agresiones = []
    for r in activas:
        if r["accion"] not in AGRESIVAS:
            continue
        if agresiones and agresiones[-1]["seat"] == r["seat"]:
            if r["accion"] == "allin":
                agresiones[-1] = r
            continue
        agresiones.append(r)

    hero = next((r for r in reversed(activas)
                 if r["seat"] == "HERO" and r["accion"] in VOLUNTARIAS), None)
    posterior = None
    if hero is not None:
        posterior = next((
            r for r in agresiones
            if r["indice"] > hero["indice"] and r["seat"] != "HERO"
        ), None)
    callers_entre_hero_y_resubida = {
        r["seat"] for r in activas
        if hero is not None
        and posterior is not None
        and hero["indice"] < r["indice"] < posterior["indice"]
        and r["seat"] not in (None, "HERO")
        and r["accion"] == "call"
    }

    primera = agresiones[0] if agresiones else None
    ultima = agresiones[-1] if agresiones else None
    agresiones_antes_hero = (
        sum(1 for r in agresiones if r["indice"] < hero["indice"])
        if hero is not None else None
    )
    agresiones_hero = sum(1 for r in agresiones if r["seat"] == "HERO")
    # Para distinguir un RFI all-in heads-up de dos spots estratégicamente
    # distintos que se le parecen en una captura aislada:
    #   limp -> shove       (no es un RFI)
    #   shove -> call -> hero (ya es multiway)
    # Solo se cuentan CALL voluntarios de rivales; los folds anteriores o
    # posteriores no cambian el spot y las ciegas/antes son ``post``.
    callers_antes = {
        r["seat"] for r in activas
        if primera is not None
        and r["indice"] < primera["indice"]
        and r["seat"] != "HERO"
        and r["accion"] == "call"
    }
    callers_despues = {
        r["seat"] for r in activas
        if ultima is not None
        and r["indice"] > ultima["indice"]
        and r["seat"] != "HERO"
        and r["accion"] == "call"
    }
    # En un bote todavía sin agresión, cada CALL rival observado es evidencia
    # positiva de un limp aunque el importe visible tarde un frame en pasar de
    # 0,5 a 1 BB. Es exactamente lo que ocurre cuando la SB completa. Se usa la
    # última acción voluntaria por asiento para no contar dos veces un cartel
    # repetido ni conservar a quien después foldeó.
    ultima_voluntaria = {}
    for r in activas:
        if r["seat"] and r["accion"] in VOLUNTARIAS:
            ultima_voluntaria[r["seat"]] = r
    fuera_de_mano = {
        p.get("seat") for p in state.get("players") or []
        if p.get("seat") and p.get("in_hand") is False
    }
    limpers_observados = {
        seat for seat, r in ultima_voluntaria.items()
        if not agresiones
        and seat != "HERO"
        and seat not in fuera_de_mano
        and r["accion"] == "call"
    }
    nivel = ("sin_agresion_observada" if not agresiones else
             "apertura_observada" if len(agresiones) == 1 else
             "resubida_observada")
    return {
        "nivel": nivel,
        "agresiones_observadas": len(agresiones),
        "primera_agresion_seat": primera["seat"] if primera else None,
        "primera_agresion_position": primera["position"] if primera else None,
        "agresiones_antes_hero": agresiones_antes_hero,
        "agresiones_hero": agresiones_hero,
        "ultimo_agresor_seat": ultima["seat"] if ultima else None,
        "ultimo_agresor_position": ultima["position"] if ultima else None,
        "ultima_agresion": ultima["accion"] if ultima else None,
        "hero_ultima_accion": hero["accion"] if hero else None,
        "rival_agresion_posterior_hero": posterior is not None,
        "rival_posterior_seat": posterior["seat"] if posterior else None,
        "rival_posterior_position": posterior["position"] if posterior else None,
        "rival_posterior_accion": posterior["accion"] if posterior else None,
        "callers_entre_hero_y_resubida": len(callers_entre_hero_y_resubida),
        "callers_antes_primera_agresion": len(callers_antes),
        "callers_despues_ultima_agresion": len(callers_despues),
        "limper_seats_observed": sorted(limpers_observados),
        "acciones_antes_del_ultimo_post": (
            len(resueltas) - len(activas) - 1 if ultimo_post is not None else 0),
        "agresion_ambigua_arranque": bool(ambiguas_arranque),
    }


class ActionLog:
    """Secuencia de acciones de la mano en curso. Un objeto por sesion; el
    llamador avisa de las fronteras con nueva_mano().

        log = ActionLog()
        for state in frames:
            if hay_mano_nueva: log.nueva_mano()
            log.observar_estado(state)
    """

    def __init__(self):
        self.mano = 0
        self._acciones = []
        self._ultimo = {}          # asiento -> última acción canónica observada
        self._registro_abierto = {}  # asiento -> evento visible en el nameplate
        self._orden = 0

    def nueva_mano(self):
        self.mano += 1
        self._acciones = []
        self._ultimo = {}
        self._registro_abierto = {}
        self._orden = 0

    def observar(self, seat, verbo, position=None, t=None, street=None,
                 committed_street_bb=None, bet_visible_bb=None, pot_bb=None):
        """Incorpora lo que muestra el nameplate de un asiento. Devuelve la
        accion registrada, o None si no habia nada nuevo que registrar."""
        if not seat:
            return None
        accion = normalizar(verbo)
        anterior = self._ultimo.get(seat)
        self._ultimo[seat] = accion
        if accion is None:
            # Vuelve a verse el nick (o un estado no accionable): el próximo
            # verbo pertenece a otro evento aunque tenga el mismo texto.
            self._registro_abierto.pop(seat, None)
            return None
        if accion == anterior:
            # El lazo rápido suele capturar primero el verbo, sin bote ni
            # comprometido. Si el análisis completo alcanza el mismo cartel,
            # enriquece AQUEL evento; no crea una segunda acción.
            abierto = self._registro_abierto.get(seat)
            if abierto is not None:
                for key, value in (
                        ("position", position),
                        ("street", street),
                        ("committed_street_bb", committed_street_bb),
                        ("bet_visible_bb", bet_visible_bb),
                        ("pot_bb", pot_bb)):
                    if abierto.get(key) is None and value is not None:
                        abierto[key] = value
            return None            # misma acción, aunque el OCR cambie puntuación

        abierto = self._registro_abierto.get(seat)
        if (accion == "allin" and anterior in _ACTUALIZABLES_A_ALLIN
                and abierto is not None):
            abierto["accion"] = "allin"
            abierto["verbo"] = verbo
            for key, value in (
                    ("street", street),
                    ("committed_street_bb", committed_street_bb),
                    ("bet_visible_bb", bet_visible_bb),
                    ("pot_bb", pot_bb)):
                if value is not None:
                    abierto[key] = value
            return abierto

        self._orden += 1
        registro = {"orden": self._orden, "seat": seat, "position": position,
                    "accion": accion, "verbo": verbo, "t": t,
                    "street": street,
                    # Son snapshots, no el incremento exacto de la acción. El
                    # nombre explícito evita convertirlos después en un sizing
                    # inventado si se perdió el frame inmediatamente anterior.
                    "committed_street_bb": committed_street_bb,
                    "bet_visible_bb": bet_visible_bb,
                    "pot_bb": pot_bb}
        self._acciones.append(registro)
        self._registro_abierto[seat] = registro
        return registro

    def observar_estado(self, state, t=None):
        """Incorpora un GameState entero. Devuelve las acciones nuevas."""
        nuevas = []
        for p in state.get("players") or []:
            r = self.observar(
                p.get("seat"), p.get("action"), p.get("position"), t,
                street=state.get("calle_seguida"),
                committed_street_bb=p.get("committed_calle"),
                bet_visible_bb=p.get("bet"),
                pot_bb=state.get("pot"))
            if r is not None:
                nuevas.append(r)
        return nuevas

    def acciones(self):
        """Lo que se ha visto de esta mano, en orden.

        `completo` es SIEMPRE False: el verbo dura menos que el periodo de
        muestreo, asi que no se puede afirmar que no falte ninguna. Se expone el
        campo -en vez de omitirlo- para que quien lo consuma tenga que mirarlo."""
        return {"mano": self.mano, "completo": False,
                "acciones": list(self._acciones)}

    def ultima_agresiva(self):
        """La ultima accion agresiva vista (apuesta, subida o all-in), o None.
        Es lo que dice si el bote esta abierto y por quien."""
        for r in reversed(self._acciones):
            if r["accion"] in AGRESIVAS:
                return r
        return None

    def cuenta(self, accion):
        return sum(1 for r in self._acciones if r["accion"] == accion)

    def resumen(self):
        """Una linea legible para el HUD y el log: 'CO sube · BB paga'."""
        _ES = {"check": "pasa", "call": "paga", "bet": "apuesta", "raise": "sube",
               "fold": "no va", "allin": "all-in", "post": "pone ciega"}
        partes = [f'{r["position"] or r["seat"]} {_ES.get(r["accion"], r["accion"])}'
                  for r in self._acciones]
        return " · ".join(partes)
