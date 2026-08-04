"""
Verificacion de la GUARDA DE REFERENCIA de table_state.analyze_layout() y de las
piezas que dependen de ella.

Todas las zonas del reconocimiento (nameplates, cartas, bote, botones, chat) son
fracciones del nucleo del tapete. Si el ovalo no se detecta, TODAS quedan
desplazadas y lo que salga son lecturas de sitios equivocados: el peor tipo de
salida, porque parece un resultado. Antes se seguia adelante con la "posicion
tipica" como fallback; medido sobre 999 frames de una sesion real, de los 21 que
cayeron en fallback CERO dieron cartas, boton, posicion, stack o recomendacion.

Sin depender de capturas: las imagenes se generan aqui, porque testing/ y
samples*/ estan fuera del repo.
"""
import cv2
import numpy as np
import pytest

from vision import color_rank_ocr as cro
from vision import dealer_button, seat_map
from vision import table_state as ts
from vision.ocr_client import MAX_PROCS, OcrBatch
from vision.rank_ocr import normalize_rank

pytestmark = pytest.mark.vision


def frame(color_tapete):
    """Un frame 1200x800 con un ovalo grande del color dado sobre fondo casi
    negro, que es la forma del cliente real.

    La PROPORCION importa: el nucleo del tapete real mide entre 2.12 y 2.36 de
    ancho/alto (medido sobre 687 frames de tres sesiones) y find_reference
    rechaza lo que baje de 2.0, porque por debajo de eso lo que ha detectado no
    es el ovalo."""
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    if color_tapete is not None:
        cv2.ellipse(img, (600, 400), (480, 215), 0, 0, 360, color_tapete, -1)
    return img


def fondo_claro():
    """Tema de fondo olivo: pasa el umbral de brillo y se suelda con el tapete."""
    img = np.full((800, 1200, 3), (60, 110, 90), dtype=np.uint8)
    cv2.ellipse(img, (600, 400), (480, 215), 0, 0, 360, (40, 140, 60), -1)
    return img


@pytest.fixture
def analizar(tmp_path):
    def _analizar(img):
        ruta = str(tmp_path / "f.png")
        cv2.imwrite(ruta, img)
        return ts.analyze_layout(ruta)
    return _analizar


def lineas(*textos):
    return [{"text": t, "left": 0, "top": 0, "right": 10, "bottom": 10, "cx": 5, "cy": 5}
            for t in textos]


# --- un tapete CON COLOR se detecta -----------------------------------------

def test_un_tapete_verde_da_referencia_real_no_fallback():
    ref = seat_map.find_reference(frame((40, 120, 40)))
    assert ref[4] is False
    assert ref[2] > 0.5 * 1200 and ref[3] > 0.3 * 800, "el ovalo ocupa casi el frame"


# --- un tapete GRIS/OSCURO no, y ahi esta el fallo real ---------------------
# El caso real: cambiar a un tapete gris oscuro (S=0, V=34) hizo fallar la
# deteccion en el 100% de los frames, frente al 98% de acierto con el verde
# (S=200, V=115), porque find_reference exige S>=45 y V>=60.

def test_un_tapete_gris_no_se_detecta():
    """Saturacion cero: no pasa S>=45."""
    assert seat_map.find_reference(frame((45, 45, 45)))[4] is True


@pytest.fixture
def estado_gris(analizar):
    return analizar(frame((45, 45, 45)))


def test_analyze_layout_corta_en_vez_de_leer_zonas_desplazadas(estado_gris):
    assert estado_gris["players"] == []
    assert estado_gris["hero_cards"] == []
    assert estado_gris["board"] == []
    assert estado_gris["table_reference_valid"] is False


def test_ni_llega_a_hacer_ocr(estado_gris):
    assert estado_gris["chat_lines"] == []


@pytest.mark.parametrize("trozo, que_es", [
    ("no se encuentra la mesa", "el sintoma"),
    ("oscuro", "el tema del tapete, que el usuario puede cambiar"),
    ("recalibra", "la otra causa que el usuario puede arreglar"),
])
def test_el_aviso_nombra_lo_que_el_usuario_puede_arreglar(estado_gris, trozo, que_es):
    aviso = " ".join(estado_gris["warnings"]).lower()
    assert trozo.lower() in aviso, que_es


def test_el_esquema_sigue_siendo_un_gamestate_valido(estado_gris):
    assert estado_gris["stack_unit"] == "bb"
    assert "pot" in estado_gris and "to_call" in estado_gris


def test_un_frame_sin_mesa_tampoco_inventa_nada(analizar):
    st = analizar(frame(None))
    assert st["players"] == []
    assert any("no se encuentra la mesa" in w for w in st["warnings"])


def test_un_frame_invalido_solo_intenta_recuperar_el_board(
        tmp_path, monkeypatch):
    ruta = tmp_path / "f.png"
    cv2.imwrite(str(ruta), frame((40, 120, 40)))

    class ReferenciaInvalida:
        fijada = (120, 90, 900, 400)

        def de(self, _bgr):
            return self.fijada + (True,)

    llamadas = []

    def solo_board(_bgr, state, ref, mazo):
        llamadas.append((ref, mazo))
        state["board_slots"] = ["As", "Kd", "7c"]
        state["board"] = ["As", "Kd", "7c"]
        return True

    monkeypatch.setattr(ts, "_leer_solo_board_con_referencia_fijada", solo_board)
    st = ts.analyze_layout(
        str(ruta), referencia=ReferenciaInvalida(), mazo="solid")

    assert llamadas == [((120, 90, 900, 400), "solid")]
    assert st["board"] == ["As", "Kd", "7c"]
    assert st["players"] == []
    assert st["hero_cards"] == []
    assert st["table_reference_valid"] is False


def test_una_ruta_que_no_existe_da_su_propio_aviso():
    st = ts.analyze_layout("/no/existe/ninguna.png")
    assert any("no se pudo leer la imagen" in w for w in st["warnings"])


# --- lecturas de OCR con VARIAS LINEAS --------------------------------------
# El pip del palo de la esquina del recorte se cuela en el OCR (el trebol se
# parece a un "4") y tesseract devuelve dos lineas. Antes se descartaba el texto
# entero y la carta se perdia: el usuario lo cazo jugando ("hay un 2 trebol" en
# un board que la app leia con solo 2 cartas). Como el pip esta ARRIBA del rango
# y tesseract emite de arriba abajo, el rango real es la ultima linea valida.

@pytest.mark.parametrize("crudo, esperado", [
    ("K", "K"),
    ("10", "10"),
    ("1O", "10"),
    ("4\n2", "2"),          # el caso real: pip de trebol + rango
    ("4\n8", "8"),
    ("4\nQ", "Q"),
    ("4", "4"),             # un 4 de verdad sigue siendo un 4
    ("4\nX", "4"),          # si la ultima linea es basura, la anterior valida
    ("X\nZ", None),         # ninguna linea valida: no se inventa carta
    ("", None),
])
def test_normalize_rank(crudo, esperado):
    assert normalize_rank(crudo) == esperado


# --- ocupacion de asientos: lo que decide TODAS las posiciones --------------
# Las posiciones salen del RECUENTO de asientos ocupados, asi que un asiento de
# mas las desplaza todas y el rango elegido es el de otra posicion. Caso real:
# en un torneo 3-Max la app veia 4 jugadores en el 34% de los frames y llego a
# asignarle al hero la posicion CO, que en una mesa de 3 no existe.

@pytest.mark.parametrize("texto, ocupado, motivo", [
    ("69,3 BB", True, "un importe en BB"),
    ("Dav6934", True, "un nick"),
    ("Igualar", True, "un verbo de accion"),
    ("No ir", True, "el 'No ir' del cliente, que va en dos palabras"),
    ("", False, "tapete vacio"),
    ("60668", False, "un ENTERO SUELTO ya no ocupa: la textura de puntos del "
                     "tapete se OCR-ea asi en 60 de 60 frames"),
    ("5.892", False, "ni con separador de miles"),
])
def test_plate_occupied(texto, ocupado, motivo):
    assert bool(ts._plate_occupied(lineas(texto))) is ocupado, motivo


def test_la_fuerza_de_la_evidencia_decide_cual_se_suelta_si_sobran():
    f = ts._fuerza_ocupacion
    assert f("HERO", {}, set(), None) == 4, "el hero nunca se suelta"
    assert f("MR", {}, set(), "MR") == 4, "ni el asiento del boton"
    assert f("MR", {}, {"MR"}, None) > f("MR", {"name": "pepe"}, set(), None), \
        "un dorso de carta pesa mas que un nombre"
    assert f("MR", {"stack": 44.5}, set(), None) > f("MR", {"name": "pepe"}, set(), None), \
        "y un importe en BB tambien"
    assert f("MR", {}, set(), None) < f("MR", {"name": "pepe"}, set(), None), \
        "lo mas debil es un asiento sin nada de eso"


# --- CACHE DE RANGOS --------------------------------------------------------
# El OCR de rango es el 86% del trabajo de un frame (90 de 105 jobs) y una carta
# del board es la MISMA IMAGEN durante toda la calle. La clave es (palo, hash del
# interior del recorte): el interior porque el borde trae tapete y fichas que se
# animan -con el recorte entero solo coincide el 52% de las veces, quitando el
# 15% de margen el 81%-, y el palo para que una colision exija la misma carta.

def carta(valor_centro, valor_borde=0):
    """Recorte sintetico de 120x84: un centro que decide el rango y un borde que
    se anima. El centro cubre HOLGADAMENTE el interior que hashea cache_key."""
    img = np.full((120, 84, 3), valor_borde, dtype=np.uint8)
    img[16:104, 10:74] = valor_centro
    return img


@pytest.fixture(autouse=True)
def cache_limpia():
    cro.reset_rank_cache()
    yield
    cro.reset_rank_cache()


def test_la_misma_carta_da_la_misma_clave():
    assert cro.cache_key(carta(200), "club") == cro.cache_key(carta(200), "club")


@pytest.mark.parametrize("otro, motivo", [
    ((carta(200), "heart"), "otro palo"),
    ((carta(150), "club"), "otro centro, o sea otro rango"),
])
def test_una_carta_distinta_da_otra_clave(otro, motivo):
    assert cro.cache_key(carta(200), "club") != cro.cache_key(*otro), motivo


def test_el_ruido_solo_en_el_borde_no_cambia_la_clave():
    """Es justo lo que se anima: tapete y fichas alrededor de la carta."""
    assert cro.cache_key(carta(200), "club") == cro.cache_key(carta(200, 77), "club")


def test_un_recorte_vacio_no_da_clave():
    assert cro.cache_key(np.zeros((0, 0, 3), np.uint8), "club") is None


def test_guardar_y_recuperar():
    k = cro.cache_key(carta(200), "club")
    assert cro.cached_rank(k)[0] is False
    cro.store_rank(k, "K")
    assert cro.cached_rank(k) == (True, "K")


def test_la_cache_conserva_la_confianza_del_origen():
    k = cro.cache_key(carta(200), "club")
    cro.store_rank(k, "K", confidence=0.73)

    assert cro.cached_rank(k) == (True, "K")
    assert cro.cached_rank_confidence(k) == pytest.approx(0.73)


def test_tambien_se_cachea_el_fallo():
    """El OCR es determinista: reintentar un None daria el mismo None, y es el
    caso mas caro."""
    k = cro.cache_key(carta(150), "club")
    cro.store_rank(k, None)
    assert cro.cached_rank(k) == (True, None)
    assert cro.cached_rank(cro.cache_key(carta(99), "spade"))[0] is False, \
        "guardar None es distinto de no tener entrada"


def test_la_cache_esta_acotada():
    for i in range(cro.CACHE_MAX + 5):
        cro.store_rank(("x", bytes([i % 256, i // 256])), "A")
    assert len(cro._RANK_CACHE) <= cro.CACHE_MAX


def test_reset_vacia_la_cache():
    cro.store_rank(cro.cache_key(carta(200), "club"), "K")
    cro.reset_rank_cache()
    assert not cro._RANK_CACHE
    assert not cro._RANK_CONFIDENCE_CACHE


# --- REPARTO DE JOBS DE OCR POR IDIOMA --------------------------------------
# Cargar el modelo espanol cuesta ~0,26 s y solo dos jobs del frame lo necesitan
# (chat y botones). Con el reparto intercalado caian en procesos DISTINTOS y el
# modelo se cargaba dos veces; juntandolos en un trozo propio, el lote baja de
# 1,202 s a 0,888 s (-26%). Lo que NO puede cambiar es que cada job reciba su
# propio resultado, en su propio sitio.

repartir = OcrBatch.__dict__["_repartir"].__func__


def pares(n_spa, n_eng):
    jobs = [{"lang": "spa", "id": f"s{i}"} for i in range(n_spa)]
    jobs += [{"id": f"e{i}"} for i in range(n_eng)]
    return list(enumerate(jobs))


@pytest.fixture
def reparto_real():
    return pares(2, 103), repartir(pares(2, 103))


def test_los_jobs_en_espanol_van_todos_en_el_mismo_trozo(reparto_real):
    _real, trozos = reparto_real
    con_spa = [t for t in trozos if any(j.get("lang") == "spa" for _i, j in t)]
    assert len(con_spa) == 1


def test_y_ese_trozo_no_lleva_nada_mas(reparto_real):
    _real, trozos = reparto_real
    for t in trozos:
        if any(j.get("lang") == "spa" for _i, j in t):
            assert all(j.get("lang") == "spa" for _i, j in t)


def test_no_se_pasa_del_numero_de_procesos(reparto_real):
    _real, trozos = reparto_real
    assert len(trozos) <= MAX_PROCS


def test_no_se_pierde_ni_se_duplica_ningun_job(reparto_real):
    real, trozos = reparto_real
    assert sorted(i for t in trozos for i, _j in t) == list(range(len(real)))


def test_sin_jobs_de_idioma_no_se_desperdicia_un_trozo():
    trozos = repartir(pares(0, 50))
    assert len(trozos) == min(MAX_PROCS, 50)
    assert sorted(i for t in trozos for i, _j in t) == list(range(50))


def test_con_un_solo_job_un_solo_trozo():
    trozos = repartir(pares(0, 1))
    assert len(trozos) == 1 and len(trozos[0]) == 1


def test_solo_jobs_en_espanol_un_trozo_con_todos():
    trozos = repartir(pares(3, 0))
    assert len(trozos) == 1 and len(trozos[0]) == 3


# --- EL VERBO NO ES UN NOMBRE -----------------------------------------------
# Cuando un jugador actua, el cliente le sustituye el nick por lo que ha hecho,
# asi que leerlo como nombre le cambia el nombre justo cuando hace algo. Medido
# sobre una sesion real: 362 de 6264 nombres leidos (6%) eran un verbo.

@pytest.mark.parametrize("texto", ["Pasar", "Igualar", "Apostar", "Subir",
                                   "Ausente", "All-in", "all in", "No ir"])
def test_los_verbos_se_reconocen_como_verbos(texto):
    assert ts.es_verbo_de_accion(texto)


@pytest.mark.parametrize("texto", ["BerniBeau", "over590", "makeao31", "44,5 BB", ""])
def test_lo_que_no_es_un_verbo_no_lo_es(texto):
    assert ts.es_verbo_de_accion(texto) is False


def test_un_nameplate_normal_da_nombre_y_no_accion():
    n, _stk, acc = ts._seat_plate_name_stack(lineas("Dav6934", "69,3"))
    assert n == "Dav6934"
    assert acc is None


def test_un_nick_en_mayusculas_es_valido_dentro_de_un_nameplate():
    """BOLIYA16 era visible durante cientos de frames pero el extractor general
    exige minúsculas para defenderse de etiquetas de UI. Dentro de la zona fija
    de un asiento ese veto no corresponde."""
    n, _stk, acc = ts._seat_plate_name_stack(lineas("BOLIYA16", "55,3 BB"))
    assert n == "BOLIYA16"
    assert acc is None


@pytest.mark.parametrize("verbo", ["Igualar", "All-in"])
def test_un_nameplate_con_el_verbo_no_devuelve_nombre(verbo):
    n, _stk, acc = ts._seat_plate_name_stack(lineas(verbo))
    assert n is None
    assert acc == verbo, "el verbo se devuelve aparte, que es informacion util"


@pytest.mark.parametrize("estado", ["Ciegas", "Ganado", "Ganador"])
def test_un_texto_temporal_sobre_el_asiento_no_se_vota_como_nombre(estado):
    n, _stk, acc = ts._seat_plate_name_stack(lineas(estado))
    assert n is None
    assert acc == estado


# --- ETIQUETAS DE POSICION SEGUN CUANTOS JUGADORES HAY ---------------------
# La equivalencia es por CUANTOS JUGADORES QUEDAN DETRAS, no por el nombre del
# asiento: es lo que determina la anchura de un rango de apertura. La tabla
# estaba escrita a mano y a partir de 6 jugadores le daba EP1 al primero en
# hablar, pero EP1 de una mesa de 9 tiene OCHO detras y el primero de una de 6
# solo tiene CINCO. Medido a 20bb: se servia un 17,0% de las manos donde tocaba
# un 25,0%, en todas las manos abiertas desde esa posicion.

def orden_de_habla(n):
    """SEATING_BY_N empieza en el BOTON; preflop se habla empezando tras la BB."""
    v = seat_map.SEATING_BY_N[n]
    corte = max(0, n - 3)
    return v[len(v) - corte:] + v[:len(v) - corte]


@pytest.mark.parametrize("n", range(2, 10))
def test_los_que_quedan_detras_cuadran_con_el_numero_de_jugadores(n):
    canon = seat_map.CANON9
    detras = [canon.index("BB") - canon.index(p) for p in orden_de_habla(n)]
    assert detras == list(range(n - 1, -1, -1))


@pytest.mark.parametrize("n, primero, motivo", [
    (6, "MP2", "EP1 tiene 8 detras; en una mesa de 6 solo hay 5"),
    (7, "MP1", ""),
    (8, "EP2", ""),
    (9, "EP1", "es la mesa para la que estan digitalizados los rangos"),
])
def test_quien_habla_primero_segun_cuantos_hay(n, primero, motivo):
    assert orden_de_habla(n)[0] == primero, motivo


def test_heads_up():
    """El boton ES la ciega pequeña: habla primero y tiene un rival detras, igual
    que la SB de una mesa de 9."""
    assert orden_de_habla(2) == ["SB", "BB"]


@pytest.mark.parametrize("n", range(3, 10))
def test_todas_las_filas_acaban_en_btn_sb_bb(n):
    assert orden_de_habla(n)[-3:] == ["BTN", "SB", "BB"]


@pytest.mark.parametrize("n", range(3, 10))
def test_seating_by_n_empieza_siempre_por_el_asiento_del_boton(n):
    assert seat_map.SEATING_BY_N[n][0] == "BTN"


def test_dealer_button_usa_la_misma_tabla():
    """No una copia que pueda discrepar."""
    assert dealer_button.SEATING_BY_N is seat_map.SEATING_BY_N


# --- un FONDO CLARO se confunde con el tapete y hay que detectarlo ----------
# Premisa rota: find_reference separa el ovalo del fondo "casi negro". Con un
# tema de fondo olivo (H=44, S=80) pasa el 42% del frame y el mayor blob acaba
# siendo fondo y tapete pegados: nucleo tocando el borde de arriba. Todas las
# zonas quedan desplazadas y -lo que lo destapo- los dorsos caen fuera, asi que
# no se detecta ningun rival y la equity no se calcula nunca.

def test_con_el_fondo_claro_pegado_al_tapete_no_hay_referencia_real():
    assert seat_map.find_reference(fondo_claro())[4] is True


def test_con_fondo_claro_analyze_layout_corta_y_nombra_la_causa(analizar):
    st = analizar(fondo_claro())
    assert any("no se encuentra la mesa" in w for w in st["warnings"])
    assert any("FONDO" in w and "claro" in w for w in st["warnings"]), \
        "es lo que el usuario puede cambiar"


def test_un_blob_demasiado_alto_para_ser_el_ovalo_no_vale():
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(img, (600, 400), (300, 380), 0, 0, 360, (40, 120, 40), -1)
    assert seat_map.find_reference(img)[4] is True


def test_un_blob_que_llega_al_borde_de_arriba_tampoco():
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(img, (600, 300), (480, 310), 0, 0, 360, (40, 120, 40), -1)
    assert seat_map.find_reference(img)[4] is True


# --- la referencia se FIJA una vez y se reutiliza ---------------------------
# El tapete no se mueve mientras juegas. Fijarlo rescata entero el tema de fondo
# claro, donde el ovalo solo se detecta bien en el 14% de los frames: analizados
# 19 -> 132 de 132, y la equity 0 -> 27.

@pytest.fixture
def fijada():
    rf = seat_map.ReferenciaFijada()
    verde = frame((40, 120, 40))
    for _ in range(seat_map.REF_MIN_PARA_FIJAR):
        rf.de(verde)
    return rf


def test_mientras_no_hay_suficientes_lecturas_no_hay_nada_fijado():
    rf = seat_map.ReferenciaFijada()
    assert rf.fijada is None


def test_tras_suficientes_lecturas_buenas_queda_fijada(fijada):
    assert fijada.fijada is not None


def test_un_frame_sin_ovalo_ya_no_corta_se_usa_la_fijada(fijada):
    ref = fijada.de(fondo_claro())
    assert ref[4] is False
    assert tuple(ref[:4]) == fijada.fijada, "la que se devuelve es la fijada, no una inventada"


def test_unas_pocas_lecturas_discrepantes_no_mueven_la_fijada(fijada):
    """Son ruido de la deteccion."""
    antes = fijada.fijada
    movido = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(movido, (600, 300), (350, 155), 0, 0, 360, (40, 120, 40), -1)
    for _ in range(seat_map.REF_SEGUIDAS_PARA_REFIJAR - 1):
        fijada.de(movido)
    assert fijada.fijada == antes


def test_pero_si_son_sostenidas_se_vuelve_a_fijar(fijada):
    """La ventana se ha movido."""
    antes = fijada.fijada
    movido = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(movido, (600, 300), (350, 155), 0, 0, 360, (40, 120, 40), -1)
    for _ in range(seat_map.REF_SEGUIDAS_PARA_REFIJAR):
        fijada.de(movido)
    assert fijada.fijada != antes


def test_una_variacion_dentro_de_la_tolerancia_no_refija_nada(fijada):
    """Es el ruido normal de la deteccion (0-4,5% medido)."""
    base = fijada.fijada
    casi = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(casi, (600, 400), (475, 213), 0, 0, 360, (40, 120, 40), -1)   # ~1% menor
    for _ in range(seat_map.REF_SEGUIDAS_PARA_REFIJAR * 2):
        fijada.de(casi)
    assert fijada.fijada == base


# --- EL PUENTE DE PAPEL DE PARED, y por que se REPARA en vez de sustituir ---
#
# El papel de pared tiene una banda clara arriba que pasa el umbral de brillo.
# Cuando el encuadre deja bastante margen por encima de la mesa, esa banda se
# suelda con el ovalo: el bloque llega a y=0 y su proporcion cae de ~2,5 a ~1,5,
# asi que _nucleo_plausible lo rechaza -bien rechazado- y el frame se pierde
# ENTERO. Lo cazo el usuario jugando (28-07-2026, sesion 014613): 123 de 123
# frames, el 100% de la partida sin analizar.
#
# La reparacion NO es un detector nuevo. Van SIETE intentos de sustituir la
# deteccion (tono dominante, forma de ovalo, ancla HSV, elipse por bordes, "lo
# que no es el fondo", textura, simetria) y los siete se descartaron por lo
# mismo: cambiaban la caja TAMBIEN donde ya funcionaba, con desvios medianos del
# 5% al 29%, y eso mueve el mapa de zonas entero.
#
# Solo se ejecuta cuando el bloque YA es implausible, o sea cuando hoy el frame
# se pierde. Comprobado sobre 880 frames de 21 sesiones:
#     669 cajas IDENTICAS   90 recuperadas   121 siguen fallando
#       0 perdidas            0 cambiadas

@pytest.fixture
def mesa_grande():
    img = np.full((900, 1400, 3), 12, dtype=np.uint8)
    cv2.ellipse(img, (700, 480), (520, 210), 0, 0, 360, (40, 120, 40), -1)
    return img


def test_sin_puente_el_ovalo_se_detecta(mesa_grande):
    assert not seat_map.find_reference(mesa_grande)[4]


def test_con_puente_se_sigue_detectando(mesa_grande):
    """Antes se perdia el frame entero."""
    puente = mesa_grande.copy()
    cv2.rectangle(puente, (820, 0), (1010, 300), (40, 120, 40), -1)
    assert not seat_map.find_reference(puente)[4]


def test_la_caja_reparada_es_practicamente_la_del_ovalo_limpio(mesa_grande):
    solo = seat_map.find_reference(mesa_grande)
    puente = mesa_grande.copy()
    cv2.rectangle(puente, (820, 0), (1010, 300), (40, 120, 40), -1)
    con = seat_map.find_reference(puente)
    tol = 0.06 * max(solo[2], solo[3])
    assert all(abs(a - b) <= tol for a, b in zip(con[:4], solo[:4]))
    assert con[1] > seat_map.NUCLEO_MARGEN_BORDE, "ya no toca el borde de arriba"


def test_un_frame_que_ya_iba_bien_devuelve_exactamente_lo_mismo(mesa_grande):
    """GARANTIA ESTRUCTURAL: si el bloque ya era plausible, no se toca."""
    a = seat_map.find_reference(mesa_grande)[:4]
    assert seat_map.find_reference(mesa_grande)[:4] == a


def test_un_bloque_que_no_es_un_ovalo_no_se_arregla_a_la_fuerza():
    img = np.full((900, 1400, 3), 12, dtype=np.uint8)
    cv2.rectangle(img, (200, 0), (1200, 700), (40, 120, 40), -1)
    assert seat_map.find_reference(img)[4], "fallback, no una caja inventada"


# --- SI NO HAY CAPSULA, NO HAY NADIE ---------------------------------------
#
# El usuario lo cazo jugando (28-07-2026, sesion 012453): la app listaba 6
# jugadores con 5 en la mesa. El sobrante era "wwww584" leido en un asiento
# VACIO -se recorto la zona y es tapete y papel de pared, nada mas-. Como las
# posiciones salen del RECUENTO, ese fantasma las corrio todas: el hero pasaba de
# BB a MP2 y le servia un rango de apertura donde tocaba la opcion de la ciega.
# Su nota: "porque me dice fold si es call? hice ciega".
#
# Se descarto en su dia mirar solo el brillo, porque "las sillas granate son tan
# oscuras como la capsula". Cierto, pero el granate esta SATURADO: pidiendo
# oscuro Y sin color si se separan. Medido sobre 2.856 zonas de 15 sesiones y
# seis temas de mesa, sale bimodal con hueco:
#     0.00-0.05   217 zonas    <- vacias (revisadas a ojo por muestreo)
#     0.05-0.10     3 zonas    <- el hueco
#     0.10-1.00  2636 zonas    <- con plate

def zona_tapete():
    z = np.zeros((120, 380, 3), np.uint8)
    z[:, :] = (40, 90, 45)
    return z


def zona_sillas():
    z = zona_tapete()
    cv2.rectangle(z, (60, 5), (150, 45), (60, 40, 110), -1)    # granate, SATURADO
    cv2.rectangle(z, (170, 5), (260, 45), (60, 40, 110), -1)
    return z


def test_una_zona_de_solo_tapete_no_tiene_capsula():
    assert not ts._hay_capsula(zona_tapete())


def test_el_papel_de_pared_tampoco():
    papel = np.zeros((120, 380, 3), np.uint8)
    papel[:, :] = (35, 55, 40)
    assert not ts._hay_capsula(papel)


def test_las_sillas_granate_no_cuentan_como_capsula():
    """Son oscuras pero CON COLOR: es lo que tumbo el intento anterior de usar
    solo el brillo."""
    assert not ts._hay_capsula(zona_sillas())


def test_un_nameplate_de_verdad_si_tiene_capsula():
    plate = zona_tapete()
    cv2.rectangle(plate, (20, 25), (330, 95), (28, 28, 30), -1)
    assert ts._hay_capsula(plate)


def test_y_con_las_sillas_encima_tambien():
    z = cv2.rectangle(zona_sillas(), (20, 25), (330, 95), (28, 28, 30), -1)
    assert ts._hay_capsula(z)


def test_el_umbral_esta_en_el_hueco_medido():
    """No pegado a un extremo."""
    assert 0.05 < ts.CAPSULA_MIN_FRAC < 0.10


def test_una_zona_de_tamaño_nulo_no_veta_nada():
    """No se inventa un vacio donde no se ha podido mirar."""
    assert ts._hay_capsula(np.zeros((0, 0, 3), np.uint8))


# --- un asiento que no existe en ESTA disposicion no cuenta -------------------
# El censo y el boton fijados de la mano en curso llegan de fuera y se midieron
# con la disposicion que hubiera entonces. Con el selector en "Auto" esa puede
# cambiar a mitad de sesion: los primeros frames se miran con la de 6 y, al
# fijarse el detector en 9, TOPC deja de existir.

def test_un_boton_fijado_en_un_asiento_inexistente_no_tumba_el_frame(analizar, tmp_path):
    """Se colaba en `occupied` -"el dealer es siempre un jugador sentado"- y el
    reparto de posiciones se caia con KeyError al buscar el centro de TOPC en una
    mesa de 9, que no lo tiene."""
    ruta = str(tmp_path / "f9.png")
    cv2.imwrite(ruta, frame((40, 140, 60)))
    st = ts.analyze_layout(ruta, max_players=9, boton_fijado="TOPC")
    assert st["max_players"] == 9
    assert all(p["seat"] != "TOPC" for p in st["players"])


def test_un_censo_con_asientos_de_otra_mesa_se_filtra(analizar, tmp_path):
    ruta = str(tmp_path / "f9b.png")
    cv2.imwrite(ruta, frame((40, 140, 60)))
    st = ts.analyze_layout(ruta, max_players=9,
                           asientos_estables=["TOPC", "UL", "HERO"])
    assert all(p["seat"] != "TOPC" for p in st["players"])


# --- una VENTANA PEQUEÑA da un ovalo mas redondo -----------------------------
# Lo destapo el usuario: "me dice todo el rato que no se encuentra la mesa". Tenia
# una mesa perfecta y bien encuadrada y los 41 frames de su sesion salian sin
# analizar. Habia hecho la ventana del cliente mas pequeña (1117x685 contra
# 1595x971) y PokerStars dibuja la mesa MAS REDONDA al encogerla: su ovalo medía
# 608x322, proporcion 1,89, y el suelo estaba en 2,0. Se rechazaba por 0,11.

def test_un_ovalo_de_proporcion_1_89_se_acepta():
    """El caso real, reproducido con las medidas de su frame."""
    img = np.full((685, 1117, 3), 12, dtype=np.uint8)
    cv2.ellipse(img, (552, 301), (304, 161), 0, 0, 360, (40, 140, 60), -1)
    x, y, w, h, fallback = seat_map.find_reference(img)
    assert not fallback, "una mesa asi de redonda tambien es una mesa"
    assert 1.8 < w / h < 2.0


def test_un_bloque_CUADRADO_se_sigue_rechazando():
    """El suelo esta para eso: lo que separa un ovalo de tapete de un panel del
    cliente soldado con el fondo. Bajarlo a 1,85 no puede convertirlo en un
    colador."""
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.rectangle(img, (300, 200), (900, 620), (40, 140, 60), -1)   # 600x420 = 1,43
    assert seat_map.find_reference(img)[4] is True


def test_lo_que_toca_el_borde_de_arriba_se_rechaza_igual():
    """La otra condicion no se ha tocado, y es la que de verdad separa los temas
    de fondo claro: se soldaban con el borde en el 80% de sus frames."""
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    cv2.ellipse(img, (600, 400), (480, 215), 0, 0, 360, (40, 140, 60), -1)
    cv2.rectangle(img, (100, 0), (1100, 200), (40, 140, 60), -1)    # banda hasta y=0
    assert seat_map.find_reference(img)[4] is True
