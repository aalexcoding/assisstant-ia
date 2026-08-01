"""
Verificacion del historial de acciones (decision/action_log.py).

Lo que de verdad protege:

  1. La DEDUPLICACION. El mismo verbo esta en pantalla varios frames seguidos;
     contarlo dos veces convertiria una subida en dos y haria creer que hay una
     3bet donde solo hubo un open. Y lo contrario tambien: dos subidas de verdad
     del mismo asiento no pueden colapsarse en una.
  2. Que la lista NUNCA se presente como completa. El verbo dura menos que el
     periodo de muestreo, asi que faltan acciones por construccion; afirmar lo
     contrario llevaria a clasificar mal el spot.
"""
import pytest

from decision import action_log as al


@pytest.fixture
def log():
    """Un historial recien abierto. Cada test parte del suyo: el ActionLog es
    memoria de UNA mano, y compartirlo entre tests seria justo el bug que
    intenta evitar (acciones de una mano contadas en la siguiente)."""
    x = al.ActionLog()
    x.nueva_mano()
    return x


# --- normalizacion del verbo -------------------------------------------------

@pytest.mark.parametrize("verbo, esperado", [
    ("Pasar", "check"), ("Pasa", "check"),
    ("Igualar", "call"), ("Paga", "call"),
    ("Apostar", "bet"), ("Subir", "raise"), ("Resubir", "raise"),
    ("No ir", "fold"), ("All-in", "allin"), ("all in", "allin"),
])
def test_verbo_del_cliente_a_accion(verbo, esperado):
    assert al.normalizar(verbo) == esperado


def test_un_nick_no_es_una_accion():
    assert al.normalizar("Dav6934") is None


def test_vacio_tampoco():
    assert al.normalizar("") is None
    assert al.normalizar(None) is None


@pytest.mark.parametrize("estado", ["Ausente", "Sentado"])
def test_un_estado_no_es_una_accion(estado):
    """'Ausente'/'Sentado' son ESTADOS: no pueden entrar en la secuencia."""
    assert al.normalizar(estado) is None


# --- deduplicacion: lo mas importante ----------------------------------------

def test_el_mismo_verbo_en_cuatro_frames_es_una_sola_subida(log):
    for _ in range(4):
        log.observar("UL", "Subir")
    assert len(log.acciones()["acciones"]) == 1


def test_variantes_ocr_del_mismo_verbo_son_una_sola_accion(log):
    log.observar("UL", "Pasar")
    log.observar("UL", "Pasar ~>")

    assert [a["accion"] for a in log.acciones()["acciones"]] == ["check"]


@pytest.mark.parametrize("primera", ["Subir", "Apostar", "Igualar"])
def test_una_segunda_linea_allin_actualiza_el_evento_en_vez_de_duplicarlo(
        log, primera):
    log.observar("UL", primera)
    log.observar("UL", "; All-in")
    log.observar("UL", "All-in")

    acciones = log.acciones()["acciones"]
    assert len(acciones) == 1
    assert acciones[0]["accion"] == "allin"
    assert acciones[0]["orden"] == 1


def test_un_allin_tras_volver_el_nick_si_es_otra_accion(log):
    log.observar("UL", "Subir")
    log.observar("UL", None)
    log.observar("UL", "All-in")

    assert [a["accion"] for a in log.acciones()["acciones"]] == ["raise", "allin"]


def test_si_vuelve_a_verse_el_nick_y_sube_otra_vez_son_dos_subidas(log):
    for _ in range(4):
        log.observar("UL", "Subir")
    log.observar("UL", None)              # vuelve a verse el nick: cierra el evento
    log.observar("UL", "Subir")
    assert len(log.acciones()["acciones"]) == 2


def test_dos_verbos_distintos_seguidos_son_dos_acciones(log):
    log.observar("UL", "Subir")
    log.observar("UL", "Igualar")
    assert len(log.acciones()["acciones"]) == 2


# --- orden y contenido -------------------------------------------------------

@pytest.fixture
def log_mano(log):
    """Una mano con las cuatro acciones ya vistas, en orden."""
    log.observar("ML", "Poner", position="SB")
    log.observar("UL", "Subir", position="CO")
    log.observar("MR", "No ir", position="BTN")
    log.observar("HERO", "Igualar", position="BB")
    return log


def test_se_conserva_el_orden_en_que_se_vieron(log_mano):
    acc = log_mano.acciones()["acciones"]
    assert [a["accion"] for a in acc] == ["post", "raise", "fold", "call"]


def test_y_de_quien_fue_cada_una(log_mano):
    acc = log_mano.acciones()["acciones"]
    assert [a["position"] for a in acc] == ["SB", "CO", "BTN", "BB"]


def test_con_numero_de_orden_correlativo(log_mano):
    acc = log_mano.acciones()["acciones"]
    assert [a["orden"] for a in acc] == [1, 2, 3, 4]


def test_el_resumen_se_lee_de_un_vistazo(log_mano):
    assert log_mano.resumen() == "SB pone ciega · CO sube · BTN no va · BB paga"


# --- la ultima agresiva, que es lo que dice si el bote esta subido ------------

def test_la_ultima_agresiva_es_la_subida_de_co(log_mano):
    assert log_mano.ultima_agresiva()["position"] == "CO"


def test_una_apuesta_posterior_la_sustituye(log_mano):
    log_mano.observar("MR", "Apostar", position="BTN")
    assert log_mano.ultima_agresiva()["position"] == "BTN"


def test_un_pase_no_la_sustituye(log_mano):
    """Pasar no es agresivo, asi que no puede desplazar a la ultima apuesta."""
    log_mano.observar("MR", "Apostar", position="BTN")
    log_mano.observar("HERO", "Pasar", position="BB")
    assert log_mano.ultima_agresiva()["position"] == "BTN"


def test_sin_acciones_no_hay_ultima_agresiva(log):
    assert log.ultima_agresiva() is None


def test_con_solo_pases_tampoco_hay_ultima_agresiva(log):
    log.observar("UL", "Pasar")
    assert log.ultima_agresiva() is None


# --- LA HONESTIDAD: nunca se presenta como completo --------------------------

def test_la_lista_nunca_se_marca_completa(log_mano):
    """acciones() marca completo=False SIEMPRE: el verbo dura menos que el
    periodo de muestreo, asi que faltan acciones por construccion."""
    assert log_mano.acciones()["completo"] is False


# --- fronteras de mano -------------------------------------------------------

def test_una_mano_nueva_vacia_el_historial(log):
    log.observar("UL", "Subir")
    log.nueva_mano()
    assert log.acciones()["acciones"] == []


def test_una_mano_nueva_sube_el_contador(log):
    log.observar("UL", "Subir")
    antes = log.mano
    log.nueva_mano()
    assert log.mano == antes + 1


def test_el_mismo_verbo_vuelve_a_contar_en_otra_mano(log):
    log.observar("UL", "Subir")
    log.nueva_mano()
    log.observar("UL", "Subir")
    assert len(log.acciones()["acciones"]) == 1


# --- desde un GameState entero -----------------------------------------------

ESTADO = {"players": [{"seat": "UL", "action": "Subir", "position": "CO"},
                      {"seat": "MR", "action": None, "position": "BTN", "name": "pepe"},
                      {"seat": "HERO", "action": "Igualar", "position": "BB",
                       "is_hero": True}]}


def test_de_un_gamestate_salen_las_acciones_de_todos_los_asientos(log):
    assert len(log.observar_estado(ESTADO)) == 2


def test_el_que_muestra_su_nick_no_aporta_ninguna(log):
    nuevas = log.observar_estado(ESTADO)
    assert all(n["seat"] != "MR" for n in nuevas)


def test_repetir_el_mismo_estado_no_duplica_nada(log):
    log.observar_estado(ESTADO)
    assert log.observar_estado(ESTADO) == []


def test_el_lazo_lento_enriquece_la_accion_del_rapido_sin_duplicarla(log):
    log.observar("UL", "Apostar", t=1.0, street="flop")
    state = {
        "calle_seguida": "flop", "pot": 7.0,
        "players": [{
            "seat": "UL", "position": "BB", "action": "Apostar",
            "committed_calle": 2.0, "bet": 2.0,
        }],
    }
    assert log.observar_estado(state, t=1.1) == []
    [a] = log.acciones()["acciones"]
    assert a["street"] == "flop"
    assert a["position"] == "BB"
    assert a["pot_bb"] == 7.0


def test_un_gamestate_sin_jugadores_no_revienta():
    assert al.ActionLog().observar_estado({}) == []


def test_la_accion_conserva_calle_y_snapshots_sin_inventar_un_incremento(log):
    state = {
        "calle_seguida": "turn", "pot": 9.5,
        "players": [{
            "seat": "UL", "position": "BB", "action": "Apostar",
            "committed_calle": 4.0, "bet": 4.0,
        }],
    }
    [a] = log.observar_estado(state)
    assert a["street"] == "turn"
    assert a["pot_bb"] == 9.5
    assert a["committed_street_bb"] == 4.0
    assert a["bet_visible_bb"] == 4.0
    assert "amount_bb" not in a


# --- reconstrucción de la secuencia preflop ---------------------------------

def _estado(acciones, players=()):
    return {
        "acciones": {"acciones": acciones, "completo": False},
        "players": list(players),
    }


def test_el_estado_preflop_completa_la_posicion_por_el_asiento():
    st = _estado(
        [{"seat": "TOPC", "position": None, "accion": "allin"}],
        [{"seat": "TOPC", "position": "CO"}],
    )
    r = al.estado_preflop(st)
    assert r["ultimo_agresor_position"] == "CO"


def test_open_y_allin_de_otro_jugador_es_una_resubida_observada():
    st = _estado([
        {"seat": "ML", "accion": "raise"},
        {"seat": "TOPC", "accion": "allin"},
    ])
    r = al.estado_preflop(st)
    assert r["nivel"] == "resubida_observada"
    assert r["agresiones_observadas"] == 2
    assert r["ultimo_agresor_seat"] == "TOPC"


def test_una_apuesta_de_flop_no_se_cuenta_como_resubida_preflop():
    st = _estado([
        {"seat": "ML", "accion": "raise", "street": "preflop"},
        {"seat": "TOPC", "accion": "bet", "street": "flop"},
    ])
    r = al.estado_preflop(st)
    assert r["nivel"] == "apertura_observada"
    assert r["agresiones_observadas"] == 1
    assert r["ultimo_agresor_seat"] == "ML"


def test_un_fold_posterior_no_borra_la_ultima_resubida():
    st = _estado([
        {"seat": "ML", "accion": "raise"},
        {"seat": "TOPC", "accion": "allin"},
        {"seat": "UR", "accion": "fold"},
    ])
    assert al.estado_preflop(st)["ultimo_agresor_seat"] == "TOPC"


def test_detecta_la_resubida_que_devuelve_la_accion_al_hero():
    st = _estado([
        {"seat": "HERO", "accion": "raise"},
        {"seat": "ML", "accion": "fold"},
        {"seat": "TOPC", "accion": "allin"},
    ], [{"seat": "TOPC", "position": "SB"}])
    r = al.estado_preflop(st)
    assert r["hero_ultima_accion"] == "raise"
    assert r["rival_agresion_posterior_hero"] is True
    assert r["rival_posterior_position"] == "SB"
    assert r["primera_agresion_seat"] == "HERO"
    assert r["agresiones_antes_hero"] == 0
    assert r["agresiones_hero"] == 1
    assert r["callers_entre_hero_y_resubida"] == 0


def test_cuenta_un_cold_call_entre_el_open_del_hero_y_el_squeeze():
    st = _estado([
        {"seat": "HERO", "accion": "raise"},
        {"seat": "SB", "accion": "call"},
        {"seat": "BB", "accion": "raise"},
    ])
    r = al.estado_preflop(st)
    assert r["callers_entre_hero_y_resubida"] == 1


def test_repetir_un_allin_antiguo_no_inventa_otra_resubida():
    st = _estado([
        {"seat": "TOPC", "accion": "allin"},
        {"seat": "UR", "accion": "fold"},
        {"seat": "TOPC", "accion": "allin"},
    ])
    r = al.estado_preflop(st)
    assert r["nivel"] == "apertura_observada"
    assert r["agresiones_observadas"] == 1


def test_una_agresion_anterior_a_la_ultima_ciega_es_residual():
    """Sesión 2026-07-31_022832, frame 0311: el all-in pertenecía a la
    transición anterior; la ciega del HERO se observó dos segundos después."""
    st = _estado([
        {"seat": "TOPC", "accion": "post", "t": 100.0},
        {"seat": "UR", "accion": "post", "t": 100.0},
        {"seat": "ML", "accion": "allin", "t": 100.0},
        {"seat": "HERO", "accion": "post", "t": 102.0},
    ])
    r = al.estado_preflop(st)
    assert r["nivel"] == "sin_agresion_observada"
    assert r["ultima_agresion"] is None
    assert r["acciones_antes_del_ultimo_post"] == 3


def test_una_agresion_posterior_a_todas_las_ciegas_si_es_actual():
    st = _estado([
        {"seat": "TOPC", "accion": "post", "t": 100.0},
        {"seat": "HERO", "accion": "post", "t": 102.0},
        {"seat": "ML", "accion": "allin", "t": 105.0},
        {"seat": "UR", "accion": "fold", "t": 106.0},
    ])
    r = al.estado_preflop(st)
    assert r["nivel"] == "apertura_observada"
    assert r["ultima_agresion"] == "allin"


def test_estado_preflop_distingue_limp_antes_y_call_despues_del_shove():
    st = _estado([
        {"seat": "HERO", "accion": "post", "t": 100.0},
        {"seat": "UL", "accion": "call", "t": 101.0},
        {"seat": "ML", "accion": "allin", "t": 102.0},
        {"seat": "UR", "accion": "call", "t": 103.0},
        {"seat": "TOPC", "accion": "fold", "t": 104.0},
    ])
    r = al.estado_preflop(st)
    assert r["callers_antes_primera_agresion"] == 1
    assert r["callers_despues_ultima_agresion"] == 1


def test_limpers_observados_deduplican_y_respetan_la_ultima_accion():
    st = _estado([
        {"seat": "HERO", "accion": "post", "t": 100.0},
        {"seat": "UL", "accion": "call", "t": 101.0},
        {"seat": "UL", "accion": "call", "t": 102.0},
        {"seat": "ML", "accion": "call", "t": 103.0},
        {"seat": "ML", "accion": "fold", "t": 104.0},
    ])
    assert al.estado_preflop(st)["limper_seats_observed"] == ["UL"]


def test_un_call_anterior_a_la_ultima_ciega_no_es_un_limper_actual():
    st = _estado([
        {"seat": "UL", "accion": "call", "t": 99.0},
        {"seat": "HERO", "accion": "post", "t": 100.0},
        {"seat": "ML", "accion": "call", "t": 101.0},
    ])
    assert al.estado_preflop(st)["limper_seats_observed"] == ["ML"]


def test_los_folds_alrededor_del_shove_no_cuentan_como_callers():
    st = _estado([
        {"seat": "HERO", "accion": "post", "t": 100.0},
        {"seat": "UL", "accion": "fold", "t": 101.0},
        {"seat": "ML", "accion": "allin", "t": 102.0},
        {"seat": "UR", "accion": "fold", "t": 103.0},
    ])
    r = al.estado_preflop(st)
    assert r["callers_antes_primera_agresion"] == 0
    assert r["callers_despues_ultima_agresion"] == 0


def test_una_agresion_en_el_mismo_frame_que_la_ultima_ciega_es_ambigua():
    st = _estado([
        {"seat": "HERO", "accion": "post", "t": 100.0},
        {"seat": "ML", "accion": "raise", "t": 100.0},
    ])
    r = al.estado_preflop(st)
    assert r["nivel"] == "sin_agresion_observada"
    assert r["agresion_ambigua_arranque"] is True
