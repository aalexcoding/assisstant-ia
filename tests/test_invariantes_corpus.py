"""
Los invariantes de core/invariantes.py, aplicados a TODO lo que la app ha
grabado jugando de verdad: 7.760 frames de las sesiones que haya en testing/.

Aqui no se muestrea. Se leen los JSON enteros -60 MB, sin abrir una sola
imagen-, asi que la pasada completa cuesta segundos y cubre el corpus entero en
vez de una esquina.

DOS NIVELES DE EXIGENCIA, y la diferencia es deliberada:

  CONTRATO -> CERO. Son afirmaciones sobre lo que el motor puede decir, no sobre
  lo bien que se lee la pantalla: recomendar con las cartas apagadas, recomendar
  sin declarar la unidad, dar una accion postflop. Un solo caso es un bug.

  PERCEPCION -> TASA CON TECHO. Un board de 1 carta o dos cartas repetidas son
  errores de OCR, y el OCR no es perfecto ni lo va a ser. Exigir cero seria un
  test que nunca pasa y que por tanto nadie mira. Lo que si se puede exigir es
  que NO EMPEOREN, asi que el techo se fija sobre la tasa medida hoy con margen,
  y queda escrito cual era.

LA ASERCION MAS FUERTE es test_ninguna_recomendacion_sale_de_un_estado_
contradictorio: de los 1.672 frames en que la app le dijo algo al usuario, CERO
tenian un estado que se contradijera a si mismo. Que el reconocimiento falle a
veces es tolerable; que falle JUSTO cuando se da una orden, no.
"""
from collections import Counter

import pytest

from core import invariantes as inv
from tests import corpus

pytestmark = pytest.mark.corpus

# Invariantes de CONTRATO: cero tolerancia. Medido sobre 7.758 frames con mesa
# detectada (re-medido el 29-07-2026), hoy los diez estan a 0.
CONTRATO = (
    "recomienda_sobre_mano_abandonada",
    "recomienda_sin_unidad",
    "accion_postflop",
    "recomienda_sin_profundidad",
    "recomienda_sin_accion",
    "recomienda_sin_motivo",
    "abstiene_sin_motivo",
    "dos_heroes",
    "posicion_duplicada",
    "demasiados_jugadores",
    # Las sesiones grabadas antes de que existiera el campo "revealed" no lo
    # traen, asi que sobre ellas este sale a 0 sin probar nada; empieza a
    # proteger con la primera sesion que se grabe a partir de ahora.
    "revelado_pero_retirado",
)

# Invariantes de PERCEPCION: (clave, tasa medida hoy, techo). El techo va con
# margen sobre lo medido, para que el test cace una regresion sin saltar por el
# ruido normal de una sesion distinta.
#
# RE-MEDIDO el 29-07-2026 sobre el corpus ACTUAL (7.758 frames con mesa). Las
# cifras anteriores eran de un corpus de 9.200 frames que ya no existe -se
# borro para recuperar los 14 GB-, asi que no se podian seguir citando.
#
# La percepcion MEJORO en todo, y los techos bajan con ella: un techo muy por
# encima de lo medido no protege de nada.
#
#     board_ilegal          3,58% -> 1,96%
#     carta_en_dos_sitios   0,54% -> 0%
#     hero_repetida         0,28% -> 0%
#     board_repetido        0,37% -> 0,27%
#     raiser_habla_despues  0,37% -> 0,09%
#
# Los dos que estan a CERO se quedan en percepcion y no pasan a contrato: son
# fallos de OCR y pueden volver con otro tema de mesa o otro mazo. El techo se
# deja bajo, no a cero.
PERCEPCION = [
    ("board_ilegal", 0.0196, 0.030),
    ("board_repetido", 0.0027, 0.008),
    ("raiser_habla_despues", 0.0009, 0.005),
    ("carta_en_dos_sitios", 0.0000, 0.004),
    ("hero_repetida", 0.0000, 0.003),
]

# LOS DE SERIE HAN EMPEORADO, y es un intercambio deliberado, no una regresion
# sorpresa. El commit 89ee297 quito el candado del rastreador -que votaba sobre
# su propia salida y por eso el conjunto de asientos no podia cambiar dentro de
# una mano- a cambio de que la ocupacion deje de contar tapete pelado como
# jugador (precision 64,8% -> 87,9%, recall 99,0% -> 99,8%).
#
#     jugadores_cambian   0,19% -> 1,87%
#     posicion_cambia     0,48% -> 1,28%
#
# El techo sube a lo medido con margen para que la suite vuelva a proteger, PERO
# es un techo provisional: la fase 3a del plan (que el override no contradiga la
# evidencia del frame) existe para bajarlo. Si dentro de unos commits sigue
# aqui, es que esa fase no se hizo.
#
# LOS DOS DE CARTAS son la vara con la que se juzga el reconocimiento sin tener
# etiquetas: no dependen de saber QUE carta es, solo de que la lectura no se
# contradiga a si misma. Medidos el 29-07-2026 sobre los 8.904 pares
# consecutivos del corpus:
#
#     board_pierde_carta      0,97%   (0,47% - 1,48% segun sesion)
#     hero_cambia_de_cartas   0,24%
#
# OJO AL LEER ESTAS CIFRAS: salen de los JSON grabados, o sea del codigo que
# habia cuando se grabaron, y las sesiones del mazo nuevo son ANTERIORES a los
# arreglos del indice (commits 9166b3a y 0dbb427). Justamente la del 29-07 a las
# 07:04 es la que peor sale en board_pierde_carta, 1,48%, porque alli las figuras
# desaparecian del board. Con la primera sesion que se grabe a partir de ahora
# esto tiene que BAJAR; si no baja, los arreglos no valian lo que dicen sus
# mediciones.
SERIE = [
    ("jugadores_cambian", 0.0187, 0.028),
    ("posicion_cambia", 0.0128, 0.020),
    ("board_pierde_carta", 0.0097, 0.016),
    ("hero_cambia_de_cartas", 0.0024, 0.006),
]


@pytest.fixture(scope="module")
def con_mesa(corpus_completo):
    """Los frames en que SI se encontro el ovalo. Sin mesa todas las zonas estan
    desplazadas y los campos vienen vacios a proposito: no hay nada que juzgar."""
    frames = [f for f in corpus_completo if not inv._sin_mesa(f.state)]
    assert frames, "ninguna sesion con mesa detectada; el test no probaria nada"
    return frames


@pytest.fixture(scope="module")
def violaciones_de_frame(con_mesa):
    """{clave: [id de frame, ...]} sobre el corpus entero."""
    out = {}
    for fr in con_mesa:
        for clave, detalle in inv.de_frame(fr.state, fr.recommendation):
            out.setdefault(clave, []).append(f"{fr.id} {detalle}")
    return out


@pytest.fixture(scope="module")
def violaciones_de_serie(corpus_completo):
    """Lo mismo entre frames consecutivos de la misma sesion."""
    por_sesion = {}
    for fr in corpus_completo:
        por_sesion.setdefault(fr.sesion, []).append(fr)
    out, pares = {}, 0
    for fs in por_sesion.values():
        fs.sort(key=lambda f: f.n)
        for a, b in zip(fs, fs[1:]):
            pares += 1
            for clave, detalle in inv.de_serie((a.state, a.recommendation),
                                               (b.state, b.recommendation)):
                out.setdefault(clave, []).append(f"{b.id} {detalle}")
    return out, pares


# --- LA ASERCION FUERTE ------------------------------------------------------

def test_ninguna_recomendacion_sale_de_un_estado_contradictorio(con_mesa):
    """Que el reconocimiento falle a veces es tolerable; que falle JUSTO cuando
    la app le dice al usuario lo que tiene que hacer, no.

    Medido: 1.672 frames con recomendacion, CERO con el estado contradiciendose."""
    con_rec = [f for f in con_mesa if f.recommendation]
    assert con_rec, "ningun frame con recomendacion; el test no probaria nada"
    malos = []
    for fr in con_rec:
        fallos = inv.de_frame(fr.state, fr.recommendation)
        if fallos:
            malos.append(f"{fr.id}: {[c for c, _d in fallos]}")
    assert not malos, f"{len(malos)} de {len(con_rec)} recomendaciones: {malos[:5]}"


# --- CONTRATO: cero tolerancia -----------------------------------------------

@pytest.mark.parametrize("clave", CONTRATO)
def test_el_contrato_del_motor_no_se_rompe_ni_una_vez(clave, violaciones_de_frame):
    casos = violaciones_de_frame.get(clave, [])
    assert not casos, f"{len(casos)} violaciones de {clave}: {casos[:5]}"


# --- PERCEPCION: la calidad de lectura no puede EMPEORAR --------------------

@pytest.mark.parametrize("clave, medido, techo", PERCEPCION)
def test_la_calidad_de_lectura_no_empeora(clave, medido, techo, violaciones_de_frame, con_mesa):
    casos = violaciones_de_frame.get(clave, [])
    tasa = len(casos) / len(con_mesa)
    assert tasa <= techo, (f"{clave}: {100 * tasa:.2f}% de {len(con_mesa)} frames "
                           f"(medido {100 * medido:.2f}%, techo {100 * techo:.2f}%). "
                           f"Ejemplos: {casos[:3]}")


@pytest.mark.parametrize("clave, medido, techo", SERIE)
def test_la_estabilidad_dentro_de_una_mano_no_empeora(clave, medido, techo,
                                                      violaciones_de_serie):
    """Nadie se levanta a mitad de mano y el boton no se mueve hasta que acaba,
    asi que si el numero de jugadores o la posicion del hero cambian es que se ha
    leido mal."""
    casos_por_clave, pares = violaciones_de_serie
    casos = casos_por_clave.get(clave, [])
    tasa = len(casos) / pares
    assert tasa <= techo, (f"{clave}: {100 * tasa:.2f}% de {pares} pares "
                           f"(medido {100 * medido:.2f}%, techo {100 * techo:.2f}%). "
                           f"Ejemplos: {casos[:3]}")


# --- que el corpus siga siendo representativo -------------------------------

def test_el_corpus_cubre_los_casos_que_importan(corpus_completo):
    """Si un caso deja de aparecer, los tests que dependen de el pasan en verde
    sin probar nada. Se comprueba que el corpus sigue teniendo material."""
    from tests import corpus as c
    cuenta = Counter()
    for fr in corpus_completo:
        cuenta.update(c.estratos(fr))
    imprescindibles = ["board_0", "board_3", "board_5", "con_recomendacion",
                       "cartas_apagadas", "multiway", "facing_bet", "con_equity"]
    faltan = [e for e in imprescindibles if cuenta[e] == 0]
    assert not faltan, f"el corpus ya no cubre: {faltan}"


def test_hay_material_de_sobra(corpus_completo):
    assert len(corpus_completo) > 1000, \
        f"solo {len(corpus_completo)} frames grabados: el corpus se ha quedado corto"


def test_las_sesiones_de_verdad_empiezan_en_la_mano_1_y_los_trozos_no(corpus_completo):
    """El criterio con el que la regresion de oro decide que puede reproducir.

    Reproducir una sesion entera en frio es la misma cuenta que la original: el
    Analizador arranca vacio igual que arranco alli. Reproducir un TROZO no lo
    es, y por eso la regresion tiene que dejarlos fuera; si no, falla siempre y
    acaba tapando una regresion de verdad (paso con notas-2026-07-29_081737:
    hero_position 'SB' grabado contra 'BTN' reproducido)."""
    por_sesion = {}
    for fr in corpus_completo:
        por_sesion.setdefault(fr.sesion, []).append(fr)
    assert por_sesion, "sin corpus no hay nada que comprobar"
    for ses, fs in por_sesion.items():
        primero = min(fs, key=lambda f: f.n)
        mano = (primero.state or {}).get("mano_seguida")
        if corpus.es_fragmento(fs):
            assert mano and mano > 1, f"{ses}: marcado fragmento con mano {mano!r}"
            assert len(fs) < 5, f"{ses}: un fragmento de {len(fs)} frames es sospechoso"
        elif mano is not None:
            assert mano == 1, f"{ses}: sesion entera que no empieza en la mano 1"
