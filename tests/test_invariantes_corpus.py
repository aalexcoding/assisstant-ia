"""
Los invariantes de core/invariantes.py, aplicados a TODO lo que la app ha
grabado jugando de verdad: ~9.200 frames de 26 sesiones.

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
contradictorio: de los 1.721 frames en que la app le dijo algo al usuario, CERO
tenian un estado que se contradijera a si mismo. Que el reconocimiento falle a
veces es tolerable; que falle JUSTO cuando se da una orden, no.
"""
from collections import Counter

import pytest

from core import invariantes as inv

pytestmark = pytest.mark.corpus

# Invariantes de CONTRATO: cero tolerancia. Medido sobre 8.314 frames con mesa
# detectada, hoy los siete estan a 0.
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
PERCEPCION = [
    ("board_ilegal", 0.0358, 0.055),
    ("carta_en_dos_sitios", 0.0054, 0.012),
    ("raiser_habla_despues", 0.0037, 0.010),
    ("board_repetido", 0.0037, 0.010),
    ("hero_repetida", 0.0028, 0.008),
]

SERIE = [
    ("posicion_cambia", 0.0048, 0.012),
    ("jugadores_cambian", 0.0019, 0.006),
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

    Medido: 1.721 frames con recomendacion, CERO con el estado contradiciendose."""
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
