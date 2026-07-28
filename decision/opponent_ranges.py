"""
Rangos de rival para la simulacion de equity, derivados de decision/preflop/
ranges.json, es decir de las MISMAS tablas que el usuario digitalizo de sus
capturas.

POR QUE NO UNA TABLA DE "TIGHTNESS" INVENTADA
---------------------------------------------
El enunciado pedia asignar rangos "mas cerrados contra varios jugadores o en
posiciones tempranas, mas amplios en posiciones tardias". Sus tablas YA hacen
exactamente eso, y con numeros con procedencia. Medido sobre ranges.json a 20bb,
como fraccion de los 1326 combos posibles:

    EP1 17,0%   EP2 18,6%   MP1 20,8%   MP2 25,0%
    HJ  27,6%   CO  35,0%   BTN 47,2%   SB  85,5%
    BB defendiendo vs BTN: 91,0%

Monotono de posicion temprana a tardia, cobertura completa de las 8 posiciones y
las 11 profundidades. Inventar una tabla equivalente seria poner numeros sin
origen en un proyecto cuya norma es documentar de donde sale cada cifra.

Y la eleccion importa MUCHO: sobre un spot real de las capturas, la equity del
hero pasa de 28% (rivales con mano aleatoria) a 14% (rivales con rango de BTN) a
6% (rango de EP1). El supuesto de rango mueve la respuesta mas que ninguna otra
decision del modelo, asi que tiene que salir de datos reales y viajar declarado
al lado del numero.

QUE RANGO SE USA PARA CADA RIVAL
--------------------------------
  - rival que NO es la BB -> open_raise[profundidad][posicion], todos los buckets
    MENOS "fold". Es "el rango con el que ese asiento ENTRO al bote desde esa
    posicion a esa profundidad", que incluye LIMP y MARGINAL, correctamente: un
    limp tambien ve el flop.
  - rival en la BB -> threebet_call[profundidad]["BB"][vs], todos menos "fold".
    Para la BB el objeto estructuralmente correcto es un rango de DEFENSA, no de
    apertura: la BB nunca abre (ya tiene la ciega puesta).

PESOS: 169 manos -> 1326 combos
-------------------------------
Una pareja son 6 combinaciones, una suited 4 y una offsuit 12. Muestrear las 169
manos con igual probabilidad haria AA tan frecuente como AKo, un sesgo de 2x.
Por eso se expande a combos reales antes de muestrear.

LIMITACION HONESTA, la mas importante de todo el modulo: estos son rangos de
ENTRADA (preflop). Un rival que sigue vivo en el turn ademas ha PAGADO una
apuesta en el flop, asi que su rango real es mas fuerte que este. Como estrechar
el rango del rival casi siempre baja la equity del hero, el numero que sale es
tipicamente un TECHO. Quien lo muestre tiene que decirlo.
"""
import numpy as np

from decision import hand_eval
from decision.preflop import lookup
from decision.preflop.lookup import _nearest_stack_key

# orden de rangos de la notacion de ranges.json ("AKs", "72o", "TT")
_NOTACION = "AKQJT98765432"

_CACHE = {}


def _combos_de_mano(mano):
    """'AA' -> 6 combos, 'AKs' -> 4, 'K6o' -> 12. Devuelve lista de (id1, id2)."""
    r1 = hand_eval.RANK_INDEX[mano[0]]
    r2 = hand_eval.RANK_INDEX[mano[1]]
    if len(mano) == 2:                       # pareja
        return [(r1 * 4 + a, r1 * 4 + b) for a in range(4) for b in range(a + 1, 4)]
    if mano[2] == "s":
        return [(r1 * 4 + s, r2 * 4 + s) for s in range(4)]
    return [(r1 * 4 + a, r2 * 4 + b) for a in range(4) for b in range(4) if a != b]


def _expandir(manos):
    """Lista de manos en notacion -> np.int32 (M, 2) con los combos reales."""
    out = []
    for m in manos:
        out.extend(_combos_de_mano(m))
    return np.array(out, dtype=np.int32).reshape(-1, 2)


def _no_fold(celda):
    """Manos de una celda {accion: [manos]} quitando el bucket 'fold'."""
    return [h for accion, manos in celda.items() if accion.lower() != "fold" for h in manos]


def _celda(facing, stack_bb, position, vs_position=None):
    """Devuelve (manos, stack_key, avisos) o (None, stack_key, avisos)."""
    avisos = []
    tabla = lookup.RANGES.get(facing)
    if not tabla:
        return None, None, [f"no existe la familia de rangos {facing!r}"]
    key = _nearest_stack_key(stack_bb, tabla.keys())
    pos_t = tabla[key].get(position)
    if pos_t is None:
        return None, float(key), [f"{position} no tiene rango de {facing} a {key}bb"]

    if facing != "threebet_call":
        return _no_fold(pos_t), float(key), avisos

    # threebet_call lleva un nivel mas: contra quien
    if vs_position is not None and vs_position in pos_t:
        return _no_fold(pos_t[vs_position]), float(key), avisos
    if not pos_t:
        return None, float(key), [f"{position} no tiene rangos de defensa a {key}bb"]
    # Postflop no se sabe contra quien defendio (las apuestas preflop ya estan en
    # el bote): se unen todas las defensas disponibles. Cuesta poco, porque los
    # rangos de defensa de la BB rondan el 86-91% de los combos, casi aleatorio.
    if vs_position is not None:
        avisos.append(f"{position} no tiene rango de defensa contra {vs_position} a {key}bb; "
                      f"se une la defensa contra el resto de posiciones")
    manos = sorted({h for vs in pos_t for h in _no_fold(pos_t[vs])})
    return manos, float(key), avisos


def entering_combos(position, stack_bb, *, vs_position=None):
    """Combos con los que un rival en esa posicion habria ENTRADO al bote.

    Devuelve (combos np.int32 (M,2), meta). combos es None si no hay rango; meta
    siempre trae el porque. meta = {position, role, stack_key, hands, combos,
    pct_of_all, source, extrapolated, warnings}."""
    meta = {"position": position, "role": None, "stack_key": None, "hands": 0,
            "combos": 0, "pct_of_all": 0.0, "source": None, "extrapolated": False,
            "warnings": []}

    if position is None:
        # NUNCA se inventa una posicion. Sin boton detectado, el rival es
        # cualquier mano: se dice, y el numero sale con ese supuesto encima.
        combos = random_combos()
        meta.update(role="unknown", source="aleatorio (posicion desconocida)",
                    hands=169, combos=len(combos), pct_of_all=1.0)
        meta["warnings"].append("no se conoce la posicion del rival; se le supone "
                                "cualquier mano (rango del 100%)")
        return combos, meta

    if position == "BB":
        facing, role = "threebet_call", "defensa"
        manos, key, avisos = _celda(facing, stack_bb, "BB", vs_position)
        if manos is None:
            # a 10bb la carpeta de origen 3BET-CALL/10BB/BB esta vacia de verdad
            # (documentado en prompt.md), asi que se busca la profundidad mas
            # cercana que SI tenga defensa de la BB
            disponibles = [k for k in lookup.RANGES[facing] if "BB" in lookup.RANGES[facing][k]]
            if disponibles:
                key2 = _nearest_stack_key(stack_bb, disponibles)
                manos, key, avisos2 = _celda(facing, float(key2), "BB", vs_position)
                avisos = avisos + avisos2 + [
                    f"no hay rango de defensa de la BB a {stack_bb:.0f}bb "
                    f"(no existe en el material de origen); se usa el de {key2}bb"]
    else:
        facing, role = "open_raise", "entrada"
        manos, key, avisos = _celda(facing, stack_bb, position)

    meta["stack_key"] = key
    meta["warnings"].extend(avisos)
    if manos is None:
        meta["role"] = None
        return None, meta

    clave = (facing, key, position, vs_position if position == "BB" else None)
    if clave not in _CACHE:
        _CACHE[clave] = _expandir(manos)
    combos = _CACHE[clave]

    meta.update(role=role, hands=len(manos), combos=len(combos),
                pct_of_all=len(combos) / 1326.0,
                source=f"ranges.json {facing}[{key:g}bb][{position}]"
                       + (f"[vs {vs_position}]" if position == "BB" and vs_position else ""))
    # misma politica de honestidad que engine._stack_key_note: si la profundidad
    # real cae fuera de la rejilla digitalizada, el rango es una extrapolacion
    rejilla = sorted(float(k) for k in lookup.RANGES[facing])
    if key is not None and (stack_bb > rejilla[-1] + 0.25 or stack_bb < rejilla[0] - 0.25):
        meta["extrapolated"] = True
        meta["warnings"].append(
            f"profundidad {stack_bb:.1f}bb fuera de la tabla de {facing} "
            f"({rejilla[0]:g}-{rejilla[-1]:g}bb); el rango de {position} es una extrapolacion")
    return combos, meta


def generic_combos(stack_bb):
    """Rango de un rival del que no se sabe la posicion pero si que ENTRO al bote:
    las manos que aparecen en al menos la mitad de los rangos de entrada de esa
    profundidad. Sale de los datos del usuario, no de una tightness inventada; en
    la practica ronda la anchura de HJ/MP2."""
    tabla = lookup.RANGES["open_raise"]
    key = _nearest_stack_key(stack_bb, tabla.keys())
    filas = [_no_fold(c) for c in tabla[key].values()]
    if not filas:
        return random_combos(), {"role": "generic", "source": None}
    cuenta = {}
    for manos in filas:
        for h in manos:
            cuenta[h] = cuenta.get(h, 0) + 1
    umbral = len(filas) / 2.0
    manos = sorted(h for h, c in cuenta.items() if c >= umbral)
    combos = _expandir(manos)
    return combos, {"role": "generic", "stack_key": float(key), "hands": len(manos),
                    "combos": len(combos), "pct_of_all": len(combos) / 1326.0,
                    "source": f"manos presentes en >=50% de los rangos de entrada a {key}bb",
                    "extrapolated": False, "warnings": [], "position": None}


_ALL = None


def random_combos():
    """Los 1326 combos. Techo teorico: un rival del que no se supone nada."""
    global _ALL
    if _ALL is None:
        pares = [(a, b) for a in range(52) for b in range(a + 1, 52)]
        _ALL = np.array(pares, dtype=np.int32)
    return _ALL
