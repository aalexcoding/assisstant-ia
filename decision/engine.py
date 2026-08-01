"""
Fase 4 (primera pieza): motor de decision. Toma el GameState que produce
vision/table_state.py (analyze_layout(), la ruta de produccion) y, si hay
datos suficientes, devuelve una recomendacion consultando
decision/preflop/lookup.py.

decide() solo recomienda ACCION en preflop: no hay rango postflop digitalizado,
asi que con board no devuelve accion. Lo que si hay postflop es equity estimada
por simulacion, en postflop_equity(), deliberadamente separado: es una
probabilidad, no una decision.

Defensa contra una subida ajena (facing="threebet_call"): si el GameState
trae facing="bet" (hay un boton "Igualar/Pagar", asi que hay una apuesta que
enfrentar) y a partir del importe apostado por asiento (table_state /
seat_map.detect_raiser) se identifica UNA sola subida clara -un unico rival
con apuesta por encima de la ciega grande-, se consulta el rango de defensa
con vs_position = la posicion de ese raiser. Cuando el importe de la mesa no
se lee -que es el caso mayoritario- se intenta ATRIBUIR la subida por la
bajada de stack del rival entre frames (decision/hand_tracker.py), pero solo
si el boton "Igualar" ya ha demostrado que la subida existe.

Conservador por diseño: si hay varias apuestas por encima de la ciega
(bote multiway o 3bet ya presente), si el propio hero ya ha subido (enfrenta
una resubida), o si el raiser no tiene posicion asignada, NO se adivina ->
se abstiene con un warning (una defensa contra la posicion equivocada es
peor que ninguna). Si no hay ninguna subida (solo ciegas/limps, o no hay
apuesta que enfrentar) se sigue con open_raise como antes: el hero abre.

Limitaciones aceptadas: solo se cubre la subida unica heads-up (el rango
threebet_call solo tiene 10/15/20/25/30/35/40bb; por debajo de 10bb NO se
abstiene -como decia antes este docstring, y era falso- sino que
lookup._nearest_stack_key redondea a la clave mas cercana y se avisa, ver
_stack_key_note); en frames de transicion entre manos el cliente puede
mostrar importes de una mano ya resuelta -no se distingue de una subida en
curso con una sola imagen-; y sigue sin registrarse el historial de apuestas
de la calle, asi que el juicio es sobre lo que hay dibujado en ese frame.

Se importa como paquete (`from decision import engine`) con la raiz del
proyecto en sys.path. Antes cada caller tenia que meter decision/ y
decision/preflop/ a mano; ya no.

BB-ONLY. La app trabaja con el cliente configurado para mostrar los importes
en BIG BLINDS, y solo con eso: el stack leido YA ES la profundidad en bb, asi
que se usa directamente como stack_bb, NO hacen falta ciegas (ni detectadas
ni manuales) y una subida es simplemente cualquier importe > 1.

Se intento soportar tambien el modo FICHAS, detectando la unidad frame a
frame, y no funciono: medido sobre una sesion real de 34 min, la unidad
detectada oscilaba DENTRO de la misma sesion (bbx30, chipsx17, bbx24,
chipsx37) aunque la config del cliente no habia cambiado. El fallo que eso
produce es el peor posible aqui -dividir por la ciega una profundidad que ya
estaba en bb, o leer 3955 fichas como 3955bb: una recomendacion con
conviccion y falsa-. Con las ciegas manuales pasaba algo parecido por otra
via: blinds.local.json no caducaba solo y en torneo el nivel sube cada pocos
minutos, asi que unas ciegas viejas daban una profundidad inflada sin que
nada lo delatara.

La salida no fue detectar mejor, sino no tener que detectar. state["stack_unit"]
sigue existiendo como GUARDA, no como interruptor: analyze_layout() lo pone a
"bb" literal y las rutas de diagnostico (analyze/analyze_color_deck), cuyos
stacks son enteros de fichas, no lo declaran. decide() rechaza cualquier
GameState que no diga "bb", asi que esa clase de fallo no puede existir.

Profundidad fuera de rejilla: lookup._nearest_stack_key redondea a la clave de
stack mas cercana sin limite, asi que a 100bb (principio de torneo) devuelve el
rango de 40bb -el maximo digitalizado- como si fuera el del spot. _stack_key_note
distingue dos casos contra la rejilla REAL de cada familia (_stack_grid, leida de
los propios datos): si la profundidad cae ENTRE dos claves que existen es una
interpolacion y se nombra la tabla usada y la vecina; si cae FUERA de la tabla es
una extrapolacion y ademas se avisa. En los dos casos se sigue recomendando
-es la mejor referencia disponible- pero no se presenta como exacta.

Cache del stack del hero: cuando es el turno del hero, su nameplate deja
de mostrar el numero de fichas y muestra la accion ("Igualar X", "All-in",
"Ganado"...) o lo tapan los botones -es decir, el stack desaparece de
pantalla justo en el momento en que se quiere recomendar. Se cachea el
ultimo stack leido (visible unos frames antes, cuando aun no era el turno)
y se reutiliza si el frame actual no lo trae, mientras sea reciente
(_HERO_STACK_TTL_S) Y SEA DE LA MISMA MANO. Dentro de una mano es una
aproximacion buena -el stack casi no se mueve, lo que cambia es lo puesto en el
bote- y para elegir el rango preflop por profundidad basta. Cruzando la frontera
de mano no: ahi has ganado o perdido el bote, o han subido las ciegas, y medido
sobre las 6 sesiones grabadas la cache de una mano anterior se equivoca en mas
del 15% el 62,3% de las veces (la de la misma mano, el 33,6%). Se anota en el
reasoning cuando se usa; ver _cached_hero_stack.
"""
import time
import statistics
from dataclasses import dataclass, field

from domain.state import GameState, Recommendation

from decision import action_log
from decision import equity
from decision import hand_tracker
from decision import journal
from decision import postflop_math

from decision.preflop.actions import translate_into
from decision.preflop.derive import bb_option, squeeze, vs_limp
from decision.preflop import bb_multi_limp, lookup, open_push, rangeconverter
from decision.preflop.lookup import recommend

_HERO_STACK_TTL_S = 90.0


@dataclass
class DecisionContext:
    """Memoria efimera de una sola sesion de analisis."""
    last_hero_stack: dict = field(
        default_factory=lambda: {
            "value": None,
            "starting_value": None,
            "t": 0.0,
            "mano": None,
        })
    player_starting_stacks: dict = field(
        default_factory=lambda: {"mano": None, "samples": {}})

    def reset(self):
        self.last_hero_stack.update(
            value=None, starting_value=None, t=0.0, mano=None)
        self.player_starting_stacks.update(mano=None, samples={})


# Compatibilidad para llamadas directas a decide(). El ciclo real recibe un
# contexto propio desde core.Analizador.
_DEFAULT_CONTEXT = DecisionContext()


def reset_state():
    """Olvida el stack cacheado del hero.

    ESTO ES ESTADO GLOBAL ENTRE LLAMADAS, y por eso hace falta poder tirarlo: sin
    esto, un test que deja un stack en la cache cambia el resultado del siguiente
    -decide() lo reutilizaria como si fuera de este frame- y la suite pasa a
    depender del orden. En produccion no se llama: la cache es justo lo que salva
    la recomendacion cuando el nameplate del hero se tapa con los botones."""
    _DEFAULT_CONTEXT.reset()

# La ciega grande vale 1 POR DEFINICION: los importes vienen en big blinds. Se
# nombra en vez de escribir 1 suelto para que se lea que es una unidad, no una
# constante magica.
BB = 1

# tolerancia (en bb) para considerar que la profundidad COINCIDE con una clave de
# la tabla. Por debajo de esto no se dice nada; por encima se nombra la tabla
# vecina, para que el usuario sepa que su profundidad cae entre dos de sus
# gráficos y cual se uso.
_STACK_KEY_EXACT_TOL = 0.25

# Un umbral FIJO no servia. Antes habia un solo _STACK_KEY_FAR_BB = 2.6 y no
# distinguia dos situaciones muy distintas:
#   - INTERPOLACION: la profundidad cae ENTRE dos claves que si existen (22,7bb
#     entre 20 y 25). El rango sale de una tabla real suya, solo que de la vecina.
#   - EXTRAPOLACION: la profundidad cae FUERA de la tabla (>40bb, todo el
#     principio de torneo; o <4bb). Ahi el rango devuelto NO es su rango para ese
#     spot y hay que avisar de verdad.
# Ademas el umbral fijo tenia un agujero: las claves de threebet_call son
# 10/15/20/25/30/35/40, asi que una defensa a 12,5bb queda a 2,5bb de la clave de
# 10 y 2,5 < 2,6 -> se servia el grafico de 10bb SIN NINGUN AVISO. Y 12,5bb si es
# una profundidad digitalizada en open_raise, asi que el hueco era invisible.
# Ahora el juicio se hace contra la rejilla REAL de cada familia (_stack_grid).


def _committed_bb(player, *, max_allowed=None):
    """Mejor lectura disponible de lo que un jugador ya puso en la mano.

    ``committed``/``committed_calle`` vienen de la bajada de stack entre
    frames; ``bet`` se lee directamente sobre la mesa. Las dos primeras son una
    cota inferior cuando el tracker entró tarde en la mano, por lo que se usa el
    máximo de las fuentes válidas, no su suma.
    """
    values = [
        player.get(field)
        for field in ("committed", "committed_calle", "bet")
        if player and isinstance(player.get(field), (int, float))
    ]
    if max_allowed is not None:
        values = [value for value in values if 0 <= float(value) <= max_allowed]
    return max([0.0, *map(float, values)])


def _cached_hero_stack(hero, mano=None, context=None):
    """Stack del hero en bb, con cache reciente: cuando es su turno el nameplate
    deja de mostrar el numero (muestra la accion, o lo tapan los botones), o sea
    que el stack desaparece de pantalla JUSTO en el momento en que hace falta
    recomendar. Devuelve (valor, cacheado).

    LA CACHE NO CRUZA LA FRONTERA DE MANO. En una mano el stack casi no se mueve
    -lo que cambia es lo que has puesto en el bote- pero ENTRE manos si: has
    ganado el bote, lo has perdido, o han subido las ciegas y con ellas la unidad
    en la que se cuenta todo. Medido sobre las 6 sesiones grabadas, comparando lo
    que la cache habria servido contra la siguiente lectura de verdad:

        cache de ESTA mano       n=1.926   error p50  1,8%   se pasa del 15%: 33,6%
        cache de mano ANTERIOR   n=1.257   error p50 18,4%   se pasa del 15%: 62,3%

    O sea que cruzando la frontera MIENTE LA MAYORIA DE LAS VECES. Y no miente en
    algo cosmetico: la profundidad elige la tabla preflop, y sus claves van de 5
    en 5 bb, asi que un 15% de error a 25bb basta para servir el grafico de otra
    profundidad con toda la confianza. Callar es mejor que eso.

    EL PLAN PEDIA OTRA COSA y se cambio con el dato delante: decia caducar "solo
    si no baja el numero de recomendaciones". Baja -el 9,3% de los frames tiran
    de cache de una mano anterior- pero ese criterio media lo que no era. Una
    recomendacion calculada sobre una profundidad que ya no existe no es una
    recomendacion ganada, es una equivocada.

    Si no hay numero de mano (`mano is None`) no se puede saber si se cruzo la
    frontera y solo manda el TTL, que es como se comportaba antes. Pasa en los
    tests que llaman a decide() con un GameState a mano, no en produccion."""
    cache = (context or _DEFAULT_CONTEXT).last_hero_stack
    val = hero.get("stack") if hero else None
    if val is not None:
        cache.update(
            value=val,
            # decide() llega aquí antes de la primera acción voluntaria del hero.
            # Por tanto solo puede haber ciegas/ante. Un ``committed`` mayor de
            # 2 BB es una frontera de mano perdida (caso real: 40 BB residuales
            # en 011143/0031), no una inversión de esta decisión.
            starting_value=float(val) + _committed_bb(
                hero, max_allowed=_BB_POSTED_MAX_MULT),
            t=time.monotonic(),
            mano=mano,
        )
        return val, False
    if cache["value"] is None:
        return None, False
    if time.monotonic() - cache["t"] > _HERO_STACK_TTL_S:
        return None, False
    if (mano is not None and cache["mano"] is not None
            and mano != cache["mano"]):
        return None, False
    return cache["value"], True


def _hero_starting_stack(hero, mano=None, context=None):
    """Stack del hero al empezar la mano, conservado de forma coherente.

    El cliente muestra el stack *restante*. Para seleccionar una tabla preflop
    hay que sumar lo ya comprometido. Cuando el nameplate se tapa no se suma el
    comprometido actual a un stack cacheado antiguo —eso lo contaría dos
    veces—: se reutiliza el total que se calculó en el mismo instante que la
    lectura de stack.
    """
    remaining, cached = _cached_hero_stack(hero, mano, context)
    if remaining is None:
        return None, cached
    cache = (context or _DEFAULT_CONTEXT).last_hero_stack
    if cached:
        return cache.get("starting_value"), True
    return float(remaining) + _committed_bb(
        hero, max_allowed=_BB_POSTED_MAX_MULT), False


def _player_starting_stack(player):
    """Stack inicial visible de un rival, o None si falta su stack restante."""
    if not player or not isinstance(player.get("stack"), (int, float)):
        return None
    return float(player["stack"]) + _committed_bb(player)


def _observe_player_starting_stacks(players, mano=None, context=None):
    """Cache robusta por asiento del stack inicial observado en esta mano."""
    cache = (context or _DEFAULT_CONTEXT).player_starting_stacks
    if mano is not None and cache.get("mano") != mano:
        cache.update(mano=mano, samples={})
    for player in players or []:
        seat = player.get("seat")
        value = _player_starting_stack(player)
        if not seat or value is None:
            continue
        samples = cache.setdefault("samples", {}).setdefault(seat, [])
        samples.append(float(value))
        del samples[:-5]


def _cached_player_starting_stack(seat, mano=None, context=None):
    if not seat:
        return None
    cache = (context or _DEFAULT_CONTEXT).player_starting_stacks
    if (mano is not None and cache.get("mano") is not None
            and cache.get("mano") != mano):
        return None
    samples = cache.get("samples", {}).get(seat) or []
    return float(statistics.median(samples)) if samples else None


def _effective_stack_vs(
        players, hero_starting_bb, *, seat=None, position=None,
        mano=None, context=None):
    """Profundidad efectiva hero-agresor y procedencia de la lectura.

    Se prioriza el asiento estable porque una posición puede estar ausente en
    el frame donde aparece el verbo. Si no se puede leer el stack del agresor,
    se conserva el stack inicial del hero y se declara el fallback: inventar un
    stack rival sería peor que seguir usando la cota conocida.
    """
    rival = None
    if seat:
        rival = next(
            (p for p in players or [] if p.get("seat") == seat
             and not p.get("is_hero")),
            None,
        )
    if rival is None and position:
        rival = next(
            (p for p in players or [] if p.get("position") == position
             and not p.get("is_hero")),
            None,
        )
    rival_starting = _player_starting_stack(rival)
    if rival_starting is None:
        rival_starting = _cached_player_starting_stack(
            seat or (rival or {}).get("seat"), mano, context)
    if rival_starting is None:
        return hero_starting_bb, None
    return min(float(hero_starting_bb), rival_starting), rival_starting


# ver seat_map.BB_POSTED_MAX_MULT: la apuesta del asiento BB es ciega + ante
# (obligatorio), no una subida, hasta este multiplo de la ciega grande.
_BB_POSTED_MAX_MULT = 2.0

# Cuantas cartas de board tiene que haber en cada calle. Sirve para contrastar
# las dos lecturas independientes que hay del avance de la mano: contar cartas en
# el frame y el rastreo a lo largo de la mano (hand_tracker.calle_seguida).
_CARTAS_POR_CALLE = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}


def _detect_raiser(players, bb):
    """Gemelo de seat_map.detect_raiser, reimplementado aqui para no acoplar el
    motor a vision/ (cv2): con el importe apostado por asiento y la ciega
    grande EFECTIVA, decide si hay una subida unica que enfrentar. Devuelve
    (vs_position, code) con code en {single, no_raise, multiway, hero_raised,
    bb_raised, raiser_no_pos, no_bb}. Ver seat_map.detect_raiser para el detalle
    y para por que el asiento BB se trata aparte (BB-ante)."""
    if not bb:
        return None, "no_bb"
    above = [p for p in players
             if isinstance(p.get("bet"), (int, float)) and p["bet"] > bb]
    if any(p.get("is_hero") for p in above):
        return None, "hero_raised"
    opp = [p for p in above if not p.get("is_hero")]
    bb_seat = [p for p in opp if p.get("position") == "BB"]
    if bb_seat and any(p["bet"] > bb * _BB_POSTED_MAX_MULT for p in bb_seat):
        return None, "bb_raised"
    opp = [p for p in opp if p.get("position") != "BB"]
    if not opp:
        return None, "no_raise"
    if len(opp) > 1:
        return None, "multiway"
    pos = opp[0].get("position")
    if pos is None:
        return None, "raiser_no_pos"
    return pos, "single"


_STACK_GRID_CACHE = {}


def _stack_grid(facing):
    """Claves de profundidad (float, ordenadas) que existen de verdad en la tabla
    de ese facing. Se lee de lookup.RANGES para que la rejilla nunca se desincronice
    con los datos: open_raise tiene 4/6/8/10/12.5/15/20/25/30/35/40 y threebet_call
    solo 10/15/20/25/30/35/40 (no hay defensa digitalizada por debajo de 10bb)."""
    if facing not in _STACK_GRID_CACHE:
        _STACK_GRID_CACHE[facing] = sorted(float(k) for k in lookup.RANGES.get(facing, {}))
    return _STACK_GRID_CACHE[facing]


def _stack_key_note(result, stack_bb, facing, warnings):
    """Devuelve una nota para el reasoning segun donde cae la profundidad real
    respecto a la rejilla de SU tabla, y avisa en warnings solo cuando toca.

    lookup._nearest_stack_key redondea a la clave mas cercana SIN limite, asi que
    hay que distinguir dos casos que antes se trataban igual:

      - EXTRAPOLACION (fuera de la rejilla): con 100bb devuelve el rango de 40bb
        como si fuera el del spot. El rango NO es el suyo para esa profundidad ->
        warning + nota visible.
      - INTERPOLACION (entre dos claves que si existen): 22,7bb sale del grafico de
        25bb, que es una tabla real suya. No es un error, es la resolucion de la
        rejilla -> se nombra la tabla usada y la vecina, sin ensuciar warnings."""
    key = result.get("stack_key")
    if key is None:
        return ""
    grid = _stack_grid(facing)
    if not grid:
        return ""

    lo, hi = grid[0], grid[-1]
    if stack_bb > hi + _STACK_KEY_EXACT_TOL or stack_bb < lo - _STACK_KEY_EXACT_TOL:
        borde = hi if stack_bb > hi else lo
        warnings.append(f"profundidad {stack_bb:.1f}bb FUERA de tu tabla de {facing} "
                        f"(cubre {lo:g}-{hi:g}bb): la accion sale del grafico de "
                        f"{borde:g}bb, no es tu rango para {stack_bb:.1f}bb")
        return (f" [OJO: extrapolado del rango de {borde:g}bb; tu tabla solo cubre "
                f"{lo:g}-{hi:g}bb]")

    if abs(stack_bb - key) <= _STACK_KEY_EXACT_TOL:
        return ""

    vecinas = [k for k in grid if k != key]
    vecina = min(vecinas, key=lambda k: abs(k - stack_bb)) if vecinas else None
    if vecina is None:
        return ""
    return (f" [interpolado: se usa tu grafico de {key:g}bb; el de {vecina:g}bb "
            f"queda a {abs(vecina - stack_bb):.1f}bb]")


# Margen para reconocer a un rival que ha ENTRADO PAGANDO (limp, o la SB
# completando): su importe queda en una ciega grande. Ancho por los dos lados
# porque en torneo con BB-ante el importe puede pasar algo de 1 y porque el OCR
# de un importe en BB da una decimal.
_LIMP_MIN_BB = 0.75
_LIMP_MAX_BB = 1.35


def _asientos_que_solo_pusieron(acciones):
    """Asientos cuya ULTIMA accion vista es 'post' (poner ciega o ante).

    Poner la ciega NO es entrar pagando: es obligatorio. El cliente lo dice con
    todas las letras -escribe "Poner" en el nameplate, distinto de "Igualar"- y
    la vigilancia rapida lo captura (ver vision/seat_watch.py). Esa evidencia
    estaba guardandose y nadie la miraba.

    ASIMETRIA DELIBERADA, la misma que en _agresor_del_log y en atribuir_subida:
    solo se usa la PRESENCIA de un 'post', nunca la AUSENCIA de un 'call'. El
    historial viene siempre con completo=False -el verbo dura menos de 1,5 s y
    solo se ve lo que se muestrea-, asi que exigir un 'call' para creerse un limp
    haria perder limpers de verdad. Ver un 'post' si es prueba positiva de que ese
    importe es una ciega."""
    ultima = {}
    for r in (acciones or {}).get("acciones") or []:
        if r.get("seat") and r.get("accion"):
            ultima[r["seat"]] = r["accion"]
    return {s for s, a in ultima.items() if a == "post"}


def _contar_limpers(players, acciones=None, secuencia=None):
    """Cuantos rivales han ENTRADO PAGANDO voluntariamente. 0 si el bote no esta
    limpeado, None si no se pudo saber.

    Dos reglas que parecen detalles y no lo son. Medido sobre una sesion real, sin
    ellas la capa derivada disparaba "subir sobre los limpers" en 45 frames y en
    LOS 45 el bote estaba en realidad SUBIDO: una recomendacion con pinta de buena
    para un spot que no era ese.

    1. LA CIEGA GRANDE NO ES UN LIMPER. Su 1bb es obligatorio, no una decision.
       Contarla como limper corria la fila donante un asiento de mas SIEMPRE, en
       todas las manos. Se le permite hasta _BB_POSTED_MAX_MULT porque en torneo
       con BB-ante su importe es ciega + ante (igual que en _detect_raiser).

       Esa regla mira la ETIQUETA de posicion, y por eso no basta: si la posicion
       sale corrida, la ciega grande real no se llama "BB" y su importe vuelve a
       parecer un limp. Paso de verdad -el usuario lo anoto en vivo el 2026-07-27,
       frame 0462 de la sesion 220231-: era BTN con Kc5s a 26,5bb, la BB real
       estaba etiquetada MP2, su 1,1bb obligatorio conto como limp y el motor
       sirvio el rango de CO en vez del de BTN y dijo FOLD. El historial de
       acciones de ese mismo frame no tenia ni un solo "Igualar": tenia "Poner"
       en los dos asientos de las ciegas. Por eso se cruza con el log, que es
       evidencia INDEPENDIENTE de la etiqueta de posicion.
    2. SI ALGUIEN HA PUESTO MAS QUE UNA CIEGA, EL BOTE NO ESTA LIMPEADO, esta
       subido, y "subir sobre los limpers" no es el spot. Se devuelve 0 para que
       la capa derivada no se dispare y el motor siga por donde iba.

    Se mira el importe leido en la mesa y, si no hay agresión, se une por asiento
    con los CALL positivos del historial vigente. Esto cubre la SB que ya mostró
    ``Igualar`` pero cuyo importe aún sigue en 0,5 BB. Devolver None cuando
    ninguna fuente vio nada importa: no es lo mismo "he mirado y no hay limpers"
    que "no he podido mirar"."""
    if secuencia is None and acciones:
        secuencia = action_log.estado_preflop({
            "players": players,
            "acciones": acciones,
        })
    if (secuencia
            and secuencia.get("nivel") != "sin_agresion_observada"):
        return 0
    limpers_log = set(
        (secuencia or {}).get("limper_seats_observed") or [])
    solo_pusieron = _asientos_que_solo_pusieron(acciones)
    visto = False
    n = 0
    contados = set()
    for p in players:
        if p.get("is_hero"):
            continue
        v = p.get("bet")
        if not isinstance(v, (int, float)):
            v = p.get("committed_calle")
        if not isinstance(v, (int, float)):
            continue
        visto = True
        # el log manda sobre la etiqueta: si lo ultimo que se le vio hacer fue
        # PONER, ese importe es una ciega o un ante, no una entrada voluntaria
        es_bb = p.get("position") == "BB" or p.get("seat") in solo_pusieron
        tope = BB * _BB_POSTED_MAX_MULT if es_bb else _LIMP_MAX_BB
        if v > tope:
            return 0                     # el bote esta SUBIDO, no limpeado
        if not es_bb and _LIMP_MIN_BB <= v <= _LIMP_MAX_BB:
            n += 1
            identidad = p.get("seat") or p.get("position")
            if identidad:
                contados.add(identidad)
    # El historial es una fuente positiva, no una exigencia: añade calls que el
    # importe todavía no refleja, pero nunca borra limpers visibles por el mero
    # hecho de que el muestreo no capturase su verbo.
    n += len(limpers_log - contados)
    return n if visto or limpers_log else None


# Orden en que se habla PREFLOP, de primero a ultimo. Es universal: las ciegas
# hablan las ultimas porque ya tienen dinero puesto.
_ORDEN_PREFLOP = ("EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB")


def _habla_antes(a, b):
    """True si la posicion a habla ANTES que b en preflop."""
    if a not in _ORDEN_PREFLOP or b not in _ORDEN_PREFLOP:
        return True          # sin poder juzgarlo, no se bloquea nada
    return _ORDEN_PREFLOP.index(a) < _ORDEN_PREFLOP.index(b)


def _contar_callers(players, vs_position):
    """Rivales, aparte del raiser, que ya han metido mas que la ciega grande: han
    PAGADO la subida. Es lo que convierte una defensa normal en un squeeze.

    ``committed_calle`` guarda solo lo añadido durante la calle. Para la SB que
    paga una apertura a 2 BB son exactamente 1,5 BB (las otras 0,5 ya estaban
    puestas), por lo que el límite es inclusivo. Usar ``> 1.5`` ocultó el caller
    real de la sesión 2026-07-31_020108/0352 y dejó pasar una defensa heads-up."""
    n = 0
    for p in players:
        if p.get("is_hero") or p.get("position") == vs_position:
            continue
        v = p.get("committed_calle")
        if not isinstance(v, (int, float)):
            v = p.get("bet")
        if isinstance(v, (int, float)) and v >= BB * 1.5:
            n += 1
    return n


def _hero_player(state):
    for p in state.get("players", []):
        if p.get("is_hero"):
            return p
    return None


def _player_by_seat_or_position(players, seat=None, position=None):
    """Jugador del agresor, priorizando el asiento (estable dentro de la mano)."""
    if seat is not None:
        found = next((p for p in players if p.get("seat") == seat), None)
        if found is not None:
            return found
    if position is not None:
        return next((p for p in players if p.get("position") == position), None)
    return None


def _ante_total_bb(players):
    """Ante total visible a partir de lo puesto por la BB, o None.

    En los torneos con BB-ante que reconoce esta app, el asiento BB muestra
    ``ciega (1 BB) + ante``. Esta misma representación ya se usa en
    ``_detect_raiser`` para no confundir sus 2 BB obligatorias con una subida.
    Exigir la lectura evita aplicar una tabla con ante de 1 BB a una estructura
    sin ante o a un frame donde ese supuesto no se puede comprobar.
    """
    bb = next((p for p in players if p.get("position") == "BB"), None)
    if bb is None:
        return None
    puesto = bb.get("bet")
    if not isinstance(puesto, (int, float)):
        puesto = bb.get("committed_calle")
    if not isinstance(puesto, (int, float)) or puesto < BB:
        return None
    return max(0.0, float(puesto) - BB)


def _open_shove_amount(state, secuencia, hero, to_call):
    """Importe total del primer all-in, solo con evidencia del estado actual."""
    players = state.get("players") or []
    rival = _player_by_seat_or_position(
        players,
        secuencia.get("ultimo_agresor_seat"),
        secuencia.get("ultimo_agresor_position"),
    )
    amount = rival.get("bet") if rival else None
    if not isinstance(amount, (int, float)) and rival is not None:
        amount = rival.get("committed_calle")
    if isinstance(amount, (int, float)):
        return float(amount)

    # El botón da lo que FALTA por poner. Sumado a lo que el hero ya tiene
    # delante reconstruye el total que hay que igualar; no se usa si falta
    # cualquiera de las dos piezas.
    hero_put = hero.get("bet") if hero else None
    if not isinstance(hero_put, (int, float)) and hero is not None:
        hero_put = hero.get("committed_calle")
    if isinstance(to_call, (int, float)) and isinstance(hero_put, (int, float)):
        return float(to_call + hero_put)
    return None


def _agresor_del_log(state):
    """Quien subio, segun el HISTORIAL DE ACCIONES (los verbos del nameplate), o
    None. Es la unica señal capaz de distinguir al que SUBE del que PAGA cuando
    los dos tienen el mismo importe puesto -que es exactamente lo que pasa en un
    squeeze- porque el importe, por definicion, coincide.

    Se exige CORROBORACION: la posicion que da el log tiene que ser una de las que
    tienen el importe mas alto en la mesa. Son dos fuentes independientes (OCR del
    nameplate vs OCR de la zona de apuesta), y sin ese cruce una sola lectura mala
    del verbo elegiria el rango de defensa equivocado."""
    secuencia = state.get("preflop_action") or action_log.estado_preflop(state)
    agresor = secuencia.get("ultimo_agresor_position")
    if agresor is None:
        return None
    apuestas = [(p.get("position"), p.get("bet")) for p in state.get("players") or []
                if not p.get("is_hero") and isinstance(p.get("bet"), (int, float))]
    if not apuestas:
        return None
    tope = max(v for _p, v in apuestas)
    if agresor not in [p for p, v in apuestas if v >= tope - 0.05]:
        return None                    # el log y la mesa no coinciden: no se elige
    return agresor


def _hay_que_igualar(state):
    """Importe (>1bb) que el boton "Igualar" esta pidiendo, o None.

    Es la evidencia INDEPENDIENTE de que hay una subida enfrente: el propio
    cliente pidiendo dinero. Solo se usa para ABSTENERSE o para disparar la
    atribucion, nunca para construir una recomendacion -ver el docstring de
    seat_map.parse_to_call_bb-."""
    v = state.get("to_call")
    return v if isinstance(v, (int, float)) and v > BB else None


def _log_dice_que_subieron(state):
    """True si el historial vigente vio a un rival SUBIR.

    Misma asimetria que en _contar_limpers y _agresor_del_log: solo se usa la
    PRESENCIA del verbo, nunca su ausencia. El historial viene con
    completo=False, asi que "no he visto ninguna subida" no significa que no la
    haya; pero haber visto un "Subir" si demuestra que el bote fue abierto.

    Antes se miraba solo la ULTIMA acción y un fold posterior borraba la subida.
    Eso ocurrió en la sesión 2026-07-31_022832: HJ fue all-in, CO foldeó y el
    motor volvió a recomendar como si el bote estuviera limpeado. Ya no hace
    falta ese recorte: estado_preflop descarta las acciones anteriores a la
    última colocación de ciegas, que era la causa real de que una agresión vieja
    contaminase la mano siguiente."""
    secuencia = state.get("preflop_action") or action_log.estado_preflop(state)
    return (secuencia.get("nivel") != "sin_agresion_observada"
            and secuencia.get("ultimo_agresor_seat") != "HERO")


_RAISE_ABSTAIN = {
    "multiway": "hay varias apuestas por encima de la ciega (bote multiway o 3bet ya "
                "presente); no se recomienda defensa contra una posicion incierta",
    "hero_raised": "el hero ya ha subido y enfrenta una resubida; fuera del modelo "
                   "(open_raise / threebet_call)",
    "bb_raised": "la ciega grande ha subido (mas que ciega+ante). La BB habla ultima "
                 "preflop, asi que no hay rango de defensa contra ella en las tablas: "
                 "los vs_position digitalizados son solo posiciones que hablan ANTES",
    "raiser_no_pos": "se detecto una subida pero el raiser no tiene posicion asignada; "
                     "sin defensa fiable",
    "no_bb": "no se pudo determinar la ciega grande para juzgar la subida",
}


def postflop_equity(state: GameState, iterations=None, seed=None, context=None):
    """Equity postflop del hero por simulacion, o None si no se puede calcular
    honestamente (el motivo va a state["warnings"]).

    seed: se pasa tal cual a equity.estimate_equity. En produccion va a None (la
    simulacion es distinta cada frame, que es lo correcto: 10.000 iteraciones
    tienen su propio error y fijar la semilla solo lo congelaria). Los tests SI
    lo fijan, porque sin el la misma entrada da un numero distinto cada vez y no
    hay nada que afirmar.

    DELIBERADAMENTE SEPARADO de decide(): esto devuelve una PROBABILIDAD, no una
    decision. decide() sigue sin recomendar nada postflop y el HUD sigue con la
    orden en blanco, porque un 14% puede ser un call correcto con el precio
    adecuado y un 60% puede ser un fold con reverse implied odds. Convertir la
    cifra en una accion exigiria modelar bote, apuestas por venir e ICM, que no
    esta hecho; hacerlo a ojo seria justo el tipo de respuesta segura y
    equivocada que este proyecto evita.

    El numero de rivales sale de player["in_hand"] (dorsos de carta). Si el campo
    no esta -GameState de una version anterior o de las rutas de diagnostico- se
    abstiene en vez de suponer, porque suponer de menos infla la equity."""
    warnings = state.setdefault("warnings", [])

    def abstain(motivo):
        warnings.append(motivo)
        return None

    board = state.get("board") or []
    if len(board) not in (3, 4, 5):
        return None                      # preflop o board ilegible: sin ruido
    if len(state.get("hero_cards") or []) != 2:
        return abstain("equity: no se ven tus 2 cartas")
    if state.get("hero_cards_dimmed"):
        return abstain("equity: tus cartas están apagadas porque ya no sigues "
                       "en la mano; no se calcula una decisión ajena")

    jugadores = state.get("players") or []
    if not any("in_hand" in p for p in jugadores):
        return abstain("equity: este GameState no dice quien sigue en la mano "
                       "(sin deteccion de dorsos); no se supone, porque suponer "
                       "menos rivales de los que hay INFLA la equity")

    rivales = [p for p in jugadores if p.get("in_hand") and not p.get("is_hero")]
    hero_visible = next((p for p in jugadores if p.get("is_hero")), None)
    if hero_visible is not None and hero_visible.get("in_hand") is False:
        return abstain("equity: el hero ya no figura en la mano")
    if not rivales:
        # o la mano termino, o es un showdown con las cartas ya giradas: en los
        # dos casos afirmar "ganas seguro" seria falso
        return abstain("equity: no se detecta ningun rival con cartas; la mano "
                       "pudo terminar o estar en showdown (cartas giradas)")

    # EL BOARD TIENE QUE CUADRAR CON LA CALLE QUE VIENE SIGUIENDO EL RASTREADOR.
    # Son dos lecturas independientes -una cuenta cartas en un frame, la otra
    # lleva la cuenta a lo largo de la mano- y si se contradicen una esta mal, sin
    # saber cual. Calcular igualmente da un numero sobre un board a medias: pasa
    # cuando el cliente esta recogiendo la mesa al acabar la mano, o cuando dos
    # cartas quedan tapadas por una animacion.
    #
    # Medido sobre los 9.225 frames grabados: la discrepancia sale en 462 (5,0%)
    # y en 17 de las 826 equities (2,1%) se calculo el numero igualmente. Un caso
    # real, sesion-2026-07-27_014058/0461-0465: 'river' con tres cartas leidas y
    # la app imprimiendo 30,6% con dos cartas de menos.
    calle = state.get("calle_seguida")
    if calle in _CARTAS_POR_CALLE and len(board) != _CARTAS_POR_CALLE[calle]:
        return abstain(f"equity: vas por {calle} pero se leen {len(board)} cartas de "
                       f"board (deberian ser {_CARTAS_POR_CALLE[calle]}); una de las dos "
                       f"lecturas esta mal y no se calcula sobre un board a medias")

    stack_bb = None
    hero = _hero_player(state)
    if state.get("stack_unit") == "bb":
        stack_bb, _cacheado = _cached_hero_stack(hero, state.get("mano_seguida"), context)

    resultado = equity.estimate_equity(
        state.get("hero_cards"), board, state.get("hero_position"), len(rivales),
        opponent_positions=[p.get("position") for p in rivales],
        # las cartas que el cliente ENSEÑA de cada rival (all-in o showdown). Van
        # como estan: si es None se le supone su rango, y si estan ahi no se
        # supone nada. Es la unica informacion cierta que hay de una mano ajena.
        opponent_hands=[p.get("cards") for p in rivales],
        stack_bb=stack_bb,
        iterations=iterations or equity.DEFAULT_ITERATIONS,
        seed=seed,
        warnings=warnings)
    if resultado is None:
        return None
    # si no se leyeron los botones puede no ser el turno del hero; el numero sigue
    # siendo correcto, pero conviene decir que quiza no haya decision que tomar
    if state.get("facing") is None:
        resultado.setdefault("warnings", []).append(
            "no se leyeron los botones de accion: puede que no sea tu turno")
    resultado["pot_odds"] = postflop_math.calcular(state, resultado)
    return resultado


def _recommend_response_to_3bet(state, secuencia, context):
    """Resuelve hero RFI -> rival 3bet con el suplemento público.

    Devuelve ``(recommendation, None)`` o ``(None, motivo)``. Solo la evidencia
    positiva del log abre esta ruta: el primer agresor observado debe ser HERO,
    la inversión del hero debe parecer un open y no puede haber cold callers.
    """
    hero_position = state.get("hero_position")
    rival_position = secuencia.get("rival_posterior_position")
    if not hero_position or not rival_position:
        return None, (
            "se vio la resubida posterior al open del hero, pero falta la "
            "posición del hero o del 3bettor")
    if not _habla_antes(hero_position, rival_position):
        return None, (
            f"la secuencia dice que {rival_position} 3beteó a {hero_position}, "
            "pero esa posición no habla después del open; posiciones incoherentes")
    if secuencia.get("agresiones_observadas") != 2:
        return None, (
            f"se observaron {secuencia.get('agresiones_observadas')} agresiones; "
            "la tabla pública solo cubre open del hero y un único 3bet")
    if secuencia.get("callers_entre_hero_y_resubida"):
        return None, (
            "un rival pagó entre el open del hero y la resubida: es un squeeze "
            "multiway, no el heads-up RFI vs 3bet de la tabla pública")

    hero = _hero_player(state)
    invested = _committed_bb(hero)
    if invested < 1.5 or invested > 4.5:
        return None, (
            f"el hero figura con {invested:.1f} BB comprometidas al recibir la "
            "resubida; no se puede corroborar que su agresión fuese un open "
            "normal (1,5-4,5 BB) y no una 3bet previa")
    if state.get("stack_unit") != "bb":
        return None, "los stacks de la respuesta a 3bet no están declarados en BB"

    mano = state.get("mano_seguida")
    hero_total = _cached_player_starting_stack("HERO", mano, context)
    if hero_total is None:
        hero_total = _player_starting_stack(hero)
    rival_seat = secuencia.get("rival_posterior_seat")
    effective_bb, rival_total = _effective_stack_vs(
        state.get("players") or [],
        hero_total,
        seat=rival_seat,
        position=rival_position,
        mano=mano,
        context=context,
    ) if hero_total is not None else (None, None)
    if effective_bb is None or rival_total is None:
        return None, (
            "se identificó la 3bet, pero no se pudo recuperar el stack inicial "
            "del hero y del 3bettor; sin profundidad efectiva no se elige tabla")
    rival_player = _player_by_seat_or_position(
        state.get("players") or [], rival_seat, rival_position)
    rival_invested = _committed_bb(rival_player)
    if rival_invested <= invested + 0.5:
        return None, (
            f"se vio el verbo de resubida, pero el importe del 3bettor no quedó "
            f"confirmado ({rival_invested:.1f} BB frente a {invested:.1f} BB del "
            "hero). Sin tamaño no se distingue una 3bet normal de la primera "
            "línea de un all-in y no se consulta una tabla distinta")

    max_players = state.get("max_players")
    adapted_6max = max_players == 6
    if max_players not in (6, 8):
        return None, (
            "el suplemento RFI vs 3bet solo se usa en mesas declaradas 8-max "
            "o en el subárbol de posiciones tardías de una mesa 6-max")
    if adapted_6max and (
            hero_position not in ("HJ", "CO", "BTN", "SB")
            or rival_position not in ("CO", "BTN", "SB", "BB")):
        return None, (
            f"no se traslada {hero_position} vs {rival_position} desde 8-max a "
            "6-max: solo se aceptan posiciones tardías con el mismo orden")

    rival_action = secuencia.get("rival_posterior_accion")
    if rival_action == "allin" and effective_bb > 25.0:
        return None, (
            f"el rival fue all-in a {effective_bb:.1f} BB; las tablas públicas "
            "de 30+ BB responden a una 3bet normal, no a ese shove")
    if rival_action != "allin" and effective_bb <= 25.0:
        return None, (
            "la tabla pública cercana de 20 BB responde específicamente a una "
            "3bet all-in, pero el historial solo observó una resubida no all-in")
    result = rangeconverter.recommend_response_to_3bet(
        state.get("hero_cards") or [],
        hero_position,
        rival_position,
        effective_bb,
        threebet_all_in=(rival_action == "allin"),
    )
    if result is None:
        return None, (
            f"RangeConverter no publica una celda utilizable para "
            f"{hero_position} vs {rival_position} a {effective_bb:.1f} BB "
            "efectivos (rejilla 20/30/40/50/60/100; interpolación solo entre "
            "donantes compatibles y fallback vecino a un máximo de 5 BB)")
    stack_key = result["stack_key"]
    if stack_key == 20 and rival_action != "allin":
        return None, (
            "la tabla pública de 20 BB responde específicamente a una 3bet "
            "all-in, pero el historial solo observó una resubida no all-in")
    if stack_key != 20 and rival_action == "allin":
        return None, (
            f"el rival fue all-in a {effective_bb:.1f} BB; la tabla pública de "
            f"{stack_key:g} BB responde a una 3bet normal, no a ese shove")
    if result["action"] == "NOT_IN_RFI":
        return None, (
            f"{lookup.normalize_hand(state.get('hero_cards') or [])} no forma "
            f"parte del RFI de {hero_position} en la solución pública de "
            f"{stack_key:g} BB; no se inventa una respuesta fuera del árbol")

    assumptions = list(result["assumptions"])
    source = result["source"]
    interpolated = source == "interpolated_chart"
    confidence = (
        f"{result['confidence']}: frecuencias interpoladas entre tablas "
        "compatibles; ante de la mesa no medible; sin ICM"
        if interpolated else
        "media-alta: posición/stack publicados; ante de la mesa no medible "
        "con fiabilidad en este frame; sin ICM"
    )
    format_note = "8-max exacto"
    assumptions.append(
        "el PDF usa ante total 1 BB; el importe de ante no se verifica en este frame")
    if adapted_6max:
        source = (
            "interpolated_chart_adapted_6max"
            if interpolated else
            "rangeconverter_public_chart_adapted_6max"
        )
        confidence = (
            "media-baja: interpolación y subárbol tardío 8-max trasladado "
            "a 6-max"
            if interpolated else
            "media: subárbol tardío 8-max trasladado a 6-max"
        )
        assumptions.append(
            "adaptación a 6-max solo para posiciones tardías; no es solución 6-max")
        format_note = "adaptado al subárbol tardío 6-max"
    if interpolated:
        lower, upper = result["donor_stack_keys"]
        interpolation = (
            f"; interpolación lineal entre {lower:g} y {upper:g} BB, "
            f"desacuerdo {result['disagreement']:.2f}"
        )
    else:
        distance = abs(effective_bb - stack_key)
        interpolation = (
            "" if distance <= _STACK_KEY_EXACT_TOL else
            f"; tabla vecina de {stack_key:g} BB, distancia {distance:.1f} BB"
        )
    sizing_note = (
        " El PDF confirma 4bet no all-in, pero su tamaño impreso no se usa: "
        "el OCR no lo recupera con fiabilidad."
        if "4BET NON-ALL-IN" in result["action"] else ""
    )
    recommendation = {
        "action": result["action"],
        "reasoning": (
            f"Respuesta al 3bet de {rival_position} después del open del hero: "
            f"{effective_bb:.1f} BB efectivos (hero {hero_total:.1f}, rival "
            f"{rival_total:.1f}); RangeConverter MTT 8-max, ante total 1 BB, "
            "chip-EV, frecuencias fuente redondeadas al 50% "
            f"({format_note}{interpolation})."
            f"{sizing_note}"
        ),
        "hero_cards": state.get("hero_cards"),
        "hero_position": hero_position,
        "stack_bb": hero_total,
        "effective_stack_bb": effective_bb,
        "stack_unit": "bb",
        "stack_cacheado": True,
        "facing_used": "response_to_3bet",
        "vs_position": rival_position,
        "source": source,
        "source_name": result.get("source_name"),
        "source_url": result.get("source_url"),
        "confidence": confidence,
        "assumptions": assumptions,
        "stack_key": stack_key,
    }
    for field in (
        "source_urls",
        "action_probabilities",
        "donor_stack_keys",
        "donor_actions",
        "interpolation_weight",
        "disagreement",
    ):
        if result.get(field) is not None:
            recommendation[field] = result[field]
    translate_into(recommendation)
    return recommendation, None


def decide(state: GameState, context=None) -> Recommendation | None:
    warnings = state.setdefault("warnings", [])
    _observe_player_starting_stacks(
        state.get("players") or [], state.get("mano_seguida"), context)

    def abstain(reason):
        warnings.append(reason)
        journal.record(state, None, reason)
        return None

    board_detected_count = state.get("board_detected_count", 0)
    if state.get("board") or (
            isinstance(board_detected_count, int)
            and not isinstance(board_detected_count, bool)
            and board_detected_count > 0):
        # NO se dice "el postflop no existe": si existe, lo da postflop_equity() y
        # el HUD lo pinta en su panel. Lo que no hay es una ACCION postflop, y es
        # a proposito -no hay rango postflop digitalizado, y convertir una
        # probabilidad en una orden seria justo lo que este repo rechaza-. El
        # texto viejo decia que el postflop era la Fase 4.3 (RAG) y que no
        # existia; se quedo caduco cuando entro el Monte Carlo y el usuario lo
        # leyo en el HUD como "se ha perdido la equity".
        detalle = (f"se detectaron {board_detected_count} caja(s) en la zona del board"
                   if not state.get("board") else "hay board resuelto")
        return abstain(
            f"{detalle}: no se recomienda accion preflop (no hay rango postflop "
            "digitalizado). La probabilidad de ganar solo se calcula cuando las "
            "cartas comunitarias estan resueltas")

    hero_cards = state.get("hero_cards") or []
    if len(hero_cards) != 2:
        return abstain("faltan las 2 cartas del hero; no se puede recomendar")

    # El cliente APAGA tus cartas cuando ya no estas en la mano y las deja
    # visibles para que sigas la jugada. Se siguen leyendo (interesan para el
    # repaso post-mano), pero recomendar ahi seria recomendar sobre una mano
    # abandonada. Lo dijo el usuario tal cual: "no tienes que pensar que estoy
    # en el juego". Ver glyph_card_detector: cara viva V=255, apagada V=77.
    if state.get("hero_cards_dimmed"):
        return abstain("tus cartas salen apagadas: ya no estas en esta mano")

    hero = _hero_player(state)

    # El historial es incompleto, pero el ORDEN de lo que sí se observó es
    # evidencia positiva. Antes cualquier acción del hero cortaba aquí y se
    # perdía una resubida rival posterior; también se conservaba una defensa
    # contra el primer raiser aunque después otro jugador hubiese ido all-in.
    # Se expone el resumen en el estado para que replay/HUD puedan auditar por
    # qué se bloqueó una recomendación.
    secuencia = action_log.estado_preflop(state)
    state["preflop_action"] = secuencia
    accion_hero = secuencia["hero_ultima_accion"]
    if accion_hero is not None:
        if accion_hero == "allin":
            return abstain("el hero ya esta all-in en esta mano; no existe otra "
                           "decision preflop que recomendar")
        if accion_hero == "fold":
            return abstain("el hero ya se retiro de esta mano; no existe otra "
                           "decision preflop que recomendar")
        if secuencia["rival_agresion_posterior_hero"]:
            if (accion_hero == "raise"
                    and secuencia.get("primera_agresion_seat") == "HERO"
                    and secuencia.get("agresiones_antes_hero") == 0
                    and secuencia.get("agresiones_hero") == 1):
                recommendation, reason = _recommend_response_to_3bet(
                    state, secuencia, context)
                if recommendation is not None:
                    journal.record(state, recommendation, None)
                    return recommendation
                return abstain(
                    "la accion ha vuelto al hero frente a una resubida. "
                    + reason)
            rival = (secuencia["rival_posterior_position"]
                     or secuencia["rival_posterior_seat"]
                     or "un rival")
            accion = secuencia["rival_posterior_accion"]
            verbo = "fue all-in" if accion == "allin" else "resubio"
            return abstain(
                f"despues de que el hero actuase ({accion_hero}), {rival} {verbo}: "
                "la accion ha vuelto al hero frente a una resubida, pero no hay "
                "rangos digitalizados de respuesta a 3bet/4bet; sin recomendacion "
                "estrategica fiable")
        return abstain(
            f"el hero ya ha actuado ({accion_hero}) en esta mano; "
            "sin una nueva accion rival que devuelva el turno, no se recomienda "
            "otra decision preflop")

    if secuencia["nivel"] == "resubida_observada":
        rival = (secuencia["ultimo_agresor_position"]
                 or secuencia["ultimo_agresor_seat"]
                 or "un rival")
        return abstain(
            f"se observaron {secuencia['agresiones_observadas']} agresiones preflop; "
            f"la ultima es de {rival}, por lo que hay una resubida antes de la "
            "decision del hero. Las tablas disponibles solo cubren open_raise y "
            "respuesta a una apertura, no cold-call/4bet frente a una resubida; "
            "sin recomendacion estrategica fiable")

    if (secuencia["nivel"] == "sin_agresion_observada"
            and secuencia.get("agresion_ambigua_arranque")):
        return abstain(
            "se vio una agresion en el mismo frame que la ultima colocacion de "
            "ciegas; el orden dentro de ese frame no es cronologico y no se puede "
            "saber si pertenece a esta mano o a la anterior. No se recomienda "
            "como bote sin abrir")

    hero_position = state.get("hero_position") or (hero.get("position") if hero else None)
    if hero_position is None:
        return abstain("no se detecto la posicion del hero; no se puede recomendar")

    # El cliente recoge las cartas antes de mover el boton, asi que los primeros
    # frames de una mano traen todavia las posiciones de la anterior y la
    # posicion es justo lo que elige la fila de rango. Medido sobre 3.816 frames:
    # 119 frames con la posicion caducada y 36 recomendaciones emitidas con ella.
    # Ver hand_tracker._abrir.
    if state.get("posiciones_asentadas") is False:
        return abstain("el boton todavia no se ha movido: estas posiciones son "
                       "de la mano anterior")

    # LA GUARDA DE UNIDAD. La app es BB-only, pero eso no se puede DAR POR HECHO:
    # analyze() y analyze_color_deck() son rutas de diagnostico que siguen
    # produciendo stacks en FICHAS ENTERAS. Si se asumiera "bb" por defecto, un
    # stack de 3955 fichas se leeria como 3955bb -> tabla de 40bb -> una
    # recomendacion con conviccion y falsa, el peor fallo posible aqui.
    # Exigiendo que la vision lo DECLARE, esa clase de fallo no puede existir.
    # Produccion es table_state.analyze_layout(), que lo pone a "bb" literal.
    unit = state.get("stack_unit")
    if unit != "bb":
        return abstain("este GameState no viene del reconocimiento en BIG BLINDS "
                       "(stack_unit != 'bb'): sus importes podrian estar en fichas y no "
                       "se pueden interpretar como profundidad. Produccion es "
                       "table_state.analyze_layout(); configura PokerStars para mostrar "
                       "los importes en big blinds")

    stack_bb, stack_cacheado = _hero_starting_stack(
        hero, state.get("mano_seguida"), context)
    if stack_bb is None:
        return abstain("no se encontro el stack del hero en BB (ni reciente en cache); "
                       "no se puede calcular la profundidad")
    cache = (context or _DEFAULT_CONTEXT).last_hero_stack
    hero_remaining_bb = cache.get("value")
    fuente = "stacks totales en BB"
    nota_cache = " stack cacheado de un frame anterior;" if stack_cacheado else ""

    # El importe que pide "Igualar" nunca puede superar las fichas restantes
    # del hero. En el frame 0099 de la sesión 2026-07-31 el OCR leyó 126 donde
    # la pantalla mostraba 12,6. Dividir por diez a ciegas no es seguro (126
    # también podría venir de 1,26), así que se conserva el valor crudo para
    # diagnóstico pero no se usa para atribuir una subida ni elegir un rango.
    to_call_pendiente = _hay_que_igualar(state)
    to_call_invalido = (
        to_call_pendiente is not None
        and isinstance(hero_remaining_bb, (int, float))
        and to_call_pendiente > hero_remaining_bb + hand_tracker.TO_CALL_MARGEN_BB
    )
    if to_call_invalido:
        warnings.append(
            f"el OCR del boton leyo {to_call_pendiente:g} BB para igualar, "
            f"mas que el stack restante del hero ({hero_remaining_bb:.1f}bb): "
            "importe imposible; "
            "se conserva como lectura cruda pero no se usa para decidir")
        to_call_pendiente = None

    # CALL VS OPEN-PUSH. Esta familia no estaba en las capturas originales y por
    # eso antes se cortaba todo all-in inicial. El suplemento público añadido es
    # deliberadamente estrecho: 8-max, 10 BB, 1 BB de ante total, sin limpers y
    # sin callers. Cada supuesto se verifica aquí; si falta uno no se degrada a
    # threebet_call ni se busca una profundidad "parecida".
    es_open_shove = (
        secuencia["nivel"] == "apertura_observada"
        and secuencia["ultima_agresion"] == "allin"
    )
    if es_open_shove:
        rival = (secuencia["ultimo_agresor_position"]
                 or secuencia["ultimo_agresor_seat"]
                 or "un rival")
        if secuencia.get("callers_antes_primera_agresion", 0):
            return abstain(
                f"{rival} fue all-in despues de uno o mas limpers: no es un open-push "
                "RFI. El suplemento es una solucion no-limp y no se extrapola")
        if secuencia.get("callers_despues_ultima_agresion", 0):
            return abstain(
                f"despues del all-in inicial de {rival} ya pago otro rival: el spot es "
                "multiway. El suplemento CALL VS OPEN-PUSH es heads-up y no se extrapola")
        if state.get("max_players") != 8:
            return abstain(
                f"{rival} fue all-in como primera agresion observada. Hay tabla "
                "suplementaria CALL VS OPEN-PUSH solo para mesa 8-max; esta mesa declara "
                f"{state.get('max_players')!r} plazas y no se traslada un rango entre "
                "formatos")
        seated_players = sum(
            1 for p in state.get("players") or [] if p.get("position") is not None)
        if seated_players != 8:
            return abstain(
                f"la mesa admite 8 plazas pero en esta mano solo hay "
                f"{seated_players} posiciones asignadas. El suplemento modela 8 "
                "jugadores activos y no se traslada a una mesa acortada")

        ante_total = _ante_total_bb(state.get("players") or [])
        if ante_total is None:
            return abstain(
                f"{rival} fue all-in como primera agresion observada, pero no se pudo "
                "comprobar el ante total en lo puesto por la BB. El suplemento exige "
                "1 BB de ante y no se usa con ese supuesto desconocido")
        if abs(ante_total - open_push.ANTE_TOTAL_BB) > open_push.ANTE_TOLERANCE_BB:
            return abstain(
                f"{rival} fue all-in como primera agresion observada, pero el ante "
                f"visible es {ante_total:.1f} BB. El suplemento CALL VS OPEN-PUSH "
                "corresponde a 1 BB de ante total y no se extrapola")

        shove_bb = _open_shove_amount(
            state, secuencia, hero, to_call_pendiente)
        if shove_bb is None:
            return abstain(
                f"{rival} fue all-in como primera agresion observada, pero no se pudo "
                "leer su tamaño. Sin tamaño no se conocen las pot odds y no se usa la "
                "tabla suplementaria de 10 BB")
        effective_bb = min(shove_bb, stack_bb)
        if abs(effective_bb - open_push.STACK_BB) > open_push.STACK_TOLERANCE_BB:
            return abstain(
                f"{rival} fue all-in por {shove_bb:.1f} BB y la profundidad efectiva "
                f"es {effective_bb:.1f} BB. El suplemento CALL VS OPEN-PUSH solo cubre "
                "10 BB exactas (tolerancia 0,5 BB); no se sustituye por threebet_call")

        result = open_push.recommend(
            hero_cards,
            hero_position,
            secuencia.get("ultimo_agresor_position"),
            effective_bb,
            state.get("max_players"),
            seated_players,
            ante_total,
        )
        if result is None:
            return abstain(
                f"el spot cumple 8-max/10 BB/ante 1 BB, pero no existe celda "
                f"CALL VS OPEN-PUSH para {hero_position} vs {rival}; sin recomendacion")

        action = result["action"]
        mixed = action == "CALL 50% / FOLD 50%"
        reasoning = (
            f"Respuesta al open-push de {rival} por {shove_bb:.1f} BB: "
            f"{effective_bb:.1f} BB efectivos. Tabla suplementaria pública "
            f"'{result.get('source_name')}' para MTT 8-max, 10 BB, ante total 1 BB "
            "y solución sin limps; no procede de las capturas ZeroS."
        )
        if mixed:
            reasoning += (
                " La celda publicada es mixta: CALL el 50% y FOLD el 50%; "
                "no se ha convertido en una acción pura.")
        recommendation = {
            "action": action,
            "reasoning": reasoning,
            "hero_cards": hero_cards,
            "hero_position": hero_position,
            "stack_bb": stack_bb,
            "effective_stack_bb": effective_bb,
            "stack_unit": unit,
            "stack_cacheado": stack_cacheado,
            "facing_used": "call_vs_open_push",
            "vs_position": secuencia.get("ultimo_agresor_position"),
            "source": result["source"],
            "source_name": result.get("source_name"),
            "source_url": result.get("source_url"),
            "confidence": "alta dentro de los supuestos; no incorpora ICM",
            "assumptions": [
                "MTT 8-max",
                "10 BB efectivas",
                "ante total 1 BB",
                "sin limpers ni callers",
                "estrategia chip-EV, no ICM",
            ],
        }
        translate_into(recommendation)
        journal.record(state, recommendation, None)
        return recommendation

    # Defensa vs subida ajena: si el hero enfrenta una apuesta (facing="bet") y
    # se identifica una subida unica, se usa el rango threebet_call contra el
    # raiser. La ciega grande efectiva (1 en modo BB) decide que cuenta como
    # subida, por eso se recomputa aqui.
    # Coherencia entre la lectura de los BOTONES y la de la POSICION: preflop solo
    # la BB puede PASAR (para cualquier otro asiento la ciega grande es una apuesta
    # viva, asi que los botones ofrecerian "Igualar"). Si los botones dicen "Pasar"
    # y la posicion leida no es BB, una de las dos lecturas esta mal; y si la que
    # falla es la posicion, el rango elegido tambien sera el equivocado.
    if state.get("facing") == "check" and hero_position != "BB":
        return abstain(f"contradiccion entre lecturas: los botones ofrecen PASAR (solo la "
                       f"BB puede pasar preflop) pero la posicion detectada es "
                       f"{hero_position}; una de las dos es erronea")

    # NOTA sobre facing=None: NO se abstiene. Seria lo "correcto" en teoria (sin
    # botones no es el turno del hero), pero los botones solo se leen en el 9,9% de
    # los frames del corpus, y sobre el log de una sesion real 55 de los 74 frames
    # decidibles (2 cartas + posicion) tenian facing=None -de ahi salieron casi
    # todas las recomendaciones-. Abstenerse mataria ~75% de la utilidad para
    # protegerse de un caso que no es el peligroso: recomendar una APERTURA cuando
    # el hero no tiene accion pendiente es un preview inofensivo. El caso de verdad
    # peligroso -enfrentar una subida que no se ha detectado- se cubre aparte, con
    # el importe del boton "Igualar" (ver la red de seguridad de to_call).
    facing = "open_raise"
    vs_position = None
    derivada_meta = None          # procedencia si la accion NO sale de una tabla suya
    origen_subida = "subida inferida del importe apostado en la mesa"
    # El importe de la mesa es evidencia aunque el OCR de los botones falle.
    # Antes solo se miraba dentro de ``facing == "bet"``: en los frames
    # 0237-0244 de la sesión 2026-07-31 seguían visibles 3,5bb de CO, pero al
    # perderse "Igualar" el motor volvió durante siete frames a open_raise.
    vs_leida, code = _detect_raiser(state.get("players", []), BB)
    if state.get("facing") == "bet" or code != "no_raise":
        vs_position = vs_leida
        if vs_position is not None:
            facing = "threebet_call"
        elif code == "multiway":
            # Varias apuestas por encima de la ciega. Por IMPORTE no se puede
            # saber quien subio y quien pago -el que paga iguala, asi que los dos
            # numeros son el mismo-, y por eso esto se abstenia siempre. El
            # historial de acciones si lo distingue, porque el cliente enseña el
            # verbo. Es justo el spot del squeeze.
            agresor = _agresor_del_log(state)
            if agresor is None:
                return abstain(_RAISE_ABSTAIN["multiway"])
            vs_position = agresor
            facing = "threebet_call"
            origen_subida = (f"subida atribuida a {agresor} por el verbo que mostro su "
                             f"nameplate, corroborado con el importe de la mesa")
        elif code != "no_raise":
            return abstain(_RAISE_ABSTAIN[code])
        else:
            # "no_raise" con facing="bet" es normal y correcto cuando el hero es la
            # SB y solo completa (el boton pide 0,5bb) o cuando hay limpers. Pero
            # si el BOTON pide mas de una ciega grande y ningun asiento tiene un
            # importe que lo explique, hay una subida que no se ha sabido atribuir
            # -tipicamente porque el OCR del importe de la mesa fallo-. Seguir por
            # open_raise ahi seria recomendar el rango de APERTURA enfrentando una
            # subida: plausible y falso, el peor fallo posible en esta app.
            to_call = to_call_pendiente
            if to_call is not None:
                # El importe dibujado en la mesa no explica la subida -es el caso
                # mayoritario: 59% de los frames preflop con to_call>1-, pero la
                # BAJADA DE STACK del rival entre frames si puede. Ver
                # hand_tracker: sube la explicacion del 41% al 84%.
                #
                # ATRIBUYE, NO INVENTA, y el orden de este if es justo la garantia:
                # solo se llega aqui porque to_call -evidencia independiente, el
                # propio cliente pidiendo un importe- ya ha demostrado que hay una
                # subida. Un comprometido inflado (por una frontera de mano que se
                # paso por alto) no puede crear un raiser de la nada.
                pos_derivada, detalle = hand_tracker.atribuir_subida(
                    state.get("players", []), to_call)
                if pos_derivada is not None:
                    vs_position = pos_derivada
                    facing = "threebet_call"
                    origen_subida = (f"subida atribuida a {pos_derivada} por su bajada de "
                                     f"stack entre frames (la mesa no mostraba el importe)")
                else:
                    return abstain(
                        f"el boton pide {to_call:g} BB para igualar, o sea que hay una subida, "
                        f"pero ningun asiento la explica: ni el importe dibujado en la mesa ni "
                        f"la bajada de stack entre frames ({detalle}); sin defensa fiable")

    # LA RED DE to_call TAMBIEN VALE SIN BOTONES LEIDOS. Estaba dentro del
    # if facing=="bet", o sea que solo se aplicaba en el 10% de los frames en que
    # se leen los botones; en el resto un to_call de 2bb se tiraba entero y el
    # motor seguia como si el bote estuviera sin abrir.
    #
    # Lo cazo el usuario jugando (28-07-2026, frame 0181): era la BB, el boton
    # pedia 2 BB y el historial habia visto "Subir" en el asiento de su derecha,
    # y aun asi la app le dijo "opcion de la BB, nadie ha subido" y le sirvio un
    # RAISE OVER LIMPERS. Su nota: "no entiendo porque me dice que suba sobre
    # limpers, yo era ciega".
    #
    # parse_facing y parse_to_call_bb leen la MISMA zona por caminos distintos,
    # asi que uno puede fallar y el otro no. Fiarse solo de facing tira la
    # evidencia mas dura que hay: el cliente pidiendo un importe.
    if facing == "open_raise":
        if to_call_invalido:
            return abstain(
                "los botones demuestran que hay una apuesta que igualar, pero su importe "
                "es imposible para el stack del hero y ningun importe fiable de la mesa "
                "ha permitido clasificarla; no se recomienda como bote sin abrir")
        to_call = to_call_pendiente
        subida_en_log = _log_dice_que_subieron(state)
        if to_call is not None or subida_en_log:
            pos_derivada, detalle = hand_tracker.atribuir_subida(
                state.get("players", []), to_call or 0)
            if pos_derivada is not None and _habla_antes(pos_derivada, hero_position):
                vs_position = pos_derivada
                facing = "threebet_call"
                origen_subida = (f"subida atribuida a {pos_derivada} por su bajada de "
                                 f"stack entre frames (los botones no se leyeron)")
            else:
                prueba = []
                if to_call is not None:
                    prueba.append(f"el boton pide {to_call:g} BB para igualar")
                if subida_en_log:
                    prueba.append("el historial vigente vio a un rival SUBIR")
                return abstain(
                    f"{' y '.join(prueba)}, o sea que el bote NO esta sin abrir, pero no se "
                    f"ha podido atribuir la subida a ningun asiento ({detalle}); sin defensa "
                    f"fiable. No se recomienda como si nadie hubiera subido")

    if facing == "threebet_call":
        # GUARDA ESTRUCTURAL: sus tablas de defensa solo cubren raisers que hablan
        # ANTES que el hero. Si el "raiser" habla despues, lo que hay delante no es
        # una subida que defender sino una RESUBIDA a una apertura del propio hero,
        # y eso esta fuera del modelo. Medido sobre dos sesiones reales: 67 de 134
        # atribuciones eran de este tipo, y la mayoria (47) eran hero=BTN vs SB, que
        # en 3-max es imposible porque la SB habla despues del BTN. Sin esta guarda
        # el motivo que se daba era "sin rango de defensa para BTN vs SB", que suena
        # a hueco de datos y no lo es: digitalizar mas graficos no lo arreglaria.
        if not _habla_antes(vs_position, hero_position):
            return abstain(f"la subida se atribuye a {vs_position}, que en preflop habla "
                           f"DESPUES que {hero_position}: eso no es una subida que defender "
                           f"sino una resubida a tu propia apertura, y esta fuera del modelo "
                           f"(open_raise / threebet_call)")

        # SQUEEZE: si ademas del raiser hay quien ya ha pagado, la defensa
        # heads-up de sus tablas se queda suelta. Ver derive.squeeze.
        agresor_seat = (
            secuencia.get("ultimo_agresor_seat")
            if secuencia.get("ultimo_agresor_position") == vs_position else None
        )
        effective_bb, rival_stack_bb = _effective_stack_vs(
            state.get("players", []),
            stack_bb,
            seat=agresor_seat,
            position=vs_position,
            mano=state.get("mano_seguida"),
            context=context,
        )
        detalle_efectivo = (
            f"stack inicial del agresor {rival_stack_bb:.1f}bb"
            if rival_stack_bb is not None
            else "stack del agresor no legible; límite conservado en el stack del hero"
        )

        callers = _contar_callers(state.get("players", []), vs_position)
        derivada = (squeeze(
            hero_cards, hero_position, vs_position, effective_bb, callers)
                    if callers >= 1 else None)
        if callers >= 1 and derivada is None:
            plural = "" if callers == 1 else "es"
            return abstain(
                f"{callers} rival{plural} ya ha{'n' if plural else ''} pagado la "
                f"subida de {vs_position}: el spot es un squeeze/multiway, pero "
                f"no existe un rango digitalizado ni un donante compatible para "
                f"{hero_position}. La tabla threebet_call disponible es heads-up "
                "y no se reutiliza con jugadores adicionales")
        if derivada is not None:
            action = derivada["action"]
            plural = "" if callers == 1 else "es"
            reasoning = (f"{callers} rival{plural} ya ha{'n' if plural else ''} pagado la "
                         f"subida de {vs_position}, asi que no es una defensa heads-up. "
                         f"INFERIDO de {derivada['donor']}, que en tu tabla dice "
                         f"'{derivada['donor_action']}': con gente dentro hay que apretar, y "
                         f"en tus tablas cada asiento aprieta la defensa un 15%. "
                         f"{effective_bb:.1f}bb efectivos ({fuente}; {detalle_efectivo};"
                         f"{nota_cache})")
            derivada_meta = derivada
            translate_into({"action": action})       # valida que hay traduccion
            result = None
        else:
            result = recommend(hero_cards, hero_position, effective_bb,
                               facing="threebet_call", vs_position=vs_position)
        if derivada is None:
            if result is None:
                return abstain(f"sin rango de defensa para {hero_position} vs {vs_position} "
                               f"a {effective_bb:.1f}bb efectivos (threebet_call)")
            action = result["action"]
            reasoning = (f"Defensa (3bet/call) de {hero_position} a "
                         f"{effective_bb:.1f}bb efectivos contra la subida de "
                         f"{vs_position} ({fuente}; {detalle_efectivo};{nota_cache} "
                         f"{origen_subida})"
                         + _stack_key_note(result, effective_bb, facing, warnings))
    elif hero_position == "BB":
        # LA OPCION DE LA BB. La BB nunca ABRE el bote, asi que si aqui no hay
        # subida que enfrentar es un bote limpeado y su decision es subir o pasar.
        #
        # Contradiccion primero: si los BOTONES piden igualar, no hay opcion que
        # valga -pasar no es gratis- y decir "pasa, es tu opcion" seria decirle al
        # usuario justo lo contrario de lo que tiene delante. Es la simetrica de
        # la guarda de facing="check" sin ser BB. Medido sobre una sesion real:
        # 49 de las 227 "CHECK (BB option)" (el 22%) se daban con los botones
        # pidiendo igualar.
        if state.get("facing") == "bet":
            return abstain("los botones piden IGUALAR, asi que no es la opcion de la BB "
                           "(pasar no es gratis) pero tampoco se ha podido atribuir la "
                           "subida a ningun asiento; sin recomendacion fiable")

        limpers = _contar_limpers(
            state.get("players", []), state.get("acciones"), secuencia)
        multiway = (
            bb_multi_limp.recommend(hero_cards, stack_bb, limpers)
            if isinstance(limpers, int) and limpers >= 2 else None
        )
        derivada = multiway or bb_option(hero_cards, stack_bb, limpers)
        if derivada is None:
            cuantos = (f"hay {limpers} rivales dentro" if isinstance(limpers, int)
                       else "no se pudo contar cuantos rivales han entrado")
            return abstain(
                f"estas en la BB con opcion y nadie ha subido, pero {cuantos}. "
                "No hay un rango digitalizado ni un donante valido para este spot "
                "multiway: pasar es legal y gratis, pero recomendarlo por defecto "
                "ocultaria manos fuertes que deben subir; sin recomendacion "
                "estrategica fiable")
        else:
            action = derivada["action"]
            if multiway is not None:
                if multiway["fallback"]:
                    reasoning = (
                        f"Opcion de la BB con {limpers} limpers a {stack_bb:.1f}bb "
                        f"({fuente};{nota_cache} nadie ha subido): CHECK es gratis y "
                        "se usa como fallback conservador. No existe una tabla multiway "
                        "completa para decidir qué otras manos deberían aislar; no se "
                        "presenta este check como solución GTO.")
                else:
                    reasoning = (
                        f"Opcion de la BB con {limpers} limpers a {stack_bb:.1f}bb "
                        f"({fuente};{nota_cache} nadie ha subido): {action} por valor "
                        f"con {lookup.normalize_hand(hero_cards)}. Heurística pública: "
                        "3 BB base + 1 BB por limper + 1 BB por estar OOP; no es una "
                        "celda de las capturas ZeroS.")
            else:
                reasoning = (
                    f"Opcion de la BB a {stack_bb:.1f}bb ({fuente};{nota_cache} nadie ha "
                    f"subido). INFERIDO de {derivada['donor']}, que en tu tabla dice "
                    f"'{derivada['donor_action']}': no es tu rango digitalizado para "
                    f"este spot, es el mas parecido que tienes. Con la opcion nunca se "
                    f"retira uno, porque pasar es gratis.")
            for sup in derivada["assumptions"]:
                reasoning += f" OJO: {sup}."
            derivada_meta = derivada
    else:
        # FRENTE A LIMPERS el bote ya no esta sin abrir: hay gente dentro, asi que
        # el rango de APERTURA se queda suelto. Si se puede contar cuantos han
        # entrado, se usa la celda real que corresponde a apretar por cada uno
        # (ver derive.vs_limp). Se exige un recuento POSITIVO: con limpers=None no
        # se sabe si hay alguien dentro, y ahi lo correcto es el rango de apertura
        # de siempre, que es lo que se venia haciendo.
        limpers = _contar_limpers(state.get("players", []), state.get("acciones"))
        derivada = (vs_limp(hero_cards, hero_position, stack_bb, limpers)
                    if isinstance(limpers, int) and limpers >= 1 else None)
        if derivada is not None:
            action = derivada["action"]
            plural = "" if derivada["limpers"] == 1 else "s"
            reasoning = (f"{derivada['limpers']} rival{plural} ha{'n' if plural else ''} "
                         f"entrado pagando, asi que el bote no esta sin abrir. INFERIDO de "
                         f"{derivada['donor']}, que en tu tabla dice "
                         f"'{derivada['donor_action']}': con limpers delante hay que apretar, "
                         f"y en tus tablas cada asiento hacia EP aprieta un 20%. "
                         f"{stack_bb:.1f}bb efectivos ({fuente};{nota_cache})")
            derivada_meta = derivada
        else:
            public = None
            use_public_family = (
                stack_bb > max(_stack_grid("open_raise"))
                and state.get("max_players") in (6, 8)
            )
            if use_public_family:
                eligible_position = not (
                    state.get("max_players") == 6
                    and hero_position not in ("HJ", "CO", "BTN", "SB")
                )
                if eligible_position:
                    public = rangeconverter.recommend_open_raise(
                        hero_cards, hero_position, stack_bb)

            if public is not None:
                action = public["action"]
                assumptions = list(public["assumptions"])
                source = public["source"]
                interpolated = source == "interpolated_chart"
                confidence = (
                    f"{public['confidence']}: frecuencias interpoladas entre "
                    "tablas compatibles; ante no medible; sin ICM"
                    if interpolated else
                    "media-alta: posición/stack publicados; ante de la mesa "
                    "no medible con fiabilidad; sin ICM"
                )
                format_note = "8-max exacto"
                assumptions.append(
                    "el PDF usa ante total 1 BB; no verificado en este frame")
                if state.get("max_players") == 6:
                    source = (
                        "interpolated_chart_adapted_6max"
                        if interpolated else
                        "rangeconverter_public_chart_adapted_6max"
                    )
                    confidence = (
                        "media-baja: interpolación y subárbol tardío 8-max "
                        "trasladado a 6-max"
                        if interpolated else
                        "media: subárbol tardío 8-max trasladado a 6-max"
                    )
                    assumptions.append(
                        "adaptación a 6-max solo para posiciones tardías")
                    format_note = "subárbol tardío trasladado a 6-max"
                if interpolated:
                    lower, upper = public["donor_stack_keys"]
                    note = (
                        f"; interpolación entre {lower:g} y {upper:g} BB "
                        f"(desacuerdo {public['disagreement']:.2f})"
                    )
                else:
                    distance = abs(stack_bb - public["stack_key"])
                    note = (
                        "" if distance <= _STACK_KEY_EXACT_TOL else
                        f"; tabla de {public['stack_key']:g} BB a "
                        f"{distance:.1f} BB"
                    )
                reasoning = (
                    f"RFI público de {hero_position} a {stack_bb:.1f} BB "
                    f"({format_note}{note}; MTT, ante total 1 BB, chip-EV, "
                    "frecuencias fuente redondeadas al 50%). El PDF fija la "
                    "selección de manos; "
                    "la etiqueta no inventa un sizing que no se haya importado "
                    "con fiabilidad."
                )
                derivada_meta = dict(
                    public,
                    source=source,
                    confidence=confidence,
                    assumptions=assumptions,
                )
            else:
                result = recommend(
                    hero_cards, hero_position, stack_bb, facing="open_raise")
                if result is None:
                    return abstain(
                        f"sin rango de apertura para {hero_position} a "
                        f"{stack_bb:.1f}bb (open_raise); revisa que la "
                        "posicion/stack esten en las tablas")
                action = result["action"]
                reasoning = (
                    f"Rango de apertura de {hero_position} a "
                    f"{stack_bb:.1f}bb efectivos ({fuente};{nota_cache} sin "
                    "subida que enfrentar, el hero abre el bote)"
                    + _stack_key_note(result, stack_bb, facing, warnings))

    recommendation = {
        "action": action,
        "reasoning": reasoning,
        "hero_cards": hero_cards,
        "hero_position": hero_position,
        "stack_bb": stack_bb,
        "effective_stack_bb": (
            effective_bb if facing == "threebet_call" else stack_bb),
        "stack_unit": unit,
        "stack_cacheado": stack_cacheado,
        "facing_used": facing,
        "vs_position": vs_position,
    }
    # Procedencia. Una etiqueta derivada como "CHECK" es indistinguible a simple
    # vista de una que sale de sus tablas, asi que cuando NO sale de ellas se dice
    # explicitamente, con la celda donante y la confianza. El HUD lo pinta aparte.
    if derivada_meta is not None:
        recommendation["source"] = derivada_meta["source"]
        recommendation["confidence"] = derivada_meta["confidence"]
        if derivada_meta.get("donor"):
            recommendation["donor"] = derivada_meta["donor"]
        recommendation["assumptions"] = derivada_meta["assumptions"]
        if derivada_meta.get("source_name"):
            recommendation["source_name"] = derivada_meta["source_name"]
        if derivada_meta.get("source_url"):
            recommendation["source_url"] = derivada_meta["source_url"]
        if derivada_meta.get("stack_key") is not None:
            recommendation["stack_key"] = derivada_meta["stack_key"]
        for field in (
            "source_urls",
            "action_probabilities",
            "donor_stack_keys",
            "donor_actions",
            "interpolation_weight",
            "disagreement",
        ):
            if derivada_meta.get(field) is not None:
                recommendation[field] = derivada_meta[field]
    else:
        recommendation["source"] = "chart"
    # action_en / action_es para el HUD. "action" se conserva con la etiqueta
    # CRUDA: es la que enlaza con ranges.json y la que registra el log, asi que
    # el historial de decisiones sigue siendo comparable entre versiones.
    translate_into(recommendation)
    journal.record(state, recommendation, None)
    return recommendation
