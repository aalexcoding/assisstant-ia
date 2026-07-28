"""
Verificacion del rastreador de mano (decision/hand_tracker.py).

Lo que de verdad protege: la DIRECCION de los errores. El comprometido derivado
es una cota inferior y se usa solo para ATRIBUIR una subida que el boton
"Igualar" ya ha demostrado; si esa asimetria se rompe, el motor puede acabar
recomendando una defensa contra un raiser inventado, que es el peor fallo posible
en esta app.
"""
import pytest

from decision import engine
from decision import hand_tracker as ht


def estado(stacks, board=(), hero=(), bets=None, posiciones=None, to_call=None):
    """GameState minimo: {asiento: stack}. stack None = nameplate ilegible."""
    bets = bets or {}
    posiciones = posiciones or {}
    return {
        "board": list(board),
        "hero_cards": list(hero),
        "to_call": to_call,
        "players": [{"seat": s, "stack": v, "bet": bets.get(s),
                     "position": posiciones.get(s),
                     "is_hero": s == "HERO"}
                    for s, v in stacks.items()],
    }


def com(info, seat):
    return info["asientos"][seat]["comprometido"]


def calentar(tr, st, n=None):
    """Una mano tiene que durar MIN_FRAMES_POR_MANO antes de poder cortarse."""
    for _ in range(n or ht.MIN_FRAMES_POR_MANO):
        info = tr.update(st)
    return info


# --- lo basico: el stack baja, eso es lo que ha puesto -----------------------

def test_una_bajada_de_stack_es_lo_comprometido():
    tr = ht.HandTracker()
    tr.update(estado({"UL": 87.9, "HERO": 50.0}))
    info = tr.update(estado({"UL": 60.5, "HERO": 50.0}))
    assert com(info, "UL") == 27.4
    assert com(info, "HERO") == 0, "el que no se movio sigue a cero"


def test_no_se_acumula_por_volver_a_ver_el_mismo_stack():
    tr = ht.HandTracker()
    tr.update(estado({"UL": 87.9}))
    tr.update(estado({"UL": 60.5}))
    assert com(tr.update(estado({"UL": 60.5})), "UL") == 27.4


# --- un nameplate ilegible no puede borrar lo que ya se sabia ---------------

def test_un_frame_sin_lectura_conserva_el_comprometido():
    tr = ht.HandTracker()
    tr.update(estado({"UL": 40.0}))
    tr.update(estado({"UL": 36.0}))
    assert com(tr.update(estado({"UL": None})), "UL") == 4.0


def test_tras_un_hueco_se_sigue_contando_desde_la_base_de_la_mano():
    tr = ht.HandTracker()
    tr.update(estado({"UL": 40.0}))
    tr.update(estado({"UL": 36.0}))
    tr.update(estado({"UL": None}))
    assert com(tr.update(estado({"UL": 30.0})), "UL") == 10.0


# --- LO CRITICO: una lectura ALTA no puede reventar la base -----------------

@pytest.fixture
def tras_lectura_imposible():
    """El punto decimal perdido: 106,5 leido como 1065. Es un error real medido."""
    tr = ht.HandTracker()
    tr.update(estado({"UL": 106.5}))
    tr.update(estado({"UL": 100.0}))
    return tr, tr.update(estado({"UL": 1065.0}))


def test_una_lectura_por_encima_de_la_base_se_descarta(tras_lectura_imposible):
    """Dentro de una mano el stack no puede subir."""
    _tr, info = tras_lectura_imposible
    assert com(info, "UL") == 6.5


def test_la_lectura_descartada_se_cuenta(tras_lectura_imposible):
    """Para poder desconfiar de un asiento que da muchas."""
    _tr, info = tras_lectura_imposible
    assert info["asientos"]["UL"]["lecturas_descartadas"] == 1


def test_la_serie_sigue_siendo_utilizable_despues_del_disparate(tras_lectura_imposible):
    tr, _info = tras_lectura_imposible
    assert com(tr.update(estado({"UL": 98.0})), "UL") == 8.5


# --- fronteras de mano -------------------------------------------------------
# Las señales se eligieron midiendo contra el numero de mano del chat sobre 3.300
# frames de tres sesiones. Juegos comparados por cuantos cortes REALES detectan:
#     chat + cartas distintas (lo de antes)   44/75 = 59%
#     chat + cartas_aparecen                  58/75 = 77%
#     chat + cartas_aparecen + board_vacio     68/75 = 91%

def test_dentro_de_la_mano_se_acumula():
    tr = ht.HandTracker()
    calentar(tr, estado({"UL": 50.0}, hero=("Ah", "Kd")))
    info = tr.update(estado({"UL": 46.0}, hero=("Ah", "Kd")))
    assert com(info, "UL") == 4.0


def test_perder_las_cartas_un_frame_y_recuperarlas_no_parte_la_mano():
    """CARTAS QUE APARECEN ya NO corta. Parecia solida -35 de 52 cortes reales-
    pero aquella medida solo contaba los cortes que se ACIERTAN, nunca los que se
    inventan. Con el boton hay por fin vara para medir la PRECISION, y la señal
    resulta ser 94% falsa: provocaba 66 de los 82 cortes falsos."""
    tr = ht.HandTracker()
    calentar(tr, estado({"UL": 50.0}))
    m0 = tr.update(estado({"UL": 46.0}))["mano"]
    info = tr.update(estado({"UL": 62.0}, hero=("7c", "2d")))
    assert info["mano"] == m0


def test_la_señal_de_cartas_que_aparecen_se_sigue_exponiendo():
    """No corta, pero es informativa para depurar."""
    motivos = ht.motivos_de_frontera(
        ht._vista(estado({"UL": 46.0})),
        ht._vista(estado({"UL": 62.0}, hero=("7c", "2d"))))
    assert "cartas_aparecen" in motivos


@pytest.fixture
def tras_mover_el_boton():
    tr = ht.HandTracker()
    calentar(tr, estado({"UL": 50.0, "MR": 30.0}, posiciones={"UL": "BTN"}))
    m0 = tr.update(estado({"UL": 46.0, "MR": 30.0}, posiciones={"UL": "BTN"}))["mano"]
    return m0, tr.update(estado({"UL": 62.0, "MR": 30.0}, posiciones={"MR": "BTN"}))


def test_el_boton_en_otro_asiento_es_mano_nueva(tras_mover_el_boton):
    m0, info = tras_mover_el_boton
    assert info["mano"] == m0 + 1


def test_al_cortar_por_boton_la_base_se_rehace(tras_mover_el_boton):
    """El que gano el bote no puede aparecer comprometido en la mano siguiente."""
    _m0, info = tras_mover_el_boton
    assert com(info, "UL") == 0


def test_se_registra_por_que_se_corto(tras_mover_el_boton):
    _m0, info = tras_mover_el_boton
    assert "boton" in info["motivos_apertura"]


def test_tras_cortar_sin_mover_el_boton_las_posiciones_no_estan_asentadas():
    """El cliente recoge las cartas ANTES de mover el boton, asi que un corte por
    board_vacio cae 1-2 frames antes de que las posiciones roten. Medido: 119
    frames con la posicion caducada y 36 recomendaciones emitidas con ella."""
    tr = ht.HandTracker()
    calentar(tr, estado({"UL": 50.0}, board=("Ah", "Kd", "2c"), posiciones={"UL": "BTN"}),
             n=ht.MIN_FRAMES_POR_MANO + 1)
    info = tr.update(estado({"UL": 50.0}, posiciones={"UL": "BTN"}))   # board_vacio
    assert info["posiciones_asentadas"] is False
    info = tr.update(estado({"UL": 50.0, "MR": 30.0}, posiciones={"MR": "BTN"}))
    assert info["posiciones_asentadas"] is True, "se asientan al mover el boton"


def test_la_primera_mano_no_hereda_posiciones_de_nadie():
    """Si el boton nunca se ha visto moverse no se bloquea nada."""
    tr = ht.HandTracker()
    calentar(tr, estado({"UL": 50.0}, posiciones={"UL": "BTN"}),
             n=ht.MIN_FRAMES_POR_MANO + 1)
    assert tr.resumen()["posiciones_asentadas"] is True


def test_una_carta_del_hero_mal_leida_no_parte_la_mano():
    """CARTAS DISTINTAS ya NO corta: parecia la señal mas fuerte y medida acierta
    3 de 52, y en una sesion sus 4 disparos fueron TODOS falsos (el OCR lee mal
    una carta del hero el 2,4% de los frames)."""
    tr = ht.HandTracker()
    calentar(tr, estado({"UL": 50.0}, hero=("Ah", "Kd")))
    m0 = tr.update(estado({"UL": 46.0}, hero=("Ah", "Kd")))["mano"]
    info = tr.update(estado({"UL": 44.0}, hero=("7c", "2d")))
    assert info["mano"] == m0
    assert "cartas" not in ht.MOTIVOS_DE_CORTE


def test_el_board_que_se_vacia_es_mano_nueva():
    """Una mano empieza siempre preflop. Se descarto en la primera medicion (267
    frames) y con 3.300 resulta ser de las mejores: 35 de 52, cero falsos."""
    tr = ht.HandTracker()
    calentar(tr, estado({"UL": 50.0}, board=("2h", "3h", "4h")))
    m0 = tr.update(estado({"UL": 46.0}, board=("2h", "3h", "4h")))["mano"]
    assert tr.update(estado({"UL": 46.0}, board=()))["mano"] == m0 + 1


def test_el_numero_de_mano_del_chat_ya_no_corta():
    """Era LA REFERENCIA de este modulo. Es una etiqueta estable de la mano, pero
    hay que LEERLA y el OCR la lee mal: va y viene entre dos manos y a veces
    inventa una. Contra la verdad de campo (104 numeros distintos en 100 minutos)
    pasaba de 111 manos a 150, un +44%, y de 21 cortes falsos a 71."""
    tr = ht.HandTracker()
    for _ in range(ht.MIN_FRAMES_POR_MANO):
        tr.update(estado({"UL": 50.0}), hand_number="111")
    assert com(tr.update(estado({"UL": 46.0}), hand_number="111"), "UL") == 4.0
    assert com(tr.update(estado({"UL": 44.0}), hand_number="222"), "UL") == 6.0


def test_la_señal_del_chat_se_sigue_exponiendo():
    motivos = ht.motivos_de_frontera(ht._vista(estado({"UL": 50.0}), "111"),
                                     ht._vista(estado({"UL": 50.0}), "222"))
    assert "mano_chat" in motivos


def test_una_mano_no_dura_dos_frames():
    """Las señales se solapan -el board se vacia y el boton se mueve en un par de
    segundos- asi que una frontera real dispara varias veces. Sin minimo, el
    rastreador veia 110 manos donde el chat contaba 53."""
    tr = ht.HandTracker()
    tr.update(estado({"UL": 50.0}, board=("2h", "3h", "4h")))
    assert tr.update(estado({"UL": 50.0}))["mano"] == 1


# --- las señales que NO cortan, y por que (medido) ---------------------------

def test_un_board_de_longitud_ilegal_no_parte_la_mano():
    """Un board de 2 cartas es basura de OCR, no una calle."""
    tr = ht.HandTracker()
    tr.update(estado({"UL": 50.0}, board=("Qc", "Qs", "8s", "Ks", "Tc")))
    assert com(tr.update(estado({"UL": 44.0}, board=("7c", "Ac"))), "UL") == 6.0


def test_perder_el_board_un_frame_tampoco_la_parte():
    tr = ht.HandTracker()
    tr.update(estado({"UL": 50.0}, board=("Qc", "Qs", "8s")))
    assert com(tr.update(estado({"UL": 44.0}, board=())), "UL") == 6.0


def test_la_señal_de_board_se_expone_pero_no_corta():
    v1 = ht._vista(estado({"UL": 50.0}, board=("Qc", "Qs", "8s")))
    v2 = ht._vista(estado({"UL": 50.0}, board=("2h", "3h", "4h")))
    assert "board" in ht.motivos_de_frontera(v1, v2)
    assert "board" not in ht.MOTIVOS_DE_CORTE


def test_la_subida_de_stack_no_corta():
    """Medida, resulto ser error de OCR y no una mano nueva."""
    assert "stack_sube" not in ht.MOTIVOS_DE_CORTE


# --- COMPROMETIDO POR CALLE --------------------------------------------------
# El total de la mano no dice si hay una apuesta que igualar AHORA: en el turn,
# lo que un rival puso en el flop ya esta en el bote. Separarlo por calle es lo
# que permite distinguir un squeeze de una resubida.

def test_preflop_la_calle_y_la_mano_llevan_lo_mismo():
    """Asi nada de lo que ya funcionaba cambia."""
    tr = ht.HandTracker()
    assert tr.update(estado({"UL": 50.0}))["calle"] == "preflop"
    a = tr.update(estado({"UL": 46.0}))["asientos"]["UL"]
    assert a["comprometido"] == a["comprometido_calle"] == 4.0


@pytest.fixture
def por_calles():
    """Una mano que pasa de preflop a flop y luego a turn, con apuesta en el flop."""
    tr = ht.HandTracker()
    tr.update(estado({"UL": 50.0}))
    tr.update(estado({"UL": 46.0}))                                  # 4 en preflop
    return tr


def test_al_salir_el_flop_la_calle_arranca_de_cero(por_calles):
    i = por_calles.update(estado({"UL": 46.0}, board=("2h", "3h", "4h")))
    assert i["calle"] == "flop"
    assert i["asientos"]["UL"]["comprometido_calle"] == 0.0, "lo del preflop ya esta en el bote"
    assert i["asientos"]["UL"]["comprometido"] == 4.0, "pero el total se conserva"


def test_una_apuesta_en_el_flop_cuenta_en_la_calle_y_suma_al_total(por_calles):
    por_calles.update(estado({"UL": 46.0}, board=("2h", "3h", "4h")))
    a = por_calles.update(estado({"UL": 40.0}, board=("2h", "3h", "4h")))["asientos"]["UL"]
    assert a["comprometido_calle"] == 6.0
    assert a["comprometido"] == 10.0


def test_el_turn_vuelve_a_poner_la_calle_a_cero(por_calles):
    por_calles.update(estado({"UL": 46.0}, board=("2h", "3h", "4h")))
    por_calles.update(estado({"UL": 40.0}, board=("2h", "3h", "4h")))
    i = por_calles.update(estado({"UL": 40.0}, board=("2h", "3h", "4h", "9s")))
    assert i["calle"] == "turn"
    assert i["asientos"]["UL"]["comprometido_calle"] == 0.0


def test_un_board_mas_corto_no_retrocede_la_calle(por_calles):
    """La calle SOLO AVANZA: un board mas corto es una lectura perdida, no una
    calle anterior. Si retrocediera, una lectura floja borraria lo que un rival
    lleva puesto en la calle en curso."""
    por_calles.update(estado({"UL": 46.0}, board=("2h", "3h", "4h")))
    por_calles.update(estado({"UL": 40.0}, board=("2h", "3h", "4h")))
    por_calles.update(estado({"UL": 40.0}, board=("2h", "3h", "4h", "9s")))
    i = por_calles.update(estado({"UL": 34.0}, board=("2h", "3h", "4h")))
    assert i["calle"] == "turn"
    assert i["asientos"]["UL"]["comprometido_calle"] == 6.0


def test_un_asiento_visto_a_mitad_de_calle_empieza_en_cero():
    """No puede inventarse una base."""
    tr = ht.HandTracker()
    tr.update(estado({"UL": 50.0}, board=("2h", "3h", "4h")))
    i = tr.update(estado({"UL": 50.0, "MR": 30.0}, board=("2h", "3h", "4h")))
    assert i["asientos"]["MR"]["comprometido_calle"] == 0.0


# --- corroboracion con el importe leido en la mesa ---------------------------

@pytest.mark.parametrize("derivado, leido, esperado", [
    (3.75, 3.8, "coinciden"),
    (3.9, 2.52, "discrepan"),
    (4.0, None, "solo_derivado"),
    (None, 4.0, "solo_leido"),
])
def test_acuerdo_entre_las_dos_señales(derivado, leido, esperado):
    assert ht.acuerdo(derivado, leido) == esperado


# --- LA REGLA DE SEGURIDAD: el comprometido no CREA subidas -----------------

JUGADORES = [
    {"seat": "UL", "position": "CO", "committed": 4.0, "is_hero": False},
    {"seat": "ML", "position": "BB", "committed": 1.0, "is_hero": False},
    {"seat": "HERO", "position": "BTN", "committed": 0.0, "is_hero": True},
]


def test_con_el_boton_pidiendo_cuatro_se_atribuye_al_que_puso_cuatro():
    assert ht.atribuir_subida(JUGADORES, to_call=4.0) == ("CO", "UL")


def test_sin_boton_que_pida_nada_no_se_atribuye_nada():
    """LA GARANTIA CENTRAL: por muy grande que sea el comprometido, el derivado no
    puede inventarse un raiser."""
    assert ht.atribuir_subida(JUGADORES, to_call=None) == (None, "sin_to_call")


@pytest.mark.parametrize("desc, jugadores, to_call, motivo", [
    ("si nadie llega a lo que pide el boton", JUGADORES, 20.0, "nadie_lo_explica"),
    ("con dos candidatos no se adivina (igual que detect_raiser)",
     JUGADORES + [{"seat": "UR", "position": "HJ", "committed": 4.0, "is_hero": False}],
     4.0, "varios_candidatos"),
    ("un candidato sin posicion no sirve para elegir rango",
     [{"seat": "UL", "position": None, "committed": 4.0, "is_hero": False}],
     4.0, "candidato_sin_posicion"),
    ("el propio hero nunca es el raiser al que defender",
     [{"seat": "HERO", "position": "BTN", "committed": 9.0, "is_hero": True}],
     4.0, "nadie_lo_explica"),
])
def test_cuando_no_se_puede_atribuir_se_dice_por_que(desc, jugadores, to_call, motivo):
    assert ht.atribuir_subida(jugadores, to_call=to_call) == (None, motivo), desc


def test_se_tolera_quedarse_un_poco_corto():
    """El comprometido es COTA INFERIOR: si la mano ya habia empezado cuando se
    vio al rival, la base ya esta rebajada."""
    pos, _ = ht.atribuir_subida(
        [{"seat": "UL", "position": "CO", "committed": 3.8, "is_hero": False}], to_call=4.0)
    assert pos == "CO"


def test_pero_no_quedarse_corto_de_mas():
    pos, _ = ht.atribuir_subida(
        [{"seat": "UL", "position": "CO", "committed": 3.0, "is_hero": False}], to_call=4.0)
    assert pos is None


# --- aplicar() cuelga el dato de los jugadores -------------------------------

def test_aplicar_cuelga_el_comprometido_de_cada_jugador():
    tr = ht.HandTracker()
    st = estado({"UL": 50.0, "HERO": 30.0}, posiciones={"UL": "CO", "HERO": "BTN"})
    tr.update(st)
    st2 = estado({"UL": 46.0, "HERO": 30.0}, posiciones={"UL": "CO", "HERO": "BTN"})
    ht.aplicar(st2, tr.update(st2))
    ul = next(p for p in st2["players"] if p["seat"] == "UL")
    assert ul["committed"] == 4.0
    assert ul["committed_calle"] == 4.0
    assert ul["committed_acuerdo"] == "solo_derivado"
    assert st2["mano_seguida"] == 1


def test_un_gamestate_sin_seat_no_rastrea_nada_ni_lanza():
    """Las rutas de diagnostico no ponen 'seat'."""
    tr = ht.HandTracker()
    info = tr.update({"players": [{"stack": 50.0, "is_hero": True}],
                      "board": [], "hero_cards": []})
    assert info["asientos"] == {}


# --- el nombre no se pierde cuando el cliente lo tapa con el verbo ----------
# El cliente sustituye el nick por la accion ("Pasar", "Igualar") JUSTO cuando el
# jugador actua, que es cuando mas falta hace saber quien es.

def con_nombre(nombre, accion, cartas=("Ah", "Kd"), boton="UL"):
    return {"board": [], "hero_cards": list(cartas), "to_call": None,
            "players": [{"seat": "UL", "name": nombre, "action": accion,
                         "stack": 50.0, "is_hero": False,
                         "position": "BTN" if boton == "UL" else None},
                        {"seat": "MR", "name": "otro", "action": None,
                         "stack": 30.0, "is_hero": False,
                         "position": "BTN" if boton == "MR" else None}]}


def test_un_nombre_legible_se_muestra_tal_cual():
    tr = ht.HandTracker()
    s = con_nombre("Dav6934", None)
    ht.aplicar(s, tr.update(s))
    assert s["players"][0]["name"] == "Dav6934"
    assert not s["players"][0].get("name_repuesto")


def test_cuando_el_cliente_tapa_el_nick_con_el_verbo_se_repone():
    tr = ht.HandTracker()
    s1 = con_nombre("Dav6934", None)
    ht.aplicar(s1, tr.update(s1))
    s2 = con_nombre(None, "Igualar")
    ht.aplicar(s2, tr.update(s2))
    assert s2["players"][0]["name"] == "Dav6934"
    assert s2["players"][0].get("name_repuesto") is True, "se marca que no es leido"


def test_una_lectura_suelta_no_tumba_al_nombre_visto_muchas_veces():
    """SE FIJA POR MAYORIA, no por "el ultimo bueno". El OCR lee el mismo nick de
    formas distintas casi cada frame: medido, un asiento dio OCHO variantes en una
    mano ("juanpalla", "Juanpalia", "juanpaila"...) con 40 cambios, y en el HUD eso
    se ve como un nombre que no para de bailar. Con la mayoria: 59 -> 12 cambios."""
    tr = ht.HandTracker()
    for _ in range(9):
        s = con_nombre("Dav6934", None)
        ht.aplicar(s, tr.update(s))
    s3 = con_nombre("Dav693A", None)          # una variante suelta del OCR
    ht.aplicar(s3, tr.update(s3))
    assert s3["players"][0]["name"] == "Dav6934"
    assert s3["players"][0].get("name_repuesto") is True


def test_si_la_lectura_nueva_se_vuelve_mayoritaria_se_adopta():
    """No es un latch."""
    tr = ht.HandTracker()
    for _ in range(9):
        s = con_nombre("Dav6934", None)
        ht.aplicar(s, tr.update(s))
    for _ in range(20):
        s4 = con_nombre("Dav693A", None)
        ht.aplicar(s4, tr.update(s4))
    assert s4["players"][0]["name"] == "Dav693A"


# ENTRE MANOS SE RECUERDA, pero solo como RESPALDO.
#
# Antes no se recordaba nada, por el caso de Zoom -el cliente te cambia de mesa
# entre manos, asi que el ocupante de un asiento puede ser otra persona-. Medido,
# eso dejaba el HUD lleno de "(?)": 308 y 337 filas de jugador sin nombre sobre
# 250 frames de dos sesiones (una de cada cinco), y en una de ellas 335 de las
# 337 eran de un asiento cuyo nombre YA se habia leido en una mano anterior.

@pytest.fixture
def tras_dos_manos():
    """Un asiento con nombre fijado, y luego una mano nueva sin lectura."""
    tr = ht.HandTracker()
    for _ in range(9):
        s = con_nombre("Dav693A", None)
        ht.aplicar(s, tr.update(s))
    s = con_nombre(None, "Pasar", cartas=())                          # se recogen las cartas
    ht.aplicar(s, tr.update(s))
    s = con_nombre(None, "Pasar", cartas=("7c", "2d"), boton="MR")    # el boton rota
    ht.aplicar(s, tr.update(s))
    return tr, s


def test_en_una_mano_nueva_sin_lectura_se_enseña_el_ultimo_nombre_conocido(tras_dos_manos):
    _tr, s = tras_dos_manos
    assert s["players"][0]["name"] == "Dav693A"
    assert s["players"][0].get("name_de_mano_anterior") is True


def test_si_el_asiento_cambia_de_ocupante_la_lectura_nueva_manda(tras_dos_manos):
    """El caso Zoom: el respaldo NO es un latch."""
    tr, _s = tras_dos_manos
    for _ in range(3):
        s5 = con_nombre("otroJugador9", None, cartas=("7c", "2d"), boton="MR")
        ht.aplicar(s5, tr.update(s5))
    assert s5["players"][0]["name"] == "otroJugador9"
    assert s5["players"][0].get("name_de_mano_anterior") is not True


def mesa(asientos, boton, cartas=("Ah", "Kd")):
    """asientos = [(seat, nombre)]; el boton nombra el asiento que lo tiene."""
    return {"board": [], "hero_cards": list(cartas), "to_call": None,
            "players": [{"seat": s, "name": n, "action": None, "stack": 40.0,
                         "is_hero": False,
                         "position": "BTN" if s == boton else None}
                        for s, n in asientos]}


TRES = [("UL", "sentado_uno"), ("MR", "otro"), ("UR", "tercero")]
SIN_UL = [("MR", "otro"), ("UR", "tercero")]


def test_un_asiento_que_no_se_ve_en_toda_una_mano_olvida_su_nombre():
    """Es la señal de que ahi ya no esta quien estaba. Sin esto el respaldo no
    caduca nunca y sostiene al ocupante anterior indefinidamente; lo noto el
    usuario: "los nombres no terminan de actualizarse cuando cambio un jugador de
    asiento"."""
    tr = ht.HandTracker()
    for _ in range(4):
        s = mesa(TRES, "UL")
        ht.aplicar(s, tr.update(s))
    assert s["players"][0]["name"] == "sentado_uno"

    # UNA MANO ENTERA SIN ESE ASIENTO: el jugador se levanto o se cambio de sitio
    ht.aplicar(mesa(SIN_UL, "MR"), tr.update(mesa(SIN_UL, "MR")))     # frontera
    for _ in range(4):
        s = mesa(SIN_UL, "MR")
        ht.aplicar(s, tr.update(s))
    s = mesa(SIN_UL, "UR")                                           # otra frontera
    ht.aplicar(s, tr.update(s))

    # y ahora vuelve a haber alguien en UL, con el nick ilegible
    s7 = mesa([("UL", None), ("MR", "otro"), ("UR", "tercero")], "UR")
    ht.aplicar(s7, tr.update(s7))
    assert s7["players"][0].get("name") is None, "no se enseña al ocupante anterior"
    assert s7["players"][1].get("name") == "otro", "los que si se vieron conservan el suyo"


# --- integracion con el motor ------------------------------------------------
# La propiedad que hace SEGURO el cambio: el comprometido solo puede convertir
# una ABSTENCION en recomendacion, nunca cambiar una recomendacion que ya habia.
# Medido sobre una sesion real entera (1.173 frames): 20 nuevas, 0 cambiadas, 0
# perdidas. Aqui se fija con casos sinteticos para que no se pueda romper.

def spot(committed=None, bet=None, to_call=None):
    """Hero en CO con AKo a 20bb, enfrentando algo. UL es el rival en HJ."""
    engine.reset_state()
    return {
        "hero_cards": ["Ah", "Kd"], "board": [], "pot": None, "blinds": None,
        "stack_unit": "bb", "hero_position": "CO", "facing": "bet",
        "to_call": to_call, "warnings": [],
        "players": [
            {"seat": "UL", "position": "HJ", "stack": 20.0, "bet": bet,
             "committed": committed, "is_hero": False},
            {"seat": "HERO", "position": "CO", "stack": 20.0, "bet": None,
             "committed": 0.0, "is_hero": True},
        ],
    }


def test_sin_importe_en_la_mesa_que_explique_la_subida_el_motor_se_abstiene():
    assert engine.decide(spot(committed=None, bet=None, to_call=4.0)) is None


def test_con_el_comprometido_derivado_si_recomienda_y_es_una_defensa():
    con = engine.decide(spot(committed=4.0, bet=None, to_call=4.0))
    assert con is not None
    assert con["facing_used"] == "threebet_call"
    assert con["vs_position"] == "HJ", "contra la posicion correcta"
    assert "bajada de stack" in con["reasoning"], \
        "el razonamiento dice DE DONDE salio la subida"


def test_si_la_mesa_explica_la_subida_el_comprometido_no_cambia_nada():
    """El importe leido manda cuando existe: es la señal ya validada."""
    leido = engine.decide(spot(committed=None, bet=4.0, to_call=4.0))
    enganya = engine.decide(spot(committed=99.0, bet=4.0, to_call=4.0))
    assert leido is not None and enganya is not None
    assert leido["vs_position"] == enganya["vs_position"] == "HJ"


def test_sin_to_call_un_comprometido_disparatado_no_crea_una_defensa():
    """LA GARANTIA CENTRAL, vista desde el motor: se sigue por el rango de
    apertura, no aparece un raiser de la nada."""
    r = engine.decide(spot(committed=99.0, bet=None, to_call=None))
    assert r is not None
    assert r["facing_used"] == "open_raise"
