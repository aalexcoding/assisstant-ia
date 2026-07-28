"""
Verificacion del estudio post-mano (decision/rag/postmano.py).

Lo que de verdad protege:

  1. Que la CONSULTA solo lleve lo observado. Enriquecerla con cosas que no se
     han visto -iniciativa, tipo de rival- buscaria una mano que no es la que se
     jugo, y las referencias parecerian pertinentes sin serlo.
  2. Que la falta de indice, de modelo o de red NO tumbe nada: esto es una ayuda
     para despues de la mano, no parte del analisis.
  3. Que haya un UMBRAL de similitud. El indice siempre devuelve los k mas
     parecidos aunque el mas parecido no se parezca en nada; sin umbral, una mano
     rara acabaria con tres referencias irrelevantes presentadas como si vinieran
     a cuento.

describir() es puro: se prueba sin indice ni modelo.
"""
import pytest

from decision.rag import postmano as pm

BOARD_QQ8 = ["Qc", "Qs", "8s"]


@pytest.fixture
def consulta_completa():
    return pm.describir(board=BOARD_QQ8, mano_ganadora="doble pareja",
                        hero_en_showdown=True)


# --- la consulta -------------------------------------------------------------

@pytest.mark.parametrize("trozo", ["Qc", "Qs", "8s", "doble pareja", "showdown"])
def test_la_consulta_lleva_lo_observado(consulta_completa, trozo):
    assert trozo in consulta_completa


@pytest.mark.parametrize("rasgo", ["emparejado", "dos del mismo palo", "cartas altas"])
def test_la_consulta_describe_la_textura_del_board(consulta_completa, rasgo):
    """Los rasgos que SI se leen de las cartas, sin suponer nada."""
    assert rasgo in consulta_completa


def test_un_board_sin_repetir_palo_es_rainbow():
    q = pm.describir(board=["2h", "7d", "9c"])
    assert "rainbow" in q
    assert "emparejado" not in q


def test_tres_del_mismo_palo_es_monocolor():
    assert "monocolor" in pm.describir(board=["2h", "7h", "9h"])


def test_sin_showdown_se_dice_tambien():
    assert "sin showdown" in pm.describir(board=["2h", "7d", "9c"], hero_en_showdown=False)


def test_sin_datos_no_se_inventa_una_consulta():
    assert pm.describir() == ""


def test_un_board_a_medio_leer_no_revienta():
    assert isinstance(pm.describir(board=["Qc", None]), str)


@pytest.mark.parametrize("inventado", ["iniciativa", "agresivo", "rango",
                                       "deberias", "recomiendo"])
def test_la_consulta_no_inventa_nada_que_no_se_haya_observado(consulta_completa, inventado):
    """Meter esto buscaria una mano que no es la que se jugo, y las referencias
    parecerian pertinentes sin serlo."""
    assert inventado not in consulta_completa.lower()


# --- robustez: esto nunca puede tumbar nada ---------------------------------

def test_una_consulta_vacia_devuelve_lista_vacia_sin_tocar_el_indice():
    assert pm.buscar("") == []


def test_estudiar_sin_datos_devuelve_la_forma_esperada():
    assert pm.estudiar() == {"consulta": "", "referencias": []}


def test_estudiar_devuelve_consulta_y_referencias():
    r = pm.estudiar(board=BOARD_QQ8, mano_ganadora="doble pareja")
    assert set(r) == {"consulta", "referencias"}
    assert isinstance(r["referencias"], list)


# --- el umbral ---------------------------------------------------------------

def test_con_un_minimo_imposible_no_se_cuela_ninguna_referencia():
    assert pm.buscar("board Qc Qs 8s", minimo=1.1) == []


def test_hay_un_umbral_por_defecto():
    """Sin el, una mano rara acabaria con tres referencias irrelevantes
    presentadas como si vinieran a cuento."""
    assert 0 < pm.SIMILITUD_MINIMA < 1


# --- formato del minuto ------------------------------------------------------

@pytest.mark.parametrize("segundos, esperado", [
    (725.3, "12:05"),
    (0, "0:00"),
    (None, "0:00"),
    (59, "0:59"),
])
def test_minuto_para_saltar_al_video(segundos, esperado):
    assert pm.minuto(segundos) == esperado
