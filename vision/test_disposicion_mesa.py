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


def test_las_anclas_de_8_no_se_pisan():
    """Cada una tiene que quedar mas cerca de SU asiento que de cualquier otro, o
    el boton saltaria de sitio. Medido: el margen real va de 1,22x a 1,98x."""
    import math
    seats = seat_map.zonas(8)["seats"]
    for s, cfg in seats.items():
        ax, ay = cfg["button"]
        ds = sorted((math.hypot(ax - (o["plate"][0] + o["plate"][2]) / 2,
                                ay - (o["plate"][1] + o["plate"][3]) / 2), n)
                    for n, o in seats.items())
        assert ds[0][1] == s, f"el ancla de {s} cae mas cerca de {ds[0][1]}"
        assert ds[1][0] / ds[0][0] >= 1.2, f"{s}: margen {ds[1][0] / ds[0][0]:.2f}x"


def test_una_disposicion_desconocida_cae_a_la_de_6():
    """NO se adivina. Una disposicion equivocada no falla de forma visible: lee
    nombres donde no hay nadie y deja jugadores invisibles, y eso desplaza TODAS
    las posiciones, que salen del recuento de asientos ocupados."""
    for n in (None, 3, 7, 99):
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


def test_las_anclas_de_9_no_se_pisan():
    """Son DERIVADAS -la sesion de 9 son dos manos y el disco solo paso por 2 de
    los 9 asientos- asi que comprobar que cada una gana a su asiento es lo unico
    que las sostiene. Medido: entre 1,59x y 2,63x."""
    import math
    seats = seat_map.zonas(9)["seats"]
    for s, cfg in seats.items():
        ax, ay = cfg["button"]
        ds = sorted((math.hypot(ax - (o["plate"][0] + o["plate"][2]) / 2,
                                ay - (o["plate"][1] + o["plate"][3]) / 2), n)
                    for n, o in seats.items())
        assert ds[0][1] == s, f"el ancla de {s} cae mas cerca de {ds[0][1]}"
        assert ds[1][0] / ds[0][0] >= 1.2, f"{s}: margen {ds[1][0] / ds[0][0]:.2f}x"
