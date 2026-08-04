"""Integración de las heurísticas GTO en el motor.

Los módulos sueltos (gto, board_texture, postflop_gto, gto_baseline) tienen sus
propios tests. Aquí solo se comprueba el CABLEADO: que decide() y
postflop_equity dejan la guía donde el HUD la busca y que el RFI de referencia
entra donde no había nada, sin desplazar a las tablas del usuario.
"""
import pytest

from decision import engine
from decision.preflop import gto_baseline


def _mesa(plazas, hero_pos, cards, stack, board=None, acciones=None):
    posiciones = {
        6: ("MP2", "HJ", "CO", "BTN", "SB", "BB"),
        9: ("EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB"),
    }[plazas]
    players = []
    for i, position in enumerate(posiciones):
        es_hero = position == hero_pos
        players.append({
            "seat": "HERO" if es_hero else f"S{i}",
            "position": position,
            "is_hero": es_hero,
            "in_hand": True,
            "stack": stack if es_hero else stack,
            "bet": 1.0 if position == "BB" else None,
        })
    return {
        "board": list(board or []),
        "hero_cards": list(cards),
        "hero_position": hero_pos,
        "facing": None,
        "stack_unit": "bb",
        "max_players": plazas,
        "pot": 1.5,
        "to_call": None,
        "players": players,
        "acciones": {"acciones": acciones or [
            {"seat": "S8" if plazas == 9 else "S5", "position": "BB",
             "accion": "post", "t": 100.0}], "completo": False},
        "warnings": [],
    }


# --- RFI de referencia a 100 BB --------------------------------------------

def test_una_mesa_de_nueve_a_cien_ciegas_deja_de_servir_la_tabla_de_cuarenta():
    """Era el agujero: las tablas digitalizadas llegan a 40 BB y para 9-max no
    hay suplemento de RangeConverter, así que _nearest_stack_key devolvía el
    rango de 40 BB como si fuera el del spot."""
    st = _mesa(9, "BTN", ("Ah", "Td"), 100.0)
    r = engine.decide(st)
    assert r is not None
    assert r["source"] == "gto_baseline_chart"
    assert r["action"] == "OPEN RAISE"
    assert r["stack_key"] == pytest.approx(100.0)
    assert "9-max" in r["reasoning"] or "9 plazas" in r["reasoning"]


def test_el_rfi_de_referencia_tambien_foldea():
    st = _mesa(9, "EP1", ("7h", "2d"), 100.0)
    r = engine.decide(st)
    assert r is not None and r["action"] == "FOLD"
    assert r["source"] == "gto_baseline_chart"


def test_no_desplaza_a_las_tablas_del_usuario_a_profundidad_corta():
    """A 30 BB la tabla digitalizada está mucho más cerca que un gráfico de 100,
    así que el motor tiene que seguir usando la suya."""
    st = _mesa(9, "BTN", ("Ah", "Td"), 30.0)
    r = engine.decide(st)
    assert r is not None
    assert r["source"] != "gto_baseline_chart"


def test_las_posiciones_sin_publicar_siguen_abstenidas_o_con_la_tabla_vieja():
    """EP2 y MP2 de una mesa de nueve no están en el gráfico y no se inventan;
    lo que salga de ahí no puede venir del baseline."""
    for posicion in ("EP2", "MP2"):
        st = _mesa(9, posicion, ("Ah", "Kd"), 100.0)
        r = engine.decide(st)
        assert r is None or r["source"] != "gto_baseline_chart"


def test_la_posicion_mas_temprana_de_una_mesa_de_seis_es_mp2_no_utg():
    """El primero en hablar de una mesa de 6 tiene cinco jugadores detrás: esta
    app lo llama MP2 y el gráfico lo llama UTG. Si la equivalencia se rompe,
    aquí se sirve el rango de otra posición."""
    assert gto_baseline.posicion_publicada("MP2", 6) == "UTG"
    st = _mesa(6, "MP2", ("Ah", "Jd"), 100.0)
    r = engine.decide(st)
    assert r is not None and r["action"] == "OPEN RAISE"
    # ATo no abre desde ahí: sirve para ver que no se está usando una fila más
    # tardía por error
    flojo = engine.decide(_mesa(6, "MP2", ("Ah", "Td"), 100.0))
    assert flojo is not None and flojo["action"] == "FOLD"


# --- guía postflop ----------------------------------------------------------

def _postflop(**kw):
    acciones = [
        {"seat": "S5", "position": "BB", "accion": "post", "t": 100.0},
        {"seat": "HERO", "position": "BTN", "accion": "raise", "t": 101.0},
        {"seat": "S5", "position": "BB", "accion": "call", "t": 102.0},
    ]
    st = _mesa(6, "BTN", ("Ac", "Qs"), 40.0,
               board=["Kh", "7d", "2c"], acciones=acciones)
    st["pot"] = 6.0
    st.update(kw)
    return st


def test_decide_sigue_sin_dar_accion_postflop_pero_ya_deja_la_guia():
    """El contrato de decide() no cambia -es el motor de rangos PREFLOP- y a la
    vez el panel del HUD deja de aparecer vacío."""
    st = _postflop()
    assert engine.decide(st) is None
    guia = st["gto"]
    assert guia["spot"] == "cbet"
    assert guia["action"].startswith("BET")
    assert any("guia postflop" in w for w in st["warnings"])


def test_la_guia_sin_equity_no_propone_pagar_ni_retirarse():
    """decide() corre antes que la simulación, así que su guía todavía no tiene
    equity: puede hablar de precio y MDF, no de si esta mano paga."""
    st = _postflop(facing="bet", to_call=2.0, pot=8.0)
    engine.decide(st)
    assert "action" not in st["gto"]
    assert st["gto"]["precio"]["mdf"] == pytest.approx(0.75)


def test_postflop_equity_pisa_la_guia_con_la_version_que_si_tiene_equity():
    st = _postflop(facing="bet", to_call=2.0, pot=8.0)
    engine.decide(st)
    eq = engine.postflop_equity(st, iterations=400, seed=7)
    assert eq is not None
    assert st["gto"]["action"] in ("FOLD", "MARGINAL CALL", "CALL", "RAISE (6 BB)")
    assert st["gto"]["precio"]["equity_estimada"] is not None
    # la guia vive SOLO en el estado: repetirla dentro del resultado de equity
    # duplicaria unos 2 KB en cada JSON de sesion grabada
    assert "gto" not in eq


def test_un_fallo_de_la_guia_no_tumba_el_analisis(monkeypatch):
    """decide() NO esta protegido por ningun try en core/analisis.py -a
    diferencia de la equity-, asi que si la guia propagase una excepcion se
    caeria el analisis entero del frame: ni recomendacion, ni equity, ni mano.
    Un board que el OCR deja imposible tiene que costar un aviso."""
    def revienta(*_a, **_k):
        raise RuntimeError("board imposible")

    monkeypatch.setattr(engine.postflop_gto, "evaluar", revienta)
    st = _postflop()
    assert engine.decide(st) is None                 # postflop siempre, sin reventar
    assert st["gto"] is None
    assert any("guia postflop: fallo interno" in w for w in st["warnings"])
    # y la equity se sigue calculando sobre ese mismo frame
    assert engine.postflop_equity(st, iterations=200, seed=3) is not None


def test_la_guia_deja_el_resumen_de_la_agresion_preflop_para_auditarla():
    """Es lo que explica por qué salió (o no salió) una c-bet."""
    st = _postflop()
    engine.decide(st)
    assert st["preflop_action"]["ultimo_agresor_seat"] == "HERO"
    assert st["gto"]["hero_es_agresor_preflop"] is True
