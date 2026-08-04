"""
Que la app pueda leer una mesa de 8, y que elegir disposicion no contamine.

EL FALLO QUE ARREGLA. seat_map define seis zonas fijas calibradas sobre una mesa
de 6. En una de 8 no faltan dos zonas: las que hay caen en el sitio equivocado.
Cada lateral de una mesa de 8 tiene DOS asientos (y = +0,44 y y = +0,94) y el
mapa de 6 define UNO en y = +0,72, o sea justo en el hueco entre los dos, asi
que se pierden DOS jugadores por lado y no uno. Medido jugando: 4,62 asientos
leidos por frame habiendo 6-8 ocupados. Ver docs/MESAS-DE-8-Y-9.md.
"""
import pytest

from vision import seat_map

pytestmark = pytest.mark.vision

REF = (100, 100, 900, 400, False)
SHAPE = (700, 1300, 3)


def test_la_mesa_de_8_tiene_ocho_asientos():
    assert len(seat_map.zonas(8)["seats"]) == 8
    assert len(seat_map.zonas(6)["seats"]) == 6


def test_son_TRES_POR_LADO_Y_DOS_ENFRENTADOS():
    """Como lo describe el usuario, y como la medicion lo reprodujo por su
    cuenta sin saberlo de antemano."""
    seats = seat_map.zonas(8)["seats"]
    centros = {s: ((z["plate"][0] + z["plate"][2]) / 2,
                   (z["plate"][1] + z["plate"][3]) / 2) for s, z in seats.items()}
    izq = [s for s, (x, _y) in centros.items() if x < 0.3]
    der = [s for s, (x, _y) in centros.items() if x > 0.7]
    enfrentados = [s for s, (x, _y) in centros.items() if 0.3 <= x <= 0.7]
    assert len(izq) == 3, izq
    assert len(der) == 3, der
    assert len(enfrentados) == 2, enfrentados


def test_los_dos_del_MEDIO_sobresalen():
    """Es la panza del ovalo, y es la mejor señal de que la geometria esta medida
    y no inventada: unas posiciones a ojo habrian salido alineadas en columna."""
    seats = seat_map.zonas(8)["seats"]
    def cx(s):
        z = seats[s]["plate"]
        return (z[0] + z[2]) / 2
    assert cx("ML") < cx("UL") and cx("ML") < cx("DL")
    assert cx("MR") > cx("UR") and cx("MR") > cx("DR")


def test_los_laterales_de_8_NO_estan_donde_los_de_6():
    """El asiento lateral de la mesa de 6 cae en el HUECO entre los dos de la de
    8. Si alguien 'simplificara' reutilizando las zonas de 6, esto se pone rojo."""
    def cy(z):
        return (z["plate"][1] + z["plate"][3]) / 2
    seis = seat_map.zonas(6)["seats"]
    ocho = seat_map.zonas(8)["seats"]
    assert cy(ocho["ML"]) < cy(seis["ML"]) < cy(ocho["DL"])
    assert cy(ocho["MR"]) < cy(seis["MR"]) < cy(ocho["DR"])


def test_las_tres_tablas_de_una_disposicion_hablan_de_los_MISMOS_asientos():
    """Pedir una disposicion tiene que dar las tres coherentes, o se leerian
    nameplates de una mesa y dorsos de otra."""
    for n in (6, 8, 9):
        z = seat_map.zonas(n)
        assert set(z["apuestas"]) == set(z["seats"]), n
        # los dorsos no incluyen al hero: sus cartas se leen boca arriba
        assert set(z["dorsos"]) == set(z["seats"]) - {seat_map.HERO_SEAT}, n


def test_cada_asiento_de_8_tiene_ancla_de_boton():
    """Sin ancla, disco_dealer le atribuiria el boton al vecino."""
    for s, cfg in seat_map.zonas(8)["seats"].items():
        assert "button" in cfg, s


# Separacion minima entre dos anclas del mismo mapa. ES EL CRITERIO QUE DE VERDAD
# USA EL CODIGO: disco_dealer mide del disco encontrado a cada ANCLA y se queda
# con la mas cercana, exigiendo que sea <= 0,75x la segunda o se abstiene. Lo que
# importa entonces es que las anclas esten separadas entre SI.
#
# La primera version de estos tests comprobaba otra cosa -que cada ancla estuviera
# mas cerca de SU asiento que de los demas- y era un criterio inventado: las
# anclas viven sobre el tapete, hacia dentro, asi que naturalmente caen entre dos
# asientos. Se descubrio al medir las anclas de la mesa de 9 de verdad: la de UL
# quedaba a 1,03x de dos asientos y el test se puso rojo sin que nada estuviera
# mal.
#
# EL UMBRAL SALE DE LAS TRES TABLAS, no de una estimacion (que ya falle una vez
# aqui mismo: dije 0,233 para la mesa de 8 sin medirlo y son 0,143):
#
#     mesa de 6   minima 0,250 (ML-UL)    2a 0,377
#     mesa de 8   minima 0,143 (ML-UL)    2a 0,176
#     mesa de 9   minima 0,159 (DL-HERO)  2a 0,221
#
# 0,12 deja pasar las tres con margen y sigue cazando dos anclas que se junten de
# verdad. Cuanto mas juntas, mas veces se calla disco_dealer -exige que la primera
# sea <= 0,75x la segunda- y en el limite le da el boton al vecino. Que la mesa de
# 8 sea la mas apretada es coherente con que sus anclas son DERIVADAS.
ANCLAS_SEPARACION_MIN = 0.12


def _separacion_minima(seats):
    """La distancia entre las dos anclas mas juntas del mapa."""
    import math
    anclas = {s: cfg["button"] for s, cfg in seats.items()}
    return min(math.hypot(ax - bx, ay - by)
               for a, (ax, ay) in anclas.items()
               for b, (bx, by) in anclas.items() if a != b)


def test_las_anclas_de_8_estan_separadas_entre_si():
    """Si dos anclas se juntan, un disco entre ellas no se puede atribuir: la
    primera no llega a ser 0,75x la segunda y disco_dealer se calla. Peor aun si
    se cruzan, porque entonces se le da el boton al vecino."""
    assert _separacion_minima(seat_map.zonas(8)["seats"]) >= ANCLAS_SEPARACION_MIN


def test_cada_ancla_de_8_es_de_UN_asiento():
    """Dos asientos no pueden compartir ancla: seria el mismo sitio de la mesa."""
    anclas = [tuple(c["button"]) for c in seat_map.zonas(8)["seats"].values()]
    assert len(set(anclas)) == len(anclas)


def test_una_disposicion_desconocida_cae_a_la_de_6():
    """NO se adivina. Una disposicion equivocada no falla de forma visible: lee
    nombres donde no hay nadie y deja jugadores invisibles, y eso desplaza TODAS
    las posiciones, que salen del recuento de asientos ocupados.

    La de 7 SALIO de esta lista el 04-08-2026, cuando el usuario señalo el frame
    4317 de sesion-2026-08-03_221628 -la mesa final de un torneo- y se pudo medir.
    Las que quedan siguen sin tabla propia."""
    for n in (None, 3, 5, 99):
        assert seat_map.zonas(n)["seats"] is seat_map.SEATS_6MAX, n


def test_elegir_disposicion_NO_toca_el_global():
    """Es el fallo que este diseño evita: la regresion de oro crea un Analizador
    por sesion EN EL MISMO PROCESO, asi que con un global una sesion de 8
    contaminaria a la siguiente de 6 y saldria como una regresion fantasma."""
    antes = dict(seat_map.SEATS)
    seat_map.zonas(8)
    assert seat_map.SEATS == antes
    assert seat_map.SEATS is seat_map.SEATS_6MAX


# --- la mesa de 9 -----------------------------------------------------------

def test_la_mesa_de_9_tiene_nueve_asientos():
    assert len(seat_map.zonas(9)["seats"]) == 9


def test_son_CUATRO_POR_LADO_Y_NADIE_EN_FRENTE():
    """Como lo describe el usuario: "si tenemos como referencia al hero que soy
    yo abajo, 4 andan a mi izquierda y otro 4 a la derecha, nadie en frente"."""
    seats = seat_map.zonas(9)["seats"]
    c = {s: ((z["plate"][0] + z["plate"][2]) / 2,
             (z["plate"][1] + z["plate"][3]) / 2) for s, z in seats.items()}
    hero = c[seat_map.HERO_SEAT]
    izq = [s for s, (x, _y) in c.items() if x < hero[0] - 0.1]
    der = [s for s, (x, _y) in c.items() if x > hero[0] + 0.1]
    assert len(izq) == 4, izq
    assert len(der) == 4, der
    # NADIE EN FRENTE: ningun asiento a la altura de arriba y centrado en x
    enfrente = [s for s, (x, y) in c.items()
                if abs(x - hero[0]) <= 0.1 and y < 0.0]
    assert not enfrente, f"la mesa de 9 no tiene asiento en frente: {enfrente}"


def test_la_de_9_NO_tiene_TOPC_y_la_de_6_y_8_SI():
    """El asiento de enfrente existe en 6 y en 8 y no en 9. Si alguien copiara
    una tabla de otra, esto se pone rojo."""
    assert "TOPC" in seat_map.zonas(6)["seats"]
    assert "TOPC" in seat_map.zonas(8)["seats"]
    assert "TOPC" not in seat_map.zonas(9)["seats"]
    assert {"TL", "TR"} <= set(seat_map.zonas(9)["seats"])


def test_las_anclas_de_9_estan_separadas_entre_si():
    """OCHO de las nueve estan MEDIDAS (disco visto en 1.157 frames de dos
    sesiones largas); ML sigue derivada porque el disco no paso nunca por ese
    asiento. Separacion minima medida: 0,159, entre HERO y DL."""
    assert _separacion_minima(seat_map.zonas(9)["seats"]) >= ANCLAS_SEPARACION_MIN


def test_cada_ancla_de_9_es_de_UN_asiento():
    anclas = [tuple(c["button"]) for c in seat_map.zonas(9)["seats"].values()]
    assert len(set(anclas)) == len(anclas)
