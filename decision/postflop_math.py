"""Ayuda matemática postflop, deliberadamente separada de una recomendación.

PokerStars muestra ``Bote`` incluyendo las fichas que el rival ya ha apostado
(comprobado en el corpus: sesión 2026-07-31_022832, frame 0400 muestra 4,75 BB
en el centro + 1 BB delante del rival = ``Bote: 5,75 BB``). Por tanto:

    equity mínima = cantidad a pagar / (bote mostrado + cantidad a pagar)

Es la misma identidad ``call / pot after calling`` derivada de EV en:
https://blog.gtowizard.com/what-are-pot-odds-in-poker/

Compararla con equity de check-down es solo una referencia. No modela que el
rango que apuesta es más fuerte, equity realization, apuestas futuras, implied
odds, rake ni ICM; por eso este módulo nunca devuelve CALL/FOLD.

Desde la entrada de decision/gto.py el precio viene acompañado de las dos cifras
de equilibrio del MISMO tamaño: cuántos foldeos necesitaba el farol del rival
(alpha) y qué parte del rango hay que defender para negárselos (MDF). Son
exactas -salen de bote y apuesta, no de una estimación- y siguen sin ser una
orden: el MDF habla de un RANGO y las pot odds de una MANO. Quién junta las dos
cosas con la equity y sí propone acción es decision/postflop_gto.py.
"""
from decision import gto


def _numero_positivo(value):
    return (isinstance(value, (int, float))
            and not isinstance(value, bool) and value > 0)


def calcular(state, equity=None):
    """Métricas de una decisión de call, o ``None`` si la lectura no basta."""
    board = state.get("board") or []
    if len(board) not in (3, 4, 5) or state.get("facing") != "bet":
        return None
    pot = state.get("pot")
    call = state.get("to_call")
    if not _numero_positivo(pot) or not _numero_positivo(call):
        return None

    final_pot = pot + call
    required = call / final_pot
    hero = next((p for p in state.get("players") or [] if p.get("is_hero")), None)
    rivals = [p for p in state.get("players") or []
              if p.get("in_hand") and not p.get("is_hero")]
    hero_stack = (hero or {}).get("stack")
    rival_stacks = [p.get("stack") for p in rivals
                    if _numero_positivo(p.get("stack"))]
    effective = (min([hero_stack, *rival_stacks])
                 if _numero_positivo(hero_stack) and rival_stacks else None)
    result = {
        "pot_bb": round(float(pot), 2),
        "call_bb": round(float(call), 2),
        "final_pot_bb": round(float(final_pot), 2),
        "required_equity": round(required, 4),
        "pot_includes_opponent_bet": True,
        "street": {3: "flop", 4: "turn", 5: "river"}[len(board)],
        "effective_stack_bb": round(float(effective), 2) if effective else None,
        # Es el SPR en el instante capturado, después de la apuesta visible; no
        # se etiqueta como "SPR del flop" porque no se guardó aquel snapshot.
        "current_spr": round(effective / pot, 2) if effective else None,
        "estimated_equity": None,
        "raw_margin_pp": None,
        "raw_call_ev_bb": None,
        # Equilibrio del tamaño que acaba de apostar el rival. bote_antes es el
        # bote SIN su apuesta: las fórmulas publicadas usan ese, no el que
        # dibuja el cliente. Si la resta no da un bote positivo, las tres cifras
        # quedan a None en vez de calcularse sobre una lectura imposible.
        "alpha": None,
        "mdf": None,
        "value_to_bluff": None,
        "bet_pct_of_pot": None,
        "note": (
            "comparación orientativa con equity de check-down; no es CALL/FOLD "
            "porque el rango que apuesta y la equity realizable no están modelados"),
    }
    bote_antes = gto.bote_antes_de(pot, call)
    equilibrio = gto.resumen(call, bote_antes) if bote_antes is not None else None
    if equilibrio is not None:
        result.update(
            alpha=equilibrio["alpha"],
            mdf=equilibrio["mdf"],
            value_to_bluff=equilibrio["ratio_valor_farol"],
            bet_pct_of_pot=equilibrio["tamano_pct"],
        )

    estimate = (equity or {}).get("equity")
    if isinstance(estimate, (int, float)) and 0 <= estimate <= 1:
        result["estimated_equity"] = round(float(estimate), 4)
        result["raw_margin_pp"] = round((estimate - required) * 100, 1)
        # EV respecto a foldear si la equity se realizase íntegramente y no
        # hubiese rake ni apuestas posteriores.
        result["raw_call_ev_bb"] = round(estimate * final_pot - call, 2)
    return result
