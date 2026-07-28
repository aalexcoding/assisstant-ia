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


def test_un_gamestate_sin_jugadores_no_revienta():
    assert al.ActionLog().observar_estado({}) == []
