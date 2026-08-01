"""Estabiliza y permite corregir el board entre frames.

Las calles completas requieren persistencia temporal antes de publicarse. Una
lectura parcial conserva su posición mediante ``board_slots`` y no puede
convertirse en una calle más corta. A diferencia del tracker anterior, una
lectura completa que contradice una carta aceptada puede corregirla si vuelve a
aparecer: un primer OCR erróneo ya no congela toda la mano.
"""
from dataclasses import dataclass, field


LONGITUDES_VALIDAS = frozenset((0, 3, 4, 5))
CONFIRMACIONES_POR_DEFECTO = 2


def _board_valido(cartas):
    """Copia un board utilizable o devuelve ``None`` para una lectura dudosa."""
    if not isinstance(cartas, (list, tuple)):
        return None
    cartas = list(cartas)
    if len(cartas) not in LONGITUDES_VALIDAS:
        return None
    if any(not isinstance(carta, str) or len(carta) != 2 for carta in cartas):
        return None
    if len(set(cartas)) != len(cartas):
        return None
    return cartas


def _slots_incompletos(state):
    """Indica si visión encontró cajas que todavía no forman una calle completa."""
    slots = state.get("board_slots")
    if not isinstance(slots, (list, tuple)) or not slots:
        return False
    return any(carta is None for carta in slots)


def _prefijos_observados(state):
    """Devuelve los prefijos de calle completos de este frame.

    Un turn confirma también las tres primeras cartas del flop y un river
    confirma flop y turn. Los slots permiten aprovechar esos prefijos incluso
    cuando la última carta todavía es ``None``.
    """
    slots = state.get("board_slots")
    if isinstance(slots, (list, tuple)) and slots:
        slots = list(slots)
        if len(slots) not in LONGITUDES_VALIDAS - {0}:
            return None
        conocidas = [c for c in slots if c is not None]
        if (any(not isinstance(c, str) or len(c) != 2 for c in conocidas)
                or len(set(conocidas)) != len(conocidas)):
            return None
    else:
        board = _board_valido(state.get("board") or [])
        if board is None:
            return None
        slots = board

    prefijos = []
    for longitud in sorted(LONGITUDES_VALIDAS - {0}):
        if longitud > len(slots):
            continue
        prefijo = slots[:longitud]
        if any(carta is None for carta in prefijo):
            continue
        valido = _board_valido(prefijo)
        if valido is not None:
            prefijos.append(valido)
    return prefijos


@dataclass
class BoardTracker:
    """Confirma calles completas y corrige lecturas persistentes.

    El primer prefijo necesita persistencia temporal. Una vez confirmado, una
    sola carta nueva se acepta si todo el prefijo coincide: turn y river solo
    añaden un slot y esperar otro frame haría perderlos en runouts rápidos. Una
    corrección de cualquier slot ya existente sigue necesitando el número de
    confirmaciones configurado.
    """
    confirmaciones: int = CONFIRMACIONES_POR_DEFECTO
    _mano: int | None = field(init=False, default=None)
    _aceptado: list[str] = field(init=False, default_factory=list)
    _pendientes: dict[int, tuple[list[str], int]] = field(
        init=False, default_factory=dict)
    _candidatos_slot: dict[int, tuple[str, int]] = field(
        init=False, default_factory=dict)

    def __post_init__(self):
        if (isinstance(self.confirmaciones, bool)
                or not isinstance(self.confirmaciones, int)
                or self.confirmaciones < 1):
            raise ValueError("confirmaciones debe ser un entero positivo")

    def aplicar(self, state, mano):
        """Normaliza ``state['board']`` in situ y devuelve el board publicado."""
        if mano != self._mano:
            self._mano = mano
            self._aceptado = []
            self._limpiar_pendiente()
            self._candidatos_slot.clear()

        incompleto = _slots_incompletos(state)
        state_fusionado, prefijos_confirmados_por_slot = self._fusionar_slots(state)
        prefijos = _prefijos_observados(state_fusionado)
        aviso = None
        if prefijos is None:
            self._limpiar_pendiente()
            aviso = "board: lectura inválida; se conserva el último board confirmado"
        elif not prefijos:
            self._limpiar_pendiente()
            if self._aceptado:
                aviso = "board: lectura transitoria; se conserva el último board confirmado"
        else:
            confirmados = []
            for prefijo in prefijos:
                longitud = len(prefijo)
                previo, vistas = self._pendientes.get(longitud, ([], 0))
                vistas = vistas + 1 if previo == prefijo else 1
                self._pendientes[longitud] = (prefijo, vistas)
                if (vistas >= self.confirmaciones
                        or longitud in prefijos_confirmados_por_slot):
                    confirmados.append(prefijo)

            candidatos = [p for p in confirmados if len(p) >= len(self._aceptado)]
            if candidatos:
                elegido = max(candidatos, key=len)
                self._aceptado = list(elegido)
                for longitud in list(self._pendientes):
                    if longitud <= len(self._aceptado):
                        del self._pendientes[longitud]

            # Turn y river añaden UNA sola carta. Si el prefijo completo ya está
            # confirmado, aceptar el nuevo slot mantiene la protección sobre las
            # cartas existentes sin retrasar la calle hasta que ya haya avanzado.
            observado = max(prefijos, key=len)
            if (self._aceptado
                    and len(observado) == len(self._aceptado) + 1
                    and observado[:len(self._aceptado)] == self._aceptado):
                self._aceptado = list(observado)
                for longitud in list(self._pendientes):
                    if longitud <= len(self._aceptado):
                        del self._pendientes[longitud]

            hay_novedad = any(
                len(p) > len(self._aceptado)
                or (len(p) == len(self._aceptado) and p != self._aceptado)
                for p in prefijos
            )
            if hay_novedad:
                aviso = "board: lectura nueva pendiente de confirmación"
            elif incompleto:
                aviso = "board: calle incompleta; se conserva el último board confirmado"

        state["board"] = list(self._aceptado)
        if aviso:
            warnings = state.setdefault("warnings", [])
            if aviso not in warnings:
                warnings.append(aviso)
        return state["board"]

    def _limpiar_pendiente(self):
        self._pendientes.clear()

    def _fusionar_slots(self, state):
        """Completa huecos solo con lecturas repetidas de la misma casilla.

        Un ``None`` no borra lo visto: precisamente representa una carta cuya
        caja existe pero cuyo rango no se pudo resolver en este frame. Una
        contradicción sí reinicia el contador de esa posición. La fusión queda
        acotada a la mano porque ``aplicar`` vacía los candidatos al cambiar
        ``mano``.
        """
        slots = state.get("board_slots")
        if not isinstance(slots, (list, tuple)) or not slots:
            return state, set()
        slots = list(slots)
        if len(slots) not in LONGITUDES_VALIDAS - {0}:
            return state, set()

        conocidas = [c for c in slots if c is not None]
        if (any(not isinstance(c, str) or len(c) != 2 for c in conocidas)
                or len(set(conocidas)) != len(conocidas)):
            return state, set()

        for posicion, carta in enumerate(slots):
            if carta is None:
                continue
            previa, vistas = self._candidatos_slot.get(posicion, (carta, 0))
            self._candidatos_slot[posicion] = (
                carta,
                vistas + 1 if previa == carta else 1,
            )

        fusionados = list(slots)
        for posicion, carta in enumerate(fusionados):
            if carta is not None:
                continue
            candidata = self._candidatos_slot.get(posicion)
            if candidata is not None and candidata[1] >= self.confirmaciones:
                fusionados[posicion] = candidata[0]

        # Nunca se fabrica un duplicado al mezclar observaciones: se deja el
        # frame original para que la validación normal se abstenga.
        conocidas = [c for c in fusionados if c is not None]
        if len(set(conocidas)) != len(conocidas):
            return state, set()
        prefijos_confirmados = {
            longitud
            for longitud in LONGITUDES_VALIDAS - {0}
            if longitud <= len(fusionados)
            and all(fusionados[i] is not None for i in range(longitud))
            and all(self._candidatos_slot.get(i, (None, 0))[1] >= self.confirmaciones
                    for i in range(longitud))
        }
        return dict(state, board_slots=fusionados), prefijos_confirmados
