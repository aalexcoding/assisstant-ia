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
(_HERO_STACK_TTL_S). Es una aproximacion (el stack efectivo baja al meter
fichas), pero para elegir el rango preflop por profundidad es suficiente y
es mucho mejor que no recomendar. Se anota en el reasoning cuando se usa.
"""
import json
import os
import time

from decision import equity
from decision import hand_tracker

from decision.preflop.actions import CHECK_BB_OPTION, translate_into
from decision.preflop.derive import bb_option, squeeze, vs_limp
from decision.preflop import lookup
from decision.preflop.lookup import recommend

_DECISIONS_LOG_PATH = os.path.join(os.path.dirname(__file__), "decisions.local.jsonl")

# El registro de decisiones se puede APAGAR. En produccion interesa (es la
# semilla para "aprender el estilo" mas adelante), pero un test que llama a
# decide() no tiene por que dejar rastro en el fichero real del usuario, y menos
# aun cientos de lineas por pasada del corpus. POKER_DECISIONS_LOG=0 lo apaga.
_LOG_ACTIVO = os.environ.get("POKER_DECISIONS_LOG", "1") != "0"

_HERO_STACK_TTL_S = 90.0
_last_hero_stack = {"value": None, "t": 0.0}


def reset_state():
    """Olvida el stack cacheado del hero.

    ESTO ES ESTADO GLOBAL ENTRE LLAMADAS, y por eso hace falta poder tirarlo: sin
    esto, un test que deja un stack en la cache cambia el resultado del siguiente
    -decide() lo reutilizaria como si fuera de este frame- y la suite pasa a
    depender del orden. En produccion no se llama: la cache es justo lo que salva
    la recomendacion cuando el nameplate del hero se tapa con los botones."""
    _last_hero_stack.update(value=None, t=0.0)

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


def _cached_hero_stack(hero):
    """Stack del hero en bb, con cache reciente: cuando es su turno el nameplate
    deja de mostrar el numero (muestra la accion, o lo tapan los botones), o sea
    que el stack desaparece de pantalla JUSTO en el momento en que hace falta
    recomendar. Devuelve (valor, cacheado)."""
    val = hero.get("stack") if hero else None
    if val is not None:
        _last_hero_stack.update(value=val, t=time.monotonic())
        return val, False
    if (_last_hero_stack["value"] is not None
            and time.monotonic() - _last_hero_stack["t"] <= _HERO_STACK_TTL_S):
        return _last_hero_stack["value"], True
    return None, False


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


def _log_decision(state, recommendation, abstain_reason):
    """Anota una linea JSONL por cada decision (recomendacion o abstencion con
    motivo). Semilla para 'aprender el estilo' mas adelante; por ahora es solo
    registro. Un fallo al escribir nunca debe tumbar decide()."""
    if not _LOG_ACTIVO:
        return
    try:
        entry = {
            "t": time.time(),
            "image": state.get("image"),
            "hero_cards": state.get("hero_cards") or [],
            "board_empty": not state.get("board"),
            "hero_position": state.get("hero_position"),
            "facing": state.get("facing"),
            "vs_position": state.get("vs_position"),
            "stack_unit": state.get("stack_unit"),
        }
        if recommendation is not None:
            entry["stack_bb"] = round(recommendation.get("stack_bb"), 2)
            entry["action"] = recommendation.get("action")
            entry["facing_used"] = recommendation.get("facing_used")
            entry["vs_position"] = recommendation.get("vs_position")
        else:
            entry["abstain"] = abstain_reason
        with open(_DECISIONS_LOG_PATH, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


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


def _contar_limpers(players, acciones=None):
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

    Se mira el importe leido en la mesa y, si no lo hay, lo que el rastreador
    deduce de la bajada de stack EN ESTA CALLE. Devolver None cuando ningun rival
    da ninguna de las dos señales importa: no es lo mismo "he mirado y no hay
    limpers" que "no he podido mirar"."""
    solo_pusieron = _asientos_que_solo_pusieron(acciones)
    visto = False
    n = 0
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
    return n if visto else None


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
    PAGADO la subida. Es lo que convierte una defensa normal en un squeeze."""
    n = 0
    for p in players:
        if p.get("is_hero") or p.get("position") == vs_position:
            continue
        v = p.get("committed_calle")
        if not isinstance(v, (int, float)):
            v = p.get("bet")
        if isinstance(v, (int, float)) and v > BB * 1.5:
            n += 1
    return n


def _hero_player(state):
    for p in state.get("players", []):
        if p.get("is_hero"):
            return p
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
    ult = ((state.get("acciones") or {}).get("acciones") or [])
    agresor = None
    for r in reversed(ult):
        if r.get("accion") in ("raise", "bet", "allin"):
            agresor = r.get("position")
            break
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
    """True si lo ULTIMO que vio el historial fue a alguien SUBIR.

    Misma asimetria que en _contar_limpers y _agresor_del_log: solo se usa la
    PRESENCIA del verbo, nunca su ausencia. El historial viene con
    completo=False, asi que "no he visto ninguna subida" no significa que no la
    haya; pero haber visto un "Subir" si demuestra que la hubo.

    DOS RECORTES, y los dos salen de medir sobre 4.749 frames preflop de 15
    sesiones, contando cuantas recomendaciones se pierden:

        se mira...                                    pierde
        nada (solo to_call)                              28
        cualquier subida de la mano                     485   <- inaceptable
        la ULTIMA accion, sea de quien sea              204
        la ultima accion Y QUE NO SEA DEL HERO          111   <- esta

    1. SOLO LA ULTIMA ACCION, no toda la mano. El historial acumula la mano
       entera, asi que una subida ya respondida bloqueaba el camino de "bote sin
       abrir" durante el resto de la mano.
    2. Y QUE NO SEA DEL PROPIO HERO. De los 204 que se perdian, 91 no tenian
       NINGUNA prueba independiente de subida, y al mirarlos eran todos el mismo
       caso: la ultima accion vista era el hero subiendo. El motor se bloqueaba
       a si mismo.

    Lo que queda es justo lo que el usuario anoto ("el que esta a mi derecha ha
    subido y a mi no me lo ha detectado rapido"): un RIVAL acaba de subir y
    todavia nadie ha respondido. De esos 111, 28 traen ademas to_call>1, 76 una
    bajada de stack de mas de 1,35bb en algun rival y 50 un importe dibujado en
    la mesa: casi todos con corroboracion independiente."""
    acciones = (state.get("acciones") or {}).get("acciones") or []
    if not acciones:
        return False
    ultima = acciones[-1]
    return (ultima.get("accion") in ("raise", "allin")
            and ultima.get("seat") != "HERO")


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


def postflop_equity(state, iterations=None, seed=None):
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

    jugadores = state.get("players") or []
    if not any("in_hand" in p for p in jugadores):
        return abstain("equity: este GameState no dice quien sigue en la mano "
                       "(sin deteccion de dorsos); no se supone, porque suponer "
                       "menos rivales de los que hay INFLA la equity")

    rivales = [p for p in jugadores if p.get("in_hand") and not p.get("is_hero")]
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
        stack_bb, _cacheado = _cached_hero_stack(hero)

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
    return resultado


def decide(state):
    warnings = state.setdefault("warnings", [])

    def abstain(reason):
        warnings.append(reason)
        _log_decision(state, None, reason)
        return None

    if state.get("board"):
        # NO se dice "el postflop no existe": si existe, lo da postflop_equity() y
        # el HUD lo pinta en su panel. Lo que no hay es una ACCION postflop, y es
        # a proposito -no hay rango postflop digitalizado, y convertir una
        # probabilidad en una orden seria justo lo que este repo rechaza-. El
        # texto viejo decia que el postflop era la Fase 4.3 (RAG) y que no
        # existia; se quedo caduco cuando entro el Monte Carlo y el usuario lo
        # leyo en el HUD como "se ha perdido la equity".
        return abstain("hay board: no se recomienda accion postflop (no hay rango "
                       "postflop digitalizado). La probabilidad de ganar SI se "
                       "calcula y sale en el panel de equity")

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

    stack_bb, stack_cacheado = _cached_hero_stack(hero)
    if stack_bb is None:
        return abstain("no se encontro el stack del hero en BB (ni reciente en cache); "
                       "no se puede calcular la profundidad")
    fuente = "stacks en BB"          # sin ciegas necesarias: el stack YA es la profundidad
    nota_cache = " stack cacheado de un frame anterior;" if stack_cacheado else ""

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
    if state.get("facing") == "bet":
        vs_position, code = _detect_raiser(state.get("players", []), BB)
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
            to_call = state.get("to_call") if _hay_que_igualar(state) else None
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
        to_call = _hay_que_igualar(state)
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
                    prueba.append("lo ultimo que se vio en la mesa fue a un rival SUBIR")
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
        callers = _contar_callers(state.get("players", []), vs_position)
        derivada = (squeeze(hero_cards, hero_position, vs_position, stack_bb, callers)
                    if callers >= 1 else None)
        if derivada is not None:
            action = derivada["action"]
            plural = "" if callers == 1 else "es"
            reasoning = (f"{callers} rival{plural} ya ha{'n' if plural else ''} pagado la "
                         f"subida de {vs_position}, asi que no es una defensa heads-up. "
                         f"INFERIDO de {derivada['donor']}, que en tu tabla dice "
                         f"'{derivada['donor_action']}': con gente dentro hay que apretar, y "
                         f"en tus tablas cada asiento aprieta la defensa un 15%. "
                         f"{stack_bb:.1f}bb efectivos ({fuente};{nota_cache})")
            derivada_meta = derivada
            translate_into({"action": action})       # valida que hay traduccion
            result = None
        else:
            result = recommend(hero_cards, hero_position, stack_bb,
                               facing="threebet_call", vs_position=vs_position)
        if derivada is None:
            if result is None:
                return abstain(f"sin rango de defensa para {hero_position} vs {vs_position} "
                               f"a {stack_bb:.1f}bb (threebet_call)")
            action = result["action"]
            reasoning = (f"Defensa (3bet/call) de {hero_position} a {stack_bb:.1f}bb efectivos "
                         f"contra la subida de {vs_position} ({fuente};{nota_cache} "
                         f"{origen_subida})"
                         + _stack_key_note(result, stack_bb, facing, warnings))
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

        limpers = _contar_limpers(state.get("players", []), state.get("acciones"))
        derivada = bb_option(hero_cards, stack_bb, limpers)
        if derivada is None:
            # sin donante valido (2+ limpers, o etiqueta que no se sabe traducir):
            # se queda el CHECK de siempre, que es la salida segura -pasar es
            # gratis- pero se dice que es un defecto, no una lectura de la mano.
            action = CHECK_BB_OPTION
            cuantos = (f"hay {limpers} rivales dentro" if isinstance(limpers, int)
                       else "no se pudo contar cuantos rivales han entrado")
            reasoning = (f"Estas en la BB con opcion a {stack_bb:.1f}bb ({fuente};{nota_cache} "
                         f"nadie ha subido, {cuantos}). Por defecto PASAR y ver el flop "
                         f"gratis: no tengo un rango tuyo para este spot con tantos rivales.")
        else:
            action = derivada["action"]
            reasoning = (f"Opcion de la BB a {stack_bb:.1f}bb ({fuente};{nota_cache} nadie ha "
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
            result = recommend(hero_cards, hero_position, stack_bb, facing="open_raise")
            if result is None:
                return abstain(f"sin rango de apertura para {hero_position} a {stack_bb:.1f}bb "
                               f"(open_raise); revisa que la posicion/stack esten en las tablas")
            action = result["action"]
            reasoning = (f"Rango de apertura de {hero_position} a {stack_bb:.1f}bb efectivos "
                         f"({fuente};{nota_cache} sin subida que enfrentar, el hero abre el bote)"
                         + _stack_key_note(result, stack_bb, facing, warnings))

    recommendation = {
        "action": action,
        "reasoning": reasoning,
        "hero_cards": hero_cards,
        "hero_position": hero_position,
        "stack_bb": stack_bb,
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
        recommendation["donor"] = derivada_meta["donor"]
        recommendation["assumptions"] = derivada_meta["assumptions"]
    else:
        recommendation["source"] = "chart"
    # action_en / action_es para el HUD. "action" se conserva con la etiqueta
    # CRUDA: es la que enlaza con ranges.json y la que registra el log, asi que
    # el historial de decisiones sigue siendo comparable entre versiones.
    translate_into(recommendation)
    _log_decision(state, recommendation, None)
    return recommendation
