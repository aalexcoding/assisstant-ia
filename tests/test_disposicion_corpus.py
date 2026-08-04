"""
El detector de disposicion contra las sesiones grabadas.

LA VERDAD DE TERRENO ES GRATIS y por eso este test existe: cada sesion guarda en
su `_sesion.json` el `max_players` que el usuario eligio en el selector al
grabarla. O sea que hay 29 mesas etiquetadas por la persona que estaba jugando en
ellas.

LO QUE SE AFIRMA no es un porcentaje bonito sino el REPARTO DE ERRORES: puede
abstenerse todo lo que haga falta, pero no puede equivocarse. Una disposicion
equivocada no falla de forma visible -lee nombres donde no hay nadie y deja
jugadores invisibles-, y eso desplaza TODAS las posiciones, que salen del
recuento de ocupados. Abstenerse, en cambio, solo significa seguir con la de 6 y
avisar, que es lo que hacia la app antes de existir esto.

Medido al escribirlo: 20 aciertos, 9 abstenciones, 0 errores.
"""
import collections

import cv2
import pytest

from tests import corpus
from vision import disposicion as disp
from vision import seat_map

pytestmark = [pytest.mark.corpus, pytest.mark.lento, pytest.mark.vision]

FRAMES_POR_SESION = 25          # dos tandas de evidencia y algo de margen
MINIMO_DECIDIDAS = 0.5          # suelo para que "abstenerse siempre" no pase


@pytest.fixture(scope="module")
def veredictos():
    """{sesion: (verdad, detectado)} reproduciendo cada sesion como en vivo."""
    frames = [f for f in corpus.todos(exigir_png=True)]
    if not frames:
        pytest.skip("no hay sesiones grabadas en testing/")
    por_sesion = {}
    for fr in sorted(frames, key=lambda f: (f.sesion, f.n)):
        por_sesion.setdefault(fr.sesion, []).append(fr)

    salida = {}
    for sesion, fs in por_sesion.items():
        verdad = corpus.meta_de_sesion(fs[0].carpeta).get("max_players")
        if verdad not in disp.PLAZAS_CANDIDATAS:
            continue                      # sin etiqueta no hay nada que afirmar
        referencia = seat_map.ReferenciaFijada()
        fijador = disp.DisposicionFijada()
        usados = 0
        for fr in fs:
            bgr = cv2.imread(fr.png)
            if bgr is None:
                continue
            ref = referencia.de(bgr)
            if ref[4] or referencia.fijada is None:
                continue                  # sin ovalo fiable las zonas no valen
            fijador.de(bgr, ref)
            usados += 1
            if usados >= FRAMES_POR_SESION:
                break
        if usados:
            salida[sesion] = (verdad, fijador.fijada)
    if not salida:
        pytest.skip("ninguna sesion grabada lleva max_players apuntado")
    return salida


def test_no_se_equivoca_en_ninguna_sesion(veredictos):
    """LA propiedad. Si esto se cae, el detector esta dando una disposicion
    equivocada por buena y hay que subir los umbrales de decidir(), no bajarlos."""
    fallos = [f"{s}: real {v}, detecta {d}"
              for s, (v, d) in sorted(veredictos.items()) if d is not None and d != v]
    assert not fallos, f"{len(fallos)} de {len(veredictos)}: {fallos}"


def test_decide_en_la_mayoria(veredictos):
    """El otro lado del trato: abstenerse siempre tambien pasaria el test de
    arriba y no serviria para nada."""
    decididas = sum(1 for _v, d in veredictos.values() if d is not None)
    assert decididas >= MINIMO_DECIDIDAS * len(veredictos), \
        f"solo {decididas} de {len(veredictos)} sesiones decididas"


def test_reparto_por_tamaño(veredictos):
    """Que no acierte solo en las de 6 por ser la mas comun del corpus: de las
    tres disposiciones tiene que decidir alguna."""
    por_tamaño = collections.defaultdict(lambda: [0, 0])
    for verdad, detectado in veredictos.values():
        por_tamaño[verdad][0] += 1
        if detectado == verdad:
            por_tamaño[verdad][1] += 1
    sin_acertar = [n for n, (_tot, ok) in por_tamaño.items() if ok == 0]
    assert not sin_acertar, (f"no acierta NI UNA de {sin_acertar}; "
                             f"reparto {dict(por_tamaño)}")
