"""Configuracion comun de la suite.

Aqui va lo que aisla un test del siguiente y el acceso al corpus grabado. La raiz
del proyecto la pone pytest en sys.path via `pythonpath` de pyproject.toml, asi
que esto ya no tiene que tocar rutas: antes cada test se abria camino con su
propio sys.path.insert.
"""
import os

import pytest

from decision import engine, journal
from tests import corpus


def pytest_addoption(parser):
    g = parser.getgroup("corpus")
    g.addoption("--corpus-n", type=int, default=corpus.N_POR_DEFECTO,
                help="cuantos frames grabados muestrear para los tests E2E")
    g.addoption("--corpus-semilla", type=int, default=None,
                help="semilla del muestreo, para repetir una ejecucion")
    g.addoption("--corpus-seleccion", default=None,
                help="repite EXACTAMENTE la seleccion volcada en un "
                     "_seleccion.local.json anterior")


def pytest_configure(config):
    """Apaga el registro de decisiones ANTES de que corra ningun test.

    decide() escribe una linea en decision/decisions.local.jsonl cada vez que se
    le llama. Es util en produccion, pero una pasada del corpus son miles de
    llamadas y ensuciarian el log real del usuario con decisiones que nadie ha
    jugado. Se apaga por env (para los subprocesos) y por atributo (para este,
    que ya tiene el modulo importado)."""
    os.environ["POKER_DECISIONS_LOG"] = "0"
    journal.set_enabled(False)


def _hay_display_gtk():
    """True solo si GTK puede crear ventanas en este proceso."""
    try:
        import gi
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk
        return Gdk.Display.get_default() is not None
    except (ImportError, ValueError):
        return False


def pytest_collection_modifyitems(config, items):
    """Sin display, GTK importa pero falla al construir la primera ventana."""
    if _hay_display_gtk():
        return
    skip = pytest.mark.skip(
        reason="los tests GTK necesitan un display (usa Xvfb o una sesion grafica)")
    for item in items:
        if item.get_closest_marker("gtk"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _sin_estado_entre_tests():
    """El motor cachea el stack del hero ENTRE llamadas (90 s de TTL) para
    sobrevivir a los frames en que el nameplate esta tapado por los botones. Eso
    es correcto en vivo y veneno en una suite: un test que deja un stack en la
    cache haria que el siguiente recomiende sobre una profundidad que su
    GameState no trae. Se limpia antes y despues de cada test."""
    engine.reset_state()
    yield
    engine.reset_state()


# --- el corpus grabado -------------------------------------------------------
# Los dos fixtures son de SESION: leer los 9.200 JSON cuesta unos segundos y no
# tiene sentido pagarlo por cada test.

@pytest.fixture(scope="session")
def corpus_completo():
    """Los ~9.200 estados grabados, SIN imagenes. Es la base de los tests de
    invariantes: recorrerlo entero cuesta segundos porque solo se lee JSON."""
    frames = corpus.todos(exigir_png=False)
    if not frames:
        pytest.skip(f"no hay sesiones grabadas en {corpus.RAIZ} (no versionadas)")
    return frames


@pytest.fixture(scope="session")
def corpus_muestra(request):
    """Los frames CON imagen que ejercita el E2E. Estratificados por caso, no los
    primeros N: ver tests/corpus.py."""
    ruta = request.config.getoption("--corpus-seleccion")
    if ruta:
        frames = corpus.cargar_seleccion(ruta)
    else:
        frames = corpus.muestrear(n=request.config.getoption("--corpus-n"),
                                  semilla=request.config.getoption("--corpus-semilla"))
    if not frames:
        pytest.skip(f"no hay frames con PNG en {corpus.RAIZ} (no versionados)")
    return frames
