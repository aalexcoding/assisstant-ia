"""
Verificacion del grabador de sesiones de testing (testing_session.py).

Lo importante que se comprueba: que la DUPLA existe siempre (mismo nombre para
el PNG y el JSON, que es lo que permite abrir uno y mirar el otro), que un fallo
guardando NO tumba la sesion -grabar es una ayuda, no la funcion de la app- y
que los tipos de numpy que trae el GameState no revientan el volcado a JSON.
"""
import json
import os

import numpy as np
import pytest

import testing_session as tss


def png(ruta):
    """El escritor de imagen que le pasa la GUI. Aqui basta con que escriba algo."""
    with open(ruta, "wb") as f:
        f.write(b"png")


@pytest.fixture
def raiz(tmp_path):
    return str(tmp_path)


@pytest.fixture
def sesion(raiz):
    return tss.TestingSession(interval=2.0,
                              region={"x": 1, "y": 2, "width": 3, "height": 4},
                              root=raiz)


def leer(directorio, nombre):
    with open(os.path.join(directorio, nombre)) as fh:
        return json.load(fh)


# --- una sesion normal -------------------------------------------------------

def test_la_carpeta_se_llama_sesion_fecha_y_se_crea_con_metadatos(sesion):
    assert os.path.basename(sesion.dir).startswith("sesion-")
    assert os.path.isdir(sesion.dir)
    assert os.path.exists(os.path.join(sesion.dir, "_sesion.json"))


def test_guardar_deja_la_dupla_png_mas_json(sesion):
    """MISMO nombre, distinta extension: es lo que permite abrir la imagen y
    mirar el JSON de al lado sin cruzar timestamps."""
    escritos = []
    n = sesion.guardar(None, {"state": {"hero_cards": ["Ah", "Kd"], "warnings": []},
                              "recommendation": {"action": "FOLD"}},
                       lambda ruta: escritos.append(ruta) or png(ruta))
    assert n == 1
    assert os.path.basename(escritos[0]) == "0001.png"
    assert os.path.exists(os.path.join(sesion.dir, "0001.json"))


def test_el_json_apunta_a_su_png_y_lleva_todo_lo_calculado(sesion):
    sesion.guardar(None, {"state": {"hero_cards": ["Ah", "Kd"], "warnings": []},
                          "recommendation": {"action": "FOLD"}}, png)
    d = leer(sesion.dir, "0001.json")
    assert d["png"] == "0001.png"
    assert ":" in d["hora"], "hora legible"
    assert d["state"]["hero_cards"] == ["Ah", "Kd"]
    assert d["recommendation"]["action"] == "FOLD"


def test_numeracion_correlativa_y_cada_png_con_su_json(sesion):
    for _ in range(4):
        sesion.guardar(None, {"state": {}}, png)
    assert os.path.exists(os.path.join(sesion.dir, "0004.png"))
    pngs = sorted(f[:-4] for f in os.listdir(sesion.dir) if f.endswith(".png"))
    jsons = sorted(f[:-5] for f in os.listdir(sesion.dir)
                   if f.endswith(".json") and not f.startswith("_"))
    assert pngs == jsons


# --- tipos de numpy: el GameState los trae y json no sabe volcarlos ---------

def test_un_gamestate_con_tipos_de_numpy_se_guarda_igual(sesion):
    n = sesion.guardar(None, {"state": {"pot": np.float32(3.75),
                                        "n": np.int64(5),
                                        "arr": np.array([1, 2])}}, png)
    assert n == 1
    d = leer(sesion.dir, "0001.json")
    assert abs(d["state"]["pot"] - 3.75) < 1e-6, "float32 -> float"
    assert d["state"]["n"] == 5, "int64 -> int"
    assert d["state"]["arr"] == [1, 2], "array -> lista"


# --- un fallo guardando no puede tumbar el analisis en vivo -----------------

def test_si_no_se_puede_escribir_devuelve_none_y_lo_cuenta(sesion):
    def revienta(_ruta):
        raise OSError("disco lleno")

    antes = sesion.errores
    assert sesion.guardar(None, {"state": {}}, revienta) is None
    assert sesion.errores == antes + 1


def test_la_sesion_sigue_viva_despues_del_fallo(sesion):
    """Grabar es una ayuda, no la funcion de la app."""
    def revienta(_ruta):
        raise OSError("disco lleno")

    sesion.guardar(None, {"state": {}}, revienta)
    assert sesion.guardar(None, {"state": {}}, png) == 2


# --- cierre ------------------------------------------------------------------

def test_los_metadatos_finales_cuadran(sesion):
    def revienta(_ruta):
        raise OSError("disco lleno")

    for _ in range(5):
        sesion.guardar(None, {"state": {}}, png)
    sesion.guardar(None, {"state": {}}, revienta)
    sesion.guardar(None, {"state": {}}, png)
    meta = leer(sesion.cerrar(), "_sesion.json")
    assert meta["frames"] == 7
    assert meta["errores"] == 1
    assert meta["intervalo_s"] == 2.0
    assert meta["recuadro"]["width"] == 3, "el recuadro con el que se grabo"
    assert "commit" in meta, "con que version se grabo"


# --- resumen -----------------------------------------------------------------

def test_el_resumen_cuenta_frames_y_recomendaciones(sesion):
    sesion.guardar(None, {"state": {"warnings": []},
                          "recommendation": {"action": "FOLD"}}, png)
    for _ in range(2):
        sesion.guardar(None, {"state": {"warnings": []}}, png)
    r = tss.resumen(sesion.cerrar())
    assert r["frames"] == 3
    assert r["con_recomendacion"] == 1


def test_dos_sesiones_van_a_carpetas_distintas(raiz, sesion):
    assert tss.TestingSession(root=raiz, now=1).dir != sesion.dir


# --- notas: marcar una situacion rara mientras se juega ---------------------
# Lo que de verdad protege: que la nota acabe DENTRO del JSON del frame (la dupla
# tiene que seguir siendo autocontenida) y que no pise nada de lo ya calculado.

@pytest.fixture
def con_notas(raiz):
    s = tss.TestingSession(root=raiz, now=2)
    s.guardar(None, {"state": {"hero_cards": ["Ah", "Kd"], "pot": np.float32(3.75)},
                     "recommendation": {"action": "FOLD"}}, png)
    s.guardar(None, {"state": {}}, png)
    return s


def test_la_nota_va_dentro_del_json_del_frame_con_el_texto_limpio(con_notas):
    assert con_notas.anotar(1, "  aqui recomendo FOLD con AK y no lo entiendo  ") is True
    d = leer(con_notas.dir, "0001.json")
    assert d["nota"] == "aqui recomendo FOLD con AK y no lo entiendo"


def test_la_nota_no_pisa_nada_de_lo_ya_calculado(con_notas):
    con_notas.anotar(1, "algo")
    d = leer(con_notas.dir, "0001.json")
    assert d["state"]["hero_cards"] == ["Ah", "Kd"]
    assert d["recommendation"]["action"] == "FOLD"
    assert d["png"] == "0001.png"


def test_hay_un_indice_de_notas_a_nivel_de_sesion(con_notas):
    con_notas.anotar(1, "algo")
    ruta = os.path.join(con_notas.dir, "_notas.jsonl")
    assert os.path.exists(ruta)
    with open(ruta) as fh:
        idx = [json.loads(l) for l in fh if l.strip()]
    assert len(idx) == 1
    assert idx[0]["n"] == 1 and idx[0]["png"] == "0001.png"
    assert leer(con_notas.dir, "_sesion.json")["notas"] == [1]


def test_una_segunda_nota_sobre_el_mismo_frame_se_acumula(con_notas):
    """Pisar la primera seria perder justo lo que el usuario se molesto en
    escribir."""
    con_notas.anotar(1, "aqui recomendo FOLD con AK y no lo entiendo")
    con_notas.anotar(1, "y ademas el bote sale mal")
    d = leer(con_notas.dir, "0001.json")
    assert d["nota"].splitlines() == ["aqui recomendo FOLD con AK y no lo entiendo",
                                      "y ademas el bote sale mal"]
    assert leer(con_notas.dir, "_sesion.json")["notas"] == [1], "no se duplica"


@pytest.mark.parametrize("desc, args", [
    ("una nota vacia no se guarda", (1, "   ")),
    ("ni una nota sin frame", (None, "algo")),
    ("anotar un frame que no existe devuelve False sin lanzar", (99, "algo")),
])
def test_anotar_devuelve_false_sin_lanzar(con_notas, desc, args):
    assert con_notas.anotar(*args) is False, desc


def test_el_resumen_lista_las_notas_enteras(con_notas):
    """Es lo mas valioso de una sesion grabada."""
    con_notas.anotar(1, "aqui recomendo FOLD con AK y no lo entiendo")
    r = tss.resumen(con_notas.dir)
    assert len(r["notas"]) == 1
    assert r["notas"][0]["n"] == 1
    assert "no lo entiendo" in r["notas"][0]["nota"]
    assert all(f["n"] != 2 for f in r["notas"]), "no inventa notas donde no las hay"


# --- la medida que decide si la vigilancia rapida cumple --------------------
# Acciones vistas por mano. La referencia con muestreo de 1,48 s eran 5,7, y una
# mano de 3-max tiene tipicamente 4-8 acciones.

@pytest.fixture
def con_vigilancia(raiz):
    s = tss.TestingSession(root=raiz, now=4)
    for n, (mano, nacc) in enumerate([(1, 1), (1, 3), (2, 2), (2, 5), (2, 4)], 1):
        s.guardar(None, {"state": {"mano_seguida": mano, "warnings": [],
                                   "acciones": {"acciones": [{}] * nacc},
                                   "vigilancia": {"ticks": 100 * n, "capsulas_ocr": 7 * n}},
                         "duracion_analisis_s": 0.7}, png)
    return tss.resumen(s.dir)


def test_el_resumen_cuenta_las_manos_seguidas(con_vigilancia):
    assert con_vigilancia["manos"] == 2


def test_las_acciones_por_mano_cogen_el_maximo_de_cada_una(con_vigilancia):
    """El historial crece dentro de la mano, asi que el ultimo frame la resume."""
    assert con_vigilancia["acciones_por_mano"] == 4.0      # (3 + 5) / 2


def test_el_ciclo_medio_y_el_estado_de_la_vigilancia(con_vigilancia):
    assert con_vigilancia["ciclo_medio_s"] == 0.7
    assert con_vigilancia["vigilancia"]["ticks"] == 500
    assert con_vigilancia["vigilancia"]["capsulas_ocr"] == 35


def test_una_sesion_sin_esos_datos_no_revienta_ni_inventa_un_numero(raiz):
    r = tss.resumen(tss.TestingSession(root=raiz, now=1).dir)
    assert r["manos"] == 0
    assert r["acciones_por_mano"] is None


def test_no_medido_no_es_no_se_vio_nada(raiz):
    """Una sesion grabada antes de que existiera el historial tiene manos pero no
    acciones, y contarla como 0 haria creer que hay una regresion donde no la hay."""
    s = tss.TestingSession(root=raiz, now=5)
    for _ in range(3):
        s.guardar(None, {"state": {"mano_seguida": 1, "warnings": []}}, png)
    r = tss.resumen(s.dir)
    assert r["manos"] == 1
    assert r["acciones_por_mano"] is None


# --- marcar sin modo testing: carpeta aparte creada al vuelo ----------------

def test_la_sesion_de_solo_notas_va_a_su_propia_carpeta(raiz):
    notas = tss.TestingSession(root=raiz, now=3, prefix="notas")
    assert os.path.basename(notas.dir).startswith("notas-")
    assert notas.guardar(None, {"state": {}}, png) == 1
    assert notas.anotar(1, "esto canta") is True
