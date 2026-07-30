"""
La geometria pura de vision/seat_map.py: el reparto de posiciones, la conversion
de zonas a pixeles y el reparto de zonas sobre el tapete.

Todo lo de aqui son funciones sin imagen -numeros que salen de numeros-, asi que
son los tests mas baratos del repo y a la vez los que cubren lo que mas caro
cuesta depurar en vivo: si _posiciones() se equivoca, la app sirve el rango de
otra posicion y falla EN SILENCIO, con una recomendacion perfectamente plausible.

Y las zonas: son fracciones del nucleo del tapete escritas a mano tras medirlas
sobre capturas. Nada impide que un retoque las solape entre si o las mueva sobre
lo que no es, y el sintoma seria un numero que se lee de donde no debe. Aqui se
afirma el reparto que se midio.
"""
import pytest

from vision import seat_map

pytestmark = pytest.mark.vision

REF = (200, 150, 1000, 500, False)          # (x0, y0, ancho, alto, es_fallback)
FORMA = (900, 1600, 3)                      # alto, ancho, canales


# --- el reparto de posiciones ------------------------------------------------

@pytest.mark.parametrize("n", range(2, 10))
def test_cada_mesa_reparte_una_etiqueta_por_asiento_y_sin_repetir(n):
    pos = seat_map.SEATING_BY_N[n]
    assert len(pos) == n
    assert len(set(pos)) == n, f"etiqueta repetida en una mesa de {n}: {pos}"
    assert set(pos) <= set(seat_map.CANON9), "etiqueta que no existe en la mesa de 9"


@pytest.mark.parametrize("n", range(2, 10))
def test_la_mesa_siempre_empieza_por_el_boton(n):
    """table_state rota el orden de reparto hasta el asiento del boton y empareja
    con esta lista, asi que el primer elemento TIENE que ser el BTN."""
    assert seat_map.SEATING_BY_N[n][0] == ("SB" if n == 2 else "BTN"), \
        "en heads-up el boton ES la ciega pequeña"


@pytest.mark.parametrize("n", range(3, 10))
def test_las_dos_ciegas_van_detras_del_boton(n):
    assert list(seat_map.SEATING_BY_N[n][1:3]) == ["SB", "BB"]


@pytest.mark.parametrize("n", range(2, 10))
def test_la_bb_cierra_la_ronda_preflop(n):
    """La BB habla la ultima preflop: es lo que hace que su rango sea de DEFENSA
    y no de apertura."""
    pos = seat_map.SEATING_BY_N[n]
    orden_habla = pos[3:] + pos[:3] if n > 2 else pos
    assert orden_habla[-1] == "BB"


@pytest.mark.parametrize("n", range(2, 10))
def test_la_etiqueta_sale_de_CUANTOS_HABLAN_DETRAS_no_del_nombre_de_la_silla(n):
    """El bug que arreglo _posiciones: la tabla estaba escrita a mano y daba EP1
    al primero en hablar de cualquier mesa de 6+. Pero EP1 de una mesa de 9 tiene
    OCHO jugadores detras y el primero de una de 6 solo cinco, asi que le toca
    MP2. Medido sobre ranges.json a 20bb, se servia un rango del 17,0% donde
    tocaba uno del 25,0%: un tercio mas tight, en TODAS las manos de esa posicion.

    La regla, comprobada asiento a asiento: quien tiene k jugadores detras lleva
    la etiqueta que en una mesa de 9 tiene esos mismos k detras."""
    pos = seat_map.SEATING_BY_N[n]
    orden_habla = pos[3:] + pos[:3] if n > 2 else pos
    for i, etiqueta in enumerate(orden_habla):
        detras = n - 1 - i
        assert seat_map.CANON9[len(seat_map.CANON9) - 1 - detras] == etiqueta, \
            f"mesa de {n}: el que tiene {detras} detras deberia ser " \
            f"{seat_map.CANON9[len(seat_map.CANON9) - 1 - detras]}, no {etiqueta}"


def test_la_mesa_de_nueve_es_la_canonica_entera():
    """Es la que esta digitalizada en ranges.json; si esta se moviera, todos los
    rangos se emparejarian con la posicion equivocada."""
    assert list(seat_map.SEATING_BY_N[9]) == ["BTN", "SB", "BB", "EP1", "EP2",
                                              "MP1", "MP2", "HJ", "CO"]


# --- zona -> pixeles ---------------------------------------------------------

def test_una_zona_se_traduce_a_pixeles_del_nucleo():
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, (0.0, 0.0, 1.0, 1.0), FORMA)
    assert (x0, y0, x1, y1) == (200, 150, 1200, 650)


def test_las_fracciones_negativas_salen_del_nucleo_a_proposito():
    """Los nameplates y los dorsos viven FUERA del ovalo, asi que sus zonas usan
    fracciones negativas o mayores que 1. No es un error de calibracion."""
    x0, y0, _x1, _y1 = seat_map.zone_to_px(REF, (-0.10, -0.10, 0.13, 0.05), FORMA)
    assert x0 == 100 and y0 == 100


def test_una_zona_que_se_sale_de_la_imagen_se_recorta_en_vez_de_petar():
    """Con un encuadre estrecho la zona de un asiento del borde se sale, y eso no
    puede tumbar el analisis del frame entero."""
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, (-5.0, -5.0, 5.0, 5.0), FORMA)
    assert (x0, y0) == (0, 0)
    assert (x1, y1) == (FORMA[1], FORMA[0])


@pytest.mark.parametrize("zona", [(-5.0, -5.0, -4.0, -4.0), (4.0, 4.0, 5.0, 5.0)])
def test_una_zona_ENTERA_fuera_de_la_imagen_da_un_recorte_vacio(zona):
    """Comportamiento ACTUAL, escrito para que se sepa: zone_to_px recorta cada
    borde por separado, asi que una zona que se sale entera devuelve un rectangulo
    invertido. numpy lo interpreta como recorte VACIO, que es lo que hace que no
    reviente: los consumidores ya comprueban `.size == 0` (card_back_fractions,
    color_card_detector.find_card_boxes). Si algun dia se decide normalizarlo,
    este test se pone rojo y hay que darle la vuelta."""
    import numpy as np
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, zona, FORMA)
    assert np.zeros(FORMA, dtype=np.uint8)[y0:y1, x0:x1].size == 0


# --- el reparto de zonas sobre el tapete -------------------------------------

def solapan(a, b):
    return (a[0] < b[2] and b[0] < a[2]) and (a[1] < b[3] and b[1] < a[3])


@pytest.mark.parametrize("mapa", ["SEATS", "CARD_BACK_ZONES"])
def test_cada_asiento_tiene_su_sitio_y_no_pisa_al_vecino(mapa):
    """Nameplates y dorsos SI tienen que estar separados: los dos identifican a un
    jugador concreto, y solaparse significa atribuirle a uno lo del de al lado
    -su nombre, su stack o sus cartas-."""
    zonas = getattr(seat_map, mapa)
    zonas = {k: (v["plate"] if isinstance(v, dict) else v) for k, v in zonas.items()}
    malos = [(a, b) for a in zonas for b in zonas
             if a < b and solapan(zonas[a], zonas[b])]
    assert not malos, f"{mapa}: zonas que se pisan {malos}"


def test_las_zonas_de_dorso_no_pisan_el_board():
    """Las dos se leen con el MISMO detector de cartas, asi que un solape haria
    que las cartas comunes contaran como la mano de un jugador."""
    malos = [s for s, z in seat_map.CARD_BACK_ZONES.items()
             if solapan(z, seat_map.BOARD_ZONE)]
    assert not malos, f"{malos} alcanzan el board"


def test_LIMITACION_las_zonas_de_apuesta_si_se_solapan_entre_ellas_y_con_el_board():
    """Comportamiento ACTUAL, medido y escrito a proposito.

    Al contrario que los nameplates, las zonas de apuesta no estan separadas: se
    calibraron con margen generoso para no cortar el numero, y TOPC y UR comparten
    una franja fina, y cuatro de ellas entran en el rectangulo del board.

    Por que no es un fallo: una zona de apuesta se lee con OCR y solo se acepta
    lo que lleve el sufijo "BB" (parse_amount_bb), y una carta no es texto. O sea
    que compartir rectangulo con el board no significa compartir lecturas. La
    franja TOPC/UR si es un riesgo real -un importe ahi se podria atribuir a
    cualquiera de los dos- pero mide 0,10 x 0,02 del nucleo y en el corpus no ha
    aparecido ni una lectura dentro.

    El test fija el solape MEDIDO: si crece, alguien ha movido una zona."""
    entre_ellas = [(a, b) for a in seat_map.SEAT_BET_ZONES for b in seat_map.SEAT_BET_ZONES
                   if a < b and solapan(seat_map.SEAT_BET_ZONES[a], seat_map.SEAT_BET_ZONES[b])]
    assert sorted(entre_ellas) == [("TOPC", "UR")], f"el solape ha cambiado: {entre_ellas}"

    con_board = sorted(s for s, z in seat_map.SEAT_BET_ZONES.items()
                       if solapan(z, seat_map.BOARD_ZONE))
    assert con_board == ["ML", "MR", "UL", "UR"], f"el solape con el board ha cambiado: {con_board}"


def test_las_zonas_estan_bien_formadas():
    todas = {f"SEATS[{k}].plate": v["plate"] for k, v in seat_map.SEATS.items()}
    for nombre in ("CARD_BACK_ZONES", "SEAT_BET_ZONES"):
        todas.update({f"{nombre}[{k}]": v for k, v in getattr(seat_map, nombre).items()})
    todas.update(BOARD_ZONE=seat_map.BOARD_ZONE, POT_ZONE=seat_map.POT_ZONE,
                 CHAT_ZONE=seat_map.CHAT_ZONE, ACTION_ZONE=seat_map.ACTION_ZONE,
                 HERO_CARDS_ZONE=seat_map.HERO_CARDS_ZONE)
    for nombre, (x0, y0, x1, y1) in todas.items():
        assert x0 < x1 and y0 < y1, f"{nombre} esta del reves: {(x0, y0, x1, y1)}"


# --- el bote: uno solo, el de encima del board -------------------------------
#
# Cuando hay un all-in el cliente PARTE el bote y dibuja cada trozo con sus
# fichas debajo del board. Esos trozos NO se leen: la etiqueta "Bote: N BB" de
# encima del board ya da el total, y sumar los trozos seria llegar al mismo
# numero con mas formas de equivocarse.

# Banda donde caen los trozos del bote partido, medida sobre frames reales
# buscando pares de importes que sumaran el bote de la etiqueta.
BANDA_BOTES_PARTIDOS = (0.225, 0.59, 0.762, 0.69)


def test_la_zona_del_bote_no_alcanza_los_trozos_del_bote_partido():
    """Si la alcanzara, el total se leeria de un trozo y saldria un bote menor
    del real, que es con lo que se calcula si un precio sale a cuenta."""
    assert not solapan(seat_map.POT_ZONE, BANDA_BOTES_PARTIDOS), \
        f"POT_ZONE {seat_map.POT_ZONE} llega a la banda de los trozos"
    assert seat_map.POT_ZONE[3] < BANDA_BOTES_PARTIDOS[1], \
        "la etiqueta del total va ENCIMA del board y los trozos debajo"


def test_la_zona_del_bote_va_por_encima_del_centro_del_board():
    """"justo encima de las 5 cartas": es la referencia que fija donde mirar."""
    centro_board = (seat_map.BOARD_ZONE[1] + seat_map.BOARD_ZONE[3]) / 2
    assert seat_map.POT_ZONE[1] < centro_board


def test_LIMITACION_las_zonas_de_apuesta_SI_alcanzan_esa_banda():
    """Deja escrito lo que hoy NO se arregla, con su razon.

    Los trozos del bote se reparten segun cuantos haya (medidos en fx
    0,225..0,762) y se meten en la zona de apuesta de ML o MR, que estan justo
    ahi. Pasa de verdad: en sesion-2026-07-28_012453/0484-0488 ML sale con
    bet=29,6, que es el trozo izquierdo del bote y no su apuesta.

    No se separa por geometria porque las dos poblaciones se tocan, y no hace
    falta porque el bote solo se parte cuando la ronda de apuestas esta CERRADA:
    de 80 frames CON recomendacion, en 0 estaba el bote partido, y de las 1.721
    recomendaciones que ha dado la app 0 tenian board. El fantasma ensucia
    player["bet"] en frames de showdown, donde el motor ya esta callado.

    Si algun dia se separan, este test se pone rojo y hay que darle la vuelta."""
    alcanzan = [s for s, z in seat_map.SEAT_BET_ZONES.items()
                if solapan(z, BANDA_BOTES_PARTIDOS)]
    assert sorted(alcanzan) == ["HERO", "ML", "MR"], \
        f"el solape medido ha cambiado: ahora alcanzan {sorted(alcanzan)}"


# --- ¿es mi turno? por pixeles, sin OCR --------------------------------------
#
# La idea es del usuario: los botones de accion SOLO existen cuando le toca al
# hero, asi que verlos es saber que es su turno. Y es la pregunta que peor
# responde el OCR: medido sobre 1.011 frames, el hero tenia botones en 216 y
# `facing` solo se leyo en 89 -o sea que la app se pierde el 59% de sus propios
# turnos- y ademas en 40 frames dijo que enfrentaba algo SIN haber botones.

def zona_de_botones(ref, forma, color, fondo=(40, 90, 40)):
    """Tapete con la zona de botones pintada de un color."""
    import numpy as np
    img = np.full(forma, fondo, dtype=np.uint8)
    x0, y0, x1, y1 = seat_map.zone_to_px(ref, seat_map.ACTION_ZONE, forma)
    img[y0:y1, x0:x1] = color
    return img


FORMA = (900, 1600, 3)
REF_BTN = (200, 100, 1000, 400, False)


def test_los_botones_rojos_del_cliente_se_ven():
    """(0,0,200) BGR = el rojo con el que PokerStars pinta No ir / Igualar."""
    assert seat_map.hay_botones(zona_de_botones(REF_BTN, FORMA, (0, 0, 200)), REF_BTN)


def test_el_tapete_pelado_no_es_un_turno():
    import numpy as np
    assert not seat_map.hay_botones(np.full(FORMA, (40, 90, 40), dtype=np.uint8), REF_BTN)


@pytest.mark.parametrize("color, desc", [
    ((40, 90, 40), "verde del tapete"),
    ((0, 0, 0), "negro"),
    ((200, 200, 200), "gris claro"),
    ((0, 150, 0), "verde vivo"),
    ((180, 0, 0), "azul"),
])
def test_ningun_otro_color_se_toma_por_un_boton(color, desc):
    assert not seat_map.hay_botones(zona_de_botones(REF_BTN, FORMA, color), REF_BTN), desc


def test_un_rojo_oscuro_o_apagado_tampoco():
    """El rail de la mesa y las sillas tiran a granate: saturados pero oscuros."""
    assert not seat_map.hay_botones(zona_de_botones(REF_BTN, FORMA, (30, 30, 70)), REF_BTN)


def test_el_umbral_cae_en_el_VALLE_y_del_lado_seguro():
    """Medido: 791 frames bajo 0,08, tres en 0,08-0,25, y 217 por encima. El
    umbral va dentro del valle pero MAS CERCA DEL LADO VACIO a proposito: un
    falso positivo cuesta un analisis de mas, y un falso negativo cuesta la
    decision entera."""
    assert 0.08 < seat_map.BOTONES_ROJO_MIN < 0.25
    assert seat_map.BOTONES_ROJO_MIN <= 0.17, "mas arriba se pierden turnos"


def test_una_zona_fuera_del_encuadre_no_inventa_un_turno():
    import numpy as np
    fuera = (200, 100, 1000, 4000, False)     # la zona se sale por abajo
    assert not seat_map.hay_botones(np.full(FORMA, (0, 0, 200), dtype=np.uint8), fuera)


# --- la guarda: con la mesa tapada, este frame no vale -----------------------
#
# Cazado por el usuario revisando el frame 0446 de sesion-2026-07-28_210655:
# abrio el panel de progreso de fichas, que tapa la mitad derecha de la mesa. El
# ovalo se detecto en 825x374 en vez de 1163x491, pero como la referencia fijada
# se devolvia igual, se siguio leyendo cada zona en su sitio de siempre. Salio un
# jugador INVENTADO en UR llamado "Ciegas" -una palabra del panel- que corrio el
# recuento de asientos y con el todas las posiciones.

def fijar(rc, ref4):
    """Fija la referencia dandole las lecturas buenas que hacen falta."""
    for _ in range(seat_map.REF_MIN_PARA_FIJAR):
        rc._muestras.append(ref4)
    rc._fija = ref4
    return rc


def test_mientras_no_haya_referencia_fijada_no_se_descarta_nada():
    """Sin nada con que comparar no se puede juzgar. Es el "siempre y cuando
    hayas detectado una antes" de la regla."""
    rc = seat_map.ReferenciaFijada()
    assert rc.fijada is None


def test_el_ovalo_donde_no_tocaba_marca_el_frame_para_descartar(monkeypatch):
    rc = fijar(seat_map.ReferenciaFijada(), (266, 175, 1163, 494))
    # el caso real del frame 0446: mucho mas pequeño
    monkeypatch.setattr(seat_map, "find_reference", lambda bgr: (266, 296, 825, 374, False))
    assert rc.de(None)[4] is True


def test_un_temblor_normal_del_detector_NO_descarta(monkeypatch):
    """find_reference oscila entre valores discretos todo el rato: medido, el
    desvio mediano es 0,05 y el p95 0,14. Descartar ahi tiraba el 40% de los
    frames por nada."""
    rc = fijar(seat_map.ReferenciaFijada(), (266, 175, 1163, 494))
    monkeypatch.setattr(seat_map, "find_reference", lambda bgr: (294, 178, 1135, 490, False))
    assert rc.de(None)[4] is False


def test_que_no_se_encuentre_el_ovalo_NO_es_motivo_para_descartar(monkeypatch):
    """Pasa en el 26% de los frames y casi siempre la mesa sigue donde estaba: es
    el detector el que tiene un mal momento. Para eso existe la referencia
    fijada; descartarlos dejaria muda una cuarta parte de la sesion."""
    rc = fijar(seat_map.ReferenciaFijada(), (266, 175, 1163, 494))
    monkeypatch.setattr(seat_map, "find_reference", lambda bgr: (0, 0, 10, 10, True))
    ref = rc.de(None)
    assert ref[4] is False
    assert ref[:4] == (266, 175, 1163, 494), "se sigue usando la fijada"


def test_si_la_ventana_se_MUEVE_de_verdad_se_vuelve_a_fijar(monkeypatch):
    """Un desvio sostenido no es un panel: es una mudanza. Se pierden los frames
    de la transicion, que es lo correcto -durante la mudanza las zonas no estan
    donde dicen- y luego se sigue trabajando."""
    rc = fijar(seat_map.ReferenciaFijada(), (266, 175, 1163, 494))
    nueva = (400, 300, 900, 380)
    monkeypatch.setattr(seat_map, "find_reference", lambda bgr: nueva + (False,))
    descartados = sum(1 for _ in range(seat_map.REF_SEGUIDAS_PARA_REFIJAR)
                      if rc.de(None)[4])
    assert descartados == seat_map.REF_SEGUIDAS_PARA_REFIJAR - 1
    assert rc.fijada == nueva
    assert rc.de(None)[4] is False, "ya re-fijada, se vuelve a trabajar"


def test_el_umbral_de_descarte_sale_de_un_valle_medido():
    """0,150-0,175 no tiene NI UNA observacion en 1.423 frames. Y es distinto del
    de re-fijar: son dos preguntas ("¿me creo esta lectura?" y "¿esta la mesa
    donde dice?") que comparten formula pero no umbral."""
    assert seat_map.REF_TOLERANCIA < seat_map.REF_DESCARTE
    assert 0.15 <= seat_map.REF_DESCARTE <= 0.175


# --- las zonas tienen que aguantar que la referencia baile -------------------

def test_la_zona_del_BOARD_deja_margen_para_la_primera_carta():
    """EL CASO, de una nota del usuario ("falta en el board el 4picas", frame 0036
    de la sesion del 30-07 a las 00:29): el board era 4♠ 9♦ 4♣ y la app leia
    ['9d','4c']. La carta SI se detectaba, pero con la caja mordida por el borde
    izquierdo de la zona, y con la caja mordida su rango salia 'A' en vez de '4'.
    O sea que la carta no se pierde: se convierte en otra.

    Y no era un caso suelto: 536 de 3.241 cajas del corpus (16,5%) salian
    estrechas.

    POR QUE HACE FALTA MARGEN Y NO PRECISION. El ancho del nucleo que mide
    find_reference oscila entre frames de la misma mesa quieta -en esa sesion da
    904 px el 23,7% de las veces, 889 el 22,3%, 931 el 17,8% y 862 el 17,1%- y
    ReferenciaFijada se queda con uno segun los primeros frames que le tocaron.
    Asi que la zona en pixeles cambia hasta 40 px de un arranque a otro sin que
    nada este mal, y el borde tiene que estar lo bastante lejos de la carta para
    aguantarlo. Medido: 0.22 es el primer valor que sirve con las cuatro lecturas;
    0.24 fallaba en dos de ellas."""
    x0 = seat_map.BOARD_ZONE[0]
    # la carta mas a la izquierda del board arranca sobre 0.26 del nucleo
    assert x0 <= 0.22, (
        f"el borde izquierdo del board esta en {x0}: muy pegado a la primera "
        f"carta, que se cortara en cuanto la referencia se fije en un modo ancho")


def test_el_board_cabe_entero_en_su_zona():
    """Cinco cartas de ~0.09 del nucleo cada una, mas los huecos. Si la zona se
    quedara estrecha por la derecha, el river se cortaria igual que se cortaba el
    flop por la izquierda."""
    x0, _y0, x1, _y1 = seat_map.BOARD_ZONE
    assert x1 - x0 >= 5 * 0.09, f"la zona mide {x1 - x0:.2f} y el board ocupa ~0.45"


def test_la_zona_de_MANO_REVELADA_deja_margen_para_las_dos_cartas():
    """EL CASO, de un torneo donde se ven las manos de todos (sesion del 30-07 a
    las 01:49): el asiento UR de la mesa de 9 salia con revealed=True y
    cards=None en TODOS los frames. El par si se detectaba y los rangos no se
    resolvian, porque su primera carta media 41 px contra los 81 de la segunda,
    empezando exactamente en el borde de la zona.

    Es el mismo mecanismo que cortaba la primera carta del board, en otra zona. La
    zona de revelada se deriva de la del DORSO, que esta calibrada para el blob que
    asoma por detras del nameplate y es mas pequeño que la carta entera, asi que
    el margen tiene que cubrir esa diferencia MAS el temblor de la referencia.

    Medido: con 0.06 se resolvian 58 de 61 manos, con 0.12 son 100 de 101."""
    assert seat_map.REVELADA_MARGEN >= 0.12


def test_la_zona_revelada_de_cada_asiento_cabe_en_la_imagen():
    """Si se sale, se recorta, y una carta a medias pierde su rango. UR de la mesa
    de 9 es el mas expuesto: su zona de dorso llega a 1.23 del nucleo y con el
    margen se va a 1.35."""
    shape = (944, 1540, 3)
    ref = (324, 195, 932, 412, False)
    for plazas in (6, 8, 9):
        z = seat_map.zonas(plazas)["dorsos"]
        for asiento in z:
            x0, y0, x1, y1 = seat_map.revealed_zone_px(ref, asiento, shape, z)
            assert x1 > x0 and y1 > y0, f"{plazas}/{asiento}: zona vacia"
            ancho_pedido = (z[asiento][2] + seat_map.REVELADA_MARGEN) * ref[2]
            # la carta mide ~0.09 del nucleo: si se recorta mas que eso, se pierde
            recortado = max(0, int(ref[0] + ancho_pedido) - shape[1])
            assert recortado < 0.09 * ref[2], (
                f"{plazas}/{asiento}: se recortan {recortado} px, mas de una carta")
