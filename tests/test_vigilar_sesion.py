"""
El vigilante de sesion: que avisa y, sobre todo, CUANTAS VECES avisa.

La parte de "que" la lleva core/invariantes.py, que ya tiene sus propios tests
sobre las 26 sesiones grabadas. Lo que se prueba aqui es lo otro, que es lo que
decide si la herramienta sirve o es ruido: una anomalia dura decenas de frames
-un board mal leido sigue mal leido mientras no cambie la calle, y la app escribe
un frame cada ~0,7 s- asi que sin dedup un solo fallo generaria cien lineas
identicas y el vigilante seria imposible de leer.

Tres reglas de silencio, y cada una responde a un tipo de repeticion distinto:

  RACHA        el mismo motivo en frames seguidos se dice UNA vez. Se suelta
               cuando cambia el motivo, para que la siguiente aparicion vuelva
               a avisar.
  YA VISTO     una recomendacion derivada o un motivo de abstencion que ya
               salio en esta sesion no se repite aunque vuelva mas tarde.
  NO DUPLICAR  si el motivo de abstencion es la redaccion larga de una
               contradiccion que se acaba de nombrar como BUG, no se dice dos
               veces lo mismo con otras palabras.
"""

import vigilar_sesion as vs


def memoria():
    return {"vistos": set(), "motivos": set()}


# Una recomendacion COMPLETA. core/invariantes exige que toda recomendacion
# viaje con profundidad, accion y motivo, asi que un frame de prueba con una
# recomendacion a medias disparia BUGs que no son los que se estan probando.
RECO = {"action": "OPEN RAISE", "stack_bb": 20.0, "reasoning": "rango de apertura",
        "source": "table"}


def frame(n=1, reco=RECO, **st):
    """Un frame sano: mesa detectada, recomendacion completa y nada raro.

    Se parte de un frame SANO a proposito. Un frame sin recomendacion y sin
    warning que lo explique ya es una contradiccion por si mismo
    (`abstiene_sin_motivo`), asi que usarlo de base mezclaria el hallazgo que se
    quiere probar con otro que no viene a cuento."""
    base = {"hero_cards": ["Ah", "Kd"], "board": [], "players": [],
            "hero_position": "BTN", "stack_unit": "bb", "warnings": [],
            "mano_seguida": 1}
    base.update(st)
    d = {"n": n, "hora": "00:00:00", "png": f"{n:04d}.png", "state": base}
    if reco is not None:
        d["recommendation"] = dict(reco)
    return d


def abstiene(n=1, motivo="no se lee tu stack", **st):
    """Un frame sin recomendacion, con su motivo declarado. Tambien es sano: la
    app se abstiene la mayor parte del tiempo."""
    return frame(n, reco=None, warnings=[motivo], **st)


def derivada(n=1, accion="CALL", mano=1):
    return frame(n, reco=dict(RECO, action=accion, source="derived",
                              confidence="media", donor="BTN"), mano_seguida=mano)


def claves(salida):
    return [t for t, _texto in salida]


# --- que se detecta ---------------------------------------------------------

def test_un_frame_normal_no_genera_ni_una_linea():
    """Si avisara de lo normal, el vigilante no serviria para nada."""
    assert vs.hallazgos(frame(), memoria()) == []


def test_una_abstencion_con_su_motivo_ya_visto_tampoco():
    m = {"vistos": set(), "motivos": {"no se lee tu stack"[:45]}}
    assert vs.hallazgos(abstiene(), m) == []


def test_una_contradiccion_se_avisa_como_BUG():
    """Un board con carta repetida no puede pasar en una mano de verdad. Se elige
    una repeticion que NO sea de una carta del hero, para que salte ese
    invariante y solo ese."""
    out = vs.hallazgos(abstiene(board=["2c", "2c", "9d"],
                                motivo="hay board: no se recomienda accion postflop"),
                       memoria())
    assert claves(out) == ["BUG"]
    assert "repetida" in out[0][1]


def test_una_recomendacion_DERIVADA_se_marca_para_revisar():
    """La capa de la Fase E no sale de las tablas del usuario, sale de una
    donante, asi que conviene mirarla con la imagen delante."""
    out = vs.hallazgos(derivada(), memoria())
    assert claves(out) == ["REVISAR"]
    assert "DERIVADA" in out[0][1]


def test_un_motivo_de_abstencion_NUEVO_se_marca_para_revisar():
    out = vs.hallazgos(abstiene(motivo="algo que no se habia visto"), memoria())
    assert claves(out) == ["REVISAR"]
    assert "motivo de abstencion nuevo" in out[0][1]


# --- RACHA: el mismo motivo seguido se dice una vez --------------------------

def test_el_mismo_fallo_en_frames_seguidos_se_avisa_UNA_vez():
    """Es la regla que hace legible el vigilante: un board mal leido sigue mal
    leido mientras no cambie la calle, o sea decenas de frames."""
    m = memoria()
    malo = dict(board=["2c", "2c", "9d"], motivo="hay board")
    primero = vs.hallazgos(abstiene(1, **malo), m)
    repes = [vs.hallazgos(abstiene(n, **malo), m) for n in range(2, 12)]
    assert len(primero) == 1
    assert all(r == [] for r in repes), "diez frames iguales, un solo aviso"


def test_al_cambiar_el_motivo_se_vuelve_a_avisar():
    # Los dos boards van en MANOS DISTINTAS, que es lo que serian en la realidad:
    # dentro de una mano el board solo añade cartas, asi que pasar de 2c 2c 9d a
    # Ah 3c 9d sin cambiar de mano es imposible y saltaria board_pierde_carta,
    # mezclando ese hallazgo con el que aqui se quiere probar.
    m = memoria()
    vs.hallazgos(abstiene(1, "hay board", board=["2c", "2c", "9d"]), m)
    otro = vs.hallazgos(abstiene(2, "hay board", board=["Ah", "3c", "9d"],
                                 mano_seguida=2), m)
    assert len(otro) == 1, "ahora una carta del hero esta en el board: otra cosa"
    assert "board" in otro[0][1] or "carta tuya" in otro[0][1]


def test_tras_frames_limpios_el_mismo_fallo_vuelve_a_avisarse():
    """La racha se suelta al pasar por un frame sin nada: si el fallo reaparece
    despues es una aparicion NUEVA, no la continuacion de la anterior."""
    m = memoria()
    malo = dict(board=["2c", "2c", "9d"], motivo="hay board")
    assert len(vs.hallazgos(abstiene(1, **malo), m)) == 1
    # los frames limpios van sin board, o sea en otra mano: un board no se vacia
    # a mitad de mano (board_vacio es justo lo que corta la mano)
    for n in (2, 3, 4):
        assert vs.hallazgos(frame(n, mano_seguida=2), m) == []
    assert len(vs.hallazgos(abstiene(5, mano_seguida=3, **malo), m)) == 1


# --- YA VISTO: no se repite dentro de la misma sesion ------------------------

def test_el_mismo_motivo_de_abstencion_no_se_repite_en_toda_la_sesion():
    m = memoria()
    primero = vs.hallazgos(abstiene(1, "no se lee tu stack"), m)
    for n in range(2, 6):
        vs.hallazgos(frame(n), m)
    tarde = vs.hallazgos(abstiene(9, "no se lee tu stack"), m)
    assert len(primero) == 1
    assert tarde == [], "ya se dijo una vez en esta sesion"


def test_un_motivo_de_abstencion_DISTINTO_si_se_avisa():
    m = memoria()
    vs.hallazgos(abstiene(1, "no se lee tu stack"), m)
    out = vs.hallazgos(abstiene(2, "no se detecta el boton"), m)
    assert len(out) == 1


def test_la_misma_derivada_en_la_misma_mano_se_dice_una_vez():
    m = memoria()
    assert len(vs.hallazgos(derivada(1), m)) == 1
    assert vs.hallazgos(derivada(2), m) == []


def test_la_misma_derivada_en_OTRA_mano_si_se_avisa():
    """Cada mano es un caso distinto que merece mirarse, aunque la accion
    coincida."""
    m = memoria()
    vs.hallazgos(derivada(1, mano=1), m)
    vs.hallazgos(frame(2), m)          # entre dos manos hay frames que sueltan la racha
    assert len(vs.hallazgos(derivada(50, mano=2), m)) == 1


def test_una_recomendacion_normal_no_se_marca():
    """Solo las derivadas: si avisara de todas, el vigilante seria un log."""
    assert vs.hallazgos(frame(), memoria()) == []


# --- NO DUPLICAR: el BUG y su redaccion larga son lo mismo -------------------

def test_no_se_dice_dos_veces_lo_mismo_con_otras_palabras():
    """El motivo de abstencion suele ser la redaccion larga de la contradiccion
    que se acaba de nombrar como BUG. Decir las dos seria repetirse."""
    out = vs.hallazgos(abstiene(motivo="board con carta repetida, no se recomienda",
                                board=["2c", "2c", "9d"]), memoria())
    assert claves(out) == ["BUG"], out


# --- la serie: entre frames de la misma mano --------------------------------

def test_un_cambio_de_posicion_a_mitad_de_mano_se_avisa():
    """El boton no se mueve hasta que acaba la mano, asi que si la posicion
    cambia es que se ha leido mal."""
    m = memoria()
    vs.hallazgos(frame(1, hero_position="BTN"), m)
    out = vs.hallazgos(frame(2, hero_position="CO"), m)
    assert claves(out) == ["BUG"]
    assert "BTN" in out[0][1] and "CO" in out[0][1]


def test_un_cambio_de_posicion_ENTRE_MANOS_es_normal():
    """Es justo lo que tiene que pasar: el boton avanza un asiento."""
    m = memoria()
    vs.hallazgos(frame(1, hero_position="BTN", mano_seguida=1), m)
    assert vs.hallazgos(frame(2, hero_position="SB", mano_seguida=2), m) == []


def test_la_memoria_de_serie_se_guarda_aunque_el_frame_este_limpio():
    """Si solo se guardara cuando hay hallazgos, la comparacion siguiente se
    haria contra un frame viejo y se perderian transiciones."""
    m = memoria()
    vs.hallazgos(frame(1, hero_position="BTN"), m)
    assert m.get("anterior") is not None


# --- la linea que se imprime ------------------------------------------------

def test_el_resumen_lleva_lo_que_hace_falta_para_verificar_con_la_imagen():
    """Un aviso sin el frame al lado no se puede comprobar, que es el punto
    entero de la herramienta."""
    d = frame(board=["2c", "5c", "9d"])
    d["recommendation"] = {"action": "CALL"}
    r = vs._resumen(d)
    assert "Ah Kd" in r and "BTN" in r and "board 2c 5c 9d" in r and "-> CALL" in r


def test_el_resumen_de_un_frame_sin_cartas_no_revienta():
    assert isinstance(vs._resumen({"state": {}}), str)
    assert isinstance(vs._resumen({}), str)


def test_emitir_escribe_el_numero_de_frame_y_la_ruta_del_png(capsys):
    vs.emitir("testing/sesion-x", frame(7), "BUG", "algo")
    linea = capsys.readouterr().out
    assert "[BUG]" in linea and "0007" in linea and "testing/sesion-x/0007.png" in linea
