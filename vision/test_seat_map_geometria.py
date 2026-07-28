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
