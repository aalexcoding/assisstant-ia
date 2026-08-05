"""
El ciclo de analisis COMPLETO contra frames reales: se vuelven a pasar por
core.Analizador los PNG que la app grabo jugando y se contrasta con lo que
calculo entonces.

Es la unica prueba que ejercita la cadena entera -deteccion del ovalo, cartas,
OCR de nameplates y chat, rastreador, registro de acciones, motor y equity- sobre
material que no se ha fabricado aqui. Todo lo demas de la suite prueba piezas.

DOS COSAS DISTINTAS, y no se pueden mezclar:

  PROPIEDADES, sobre toda la muestra. Ningun frame lanza, el GameState cumple su
  esquema, los invariantes se sostienen y el ciclo cabe en su presupuesto de
  tiempo. Valen para cualquier sesion, sea del commit que sea.

  REGRESION DE ORO, solo sobre las sesiones grabadas con ESTE MISMO commit. Ahi
  si se puede exigir igualdad campo a campo, porque cualquier diferencia es un
  cambio de comportamiento. Comparar contra una sesion de hace tres commits seria
  un test que falla por haber arreglado algo.

Se marcan `lento` porque un ciclo son ~0,55 s: 500 frames son unos cinco minutos.
"""
import time

import pytest

from core import Analizador
from core import invariantes as inv
from tests import corpus

pytestmark = [pytest.mark.corpus, pytest.mark.lento, pytest.mark.vision]

# Campos que significan algo para el usuario y sobre los que decide. NO se
# comparan tiempos, lineas crudas de chat ni equity: son un reloj, un OCR y un
# Monte Carlo, y cambiarian sin que nada este mal.
CAMPOS_ORO = ("hero_cards", "board", "hero_position", "stack_unit", "facing",
              "vs_position", "hero_cards_dimmed", "mano_seguida")

# `mano_seguida` entra el 29-07-2026, al cambiar el corte por board_vacio
# (hand_tracker.BOARD_VACIO_FRAMES). Es reproducible aunque sea un contador con
# memoria: la sesion se reproduce ENTERA y en orden, asi que el rastreador ve la
# misma secuencia que vio en vivo. Y es justo el campo donde se nota que una
# lectura floja del board parta una mano en dos, que era el fallo.

# BAJADO de 3,0 a 1,8 el 29-07-2026. Un techo de 3 s protegia de algo que ya no
# puede pasar: medido sobre las 7 sesiones grabadas, el p95 del ciclo va de 0,836
# a 1,149 s, y en la ultima -con el chat espaciado y el disco solapado- es 0,889.
# Un techo muy por encima de lo medido no caza ninguna regresion; 1,8 deja el
# doble del p95 tipico de margen y sigue avisando si algo se dispara.
LATENCIA_P95_MAX_S = 1.8

# Esquema minimo del GameState: campo -> tipos admitidos. Es el contrato entre
# vision/ y decision/, que hasta ahora no estaba escrito en ningun sitio.
ESQUEMA = {
    "hero_cards": (list,),
    "board": (list,),
    "players": (list,),
    "warnings": (list,),
    "pot": (float, int, type(None)),
    "to_call": (float, int, type(None)),
    "hero_position": (str, type(None)),
    "facing": (str, type(None)),
    "vs_position": (str, type(None)),
    "stack_unit": (str,),
    "chat_lines": (list, type(None)),
    "table_reference_valid": (bool,),
}


@pytest.fixture(scope="module")
def reanalizados(corpus_muestra):
    """Re-analiza la muestra y devuelve [(frame_grabado, Analisis, segundos)].

    UN Analizador POR SESION: la memoria entre frames (referencia del tapete,
    plantilla del boton, rastreador) es de la sesion, y mezclarla entre sesiones
    daria resultados que no se parecen a los de una partida."""
    por_sesion, salida = {}, []
    for fr in sorted(corpus_muestra, key=lambda f: (f.sesion, f.n)):
        an = por_sesion.setdefault(
            fr.sesion, Analizador(seed_equity=1))
        t0 = time.perf_counter()
        try:
            res = an.analizar(fr.png)
        except Exception as e:                      # noqa: BLE001
            salida.append((fr, e, time.perf_counter() - t0))
            continue
        salida.append((fr, res, time.perf_counter() - t0))
    return salida


# --- propiedades, sobre toda la muestra -------------------------------------

def test_ningun_frame_lanza(reanalizados):
    """Un fallo de UN frame se acota dentro del Analizador; que se escape
    significa que el lazo en vivo se quedaria mudo."""
    malos = [(fr.id, res) for fr, res, _t in reanalizados if isinstance(res, Exception)]
    assert not malos, f"{len(malos)} frames lanzaron: {malos[:3]}"


def test_el_gamestate_cumple_el_esquema(reanalizados):
    """El GameState es un dict libre, y ese es el acoplamiento silencioso entre
    vision/ y decision/: si analyze_layout deja de poner un campo, el motor se
    entera en produccion."""
    malos = []
    for fr, res, _t in reanalizados:
        if isinstance(res, Exception):
            continue
        for campo, tipos in ESQUEMA.items():
            if campo not in res.state:
                malos.append(f"{fr.id}: falta {campo!r}")
            elif not isinstance(res.state[campo], tipos):
                malos.append(f"{fr.id}: {campo} es {type(res.state[campo]).__name__}")
    assert not malos, malos[:5]


def test_la_unidad_se_declara_siempre_en_produccion(reanalizados):
    """analyze_layout es la ruta de produccion y pone stack_unit='bb' literal. Si
    dejara de hacerlo, el motor se abstendria en todos los frames."""
    malos = [fr.id for fr, res, _t in reanalizados
             if not isinstance(res, Exception) and res.state.get("stack_unit") != "bb"]
    assert not malos, malos[:5]


def test_los_invariantes_se_cumplen_en_lo_reanalizado(reanalizados):
    """Lo mismo que se exige sobre lo grabado, exigido sobre lo que sale HOY:
    ninguna recomendacion puede venir de un estado que se contradiga."""
    malos = []
    for fr, res, _t in reanalizados:
        if isinstance(res, Exception) or not res.recommendation:
            continue
        fallos = inv.de_frame(res.state, res.recommendation)
        if fallos:
            malos.append(f"{fr.id}: {[c for c, _d in fallos]}")
    assert not malos, malos[:5]


def test_un_rival_que_enseña_las_cartas_cuenta_como_en_la_mano(reanalizados):
    """El cableado entre las dos señales de seat_map, sobre frames de verdad.

    detect_in_hand_seats solo ve DORSOS, asi que en un all-in -cuando el cliente
    gira las cartas- deja de ver a jugadores que siguen en la mano, y la equity
    del hero sale contra menos rivales de los que hay, o sea INFLADA. Por eso
    analyze_layout tiene que unir los dorsos con revealed_pair_seats.

    Si alguien vuelve a dejar `en_mano` con una sola de las dos fuentes, esto se
    pone rojo. Medido antes del arreglo: en sesion-2026-07-28_012453/0485 la
    equity daba 12,7% con la pantalla mostrando 0%."""
    malos = []
    for fr, res, _t in reanalizados:
        if isinstance(res, Exception):
            continue
        for p in res.state.get("players") or []:
            if p.get("revealed") and not p.get("in_hand"):
                malos.append(f"{fr.id}: {p.get('seat')} enseña la mano y no cuenta")
    assert not malos, malos[:5]


def test_el_ciclo_cabe_en_su_presupuesto(reanalizados):
    """El HUD va al ritmo del analisis: si el p95 se dispara, el usuario ve la
    recomendacion tarde, que para lo que sirve es como no verla."""
    tiempos = sorted(t for _fr, res, t in reanalizados if not isinstance(res, Exception))
    assert tiempos, "no se analizo ningun frame"
    p95 = tiempos[int(len(tiempos) * 0.95) - 1]
    assert p95 <= LATENCIA_P95_MAX_S, \
        f"p95 {p95:.2f}s (mediana {tiempos[len(tiempos) // 2]:.2f}s) sobre {len(tiempos)} frames"


# --- regresion de oro, solo con sesiones de ESTE commit ---------------------
#
# ESTO NO PUEDE IR SOBRE LA MUESTRA. El Analizador tiene memoria entre frames -la
# referencia del tapete se fija con las primeras lecturas, la plantilla del boton
# se aprende, la escala del glifo se busca una vez, el rastreador acumula- asi
# que un frame suelto se analiza EN FRIO y da un resultado peor que el que dio en
# vivo, cuando llevaba doscientos frames de contexto. Comparar eso con lo grabado
# marcaria diferencias que solo dicen que el analizador acababa de arrancar.
#
# La sesion se reproduce ENTERA y EN ORDEN, que es lo que hace replay.py.

@pytest.fixture(scope="module")
def al_dia():
    actual = corpus.commit_actual()
    if not actual:
        pytest.skip("no se puede saber el commit del arbol de trabajo")
    frames = [f for f in corpus.todos(exigir_png=True) if f.commit == actual]
    if not frames:
        pytest.skip(f"ninguna sesion grabada con el commit actual ({actual}); "
                    f"graba una con 'Grabar sesion de testing' para tener oro")

    # NI DE OTRA PLATAFORMA. El mismo argumento que el del commit, y se descubrio
    # igual de caro: el 05-08-2026, al abrir la suite en un Mac por primera vez,
    # cinco tests de oro salieron rojos -board, facing, vs_position, la
    # recomendacion y el recuento- contra una sesion grabada en Linux. No habia
    # nada roto: el OCR es una libreria del SISTEMA con su propio traineddata, y
    # la misma imagen se lee distinto en una distro y en un Mac. Comparar campo a
    # campo entre plataformas es un test que falla por haber cambiado de maquina,
    # que es exactamente lo que este fichero ya evitaba con los commits.
    #
    # Las sesiones viejas no guardan plataforma y se dan por linux, que es donde
    # se grabaron todas (ver corpus.plataforma_de_sesion).
    aqui = corpus.plataforma_actual()
    frames = [f for f in frames if corpus.plataforma_de_sesion(f.carpeta) == aqui]
    if not frames:
        pytest.skip(
            f"las sesiones del commit actual se grabaron en otra plataforma y "
            f"esto corre en {aqui}: el OCR del sistema no es el mismo, asi que "
            f"una comparacion campo a campo diria que ha cambiado el codigo "
            f"cuando lo que ha cambiado es la maquina. Graba una sesion aqui "
            f"para tener oro de esta plataforma.")

    por_sesion = {}
    for fr in frames:
        por_sesion.setdefault(fr.sesion, []).append(fr)

    # FUERA LOS TROZOS SUELTOS. Un frame sacado de mitad de una sesion -las
    # carpetas notas-*- no se puede reproducir en frio: al analisis le falta la
    # historia que tenia delante. Ver corpus.es_fragmento para el criterio y por
    # que se decide por el numero de mano y no por el nombre de la carpeta.
    por_sesion = {s: fs for s, fs in por_sesion.items() if not corpus.es_fragmento(fs)}
    if not por_sesion:
        pytest.skip(f"del commit actual ({actual}) solo hay trozos sueltos, que no "
                    f"son reproducibles en frio; graba una sesion entera")

    pares = []
    for _ses, fs in sorted(por_sesion.items()):
        # CON LA MISMA CONFIGURACION CON LA QUE SE GRABO. max_players no es solo
        # un tope de asientos: desde que hay tablas de 8 y 9 plazas ELIGE LA
        # GEOMETRIA, asi que reproducir una sesion de 9 con la disposicion de 6
        # no compara la app contra si misma sino dos apps distintas. Paso en
        # cuanto se grabo la primera sesion de 9: 4 tests rojos sin que nada
        # estuviera mal.
        meta = corpus.meta_de_sesion(fs[0].carpeta)
        an = Analizador(seed_equity=1,
                        max_players=meta.get("max_players"),
                        mazo=meta.get("mazo"))
        for fr in sorted(fs, key=lambda f: f.n):
            try:
                pares.append((fr, an.analizar(fr.png)))
            except Exception as e:                  # noqa: BLE001
                pytest.fail(f"{fr.id} lanzo al reproducir: {e}")
    return pares


@pytest.mark.parametrize("campo", CAMPOS_ORO)
def test_regresion_de_oro_del_estado(al_dia, campo):
    """Sobre las sesiones grabadas con este mismo codigo, el re-analisis tiene que
    dar EXACTAMENTE lo mismo. Cualquier diferencia es un cambio de comportamiento
    que alguien tiene que haber querido."""
    difieren = []
    for fr, res in al_dia:
        antes, ahora = fr.state.get(campo), res.state.get(campo)
        if antes != ahora:
            difieren.append(f"{fr.id}: {antes!r} -> {ahora!r}")
    assert not difieren, f"{len(difieren)} de {len(al_dia)} frames: {difieren[:5]}"


def test_regresion_de_oro_de_la_recomendacion(al_dia):
    """La accion es la salida de la app: es lo ultimo que puede cambiar sin que
    nadie se entere."""
    difieren = []
    for fr, res in al_dia:
        antes = (fr.recommendation or {}).get("action")
        ahora = (res.recommendation or {}).get("action")
        if antes != ahora:
            difieren.append(f"{fr.id}: {antes!r} -> {ahora!r}")
    assert not difieren, f"{len(difieren)} de {len(al_dia)} frames: {difieren[:5]}"


def test_no_se_pierden_recomendaciones(al_dia):
    """Aparte de la igualdad campo a campo: que el numero total no baje. Es la
    forma mas rapida de ver que un cambio ha vuelto la app mas muda."""
    antes = sum(1 for fr, _res in al_dia if fr.recommendation)
    ahora = sum(1 for _fr, res in al_dia if res.recommendation)
    assert ahora >= antes, f"se recomendaba en {antes} frames y ahora en {ahora}"


# --- el badge de torneo tapaba el stack del hero ----------------------------

# Suelo de frames con las 2 cartas del hero vivas en los que SI se le lee el
# stack. Sin stack no hay profundidad y decide() se abstiene, asi que esta tasa
# es, casi literalmente, cuantas veces la app puede hablar.
TASA_STACK_HERO_MIN = 0.70


def test_al_hero_se_le_lee_el_stack_casi_siempre(reanalizados):
    """EL CASO, anotado por el usuario mientras jugaba: "no se ve mi stack porque
    mi badge es dorado, plateado o bronce".

    Cuando va entre los tres primeros del torneo, PokerStars le pone una insignia
    que vuelve CLARA la franja del stack mientras la del nombre sigue oscura. El
    nameplate del hero se ancla a sus cartas, asi que sale un recorte ajustado con
    las dos mitades de polaridad OPUESTA pegadas, y ahi tesseract perdia la clara.
    No era polaridad -invertir el recorte entero lo empeora- sino mezclar las dos:
    aislada, la franja se lee perfecta.

    Medido sobre sesion-2026-07-28_210655 (730 frames, el usuario subiendo hasta
    el 2.o puesto), antes y despues de leer la franja aparte:

        franja del stack      antes    despues
        clara (con badge)      0/101    la lee
        oscura (normal)      135/159

        stack leido, en total   54%        89%
        frames con recomendacion 197       290

    A los RIVALES no les pasaba: con franja clara se les lee el 66% y con oscura
    el 70%, o sea lo mismo. Sus zonas son las fracciones fijas del ovalo, mas
    holgadas, y no meten el contraste partido dentro del mismo recorte."""
    vivas = leidos = 0
    for _fr, res, _t in reanalizados:
        if isinstance(res, Exception):
            continue
        st = res.state
        if len(st.get("hero_cards") or []) != 2 or st.get("hero_cards_dimmed"):
            continue
        hero = next((p for p in st.get("players") or [] if p.get("is_hero")), None)
        if hero is None:
            continue
        vivas += 1
        leidos += hero.get("stack") is not None
    if vivas < 20:
        pytest.skip("la muestra no trae suficientes frames con el hero en mano")
    tasa = leidos / vivas
    assert tasa >= TASA_STACK_HERO_MIN, (
        f"solo se lee el stack del hero en {100*tasa:.0f}% de los {vivas} frames "
        f"con sus cartas vivas ({leidos}); sin stack no hay profundidad y el motor "
        f"se calla")
