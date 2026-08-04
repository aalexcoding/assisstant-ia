"""
Los helpers PUROS de gui.py: los que convierten un GameState en lo que el
usuario acaba leyendo en pantalla.

No levantan ventana ni necesitan display -son funciones y staticmethods-, pero
importan gui, asi que hace falta PyGObject.

POR QUE MERECEN TESTS pese a ser "solo pintar":

  - cards_markup y players_markup construyen MARKUP de Pango a base de concatenar
    cadenas. Un nick con un "&" o un "<" -y los nicks los escribe un desconocido-
    rompe el markup, y GTK entonces no pinta el panel: la app se queda sin
    mostrar la mesa por culpa de como se llama alguien.
  - _no_reco_reason es lo UNICO que ve el usuario cuando la app no recomienda.
    Su orden de comprobaciones no es cosmetico: primero lo que invalida todo lo
    demas (sin mesa no hay zona en su sitio), y segundo lo que el usuario puede
    arreglar en dos segundos (el selector de tamaño de mesa mal puesto). Si ese
    orden se altera, el sintoma vuelve a ser "no dice nada" sin causa visible.
  - _result_sig decide si el panel de la mano anterior se refresca o parpadea.
"""
import pytest

gi = pytest.importorskip("gi", reason="hace falta PyGObject")
gi.require_version("Gtk", "4.0")

import gui                                # noqa: E402

pytestmark = pytest.mark.gtk

VENTANA = gui.PokerAssistantWindow


# --- cartas ------------------------------------------------------------------

def test_sin_cartas_se_pinta_un_guion_y_no_una_lista_vacia():
    assert gui.cards_markup([]) == "<i>-</i>"
    assert gui.cards_markup(None) == "<i>-</i>"


@pytest.mark.parametrize("codigo", ["Ah", "Kd", "Ts", "2c"])
def test_una_carta_lleva_su_rango_y_el_simbolo_de_su_palo(codigo):
    m = gui.cards_markup([codigo])
    assert codigo[:-1] in m
    assert gui.SUIT_SYMBOLS[codigo[-1].lower()] in m
    assert gui.SUIT_COLORS[codigo[-1].lower()] in m


def test_los_cuatro_palos_se_pintan_de_colores_distintos():
    """Es lo que permite ver un proyecto de color de un vistazo."""
    colores = {gui.SUIT_COLORS[p] for p in "hdcs"}
    assert len(colores) == 4


def test_una_carta_ilegible_no_rompe_el_markup():
    """El OCR devuelve basura de vez en cuando y eso no puede dejar el panel en
    blanco: se escapa y se pinta tal cual."""
    for basura in ["", "X", None, "???"]:
        assert isinstance(gui.cards_markup([basura]), str)


def test_las_dos_cartas_del_hero_salen_separadas():
    m = gui.cards_markup(["Ah", "Kd"])
    assert m.count("<span") == 2


# --- jugadores ---------------------------------------------------------------

def test_sin_jugadores_se_dice_y_no_se_deja_en_blanco():
    assert "sin jugadores" in gui.players_markup([])
    assert "sin jugadores" in gui.players_markup(None)


def test_un_jugador_muestra_nombre_posicion_y_stack_CON_unidad():
    """Sin la unidad, 44,5 BB y 44,5 fichas se ven igual, y son cosas
    completamente distintas para decidir."""
    m = gui.players_markup([{"name": "pepe", "position": "BTN", "stack": 44.5}])
    assert "pepe" in m and "[BTN]" in m and "44.5 BB" in m


def test_el_hero_se_marca_para_no_confundirse_de_asiento():
    m = gui.players_markup([{"name": "yo", "stack": 10.0, "is_hero": True}])
    assert "(TU)" in m


def test_un_stack_sin_leer_sale_como_interrogacion_y_no_como_cero():
    """Cero seria mentira: un stack que no se ha podido leer no es un jugador
    sin fichas."""
    m = gui.players_markup([{"name": "pepe", "stack": None}])
    assert "?" in m and "0 BB" not in m


def test_un_nombre_que_no_se_leyo_sale_como_interrogante():
    assert "(?)" in gui.players_markup([{"name": None, "stack": 5.0}])


def test_un_nombre_de_una_mano_ANTERIOR_se_pinta_en_cursiva():
    """El respaldo de nombres rellena el 24% de las filas del HUD, pero no todo
    lo que rellena sigue siendo verdad: de 859 mano-asiento sostenidos por el
    respaldo, 106 resultaron ser otra persona. El HUD no puede saber cual es
    cual, pero si puede dejar de afirmarlo con la misma confianza que una lectura
    de este frame."""
    ahora = gui.players_markup([{"name": "pepe", "stack": 5.0}])
    antes = gui.players_markup([{"name": "pepe", "stack": 5.0,
                                 "name_de_mano_anterior": True}])
    assert "<i>pepe</i>" in antes
    assert "<i>" not in ahora


def test_el_nombre_se_escapa_una_sola_vez_aunque_vaya_en_cursiva():
    """La cursiva envuelve al nombre YA escapado. Escapar despues convertiria el
    propio <i> en texto, y escapar dos veces dejaria un &amp;lt; a la vista."""
    m = gui.players_markup([{"name": "a<b>&c", "stack": 1.0,
                             "name_de_mano_anterior": True}])
    assert "<i>a&lt;b&gt;&amp;c</i>" in m


def test_lo_comprometido_se_pinta_como_COTA_INFERIOR():
    """Es una cota inferior porque si la mano ya habia empezado cuando se vio al
    jugador por primera vez, se pierde lo que puso antes. El simbolo lo dice."""
    m = gui.players_markup([{"name": "a", "stack": 5.0, "committed": 2.5}])
    assert "≥2.5 BB" in m


def test_lo_comprometido_va_en_verde_solo_cuando_la_mesa_lo_corrobora():
    """Verde = el importe dibujado en la mesa dice lo mismo que el descuadre del
    stack. Gris = solo se tiene una de las dos fuentes."""
    verde = gui.players_markup([{"name": "a", "stack": 5.0, "committed": 2.0,
                                 "committed_acuerdo": "coinciden"}])
    gris = gui.players_markup([{"name": "a", "stack": 5.0, "committed": 2.0,
                                "committed_acuerdo": "discrepan"}])
    assert "#2ecc71" in verde
    assert "#2ecc71" not in gris


def test_un_comprometido_de_cero_no_ensucia_la_linea():
    assert "≥" not in gui.players_markup([{"name": "a", "stack": 5.0, "committed": 0}])


def test_la_accion_del_cliente_se_muestra_aparte_del_nick():
    """El cliente TAPA el nick con el verbo justo cuando ese jugador actua, asi
    que el rastreador repone el nombre y la accion se enseña al lado."""
    m = gui.players_markup([{"name": "pepe", "stack": 5.0, "action": "Subir"}])
    assert "pepe" in m and "Subir" in m


@pytest.mark.parametrize("nick", ["a&b", "<script>", 'x"y', "a<b>c", "&amp;"])
def test_un_NICK_CON_CARACTERES_DE_MARKUP_no_rompe_el_panel(nick):
    """Los nicks los escribe un desconocido. Un "&" sin escapar deja el markup
    invalido y GTK no pinta NADA: la app se quedaria sin mesa en pantalla por
    culpa de como se llama alguien. Se comprueba que Pango lo acepta."""
    from gi.repository import Pango
    m = gui.players_markup([{"name": nick, "stack": 5.0, "action": nick}])
    Pango.parse_markup(m, -1, "\0")       # lanza si el markup es invalido


def test_una_accion_con_caracteres_raros_tampoco():
    from gi.repository import Pango
    m = gui.players_markup([{"name": "a", "stack": 1.0, "action": "Igualar & subir <x>"}])
    Pango.parse_markup(m, -1, "\0")


def test_cada_jugador_ocupa_una_linea():
    m = gui.players_markup([{"name": "a", "stack": 1.0}, {"name": "b", "stack": 2.0}])
    assert len(m.split("\n")) == 2


# --- por que no hay recomendacion -------------------------------------------

def test_lo_PRIMERO_que_se_dice_es_que_no_se_encuentra_la_mesa():
    """Invalida todo lo demas: sin la referencia del tapete ninguna zona esta
    donde toca, asi que cualquier otro motivo seria una consecuencia."""
    st = {"warnings": ["no se encuentra la mesa en la captura",
                       "faltan las 2 cartas del hero"],
          "hero_cards": [], "players": []}
    assert "no se encuentra la mesa" in VENTANA._no_reco_reason(st)


def test_el_tamaño_de_mesa_mal_puesto_se_nombra_Y_se_dice_como_arreglarlo():
    """Sin esto el sintoma es "no dice nada" y no hay forma de adivinar la causa,
    aunque se arregle en dos segundos con el selector."""
    st = {"warnings": ["5 asientos ocupados en una mesa de 3"],
          "hero_cards": ["Ah", "Kd"], "players": [{"name": "a"}]}
    r = VENTANA._no_reco_reason(st)
    assert "asientos ocupados en una mesa de" in r
    assert "'Mesa'" in r or "Mesa" in r


def test_el_tamaño_de_mesa_gana_a_cualquier_otro_aviso_menos_al_de_la_mesa():
    st = {"warnings": ["faltan las 2 cartas del hero",
                       "5 asientos ocupados en una mesa de 3"],
          "hero_cards": [], "players": []}
    assert "asientos ocupados" in VENTANA._no_reco_reason(st)


def test_sin_mesa_ni_cartas_se_sugiere_que_quiza_no_hay_partida():
    st = {"warnings": [], "hero_cards": [], "players": []}
    r = VENTANA._no_reco_reason(st)
    assert "lobby" in r or "mesa de poker" in r


def test_postflop_se_explica_que_no_hay_rango_digitalizado():
    """Y de paso que la equity que si sale es una probabilidad, no una decision.
    Es la confusion mas facil de cometer con este panel."""
    st = {"warnings": [], "hero_cards": ["Ah", "Kd"], "board": ["2c", "5c", "9d"],
          "players": [{"name": "a"}]}
    r = VENTANA._no_reco_reason(st)
    assert "ostflop" in r
    assert "probabilidad" in r and "decision" in r


def test_sin_cartas_se_explica_que_puede_no_ser_tu_mano():
    st = {"warnings": [], "hero_cards": ["Ah"], "hero_position": "BTN",
          "players": [{"name": "a"}]}
    assert "2 cartas" in VENTANA._no_reco_reason(st)


def test_sin_posicion_se_nombra_el_boton_del_dealer():
    st = {"warnings": [], "hero_cards": ["Ah", "Kd"], "players": [{"name": "a"}]}
    assert "boton de dealer" in VENTANA._no_reco_reason(st)


def test_sin_stack_en_BB_se_explica_el_ajuste_del_cliente():
    """Es el caso mas comun con todo lo demas listo, y el unico que el usuario
    puede arreglar: parse_amount_bb EXIGE el sufijo "BB", asi que no leerlo casi
    siempre significa que el cliente no esta en modo big blinds."""
    st = {"warnings": [], "hero_cards": ["Ah", "Kd"], "hero_position": "BTN",
          "players": [{"name": "yo", "is_hero": True, "stack": None}]}
    r = VENTANA._no_reco_reason(st)
    assert "BIG BLINDS" in r
    assert "adivinar" in r or "falsa" in r, "y por que se abstiene en vez de suponer"


def _listo(**extra):
    """Un estado con todo lo que las comprobaciones anteriores exigen, para poder
    llegar al final de la cadena."""
    return dict({"warnings": [], "hero_cards": ["Ah", "Kd"], "hero_position": "BTN",
                 "players": [{"name": "yo", "is_hero": True, "stack": 20.0}]}, **extra)


def test_si_no_encaja_ningun_caso_se_devuelve_el_ultimo_aviso_tecnico():
    st = _listo(warnings=["algo muy concreto que paso"])
    assert VENTANA._no_reco_reason(st) == "algo muy concreto que paso"


def test_sin_ningun_aviso_se_dice_algo_igualmente():
    """Nunca se deja el panel vacio: el usuario tiene que poder distinguir "no
    aplica" de "se ha colgado"."""
    assert VENTANA._no_reco_reason(_listo()).strip()


# --- firma de la mano terminada ---------------------------------------------

def test_dos_resultados_iguales_dan_la_misma_firma():
    """Es lo que evita que el panel de la mano anterior parpadee en cada frame."""
    r = {"winner": "pepe", "amount": "1.200", "winning_hand": "trio de ases"}
    assert VENTANA._result_sig(dict(r)) == VENTANA._result_sig(dict(r))


@pytest.mark.parametrize("campo, valor", [
    ("winner", "otro"), ("amount", "999"), ("winning_hand", "color"),
])
def test_cambiar_cualquiera_de_los_tres_campos_cambia_la_firma(campo, valor):
    base = {"winner": "pepe", "amount": "1.200", "winning_hand": "trio de ases"}
    assert VENTANA._result_sig(base) != VENTANA._result_sig(dict(base, **{campo: valor}))


def test_un_resultado_a_medias_da_firma_igualmente():
    """Sirve de respaldo cuando no se lee el numero de mano, asi que no puede
    reventar con campos ausentes."""
    assert isinstance(VENTANA._result_sig({}), str)
    assert isinstance(VENTANA._result_sig({"winner": "a"}), str)


# --- resumen de un frame marcado --------------------------------------------

def test_el_resumen_enseña_lo_que_habia_en_pantalla():
    """Para que el usuario vea de inmediato que marco el frame que creia."""
    datos = {"state": {"hero_cards": ["Ah", "Kd"], "board": ["2c", "5c", "9d"],
                       "hero_position": "BTN"},
             "recommendation": {"action": "OPEN RAISE"}}
    r = VENTANA._resumen_marcado(datos)
    assert "Ah Kd" in r and "board 2c 5c 9d" in r and "BTN" in r and "OPEN RAISE" in r


def test_el_resumen_dice_cuando_no_hubo_recomendacion():
    """Marcar un frame MUDO es justo el caso mas interesante de anotar, asi que
    no puede quedar en blanco."""
    assert "sin recomendacion" in VENTANA._resumen_marcado({"state": {"hero_cards": ["Ah", "Kd"]}})


def test_el_resumen_de_un_frame_vacio_no_revienta():
    for datos in (None, {}, {"state": None}):
        assert isinstance(VENTANA._resumen_marcado(datos), str)


def test_un_jugador_fuera_de_la_mano_se_pinta_APAGADO():
    """La nota del usuario sobre el frame 254: en el HUD un retirado se veia
    igual que uno que sigue jugando, y contra cuantos vas es de lo primero que se
    mira. El cliente los distingue oscureciendo la tarjeta y quitando el reverso
    de las cartas, y la app ya lo lee; era el HUD el que no lo pintaba."""
    juega = gui.players_markup([{"name": "a", "stack": 5.0, "in_hand": True}])
    fuera = gui.players_markup([{"name": "b", "stack": 5.0, "in_hand": False}])
    assert "#7f8c8d" in fuera
    assert "#7f8c8d" not in juega


def test_se_apaga_la_fila_entera_no_solo_el_nombre():
    """De un vistazo se quiere leer "estos cuentan y estos no", y un detalle
    pequeño en un lado no se lee de un vistazo."""
    m = gui.players_markup([{"name": "b", "stack": 5.0, "position": "BTN",
                             "in_hand": False, "committed": 2.0}])
    assert m.startswith('<span foreground="#7f8c8d">') and m.endswith("</span>")
    assert "BTN" in m and "5 BB" in m


def test_sin_el_campo_in_hand_se_pinta_normal():
    """Las sesiones grabadas antes de que existiera el campo no lo traen; no se
    les puede inventar que estaban fuera de la mano."""
    assert "#7f8c8d" not in gui.players_markup([{"name": "c", "stack": 5.0}])


# --- guia postflop (GTO) -----------------------------------------------------
# La linea de cifras del panel nuevo. Se testea aparte del motor porque el fallo
# que importa aqui es de PINTADO: un None que se cuela en un formato numerico
# deja el panel entero en blanco y el usuario no ve ni el aviso.

def test_la_linea_de_defensa_nombra_alpha_mdf_y_precio():
    guia = {"precio": {
        "tamano_rival_pct": 33.3, "alpha_rival": 0.25, "mdf": 0.75,
        "ratio_valor_farol_equilibrado": 4.0, "pagar_bb": 2.0,
        "equity_requerida": 0.20, "margen_pp": 15.0}}
    m = VENTANA._gto_math_markup(guia)
    assert "25%" in m and "75%" in m and "4:1" in m
    assert "20%" in m and "+15 puntos" in m


def test_la_linea_de_defensa_sin_equity_no_pinta_un_margen_vacio():
    guia = {"precio": {
        "tamano_rival_pct": 50.0, "alpha_rival": 0.333, "mdf": 0.667,
        "ratio_valor_farol_equilibrado": 3.0, "pagar_bb": 2.0,
        "equity_requerida": 0.25}}
    m = VENTANA._gto_math_markup(guia)
    assert "margen" not in m
    assert "33%" in m and "67%" in m


def test_la_linea_de_cbet_nombra_tamano_y_banda():
    guia = {"cbet": {
        "tamano_pct_del_bote": 33, "tamano_bb": 1.98,
        "banda_frecuencia": "muy alta", "banda_glosa": "por encima del 70%",
        "alpha": 0.2481, "ratio_valor_farol": 4.03}}
    m = VENTANA._gto_math_markup(guia)
    assert "33%" in m and "1.98 BB" in m and "muy alta" in m
    assert "25%" in m and "4.03:1" in m


def test_la_linea_de_cbet_sin_bote_leido_no_inventa_un_importe():
    guia = {"cbet": {
        "tamano_pct_del_bote": 66, "tamano_bb": None,
        "banda_frecuencia": "media", "banda_glosa": "en torno al 40-55%"}}
    m = VENTANA._gto_math_markup(guia)
    assert "BB" not in m and "66%" in m


def test_sin_cifras_la_linea_queda_vacia_y_no_llena_de_guiones():
    """Un renglon de guiones se lee como un dato que vale cero."""
    assert VENTANA._gto_math_markup({"motivo": "no es tu turno"}) == ""


def test_postflop_manda_al_panel_de_la_guia_cuando_esta_propone_algo():
    """El panel de la recomendacion es el de SUS tablas y postflop se queda en
    blanco a proposito; el usuario tiene que saber donde mirar."""
    st = {"warnings": [], "hero_cards": ["Ah", "Kd"], "board": ["2c", "5c", "9d"],
          "players": [{"name": "a"}], "gto": {"action": "BET (2 BB)"}}
    r = VENTANA._no_reco_reason(st)
    assert "Guia postflop" in r or "Guía postflop" in r


def test_postflop_repite_el_motivo_de_la_guia_cuando_esta_tampoco_propone():
    st = {"warnings": [], "hero_cards": ["Ah", "Kd"], "board": ["2c", "5c", "9d"],
          "players": [{"name": "a"}],
          "gto": {"motivo": "el hero no fue el agresor preflop"}}
    assert "no fue el agresor preflop" in VENTANA._no_reco_reason(st)


def test_la_linea_de_cbet_sobrevive_a_una_banda_ausente():
    """En turn y river postflop_gto omite la banda -su heuristica es de flop-.
    El renglon no puede pintar "None" ni quedarse en blanco."""
    guia = {"cbet": {
        "tamano_pct_del_bote": 33, "tamano_bb": 3.0,
        "banda_frecuencia": None, "banda_glosa": None,
        "alpha": 0.248, "ratio_valor_farol": 4.03}}
    m = VENTANA._gto_math_markup(guia)
    assert "None" not in m
    assert "33%" in m and "3 BB" in m and "flop" in m
