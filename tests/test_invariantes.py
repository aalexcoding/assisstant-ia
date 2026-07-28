"""
Cada invariante de core/invariantes.py, provocado a proposito.

POR QUE HACE FALTA ESTO teniendo ya tests/test_invariantes_corpus.py: alli se
comprueba que los invariantes NO SALTAN sobre los 9.225 frames grabados, y de
hecho los de contrato estan a cero. Pero un invariante que nunca salta es
indistinguible de uno ROTO: si una comprobacion tuviera el signo cambiado o
mirara la clave equivocada, el corpus saldria igual de verde y el vigilante
llevaria meses sin ver nada.

Asi que aqui se hace lo contrario: se construye a mano un estado que viola cada
regla y se exige que la nombre. Los dos ficheros juntos dicen algo que ninguno
dice solo -"esto detecta lo que promete, Y no ha ocurrido"-, y son la diferencia
entre una red de seguridad y un adorno.
"""
import pytest

from core import invariantes as inv

RECO = {"action": "OPEN RAISE", "stack_bb": 20.0, "reasoning": "rango de apertura"}


def estado(**extra):
    """Un estado con mesa detectada y sin nada raro."""
    return dict({"hero_cards": ["Ah", "Kd"], "board": [], "players": [],
                 "hero_position": "BTN", "stack_unit": "bb", "warnings": [],
                 "mano_seguida": 1}, **extra)


def claves(fallos):
    return {c for c, _detalle in fallos}


# --- el suelo: sin mesa no se juzga nada ------------------------------------

@pytest.mark.parametrize("aviso", [
    "no se encuentra la mesa en la captura",
    "no se detecto el ovalo del tapete",
])
def test_sin_mesa_detectada_no_se_afirma_nada(aviso):
    """Si no se encuentra el ovalo, ninguna zona esta donde toca y los campos
    vienen vacios A PROPOSITO. Juzgarlos daria cientos de falsos positivos.

    El "sin mesa" se reconoce por el AVISO, no por un estado vacio: un estado
    vacio sin explicacion si es una contradiccion (ver abstiene_sin_motivo)."""
    st = {"players": [], "hero_cards": [], "board": [], "warnings": [aviso]}
    assert inv.de_frame(st) == []
    assert inv.de_frame(st, RECO) == []


def test_un_estado_vacio_SIN_explicacion_si_se_seniala():
    """Es la diferencia entre "no hay mesa" y "algo se ha roto y nadie lo dice"."""
    assert "abstiene_sin_motivo" in claves(inv.de_frame({}))


def test_un_estado_sano_no_produce_ni_un_fallo():
    assert inv.de_frame(estado(), RECO) == []


def test_una_abstencion_con_su_motivo_tampoco():
    assert inv.de_frame(estado(warnings=["no se lee tu stack"]), None) == []


# --- las reglas del juego ---------------------------------------------------

def test_un_board_con_carta_repetida():
    """No puede pasar en una mano de verdad: es un fallo de lectura."""
    f = inv.de_frame(estado(board=["2c", "2c", "9d"], warnings=["x"]))
    assert "board_repetido" in claves(f)


def test_una_carta_del_hero_tambien_en_el_board():
    f = inv.de_frame(estado(board=["Ah", "3c", "9d"], warnings=["x"]))
    assert "carta_en_dos_sitios" in claves(f)


def test_las_dos_cartas_del_hero_iguales():
    f = inv.de_frame(estado(hero_cards=["Ah", "Ah"], warnings=["x"]))
    assert "hero_repetida" in claves(f)


@pytest.mark.parametrize("n", [1, 2, 6, 7])
def test_un_board_de_longitud_imposible(n):
    """En Hold'em el board tiene 0, 3, 4 o 5 cartas. Cualquier otra cosa es OCR."""
    board = ["2c", "5c", "9d", "Ts", "Jh", "Qc", "Kd"][:n]
    f = inv.de_frame(estado(board=board, warnings=["x"]))
    assert "board_ilegal" in claves(f)


@pytest.mark.parametrize("n", [0, 3, 4, 5])
def test_un_board_de_longitud_legal_no_salta(n):
    board = ["2c", "5c", "9d", "Ts", "Jh"][:n]
    assert "board_ilegal" not in claves(inv.de_frame(estado(board=board, warnings=["x"])))


def test_mas_jugadores_de_los_que_caben():
    jug = [{"seat": f"S{i}"} for i in range(inv.MAX_JUGADORES + 1)]
    f = inv.de_frame(estado(players=jug, warnings=["x"]))
    assert "demasiados_jugadores" in claves(f)


def test_dos_asientos_marcados_como_hero():
    """Solo hay un "tu". Dos significa que el asiento del hero se confundio, y
    con el todo lo que se calcula respecto a el."""
    jug = [{"seat": "HERO", "is_hero": True}, {"seat": "UL", "is_hero": True}]
    f = inv.de_frame(estado(players=jug, warnings=["x"]))
    assert "dos_heroes" in claves(f)


def test_dos_asientos_con_la_misma_posicion():
    """Las posiciones salen del recuento de ocupados: una duplicada significa que
    el reparto entero esta mal."""
    jug = [{"seat": "UL", "position": "BTN"}, {"seat": "UR", "position": "BTN"}]
    f = inv.de_frame(estado(players=jug, warnings=["x"]))
    assert "posicion_duplicada" in claves(f)


@pytest.mark.parametrize("hero, vs", [("BTN", "BTN"), ("EP1", "CO"), ("SB", "BB")])
def test_el_raiser_al_que_defiendes_no_puede_hablar_DESPUES_que_tu(hero, vs):
    """Si habla despues, lo de delante no es una subida que defender sino una
    resubida a la apertura del propio hero, y las tablas no cubren eso."""
    f = inv.de_frame(estado(hero_position=hero, vs_position=vs, warnings=["x"]))
    assert "raiser_habla_despues" in claves(f)


@pytest.mark.parametrize("hero, vs", [("BB", "BTN"), ("CO", "EP1"), ("BTN", "HJ")])
def test_un_raiser_que_habla_antes_es_normal(hero, vs):
    f = inv.de_frame(estado(hero_position=hero, vs_position=vs, warnings=["x"]))
    assert "raiser_habla_despues" not in claves(f)


def test_un_rival_que_enseña_la_mano_no_puede_contar_como_retirado():
    """El caso del all-in: el cliente gira las cartas, el dorso desaparece y el
    recuento de rivales baja justo cuando mas importa (ver
    seat_map.revealed_pair_seats)."""
    jug = [{"seat": "ML", "revealed": True, "in_hand": False}]
    f = inv.de_frame(estado(players=jug, warnings=["x"]))
    assert "revelado_pero_retirado" in claves(f)


def test_un_rival_que_enseña_la_mano_Y_cuenta_esta_bien():
    jug = [{"seat": "ML", "revealed": True, "in_hand": True}]
    assert "revelado_pero_retirado" not in claves(inv.de_frame(estado(players=jug, warnings=["x"])))


def test_los_frames_viejos_sin_el_campo_revealed_no_disparan_nada():
    """Las sesiones grabadas antes de que existiera el campo no lo traen. El
    invariante vigila de aqui en adelante, no reprocha el pasado."""
    jug = [{"seat": "ML", "in_hand": False}]
    assert "revelado_pero_retirado" not in claves(inv.de_frame(estado(players=jug, warnings=["x"])))


# --- el contrato del motor --------------------------------------------------

def test_no_se_recomienda_sobre_una_mano_ya_abandonada():
    """Cartas apagadas = el hero ya se retiro. Recomendar ahi es peor que
    callarse: el usuario podria actuar sobre una mano que ya no tiene."""
    f = inv.de_frame(estado(hero_cards_dimmed=True), RECO)
    assert "recomienda_sobre_mano_abandonada" in claves(f)


@pytest.mark.parametrize("unidad", [None, "chips", "fichas", ""])
def test_no_se_recomienda_sin_declarar_que_los_importes_son_BB(unidad):
    """LA GUARDA. Un GameState con los stacks en fichas enteras daria una
    profundidad plausible y falsa, que es el peor fallo posible de esta app."""
    f = inv.de_frame(estado(stack_unit=unidad), RECO)
    assert "recomienda_sin_unidad" in claves(f)


def test_no_se_recomienda_una_ACCION_con_board_en_la_mesa():
    """No hay rango postflop digitalizado. La equity si se calcula, pero eso es
    una probabilidad y no una decision."""
    f = inv.de_frame(estado(board=["2c", "5c", "9d"]), RECO)
    assert "accion_postflop" in claves(f)


def test_toda_recomendacion_tiene_que_traer_la_profundidad():
    f = inv.de_frame(estado(), dict(RECO, stack_bb=None))
    assert "recomienda_sin_profundidad" in claves(f)


@pytest.mark.parametrize("accion", [None, "", 0])
def test_toda_recomendacion_tiene_que_traer_una_accion(accion):
    f = inv.de_frame(estado(), dict(RECO, action=accion))
    assert "recomienda_sin_accion" in claves(f)


@pytest.mark.parametrize("motivo", [None, "", "   "])
def test_toda_recomendacion_tiene_que_traer_su_motivo(motivo):
    """Una orden sin justificacion no se puede auditar, ni por el usuario ni
    despues."""
    f = inv.de_frame(estado(), dict(RECO, reasoning=motivo))
    assert "recomienda_sin_motivo" in claves(f)


def test_toda_abstencion_tiene_que_dejar_su_motivo():
    """Callarse sin decir por que es indistinguible de haberse colgado."""
    f = inv.de_frame(estado(warnings=[]), None)
    assert "abstiene_sin_motivo" in claves(f)


def test_un_estado_que_viola_varias_reglas_las_nombra_TODAS():
    """Devolver solo la primera escondería el resto y haria falta arreglar de una
    en una para ver la siguiente."""
    f = inv.de_frame(estado(board=["2c", "2c"], stack_unit="chips",
                            hero_cards_dimmed=True), dict(RECO, action=None))
    assert claves(f) >= {"board_repetido", "board_ilegal", "recomienda_sin_unidad",
                         "recomienda_sobre_mano_abandonada", "accion_postflop",
                         "recomienda_sin_accion"}


# --- entre frames consecutivos ----------------------------------------------

def par(a, b):
    return inv.de_serie((a, None), (b, None))


def test_el_numero_de_jugadores_no_puede_cambiar_a_mitad_de_mano():
    """Nadie se sienta ni se levanta con la mano en curso."""
    a = estado(players=[{"seat": "UL"}, {"seat": "UR"}])
    b = estado(players=[{"seat": "UL"}])
    assert "jugadores_cambian" in claves(par(a, b))


def test_la_posicion_del_hero_no_puede_cambiar_a_mitad_de_mano():
    """El boton no se mueve hasta que acaba la mano."""
    assert "posicion_cambia" in claves(par(estado(hero_position="BTN"),
                                          estado(hero_position="CO")))


def test_ENTRE_MANOS_todo_puede_cambiar_legitimamente():
    """Es justo lo que tiene que pasar: el boton avanza un asiento y la gente
    entra y sale."""
    a = estado(hero_position="BTN", players=[{"seat": "UL"}], mano_seguida=1)
    b = estado(hero_position="SB", players=[{"seat": "UL"}, {"seat": "UR"}], mano_seguida=2)
    assert par(a, b) == []


def test_sin_numero_de_mano_no_se_compara_nada():
    """Sin saber si son la misma mano, cualquier diferencia podria ser legitima."""
    a = estado(hero_position="BTN", mano_seguida=None)
    assert par(a, estado(hero_position="CO", mano_seguida=None)) == []


def test_una_posicion_que_aun_no_se_conoce_no_cuenta_como_cambio():
    """Pasar de None a BTN es la deteccion llegando, no el boton moviendose."""
    assert par(estado(hero_position=None), estado(hero_position="BTN")) == []
    assert par(estado(hero_position="BTN"), estado(hero_position=None)) == []


def test_sin_mesa_en_cualquiera_de_los_dos_frames_no_se_compara():
    assert par({}, estado(hero_position="CO")) == []
    assert par(estado(hero_position="BTN"), {}) == []
