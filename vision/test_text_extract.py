"""
Verificacion del parseo de texto de la mesa (vision/text_extract.py): bote,
ciegas, nombres y stacks a partir de las lineas que devuelve el OCR.

Son 400 lineas de expresiones regulares que hasta ahora solo se ejercitaban de
refilon, y estan en el peor sitio posible para no tener tests: entre un OCR que
se equivoca y un motor que decide sobre lo que salga de aqui. Un separador de
miles interpretado como decimal cambia una profundidad por mil, y eso produce
una recomendacion con conviccion y falsa.

Es puro texto: ni opencv ni tesseract.
"""
import pytest

from vision import text_extract as tx


def L(texto, cx=0, cy=0):
    """Una linea OCR con la forma que devuelve parse_tsv_lines."""
    return {"text": texto, "cx": cx, "cy": cy,
            "left": cx - 5, "top": cy - 5, "right": cx + 5, "bottom": cy + 5}


def tsv(*filas):
    """TSV como el de tesseract. Cada fila: (bloque, par, linea, left, top, w, h,
    conf, texto)."""
    cabecera = "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext"
    lineas = [cabecera]
    for i, (b, p, l, left, top, w, h, conf, texto) in enumerate(filas):
        lineas.append(f"5\t1\t{b}\t{p}\t{l}\t{i}\t{left}\t{top}\t{w}\t{h}\t{conf}\t{texto}")
    return "\n".join(lineas)


# --- conversion de numeros ---------------------------------------------------

@pytest.mark.parametrize("crudo, esperado", [
    ("250", 250),
    ("1.900", 1900),            # separador de MILES del cliente en castellano
    ("12,500", 12500),          # separador de miles del cliente en ingles
    ("17,5K", 17500),           # con sufijo, la coma es DECIMAL
    ("12.5K", 12500),
    ("1,2M", 1200000),
    ("300K", 300000),
    ("17, 5K", 17500),          # el OCR mete un espacio detras de la coma
])
def test_to_int_corner(crudo, esperado):
    """El . y la , cambian de significado segun haya o no sufijo K/M: miles sin
    sufijo, decimal con sufijo. Confundirlos es un error de mil veces."""
    assert tx._to_int_corner(crudo) == esperado


def test_to_int_corner_con_basura_devuelve_none():
    assert tx._to_int_corner("xxK") is None


@pytest.mark.parametrize("crudo, esperado", [("1.900", 1900), ("12,500", 12500), ("250", 250)])
def test_to_int_trata_los_separadores_como_miles(crudo, esperado):
    assert tx._to_int(crudo) == esperado


# --- parse_tsv_lines ---------------------------------------------------------

def test_las_palabras_de_una_linea_se_juntan():
    salida = tx.parse_tsv_lines(tsv((1, 1, 1, 10, 20, 30, 10, 90, "Bote:"),
                                    (1, 1, 1, 45, 20, 25, 10, 90, "3,75")))
    assert len(salida) == 1
    assert salida[0]["text"] == "Bote: 3,75"


def test_la_caja_de_la_linea_envuelve_todas_sus_palabras():
    salida = tx.parse_tsv_lines(tsv((1, 1, 1, 10, 20, 30, 10, 90, "Bote:"),
                                    (1, 1, 1, 45, 18, 25, 14, 90, "3,75")))
    ln = salida[0]
    assert ln["left"] == 10 and ln["top"] == 18
    assert ln["right"] == 70 and ln["bottom"] == 32


def test_lineas_distintas_no_se_mezclan():
    salida = tx.parse_tsv_lines(tsv((1, 1, 1, 10, 20, 30, 10, 90, "uno"),
                                    (1, 1, 2, 10, 60, 30, 10, 90, "dos")))
    assert sorted(l["text"] for l in salida) == ["dos", "uno"]


def test_se_descarta_lo_que_el_ocr_lee_con_poca_confianza():
    """Por debajo de 25 es ruido, y el ruido es lo que fabrica nombres y stacks
    que no existen."""
    salida = tx.parse_tsv_lines(tsv((1, 1, 1, 10, 20, 30, 10, 10, "basura")))
    assert salida == []


def test_se_descartan_las_palabras_vacias():
    salida = tx.parse_tsv_lines(tsv((1, 1, 1, 10, 20, 30, 10, 90, "   ")))
    assert salida == []


def test_un_tsv_vacio_no_revienta():
    assert tx.parse_tsv_lines("") == []


# --- merge_line_sets ---------------------------------------------------------

def test_dos_lecturas_de_la_misma_posicion_no_se_duplican():
    """Las pasadas de OCR se solapan; sin deduplicar, el mismo nameplate contaria
    dos veces y con el la ocupacion del asiento."""
    a, b = [L("pepe", 100, 100)], [L("pepe", 105, 103)]
    assert len(tx.merge_line_sets(a, b)) == 1


def test_dos_lecturas_lejanas_se_conservan_las_dos():
    a, b = [L("pepe", 100, 100)], [L("juan", 400, 300)]
    assert len(tx.merge_line_sets(a, b)) == 2


def test_manda_la_primera_lectura_de_cada_posicion():
    """El orden de los conjuntos es la prioridad."""
    a, b = [L("bueno", 100, 100)], [L("corrupto", 102, 101)]
    assert tx.merge_line_sets(a, b)[0]["text"] == "bueno"


# --- el bote -----------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("Bote: 3.750", 3750),
    ("Pot: 12,500", 12500),
    ("bote 1.200", 1200),
    ("BOTE: 500", 500),
])
def test_find_pot_en_fichas(texto, esperado):
    assert tx.find_pot([L(texto)]) == esperado


def test_find_pot_descarta_lo_inverosimil():
    """MIN_PLAUSIBLE_POT existe porque el OCR produce numeros de una cifra en
    cualquier sitio."""
    assert tx.find_pot([L("Bote: 3")]) is None


def test_find_pot_sin_etiqueta_no_encuentra_nada():
    assert tx.find_pot([L("3.750")]) is None


@pytest.mark.parametrize("texto, esperado", [
    ("Bote: 3,75 BB", 3.75),
    ("Bote: 12,5 BB", 12.5),
    ("Pot: 4 BB", 4.0),
    ("Bote: 0,5 BB", 0.5),
])
def test_find_pot_bb(texto, esperado):
    assert tx.find_pot_bb([L(texto)]) == esperado


def test_find_pot_bb_exige_la_etiqueta():
    """En modo BB todos los importes llevan el mismo sufijo, asi que sin ella un
    stack de la zona se confundiria con el bote."""
    assert tx.find_pot_bb([L("47,8 BB")]) is None


def test_find_pot_bb_descarta_un_bote_imposible():
    assert tx.find_pot_bb([L(f"Bote: {tx.MAX_PLAUSIBLE_POT_BB + 100:g} BB")]) is None


# --- las ciegas --------------------------------------------------------------

@pytest.mark.parametrize("texto, sb, bb, ante", [
    ("Blinds 250/500", 250, 500, None),
    ("blinds 250/500 ante 80", 250, 500, 80),
    ("250/500 ante 80", 250, 500, 80),
    ("250/500 (80)", 250, 500, 80),
    ("Blinds $250/$500", 250, 500, None),
])
def test_find_blinds(texto, sb, bb, ante):
    assert tx.find_blinds([L(texto)]) == {"sb": sb, "bb": bb, "ante": ante}


def test_find_blinds_acepta_la_ante_sin_valor():
    """La barra de titulo del cliente en castellano a veces pierde el valor de la
    ante (fuente muy fina): se acepta sb/bb antes que descartar la linea."""
    assert tx.find_blinds([L("15.000/30.000 ante")]) == {"sb": 15000, "bb": 30000, "ante": None}


def test_find_blinds_descarta_una_bb_inverosimil():
    """Cualquier par 'x/y' del HUD (posicion en el torneo, por ejemplo) casaria
    con el patron; MIN_PLAUSIBLE_BB lo filtra."""
    assert tx.find_blinds([L("Blinds 2/4")]) is None


def test_una_ante_ridicula_se_descarta_pero_las_ciegas_se_conservan():
    r = tx.find_blinds([L("blinds 250/500 ante 2")])
    assert r == {"sb": 250, "bb": 500, "ante": None}


def test_find_blinds_junta_lineas_de_la_misma_fila():
    """El OCR puede partir la barra de titulo en trozos."""
    r = tx.find_blinds([L("Blinds 250", cx=100, cy=50), L("/500", cx=160, cy=52)])
    assert r == {"sb": 250, "bb": 500, "ante": None}


def test_sin_ciegas_devuelve_none():
    assert tx.find_blinds([L("cualquier cosa")]) is None


# --- el indicador compacto de la esquina ------------------------------------

@pytest.mark.parametrize("texto, sb, bb, ante", [
    ("250/500(80)", 250, 500, 80),
    ("1.900/3.800(500)", 1900, 3800, 500),
    ("17,5K/35K(4,5K)", 17500, 35000, 4500),
    ("1,2M/2,4M(300K)", 1200000, 2400000, 300000),
])
def test_find_blinds_corner(texto, sb, bb, ante):
    assert tx.find_blinds_corner([L(texto)]) == {"sb": sb, "bb": bb, "ante": ante}


def test_el_filtro_de_cordura_descarta_un_par_imposible():
    """sb>0 y bb>sb siempre: un caracter de mas o de menos en el K/M produce
    justamente esto."""
    assert tx.find_blinds_corner([L("500/250(80)")]) is None


def test_require_double_descarta_una_lectura_corrupta():
    """Verificado contra las 93 capturas de samples_pokerstars/: casi todos los
    aciertos K/M cumplen bb == 2*sb."""
    assert tx.find_blinds_corner([L("250/700(80)")], require_double=True) is None
    assert tx.find_blinds_corner([L("250/700(80)")], require_double=False) is not None


def test_se_prueban_los_conjuntos_en_orden_y_una_pasada_mala_no_tapa_a_la_buena():
    """Un mismo error de OCR no aparece igual en todas las pasadas: si la de
    mayor prioridad da basura, la siguiente puede dar el bueno."""
    mala, buena = [L("no hay ciegas aqui")], [L("250/500(80)")]
    assert tx.find_blinds_corner(mala, buena)["bb"] == 500


# --- las ciegas del chat -----------------------------------------------------

def test_find_blinds_chat():
    r = tx.find_blinds_chat([L("Los limites suben: Ciegas 50/100 Ante 15")])
    assert r == {"sb": 50, "bb": 100, "ante": 15}


def test_del_historial_del_chat_manda_el_nivel_MAS_ALTO():
    """En un torneo las ciegas solo suben, asi que el aviso con la bb mayor es el
    nivel actual. Depender del orden de las lineas OCR seria depender del azar."""
    r = tx.find_blinds_chat([L("Ciegas 200/400 Ante 50"),
                             L("Ciegas 50/100 Ante 15"),
                             L("Ciegas 100/200 Ante 25")])
    assert r["bb"] == 400


def test_sin_mensajes_de_ciegas_en_el_chat_devuelve_none():
    assert tx.find_blinds_chat([L("Repartidor: pepe gana el bote (500)")]) is None


# --- nombres -----------------------------------------------------------------

@pytest.mark.parametrize("crudo, limpio", [
    ("  pepe  ", "pepe"),
    ("pepe,", "pepe"),
    ("'pepe'", "pepe"),
    ("’pepe’", "pepe"),          # apostrofo tipografico del OCR
    ("|pepe|", "pepe"),
])
def test_clean_name_quita_la_basura_de_los_extremos(crudo, limpio):
    assert tx._clean_name(crudo) == limpio


@pytest.mark.parametrize("texto", ["Dav6934", "BerniBeau", "over590",
                                   "LinyoKing's", "LinyoKing’s", "juan_perez",
                                   "a-b-c-d"])
def test_un_nick_valido_se_acepta(texto):
    assert tx._is_name_candidate(texto)


def test_limitacion_conocida_la_lista_negra_casa_por_SUBCADENA():
    """"makeao31" se rechaza porque "make" esta en NAME_BLACKLIST y la
    comprobacion es por subcadena, no por palabra completa. Es un fallo real y
    esta medido -3 de 542 nombres de tres sesiones-, asi que no se arregla a la
    ligera: la ocupacion del asiento se salva igual por el stack en BB (ver
    test_bugfixes_bb.py, bloque 0.3).

    El test deja escrito el comportamiento ACTUAL. El dia que se arregle, este
    test falla y hay que darle la vuelta, que es justo lo que se quiere."""
    assert not tx._is_name_candidate("makeao31")
    assert "make" in tx.NAME_BLACKLIST


@pytest.mark.parametrize("texto, motivo", [
    ("ab", "menos de tres caracteres: 5.007 lineas de ruido medidas asi"),
    ("", "vacio"),
    ("30,9 BB", "un stack no es un nombre"),
    ("pot", "la lista negra"),
    ("Fold", "la lista negra, sin importar mayusculas"),
    ("VELOCIDAD", "sin dos minusculas es un rotulo de la UI, no un nick"),
    ("9pepe", "un nick empieza por letra"),
])
def test_lo_que_no_es_un_nick_se_rechaza(texto, motivo):
    assert not tx._is_name_candidate(texto), motivo


def test_el_apostrofo_dentro_del_nick_se_conserva():
    """Sin el, "LinyoKing's" salia "(?)" en TODOS los frames de la sesion 220231
    mientras los otros cinco asientos se leian bien."""
    assert tx._is_name_candidate("LinyoKing's")
    assert tx._clean_name("LinyoKing's") == "LinyoKing's"


# --- numeros -----------------------------------------------------------------

@pytest.mark.parametrize("texto", ["12,500", "1.900", "3955", "500"])
def test_un_numero_de_fichas_se_reconoce(texto):
    assert tx._is_number_candidate(texto)


@pytest.mark.parametrize("texto", ["pepe", "", "12", "1,2,3", "12.5"])
def test_lo_que_no_es_un_numero_de_fichas_se_rechaza(texto):
    assert not tx._is_number_candidate(texto)


# --- emparejar nombre con stack ---------------------------------------------

def test_find_players_empareja_por_proximidad():
    """Sin coordenadas fijas: el nombre y el numero que estan cerca son del mismo
    jugador, este donde este el asiento."""
    lineas = [L("Dav6934", cx=200, cy=300), L("12,500", cx=200, cy=320),
              L("pepito99", cx=800, cy=300), L("3.400", cx=800, cy=320)]
    jugadores = tx.find_players(lineas, image_diagonal=1400)
    por_nombre = {p["name"]: p["stack"] for p in jugadores}
    assert por_nombre == {"Dav6934": 12500, "pepito99": 3400}


def test_un_nombre_sin_numero_cerca_no_produce_jugador():
    """Un nick suelto no basta: sin stack no hay nada que decidir, y aceptarlo
    añadiria un asiento ocupado que corre TODAS las posiciones."""
    assert tx.find_players([L("Dav6934", cx=200, cy=300)], image_diagonal=1400) == []


def test_sin_lineas_no_hay_jugadores():
    assert tx.find_players([], image_diagonal=1400) == []
