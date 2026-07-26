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

DEDUPLICACION. El mismo verbo visible en varios frames seguidos es UNA accion.
Se compara con lo ultimo observado EN ESE ASIENTO, asi que "Subir, Subir, (nick),
Subir" son dos subidas y no una ni cuatro: volver a ver el nick cierra el evento.

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
        self._ultimo = {}          # asiento -> ultimo verbo crudo observado
        self._orden = 0

    def nueva_mano(self):
        self.mano += 1
        self._acciones = []
        self._ultimo = {}
        self._orden = 0

    def observar(self, seat, verbo, position=None, t=None):
        """Incorpora lo que muestra el nameplate de un asiento. Devuelve la
        accion registrada, o None si no habia nada nuevo que registrar."""
        if not seat:
            return None
        anterior = self._ultimo.get(seat)
        self._ultimo[seat] = verbo
        if verbo is None or verbo == anterior:
            return None            # sin cambio: la misma accion que ya se anoto
        accion = normalizar(verbo)
        if accion is None:
            return None
        self._orden += 1
        registro = {"orden": self._orden, "seat": seat, "position": position,
                    "accion": accion, "verbo": verbo, "t": t}
        self._acciones.append(registro)
        return registro

    def observar_estado(self, state, t=None):
        """Incorpora un GameState entero. Devuelve las acciones nuevas."""
        nuevas = []
        for p in state.get("players") or []:
            r = self.observar(p.get("seat"), p.get("action"), p.get("position"), t)
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
