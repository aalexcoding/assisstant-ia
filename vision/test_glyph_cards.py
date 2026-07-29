"""
Verificacion del mazo de cara blanca (vision/glyph_card_detector.py) y de que
convive con el de fondo solido sin romperlo.

Lo que de verdad protege:

  1. Que el palo salga del COLOR DE LA TINTA y no del fondo. Es el cambio
     entero: el 26-07-2026 el usuario cambio de mazo y la app se quedo ciega
     267 frames seguidos porque el detector viejo miraba el fondo.
  2. Que las cartas PEGADAS se separen. Sus caras blancas se funden en un solo
     contorno, asi que sin corte por columnas un board de 5 sale como 2 cajas.
  3. Que una carta APAGADA se marque como tal. Apagada significa que el hero ya
     no esta en la mano; tratarla como viva haria recomendar sobre una mano
     abandonada, que es peor que no recomendar.
  4. Que el mazo viejo siga funcionando, incluida la POLARIDAD del OCR de rango:
     los dos mazos comparten el voto y el '10', y solo cambia de donde sale la
     tinta.

Las imagenes se generan aqui (colores medidos sobre capturas reales, ver el
docstring del modulo), asi que el test no depende de tener las capturas.
"""
import cv2
import numpy as np
import pytest

from vision import color_card_detector as solido
from vision import color_rank_ocr, seat_map
from vision import glyph_card_detector as glifo
from vision import table_state as ts

pytestmark = pytest.mark.vision

# colores BGR de la tinta, convertidos de los HSV medidos en cartas reales
TINTA = {
    "heart": (40, 40, 205),      # rojo
    "diamond": (200, 60, 40),    # azul
    "club": (40, 120, 40),       # verde
    "spade": (10, 10, 10),       # negro
}
CARA_VIVA = (255, 255, 255)
CARA_APAGADA = (77, 77, 77)
TAPETE = (90, 150, 110)          # verde del tapete, S~97: no debe votar trebol
PALOS = ("heart", "diamond", "club", "spade")

ANCHO_CARTA, ALTO_CARTA = 87, 121
HUECO = 7
REF = (100, 100, 900, 400, False)

# el mazo de fondo solido tiene mas de un juego de colores: PokerStars los cambia
# con el tema y el usuario lo cambia sin que la app se entere. Medidos sobre 205
# cartas de board de una sesion real.
NUEVOS = {"heart": (0, 142, 130), "club": (48, 139, 138),
          "diamond": (97, 126, 128), "spade": (0, 0, 90)}
VIEJOS = {"heart": (5, 190, 230), "club": (82, 230, 170),
          "diamond": (110, 105, 190), "spade": (20, 20, 140)}


def mesa(n_cartas, palos, cara=CARA_VIVA, alto=ALTO_CARTA):
    """Franja de tapete con n cartas pegadas (hueco de 7px, como el cliente).

    La carta se dibuja con la disposicion REAL, que es la que hace falta aislar:
    rango pequeño arriba a la izquierda con su pip debajo, rango grande a la
    derecha, y el pip grande DEBAJO del rango grande y casi igual de alto -que
    es justo por lo que no se puede separar por tamaño-.

    `alto` menor que ALTO_CARTA es la carta del HERO, a la que el cliente le tapa
    la mitad de abajo con su propio nameplate. Se modela TAPANDO, no encogiendo:
    la carta se dibuja entera y se recorta el sobrante. Encogerla seria dibujar
    una carta que el cliente no dibuja nunca -con el indice a escala reducida- y
    ademas escondería el error que este fixture tiene que poder ver: el indice
    mide lo mismo en las dos, y por eso glyph_card_detector lo escala con el
    ANCHO de la carta y no con su alto (ver INDICE_ANCHO_FRAC alli)."""
    img = np.full((alto + 80, 60 + n_cartas * (ANCHO_CARTA + HUECO) + 60, 3),
                  TAPETE, dtype=np.uint8)
    entera = np.full((ALTO_CARTA, ANCHO_CARTA, 3), TAPETE, dtype=np.uint8)
    for i in range(n_cartas):
        x = 60 + i * (ANCHO_CARTA + HUECO)
        c = entera.copy()
        cv2.rectangle(c, (0, 0), (ANCHO_CARTA - 1, ALTO_CARTA - 1), cara, -1)
        t = TINTA[palos[i]]
        cv2.putText(c, "K", (34, int(ALTO_CARTA * 0.50)),               # rango grande
                    cv2.FONT_HERSHEY_SIMPLEX, ALTO_CARTA / 105.0, t, 4)
        # El INDICE -rango pequeño y su pip- va en la esquina de arriba a la
        # izquierda, que es de donde glyph_card_detector saca el palo. Su tinta
        # esta MEDIDA en cartas reales (sesion del 29-07 a las 07:04, frame 275):
        # el indice de una carta de 87x122 mide 28x40 px y lleva entre 311 y 498
        # px de tinta, o sea el 40-65% de su area. La version anterior de este
        # fixture dejaba 40 px -por debajo de TINTA_MIN_PX- y ponia el pip
        # pequeño FUERA del indice.
        cv2.putText(c, "K", (5, int(ALTO_CARTA * 0.22)),                # rango pequeño
                    cv2.FONT_HERSHEY_SIMPLEX, ALTO_CARTA / 280.0, t, 3)
        cv2.circle(c, (13, int(ALTO_CARTA * 0.29)),                     # pip pequeño
                   max(3, ALTO_CARTA // 22), t, -1)
        cv2.circle(c, (52, int(ALTO_CARTA * 0.76)),                     # pip grande
                   max(5, ALTO_CARTA // 12), t, -1)
        img[40:40 + alto, x:x + ANCHO_CARTA] = c[:alto]                 # tapada por abajo
    return img


def recorte_glifo(palo="spade"):
    return mesa(1, [palo])[40:40 + ALTO_CARTA, 60:60 + ANCHO_CARTA]


def carta_vieja_img():
    """Carta del mazo viejo: fondo salmon con el rango en BLANCO."""
    img = np.full((ALTO_CARTA + 60, ANCHO_CARTA + 60, 3), TAPETE, dtype=np.uint8)
    cv2.rectangle(img, (30, 30), (30 + ANCHO_CARTA, 30 + ALTO_CARTA), (80, 90, 245), -1)
    cv2.putText(img, "K", (55, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 4)
    return img


def recorte_vieja():
    return carta_vieja_img()[30:30 + ALTO_CARTA, 30:30 + ANCHO_CARTA]


def tapete(h=200, w=400):
    return np.full((h, w, 3), TAPETE, dtype=np.uint8)


def felt(color=(60, 110, 70)):
    return np.full((700, 1200, 3), color, dtype=np.uint8)


# --- el palo sale de la tinta, con la cara blanca ---------------------------

@pytest.mark.parametrize("palo", PALOS)
def test_una_carta_sobre_cara_blanca_se_lee_por_su_tinta(palo):
    cajas = glifo.find_card_boxes(mesa(1, [palo]))
    assert len(cajas) == 1
    assert cajas[0]["suit"] == palo


@pytest.mark.parametrize("palo", PALOS)
def test_una_figura_ilustrada_no_pierde_su_palo(palo):
    """J, Q y K de este mazo son un DIBUJO A TODO COLOR, no un glifo sobre
    blanco, y ese dibujo es tinta que entra en el voto del palo.

    Es un fallo real y medido: en el board 10♥ 9♣ 2♥ Q♦ 8♦ (sesion del 29-07 a
    las 07:04, frame 275) la dama sacaba 899 votos de diamante contra 452 de
    picas -los trazos oscuros de su vestido-, o sea 1,99 contra un VENTAJA_MIN
    de 2,0. No es que se leyera mal: find_card_boxes DESCARTA LA CAJA ENTERA
    cuando el palo no es concluyente, asi que la carta desaparecia del board. Por
    eso J/Q/K eran el 3,6% de las cartas de esa sesion cuando tocan al 23%.

    Aqui se le pinta a la carta un cuerpo con tinta de los otros tres palos, mas
    del doble de la suya, dejando el indice limpio. Con el voto sobre la carta
    entera esto no se resuelve; leyendo el indice, si."""
    img = mesa(1, [palo])
    x, y = 60, 40
    ajenos = [c for p, c in TINTA.items() if p != palo]
    for k, color in enumerate(ajenos):        # el "vestido" de la figura
        cv2.rectangle(img, (x + 30, y + 45 + k * 22),
                      (x + ANCHO_CARTA - 6, y + 63 + k * 22), color, -1)
    cajas = glifo.find_card_boxes(img)
    assert len(cajas) == 1, "la figura no puede desaparecer del board"
    assert cajas[0]["suit"] == palo


def test_el_indice_se_escala_con_el_ancho_no_con_el_alto():
    """A la carta del hero el cliente le tapa la mitad de abajo con su nameplate,
    asi que mide 87x73 en vez de 87x122. Su INDICE no encoge -lo tapado es el
    borde de abajo, no la esquina de arriba-, y si se escalara con el alto
    visible se quedaria en 24 px, por debajo de TINTA_MIN_PX: la app dejaria de
    leer las cartas del propio hero, que es de lo que depende todo lo demas."""
    entera = glifo.find_card_boxes(mesa(1, ["heart"]))
    tapada = glifo.find_card_boxes(mesa(1, ["heart"], alto=73), esperadas=1)
    assert len(entera) == 1 and len(tapada) == 1
    assert entera[0]["suit"] == tapada[0]["suit"] == "heart"
    assert tapada[0]["h"] < entera[0]["h"], "la del hero va cortada de verdad"


def test_el_verde_del_tapete_no_vota_trebol():
    """Su saturacion no llega a COLOR_S_MIN."""
    solo = np.full((ALTO_CARTA, ANCHO_CARTA, 3), TAPETE, dtype=np.uint8)
    hsv = cv2.cvtColor(solo, cv2.COLOR_BGR2HSV)
    assert glifo.suit_votes(hsv, glifo._cara(hsv))["club"] == 0


# --- cartas pegadas ---------------------------------------------------------

@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_un_grupo_de_cartas_pegadas_se_separa(n):
    palos = ["heart", "spade", "club", "diamond", "heart"][:n]
    cajas = glifo.find_card_boxes(mesa(n, palos))
    assert len(cajas) == n
    assert [c["suit"] for c in cajas] == palos, "en orden de izquierda a derecha"


def test_cinco_cartas_del_mismo_palo_tambien_se_separan():
    """El corte es geometrico, no por color."""
    assert len(glifo.find_card_boxes(mesa(5, ["heart"] * 5))) == 5


# --- ruido ------------------------------------------------------------------

def test_un_trozo_de_carta_demasiado_estrecho_se_descarta():
    """La animacion de descarte deja una franja fina."""
    img = mesa(3, ["heart", "spade", "club"])
    cv2.rectangle(img, (img.shape[1] - 45, 40),
                  (img.shape[1] - 5, 40 + ALTO_CARTA - 1), CARA_VIVA, -1)
    assert len(glifo.find_card_boxes(img)) == 3


def test_tapete_solo_no_produce_ninguna_carta():
    assert glifo.find_card_boxes(tapete()) == []


# --- carta apagada = el hero ya no juega la mano ----------------------------

def test_las_cartas_vivas_se_detectan_y_no_se_marcan_apagadas():
    vivas = glifo.find_card_boxes(mesa(2, ["heart", "club"], cara=CARA_VIVA))
    assert len(vivas) == 2
    assert not any(c["dimmed"] for c in vivas)


def test_las_apagadas_tambien_se_detectan_y_se_marcan():
    """Si no se detectaran, la app se queda ciega el 21% de los frames; y si no se
    marcaran, recomendaria sobre una mano abandonada."""
    apagadas = glifo.find_card_boxes(mesa(2, ["heart", "club"], cara=CARA_APAGADA))
    assert len(apagadas) == 2
    assert all(c["dimmed"] for c in apagadas)
    assert [c["suit"] for c in apagadas] == ["heart", "club"], "con el palo correcto"


# --- las cartas del hero salen recortadas por su nameplate -----------------

def test_dos_cartas_cortadas_por_el_nameplate_se_detectan_igual():
    """87x73, alto/ancho 0.84."""
    cajas = glifo.find_card_boxes(mesa(2, ["spade", "diamond"], alto=73))
    assert len(cajas) == 2
    assert [c["suit"] for c in cajas] == ["spade", "diamond"]


# --- convivencia con el mazo de fondo solido -------------------------------

def test_el_detector_de_fondo_solido_sigue_leyendo_su_mazo():
    assert len(solido.find_card_boxes(carta_vieja_img())) == 1


def test_el_detector_de_tinta_no_se_inventa_cartas_del_mazo_viejo():
    """Su cara es de color, no clara."""
    assert glifo.find_card_boxes(carta_vieja_img()) == []


def test_la_mascara_del_mazo_nuevo_marca_la_tinta_no_la_cara():
    """La cara es la mayoria del recorte."""
    c = recorte_glifo()
    m_glyph = color_rank_ocr.rank_mask(c, "glyph")
    assert m_glyph.mean() < color_rank_ocr.rank_mask(c, "solid").mean()
    assert 0.02 < (m_glyph > 0).mean() < 0.45, "deja fuera la mayor parte de la carta"


# --- aislar el rango grande (el pip mide casi lo mismo) --------------------

@pytest.fixture
def carta_k():
    return mesa(1, ["club"])[40:40 + ALTO_CARTA, 60:60 + ANCHO_CARTA]


def test_el_rango_aislado_usa_menos_tinta_que_la_mascara_completa(carta_k):
    """Se han ido el pip y el rango pequeño."""
    completa = color_rank_ocr.rank_mask(carta_k, "glyph")
    aislada = color_rank_ocr.rango_grande_mask(carta_k, "glyph")
    assert (aislada > 0).sum() < (completa > 0).sum()


def test_lo_que_queda_esta_arriba_y_no_esta_vacio(carta_k):
    completa = color_rank_ocr.rank_mask(carta_k, "glyph")
    aislada = color_rank_ocr.rango_grande_mask(carta_k, "glyph")
    ys_a, ys_c = np.where(aislada > 0)[0], np.where(completa > 0)[0]
    assert ys_a.size > 0, "aislar no puede dejar la carta en blanco"
    assert ys_a.max() < ys_c.max(), "el rango va arriba"


def test_los_dos_mazos_aislan_por_componentes_no_por_altura(carta_k):
    """Las cartas del hero salen cortadas por su nameplate y una fraccion fija de
    la altura les parte el numero. Ese era el motivo de que hubiera que ELEVARLAS
    para leerlas."""
    entera = color_rank_ocr.rank_mask(carta_k, "solid")
    assert np.array_equal(color_rank_ocr.rango_grande_mask(carta_k, "solid"),
                          color_rank_ocr._fila_de_arriba(entera))


def test_en_una_carta_cortada_no_se_pierde_la_parte_de_abajo_del_glifo():
    """El caso real que obligaba al usuario a elevar sus cartas con el raton."""
    franja = np.full((53, 83, 3), (60, 60, 200), np.uint8)
    cv2.putText(franja, "K", (18, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 4)
    ys = np.where(color_rank_ocr.rango_grande_mask(franja, "solid") > 0)[0]
    ys_ent = np.where(color_rank_ocr.rank_mask(franja, "solid") > 0)[0]
    assert len(ys) > 0
    assert ys.max() >= ys_ent.max() - 1


# --- las 2 cartas del hero se dibujan PEGADAS, sin hueco -------------------

def pegadas(palos, alto=73):
    """Dos cartas sin NADA entre ellas, que es como el cliente dibuja la mano del
    hero: el corte por perfil de columnas no las puede separar."""
    img = mesa(len(palos), palos, alto=alto)
    for i in range(len(palos) - 1):
        x = 60 + (i + 1) * (ANCHO_CARTA + HUECO) - HUECO
        img[40:40 + alto, x:x + HUECO] = CARA_VIVA
    return img


def test_un_bloque_pegado_sin_decir_cuantas_hay_no_se_reparte():
    """No se inventa nada."""
    assert len(glifo.find_card_boxes(pegadas(["heart", "diamond"]))) == 0


def test_diciendo_que_son_dos_el_bloque_se_reparte():
    cajas = glifo.find_card_boxes(pegadas(["heart", "diamond"]), esperadas=2)
    assert len(cajas) == 2
    assert [c["suit"] for c in cajas] == ["heart", "diamond"]
    assert abs(cajas[0]["w"] - cajas[1]["w"]) <= 2, "el reparto es a partes iguales"


def test_un_resto_estrecho_no_se_cuela_como_tercera_carta():
    """Una ficha o el disco del boton: colarlo era peor que el bug que esto
    arregla."""
    ruido = pegadas(["spade", "club"]).copy()
    cv2.rectangle(ruido, (5, 45), (5 + 43, 45 + 60), CARA_VIVA, -1)
    cv2.circle(ruido, (26, 75), 9, TINTA["heart"], -1)
    assert len(glifo.find_card_boxes(ruido, esperadas=2)) == 2


def test_si_las_dos_cartas_ya_venian_separadas_esperadas_no_las_toca():
    cajas = glifo.find_card_boxes(mesa(2, ["club", "spade"], alto=73), esperadas=2)
    assert [c["suit"] for c in cajas] == ["club", "spade"]


def test_una_sola_carta_visible_no_se_parte_por_completar_dos():
    assert len(glifo.find_card_boxes(mesa(1, ["heart"], alto=73), esperadas=2)) == 1


def test_el_board_no_declara_cuantas_cartas_hay_y_sigue_separandose_solo():
    img = mesa(5, ["heart", "spade", "club", "diamond", "heart"])
    assert len(glifo.find_card_boxes(img)) == 5


# --- el borde de la carta vecina no puede parecer un '1' -------------------
# Al cortar por la costura entre cartas pegadas, el borde oscuro entra en el
# recorte como una barra alta y fina pegada al lateral: la forma exacta de un '1'.

@pytest.fixture
def con_borde():
    c = recorte_glifo().copy()
    c[:, 0:3] = (20, 20, 20)
    c[:, -3:] = (20, 20, 20)
    return c


def test_las_barras_del_lateral_no_se_cuentan_como_glifo(con_borde):
    comps = color_rank_ocr._rank_components(
        color_rank_ocr.rango_grande_mask(con_borde, "glyph"))
    assert all(c[0] > 3 and c[0] + c[2] < ANCHO_CARTA - 3 for c in comps)
    assert len(comps) >= 1, "el rango de verdad sigue ahi"


def test_y_por_tanto_no_disparan_la_deteccion_del_diez(con_borde):
    assert not color_rank_ocr.is_ten(con_borde, "glyph")


# --- las dos vistas del mazo nuevo van sin pip ----------------------------

def test_la_vista_de_desempate_parte_del_rango_aislado():
    """Un pip leido como '0' detras de un rango leido como '1' fabrica dieces
    fantasma."""
    cerrada = color_rank_ocr._rank_only_close_img(recorte_glifo("diamond"), "glyph")
    assert (cerrada[:, :, 0] < 128).sum() > 0


def test_con_deck_solid_la_mascara_sigue_siendo_la_de_siempre():
    c = recorte_vieja()
    assert np.array_equal(color_rank_ocr.rank_mask(c, "solid"),
                          color_rank_ocr._white_mask(c))


def test_el_mazo_entra_en_la_clave_de_cache():
    """El mismo recorte no se confunde entre polaridades."""
    c = recorte_glifo()
    assert (color_rank_ocr.cache_key(c, "spade", "glyph")
            != color_rank_ocr.cache_key(c, "spade", "solid"))


# --- el disco del dealer, sea del color que sea ---------------------------
# El tema de mesa decide si el disco es claro con la pica roja pequeña o crema
# con la pica roja grande. Exigir que gane el claro dejaba la app sin boton -y
# por tanto sin posiciones y sin recomendaciones- en 44 frames seguidos.

def mesa_con_boton(seat, fondo, pica):
    img = felt()
    fx, fy = seat_map.SEATS[seat]["button"]
    cx, cy = int(REF[0] + fx * REF[2]), int(REF[1] + fy * REF[3])
    r = int((seat_map.BUTTON_AREA_FRAC_MIN + seat_map.BUTTON_AREA_FRAC_MAX) / 2
            * REF[2] * REF[3] / np.pi) ** 0.5
    cv2.circle(img, (cx, cy), int(r), fondo, -1)
    cv2.circle(img, (cx, cy), max(2, int(r * pica)), (40, 40, 235), -1)   # pica roja
    return img


@pytest.mark.parametrize("desc, fondo, pica", [
    ("el disco CLARO con pica roja", (245, 245, 245), 0.52),
    ("el disco CREMA con la pica roja dominando", (205, 235, 245), 0.80),
])
def test_el_boton_se_encuentra_con_los_dos_temas(desc, fondo, pica):
    assert seat_map.detect_button_seat(mesa_con_boton("UL", fondo, pica), REF) == "UL", desc


def test_el_boton_se_encuentra_en_el_asiento_donde_esta():
    img = mesa_con_boton("MR", (245, 245, 245), 0.52)
    assert seat_map.detect_button_seat(img, REF) == "MR"


@pytest.mark.parametrize("desc, fondo, pica", [
    ("una ficha de UN SOLO color no es el boton (falta el claro)", (40, 40, 235), 0.0),
    ("un disco claro sin pica tampoco (falta el rojo)", (245, 245, 245), 0.0),
])
def test_lo_que_no_es_el_boton_no_se_toma_por_el(desc, fondo, pica):
    assert seat_map.detect_button_seat(mesa_con_boton("UL", fondo, pica), REF) is None, desc


def test_el_tapete_pelado_no_inventa_boton():
    assert seat_map.detect_button_seat(felt(), REF) is None


# --- el dorso de las cartas cambia de color con el tema -------------------
# Sin dorsos no se sabe cuantos rivales siguen en la mano, y sin eso no hay
# equity: el usuario lo noto como que los porcentajes habian desaparecido.

DORSOS = {"granate": (178, 131, 127), "naranja": (19, 255, 248)}


def mesa_con_dorso(seat, hsv_color):
    img = felt()
    bgr = cv2.cvtColor(np.uint8([[list(hsv_color)]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, seat_map.CARD_BACK_ZONES[seat], img.shape)
    w, h = x1 - x0, y1 - y0
    cv2.rectangle(img, (x0 + int(w * .12), y0 + int(h * .22)),
                  (x0 + int(w * .88), y0 + int(h * .78)), bgr, -1)
    return img


@pytest.mark.parametrize("nombre", sorted(DORSOS))
def test_un_dorso_cuenta_como_asiento_con_cartas(nombre):
    img = mesa_con_dorso("ML", DORSOS[nombre])
    assert seat_map.detect_in_hand_seats(img, REF) == {"ML"}


def test_cada_dorso_se_cuenta_en_su_asiento():
    img = mesa_con_dorso("UR", DORSOS["naranja"])
    assert seat_map.detect_in_hand_seats(img, REF) == {"UR"}


def test_el_tapete_pelado_no_da_ningun_asiento_con_cartas():
    assert seat_map.detect_in_hand_seats(felt(), REF) == set()


# --- la mano BOCA ARRIBA de un rival (all-in / showdown) -------------------
#
# En cuanto el cliente gira las cartas el dorso desaparece, asi que mirando solo
# dorsos el recuento de rivales BAJA justo en un all-in, que es cuando el hero
# mas necesita saber contra cuantos va. Infravalorar rivales INFLA la equity.
#
# Tamaño medido sobre las cartas reveladas de sesion-2026-07-28_012453/0485:
# 85x54 y 86x54 px. Una carta revelada se dibuja TUMBADA (alto/ancho ~0,64), al
# reves que las del board y las del hero.
REVELADA_W, REVELADA_H = 85, 54

# REF propia: con la del resto del fichero la zona de TOPC cae por encima del
# borde superior de la imagen y no se podria dibujar nada dentro.
REF_REV = (100, 250, 900, 400, False)


def mesa_con_mano_revelada(seat, palos=("diamond", "spade"), ref=REF_REV, dy=0):
    """Tapete con las cartas de `palos` boca arriba en la zona de `seat`.

    `dy` desplaza el par hacia abajo, para reproducir que en la mesa real las
    cartas NO estan centradas en la zona del dorso: asoman por debajo."""
    img = felt()
    x0, y0, x1, y1 = seat_map.zone_to_px(ref, seat_map.CARD_BACK_ZONES[seat], img.shape)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2 + dy
    izq = cx - (len(palos) * (REVELADA_W + 8) - 8) // 2
    for i, palo in enumerate(palos):
        bgr = cv2.cvtColor(np.uint8([[list(NUEVOS[palo])]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
        ex = izq + i * (REVELADA_W + 8)
        cv2.rectangle(img, (ex, cy - REVELADA_H // 2),
                      (ex + REVELADA_W, cy + REVELADA_H // 2), bgr, -1)
    return img


@pytest.mark.parametrize("seat", sorted(seat_map.CARD_BACK_ZONES))
def test_una_mano_boca_arriba_cuenta_como_asiento_en_la_mano(seat):
    """En los cinco asientos, no solo en el que se depuro."""
    assert seat_map.revealed_pair_seats(mesa_con_mano_revelada(seat), REF_REV) == {seat}


def test_el_tapete_pelado_no_inventa_manos_reveladas():
    assert seat_map.revealed_pair_seats(felt(), REF_REV) == set()


def test_una_carta_suelta_no_es_una_mano():
    """Una caja suelta es ruido de UI -un icono del avatar, una ficha-, y
    aceptarla añadiria un rival que no existe."""
    assert seat_map.revealed_pair_seats(mesa_con_mano_revelada("ML", ("spade",)), REF_REV) == set()


def test_la_insignia_de_porcentaje_no_cuenta_como_carta():
    """Junto a las cartas reveladas el cliente pinta el "100 %" / "0 %" de la
    equity, DENTRO de la zona. No puede colarse como tercera caja: es plana
    (alto/ancho ~0,35) y se queda fuera del rango de aspecto de una carta."""
    img = mesa_con_mano_revelada("ML")
    x0, y0, x1, y1 = seat_map.zone_to_px(REF_REV, seat_map.CARD_BACK_ZONES["ML"], img.shape)
    rojo = cv2.cvtColor(np.uint8([[list(NUEVOS["heart"])]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
    cv2.rectangle(img, (x0 + 4, y0 + 4), (x0 + 84, y0 + 32), rojo, -1)   # 80x28
    assert seat_map.revealed_pair_seats(img, REF_REV) == {"ML"}


def test_el_margen_hace_falta_porque_la_zona_esta_calibrada_para_el_DORSO():
    """Las zonas se midieron sobre el blob del DORSO, que asoma por detras del
    nameplate y es mas pequeño que la carta entera, asi que las cartas reveladas
    se salen por abajo. Y find_card_boxes RECORTA a la region que se le da: una
    carta a medias fuera pierde alto y no pasa el filtro de tamaño. Medido en
    sesion-2026-07-28_012453/0485, la zona de TOPC cortaba las dos cartas de
    arrepia69 y devolvia 0 cajas; con REVELADA_MARGEN entran las dos."""
    img = mesa_con_mano_revelada("TOPC", dy=20)     # asomando por debajo, como en la mesa
    crudas = solido.find_card_boxes(
        img, seat_map.zone_to_px(REF_REV, seat_map.CARD_BACK_ZONES["TOPC"], img.shape))
    assert len(crudas) < 2, "la zona cruda ya llega a las cartas: sobraria el margen"
    assert seat_map.revealed_pair_seats(img, REF_REV) == {"TOPC"}


def test_un_dorso_no_es_una_mano_revelada():
    """La señal nueva no se limita a repetir la vieja."""
    assert seat_map.revealed_pair_seats(mesa_con_dorso("ML", DORSOS["granate"]), REF) == set()


@pytest.mark.parametrize("palos, visto_por_el_dorso, desc", [
    (("diamond", "spade"), False, "diamante AZUL y pica negra: el dorso no ve nada"),
    (("heart", "spade"), True, "con un corazon, el rojo cae en el perfil granate"),
])
def test_POR_QUE_el_fallo_era_intermitente(palos, visto_por_el_dorso, desc):
    """La razon por la que unas manos reveladas se contaban y otras no era el
    COLOR, no la logica.

    El perfil granate del dorso es (H>=168 o H<=6, S 95-175, V 85-175) y el rojo
    del mazo nuevo es HSV (0, 142, 130): cae dentro. Los otros tres palos no -en
    este mazo el diamante es AZUL, no rojo-, asi que detect_in_hand_seats veia
    una mano revelada solo si llevaba un corazon, o sea el 44% de las veces.

    Es exactamente lo que pasa en sesion-2026-07-28_012453/0485: CoNatas (7d Qh,
    con corazon) contaba como en la mano y arrepia69 (Ac Qd, verde y azul) no,
    con lo que la equity del hero se calculo contra un rival en vez de dos.

    revealed_pair_seats no depende del color de los palos, asi que ve las dos."""
    img = mesa_con_mano_revelada("ML", palos)
    assert (seat_map.detect_in_hand_seats(img, REF_REV) == {"ML"}) is visto_por_el_dorso, desc
    assert seat_map.revealed_pair_seats(img, REF_REV) == {"ML"}, "la señal nueva las ve siempre"


# --- el mazo nuevo lee el rango con UNA sola vista ------------------------
# Una segunda vista mete mas error del que quita, y las dos posibles estan
# medidas: la mascara completa fabrica dieces fantasma (T al 10,4%) y el rango
# aislado con cierre morfologico pierde el trazo fino del 8 y lo lee 3 -el 8
# desaparecio de la baraja, 0% de las lecturas en una sesion entera-.

class _Batch:
    def __init__(self):
        self.n = 0

    def job_count(self):
        return self.n

    def add_text_job(self, *a, **k):
        self.n += 1


def test_el_mazo_de_cara_blanca_encola_una_sola_vista():
    b = _Batch()
    color_rank_ocr.add_rank_jobs(b, recorte_glifo(), deck="glyph")
    assert b.n == len(color_rank_ocr.PSM_SCALE_VARIANTS)


def test_el_de_fondo_solido_sigue_encolando_dos():
    """Ancla + close, que ahi si suman."""
    b = _Batch()
    color_rank_ocr.add_rank_jobs(b, recorte_vieja(), deck="solid")
    assert b.n == 2 * len(color_rank_ocr.PSM_SCALE_VARIANTS)


def test_el_mazo_nuevo_cuesta_la_mitad_de_ocr_por_carta():
    b, b2 = _Batch(), _Batch()
    color_rank_ocr.add_rank_jobs(b, recorte_glifo(), deck="glyph")
    color_rank_ocr.add_rank_jobs(b2, recorte_vieja(), deck="solid")
    assert b.n < b2.n


# --- el boton tambien se encuentra SIN mirar el color ---------------------
# La via de forma: en el hueco del boton hay ALGO que tapa el tapete y en los
# otros cinco no hay nada. Asi el tema de mesa deja de importar.

def mesa_con_disco(seat, color_bgr, fondo=(60, 110, 70)):
    img = felt(fondo)
    fx, fy = seat_map.SEATS[seat]["button"]
    cx, cy = int(REF[0] + fx * REF[2]), int(REF[1] + fy * REF[3])
    r = int(((seat_map.BOTON_FORMA_AREA_MIN + seat_map.BOTON_FORMA_AREA_MAX) / 2
             * REF[2] * REF[3] / np.pi) ** 0.5)
    cv2.circle(img, (cx, cy), r, color_bgr, -1)
    return img


@pytest.mark.parametrize("nombre, color", [
    ("azul", (220, 120, 20)), ("morado", (180, 40, 130)),
    ("blanco", (250, 250, 250)), ("negro", (15, 15, 15)),
])
def test_un_disco_de_un_color_que_nadie_ha_calibrado_se_encuentra_igual(nombre, color):
    assert seat_map.detect_button_seat_por_forma(mesa_con_disco("MR", color), REF) == "MR"


def test_con_dos_discos_parecidos_no_se_elige():
    """No se sabe cual es, y elegir corre todas las posiciones."""
    doble = np.maximum(mesa_con_disco("MR", (220, 120, 20)),
                       mesa_con_disco("UL", (220, 120, 20)))
    assert seat_map.detect_button_seat_por_forma(doble, REF) is None


def test_por_forma_el_tapete_pelado_no_da_boton():
    assert seat_map.detect_button_seat_por_forma(felt(), REF) is None


def test_por_forma_funciona_con_el_tapete_de_otro_color():
    """Se lee del propio frame."""
    img = mesa_con_disco("UL", (220, 120, 20), fondo=(120, 60, 90))
    assert seat_map.detect_button_seat_por_forma(img, REF) == "UL"


def test_la_union_responde_cuando_responde_el_de_color():
    img = mesa_con_disco("TOPC", (250, 250, 250))
    assert seat_map.detect_button_seat_union(img, REF) == "TOPC"


# --- la plantilla del disco, aprendida de la propia mesa ------------------
# Idea del usuario: guardar el disco UNA VEZ en la sesion y buscarlo tal cual.
# Es la unica via que no depende de segmentar bien el contorno, que es el fallo
# mas comun del tema de fieltro liso (su aro dorado lo parte).

def disco_raro(seat, fondo=(60, 110, 70)):
    """Un disco que ningun umbral de color reconoceria: aro verde lima y estrella
    morada."""
    img = felt(fondo)
    fx, fy = seat_map.SEATS[seat]["button"]
    cx, cy = int(REF[0] + fx * REF[2]), int(REF[1] + fy * REF[3])
    r = int(((seat_map.BOTON_FORMA_AREA_MIN + seat_map.BOTON_FORMA_AREA_MAX) / 2
             * REF[2] * REF[3] / np.pi) ** 0.5)
    cv2.circle(img, (cx, cy), r, (60, 230, 180), -1)
    cv2.circle(img, (cx, cy), max(2, r // 2), (200, 30, 140), -1)
    return img


def test_una_plantilla_recien_creada_no_responde():
    pl = seat_map.PlantillaBoton()
    assert not pl.lista
    assert pl.buscar(disco_raro("UL"), REF) is None


@pytest.fixture
def plantilla_aprendida():
    pl = seat_map.PlantillaBoton()
    for _ in range(seat_map.PLANTILLA_MIN_DISCOS):
        pl.aprender(disco_raro("UL"), REF, "UL")
    return pl


def test_tras_suficientes_discos_ya_tiene_plantilla(plantilla_aprendida):
    assert plantilla_aprendida.lista


def test_encuentra_ese_disco_en_otro_asiento(plantilla_aprendida):
    assert plantilla_aprendida.buscar(disco_raro("MR"), REF) == "MR"


def test_en_una_mesa_vacia_la_plantilla_no_inventa_un_asiento(plantilla_aprendida):
    assert plantilla_aprendida.buscar(felt(), REF) is None


def test_con_plantilla_no_cambia_una_respuesta_que_las_otras_vias_ya_daban(
        plantilla_aprendida):
    img = mesa_con_disco("TOPC", (250, 250, 250))
    assert seat_map.detect_button_seat_union(img, REF, plantilla_aprendida) == "TOPC"


def test_aprender_de_un_frame_sin_disco_no_guarda_nada():
    pl = seat_map.PlantillaBoton()
    antes = len(pl)
    pl.aprender(felt(), REF, "UL")
    assert len(pl) == antes


# --- el mazo de fondo solido tiene mas de un juego de colores -------------

def carta_solida(hsv_color, w=83, h=117):
    """Carta del mazo de fondo solido: bloque de color, rango en BLANCO arriba y
    pip en un tono mas oscuro del mismo color ABAJO, que es la disposicion real y
    la que hace falta para probar que el rango se busca solo arriba."""
    img = np.full((h + 60, w + 60, 3), TAPETE, dtype=np.uint8)
    bgr = cv2.cvtColor(np.uint8([[list(hsv_color)]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
    oscuro = [max(0, int(x * 0.72)) for x in bgr]
    cv2.rectangle(img, (30, 30), (30 + w, 30 + h), bgr, -1)
    # el rango ocupa entre el 4,7% y el 15,7% del recorte en las cartas reales;
    # dibujarlo pequeño lo tira el filtro de ruido y el molde deja de valer
    cv2.putText(img, "K", (34, 30 + int(h * 0.52)), cv2.FONT_HERSHEY_SIMPLEX,
                h / 62.0, (255, 255, 255), 7)
    cv2.circle(img, (30 + w // 2, 30 + int(h * 0.80)), max(6, h // 9), oscuro, -1)
    return img


@pytest.mark.parametrize("palo", PALOS)
@pytest.mark.parametrize("juego", ["nuevos", "viejos"])
def test_los_dos_juegos_de_colores_del_mazo_solido(juego, palo):
    colores = NUEVOS if juego == "nuevos" else VIEJOS
    cajas = solido.find_card_boxes(carta_solida(colores[palo]))
    assert len(cajas) == 1
    assert cajas[0]["suit"] == palo


def test_las_cartas_del_hero_recortadas_por_su_nameplate_se_detectan():
    """83x54."""
    assert len(solido.find_card_boxes(carta_solida(NUEVOS["diamond"], 83, 54))) == 1


def test_el_tapete_solo_no_da_cartas_en_el_mazo_solido():
    assert solido.find_card_boxes(tapete(200, 300)) == []


# --- la mascara del rango se recorta al glifo, en LOS DOS mazos -----------
# Sin recortar, el rango queda pequeño dentro de un recuadro casi vacio y
# tesseract ni lo encuentra: en un 9 real de board, 5 de las 9 variantes
# devolvian cadena vacia y las otras 4 daban '3','J','3','3'. Recortada, las 9
# dicen '9'. En la sesion jugando, los boards con carta repetida bajaron de 13 a 1.

class _Vistas:
    def __init__(self):
        self.imgs = []

    def job_count(self):
        return len(self.imgs)

    def add_text_job(self, img, **k):
        self.imgs.append(img)


@pytest.mark.parametrize("deck", ["solid", "glyph"])
def test_el_ancla_que_se_manda_al_ocr_esta_recortada_al_glifo(deck):
    carta = recorte_vieja() if deck == "solid" else recorte_glifo()
    v = _Vistas()
    color_rank_ocr.add_rank_jobs(v, carta, deck=deck)
    ancla = v.imgs[0]
    entera = color_rank_ocr.rank_mask(carta, deck)
    assert ancla.shape[0] * ancla.shape[1] < entera.shape[0] * entera.shape[1]
    assert (ancla[:, :, 0] < 128).sum() > 0, "no se ha recortado a nada"


# --- una carta no se solapa con otra ni mide el doble ---------------------
# Las fichas del bote se apoyan encima de las cartas, y cuando el chip es rojo y
# la carta tambien SE FUNDEN. El blob resultante sigue pasando el filtro de forma
# (183x140 da 1.31, dentro del 0.6-2.0) y salia como una carta MAS, encima de las
# buenas: boards de SEIS cartas con una contada dos veces.

def fila_solida(n, palo="heart", w=83, h=117, hueco=11):
    img = np.full((h + 60, 60 + n * (w + hueco) + 60, 3), TAPETE, dtype=np.uint8)
    bgr = cv2.cvtColor(np.uint8([[list(NUEVOS[palo])]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
    for i in range(n):
        x = 60 + i * (w + hueco)
        cv2.rectangle(img, (x, 30), (x + w, 30 + h), bgr, -1)
        cv2.putText(img, "K", (x + 18, 30 + int(h * 0.6)), cv2.FONT_HERSHEY_SIMPLEX,
                    h / 90.0, (255, 255, 255), 4)
    return img


def test_cinco_cartas_separadas_dan_cinco_cajas():
    assert len(solido.find_card_boxes(fila_solida(5))) == 5


@pytest.fixture
def con_chip_puente():
    """Un chip del mismo color puenteando dos cartas: las funde en un blob doble."""
    img = fila_solida(5).copy()
    bgr = cv2.cvtColor(np.uint8([[list(NUEVOS["heart"])]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
    cv2.circle(img, (60 + 83 + 5, 30 + 110), 26, bgr, -1)
    return solido.find_card_boxes(img)


def test_con_un_chip_puenteando_no_salen_mas_de_cinco(con_chip_puente):
    assert len(con_chip_puente) <= 5


def test_ninguna_caja_se_solapa_con_otra(con_chip_puente):
    assert all(not (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"])
               for i, a in enumerate(con_chip_puente) for b in con_chip_puente[i + 1:])


def test_ninguna_caja_mide_el_doble_que_las_demas(con_chip_puente):
    """Seria dos cartas fundidas."""
    anchos = [c["w"] for c in con_chip_puente]
    assert not anchos or max(anchos) <= 1.6 * sorted(anchos)[len(anchos) // 2]


def test_con_solo_dos_cajas_no_se_filtra_por_ancho():
    """La mano del hero son 2 y no hay mediana fiable."""
    assert len(solido.find_card_boxes(fila_solida(2))) == 2


# --- el rango se busca en la parte de ARRIBA de la carta -----------------
# En el mazo de fondo solido el rango va arriba y el pip debajo, y las FICHAS del
# bote -que son claras- se apoyan sobre la mitad inferior y entran en la mascara
# de blanco como manchas pegadas al numero. Medido sobre 28 cartas de board
# etiquetadas: carta entera 18/28, mitad 21/28, 65% de arriba 22/28.

@pytest.fixture
def carta_limpia():
    return carta_solida(NUEVOS["club"])


def test_en_una_carta_limpia_aislar_no_quita_nada(carta_limpia):
    """El pip es de color, no blanco, asi que nunca estuvo en la mascara."""
    entera = color_rank_ocr.rank_mask(carta_limpia, "solid")
    arriba = color_rank_ocr.rango_grande_mask(carta_limpia, "solid")
    assert (arriba > 0).sum() == (entera > 0).sum()
    assert np.array_equal(np.where(arriba > 0)[0], np.where(entera > 0)[0]), \
        "el glifo se conserva entero"


def test_una_ficha_clara_apoyada_abajo_ensucia_la_mascara_completa_pero_no_la_del_rango(
        carta_limpia):
    entera = color_rank_ocr.rank_mask(carta_limpia, "solid")
    arriba = color_rank_ocr.rango_grande_mask(carta_limpia, "solid")
    con_ficha = carta_limpia.copy()
    cv2.circle(con_ficha, (30 + 40, 30 + 100), 16, (245, 245, 245), -1)
    sucia = color_rank_ocr.rank_mask(con_ficha, "solid")
    limpia = color_rank_ocr.rango_grande_mask(con_ficha, "solid")
    assert (sucia > 0).sum() > (entera > 0).sum()
    assert abs(int((limpia > 0).sum()) - int((arriba > 0).sum())) < 30


# --- el rango por CALCO, con las plantillas guardadas --------------------
# Idea del usuario: la fuente es la misma en los cuatro palos, asi que basta una
# plantilla por rango, generada una vez y versionada. Medido sobre 1.208 glifos
# de cuatro sesiones: dos ejemplares del mismo rango correlacionan 0.927 o mas y
# dos rangos distintos 0.878 como mucho.

@pytest.fixture(scope="module")
def glifos():
    etiquetas, M = color_rank_ocr._glifos()
    atlas = cv2.imread(color_rank_ocr.GLIFOS_FICHERO, cv2.IMREAD_GRAYSCALE)
    return etiquetas, M, atlas


def test_las_plantillas_se_cargan_del_fichero_versionado(glifos):
    _etiquetas, M, _atlas = glifos
    assert len(M) > 0


def test_las_plantillas_cubren_los_trece_rangos(glifos):
    etiquetas, _M, _atlas = glifos
    assert set(etiquetas) == set("2 3 4 5 6 7 8 9 10 J Q K A".split())


def test_el_atlas_tiene_una_casilla_por_etiqueta(glifos):
    etiquetas, _M, atlas = glifos
    lado = color_rank_ocr.GLIFO_LADO
    assert atlas.shape == (lado, lado * len(etiquetas))


def test_dos_plantillas_de_rangos_distintos_no_llegan_al_umbral(glifos):
    """Es lo que hace que el argmax acierte. Se compara al nivel de los vectores,
    no reconstruyendo una carta falsa: binarizar la plantilla destruye los grises
    del promedio y el parecido se hunde sin que eso diga nada del sistema."""
    etiquetas, M, _atlas = glifos
    mejor_ajeno = max(float(M[i] @ M[j])
                      for i in range(len(etiquetas)) for j in range(len(etiquetas))
                      if i != j and etiquetas[i] != etiquetas[j])
    assert mejor_ajeno < color_rank_ocr.GLIFO_UMBRAL


def test_cada_plantilla_se_identifica_a_si_misma_por_argmax(glifos):
    etiquetas, M, _atlas = glifos
    assert all(etiquetas[int(np.argmax(M @ M[i]))] == r for i, r in enumerate(etiquetas))


def test_el_umbral_es_el_95_por_ciento_calcado():
    """No un coeficiente: significa que 95 de cada 100 pixeles del glifo coinciden
    con la plantilla. Esta por encima del 90% a proposito, porque los glifos
    REDONDOS (3, 6, 8, 9) ganan a su segunda opcion por menos de 0.12 y ahi un
    falso positivo seria silencioso."""
    assert color_rank_ocr.GLIFO_UMBRAL == 0.95


def _calcado(g_bin, i):
    return color_rank_ocr._acuerdo(g_bin.astype(np.float32),
                                   color_rank_ocr._plantilla_binaria(i))


def test_cada_plantilla_se_calca_a_si_misma_al_cien_por_cien(glifos):
    etiquetas, _M, atlas = glifos
    lado = color_rank_ocr.GLIFO_LADO
    for i, r in enumerate(etiquetas):
        trozo = (atlas[:, i * lado:(i + 1) * lado] > 127)
        assert abs(_calcado(trozo, i) - 1.0) < 1e-9, f"la plantilla del '{r}'"


def test_un_glifo_al_que_le_falta_la_mitad_no_llega_al_umbral(glifos):
    _etiquetas, _M, atlas = glifos
    lado = color_rank_ocr.GLIFO_LADO
    roto = (atlas[:, 0:lado] > 127).copy()
    roto[:, lado // 2:] = False
    assert _calcado(roto, 0) < color_rank_ocr.GLIFO_UMBRAL


def test_un_borron_que_no_es_ningun_glifo_no_se_fuerza_a_un_rango():
    """Cae al OCR en vez de inventarse una carta."""
    ruido = np.full((80, 80, 3), (40, 140, 60), np.uint8)
    cv2.circle(ruido, (40, 40), 22, (255, 255, 255), -1)
    got, _sim = color_rank_ocr.rango_por_calco(ruido, "solid")
    assert got is None


# --- las plantillas conservan la PROPORCION del glifo --------------------
# La primera version escalaba cada glifo a un cuadrado, y eso deforma -una 'J'
# estrecha se estiraba hasta llenarlo- y tira la proporcion, que es informacion
# que distingue unos glifos de otros. Lo cazo el usuario abriendo el atlas.

@pytest.fixture(scope="module")
def anchos(glifos):
    etiquetas, _M, atlas = glifos
    lado = color_rank_ocr.GLIFO_LADO
    out = {}
    for i, r in enumerate(etiquetas):
        cols = np.where(atlas[:, i * lado:(i + 1) * lado].max(axis=0) > 40)[0]
        out[r] = (cols.max() - cols.min() + 1) if len(cols) else 0
    return out


def test_la_jota_es_mas_estrecha_que_la_dama(anchos):
    """Si se hubieran escalado a un cuadrado medirian lo mismo."""
    assert anchos["J"] < anchos["Q"], f"{anchos['J']} vs {anchos['Q']} px"


def test_el_diez_es_el_mas_ancho_de_los_trece(anchos):
    assert anchos["10"] == max(anchos.values())


def test_ningun_glifo_llena_el_ancho_entero_salvo_el_mas_ancho(anchos):
    assert sum(1 for a in anchos.values() if a >= color_rank_ocr.GLIFO_LADO - 1) <= 1


def test_un_glifo_estrecho_se_escala_por_su_alto_y_no_se_estira():
    m = np.zeros((40, 12), np.uint8)      # un glifo muy estrecho, tipo '1'
    m[5:35, 3:9] = 255
    g = color_rank_ocr._encajar(m)
    cols = np.where(g.max(axis=0) > 0.15)[0]
    filas = np.where(g.max(axis=1) > 0.15)[0]
    assert (cols.max() - cols.min()) < (filas.max() - filas.min())


# --- los cuatro estados de un asiento --------------------------------------
#
# La taxonomia es del usuario y es la especificacion que le faltaba a la
# ocupacion. Lo que aporta es SEPARAR dos preguntas que antes iban juntas:
# "¿sentado?" (estados 2/3/4) y "¿en la mano?" (3/4). Antes "sentado" dependia
# de que el OCR leyera el nick, y sobre una capsula oscurecida -un jugador ya
# retirado- eso falla a menudo: el asiento desaparecia del recuento y con el se
# desplazaban TODAS las posiciones.

@pytest.mark.parametrize("frac, dorsos, vista, esperado, desc", [
    (0.00, False, False, ts.HUECO, "tapete pelado"),
    (0.45, False, False, ts.SENTADO, "capsula sin cartas: sentado y retirado"),
    (0.45, True, False, ts.EN_MANO_TAPADAS, "con dorsos"),
    (0.45, False, True, ts.EN_MANO_A_LA_VISTA, "boca arriba"),
    (0.45, True, True, ts.EN_MANO_A_LA_VISTA, "girando: manda lo que se ve"),
])
def test_los_cuatro_estados(frac, dorsos, vista, esperado, desc):
    assert ts.estado_asiento(frac, dorsos, vista) == esperado, desc


@pytest.mark.parametrize("frac, dorsos, vista", [
    (0.00, True, False), (0.00, False, True),
])
def test_las_CARTAS_mandan_sobre_la_capsula(frac, dorsos, vista):
    """A una silla vacia no se le reparte. Si hay cartas, hay alguien, aunque la
    capsula no se vea: es la evidencia mas fuerte que existe."""
    assert ts.estado_asiento(frac, dorsos, vista) != ts.HUECO


def test_un_asiento_fuera_del_encuadre_no_se_inventa():
    """_capsula_frac devuelve None cuando no hay zona que mirar. Contarlo como
    ocupado añadiria un asiento y correria todas las posiciones."""
    assert ts.estado_asiento(None, False, False) == ts.HUECO


def test_el_umbral_de_capsula_cae_en_el_VALLE_entre_las_dos_poblaciones():
    """Medido sobre 13.900 observaciones de asiento de las 26 sesiones: la
    poblacion sin cartas es bimodal -1.594 observaciones bajo 0,05 (hueco), un
    valle de 71 entre 0,05 y 0,10, y ~4.000 entre 0,30 y 0,60 (sentado)-, y los
    asientos CON cartas empiezan en 0,126 (p01). El umbral tiene que quedar entre
    el hueco y ambos."""
    assert 0.05 <= ts.CAPSULA_MIN_FRAC <= 0.12
    assert ts.estado_asiento(0.02, False, False) == ts.HUECO
    assert ts.estado_asiento(0.13, False, False) == ts.SENTADO
