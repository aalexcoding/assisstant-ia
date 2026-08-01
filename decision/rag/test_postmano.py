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
import json

import numpy as np
import pytest

from decision.rag import catalog
from decision.rag import postmano as pm
from decision.rag import query

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


def test_un_indice_ausente_es_un_error_de_biblioteca_y_el_hud_degrada_bien(tmp_path, monkeypatch):
    """query no debe terminar el proceso: la GUI decide que una ayuda opcional
    se muestra vacia cuando falta el indice."""
    monkeypatch.setattr(query, "EMB_PATH", str(tmp_path / "embeddings.npy"))
    monkeypatch.setitem(query._STATE, "emb", None)
    with pytest.raises(query.IndexUnavailableError):
        query.search("flop seco")
    assert pm.buscar("flop seco") == []


def test_estado_de_indice_compatible_carga_meta_y_vectores(tmp_path, monkeypatch):
    emb = tmp_path / "embeddings.npy"
    meta = tmp_path / "meta.jsonl"
    manifest = tmp_path / "manifest.json"
    np.save(emb, np.zeros((1, 384), dtype=np.float32))
    meta.write_text(json.dumps({"video": "v", "text": "x"}) + "\n")
    manifest.write_text(json.dumps({
        "model": "modelo-test",
        "fastembed_version": query._fastembed_version(),
        "count": 1,
    }))
    monkeypatch.setattr(query, "EMB_PATH", str(emb))
    monkeypatch.setattr(query, "META_PATH", str(meta))
    monkeypatch.setattr(query, "MANIFEST_PATH", str(manifest))
    query.reset_state()
    assert query.index_status() == {
        "available": True, "reason": None, "count": 1,
        "model": "modelo-test"}
    query.reset_state()


def test_estudio_distingue_indice_roto_de_cero_coincidencias(monkeypatch):
    def roto(*_a, **_kw):
        raise query.IndexIncompatibleError("reconstruir índice")

    monkeypatch.setattr(query, "search", roto)
    r = pm.estudiar(board=BOARD_QQ8)
    assert r["referencias"] == []
    assert "reconstruir" in r["problema"]


@pytest.mark.parametrize("k", [0, -1, True, "3"])
def test_query_rechaza_un_numero_de_resultados_invalido(k):
    with pytest.raises(ValueError, match="entero positivo"):
        query.search("flop seco", k=k)


def test_estudiar_sin_datos_devuelve_la_forma_esperada():
    assert pm.estudiar() == {
        "consulta": "", "fichas": [], "referencias": [], "problema": None}


def test_estudiar_devuelve_consulta_y_referencias():
    r = pm.estudiar(board=BOARD_QQ8, mano_ganadora="doble pareja")
    assert set(r) == {"consulta", "fichas", "referencias", "problema"}
    assert isinstance(r["referencias"], list)
    assert isinstance(r["fichas"], list)


def test_contexto_incluye_solo_datos_observados_del_spot():
    state = {
        "hero_cards": ["Ah", "Qh"], "board": ["Jh", "7c", "2d"],
        "hero_position": "BTN", "pot": 6.5, "calle_seguida": "flop",
        "players": [
            {"seat": "HERO", "position": "BTN", "is_hero": True,
             "in_hand": True, "stack": 27.0},
            {"seat": "LL", "position": "BB", "in_hand": True, "stack": 20.0},
        ],
        "preflop_action": {
            "agresiones_observadas": 1, "ultimo_agresor_seat": "HERO"},
        "acciones": {"completo": False, "acciones": [
            {"street": "flop", "seat": "LL", "position": "BB",
             "accion": "check", "pot_bb": 6.5},
        ]},
    }
    c = pm.contexto_desde_estado(
        state, {"street": "flop", "made_name": "Carta alta"})
    assert c["position_relation"] == "IP"
    assert c["initiative"] == "con_iniciativa"
    assert c["pot_type"] == "single_raised"
    assert c["spr"] == pytest.approx(20 / 6.5, abs=.01)
    q = pm.describir(contexto=c)
    for expected in ("Ah Qh", "Carta alta", "con posicion", "iniciativa",
                     "bote subido", "flop BB check"):
        assert expected in q


def test_multiway_entre_dos_rivales_no_inventa_ip_oop():
    state = {
        "hero_position": "CO", "players": [
            {"is_hero": True, "position": "CO", "in_hand": True},
            {"position": "BB", "in_hand": True},
            {"position": "BTN", "in_hand": True},
        ],
    }
    assert pm.contexto_desde_estado(state)["position_relation"] is None


@pytest.mark.parametrize("agresiones, tipo", [
    (1, "single_raised"), (2, "3bet"), (3, "4bet_plus"), (4, "4bet_plus"),
])
def test_contexto_distingue_botes_resubidos(agresiones, tipo):
    state = {
        "players": [
            {"is_hero": True, "in_hand": True},
            {"is_hero": False, "in_hand": True},
        ],
        "preflop_action": {
            "agresiones_observadas": agresiones,
            "ultimo_agresor_seat": "HERO",
        },
    }
    assert pm.contexto_desde_estado(state)["pot_type"] == tipo


def test_contexto_detecta_squeeze_solo_con_secuencia_positiva():
    state = {
        "hero_cards": ["Ah", "Kh"],
        "players": [
            {"is_hero": True, "in_hand": True},
            {"is_hero": False, "in_hand": True},
        ],
        "preflop_action": {
            "agresiones_observadas": 2,
            "ultimo_agresor_seat": "HERO",
        },
        "acciones": {"completo": False, "acciones": [
            {"street": "preflop", "accion": "raise", "seat": "V1"},
            {"street": "preflop", "accion": "call", "seat": "V2"},
            {"street": "preflop", "accion": "raise", "seat": "HERO"},
        ]},
    }
    assert pm.contexto_desde_estado(state)["squeeze_observed"] is True
    state["acciones"]["acciones"].pop(1)
    # Lista incompleta: no haber visto el call no demuestra que no existiese.
    assert pm.contexto_desde_estado(state)["squeeze_observed"] is None


def test_catalogo_excluye_los_dos_anuncios_del_curso():
    anuncio = catalog.metadata(
        "cuando_estara_disponible_el_contenido_de_este_curso_en_3bet_pots_y_4bet")
    assert anuncio["is_strategy"] is False


def test_catalogo_extrae_spot_de_la_ruta_sin_leer_la_transcripcion():
    m = catalog.metadata(
        "x",
        "/curso/Defensa de ciegas (Juego sin iniciativa OOP)/leccion.mp4")
    assert m["position_relation"] == "OOP"
    assert m["initiative"] == "sin_iniciativa"
    assert m["pot_type"] == "single_raised"


# --- el umbral ---------------------------------------------------------------

def test_con_un_minimo_imposible_no_se_cuela_ninguna_referencia():
    assert pm.buscar("board Qc Qs 8s", minimo=1.1) == []


def test_no_ocupan_todo_el_panel_tres_chunks_del_mismo_video(monkeypatch):
    rows = [
        {"video": "uno", "text": f"a{i}", "score": .8 - i / 100,
         "start_time": i * 60}
        for i in range(3)
    ] + [
        {"video": "dos", "text": "b", "score": .7, "start_time": 0},
        {"video": "tres", "text": "c", "score": .6, "start_time": 0},
    ]
    monkeypatch.setattr(query, "search", lambda *_a, **_kw: rows)
    refs = pm.buscar("flop", k=3)
    assert [r["video"] for r in refs] == ["uno", "dos", "tres"]


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
