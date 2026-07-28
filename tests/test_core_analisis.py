"""
El nucleo extraido de la GUI (core/analisis.py): el ciclo de analisis y el lazo
rapido de vigilancia.

El E2E sobre el corpus ya ejercita `analizar()` de punta a punta con imagenes de
verdad. Lo que falta cubrir, y es lo que hay aqui, son las dos cosas que ese
camino no toca:

  EL LAZO RAPIDO (vigilar / tick). Corre a 10 Hz junto al analisis lento y su
  unico trabajo es no perderse el cartel que el cliente pone en el nameplate
  cuando alguien actua -"Subir", "Igualar"- porque dura menos que un ciclo
  completo. Tiene un tope de seguridad para no encadenar OCRs y comerse la
  maquina, que es un sintoma de lag que ya se arreglo una vez.

  LOS FALLOS ACOTADOS. Cada pieza opcional del ciclo va envuelta: si el chat no
  se parsea, o el rastreador revienta, o la equity falla, el frame tiene que
  salir igualmente con lo que si se pudo calcular. Un fallo que se escape deja el
  HUD mudo, y eso en una mesa en vivo no se puede recuperar.

Se usan dobles en vez de imagenes porque lo que se prueba aqui es el CABLEADO, no
el reconocimiento: quien llama a quien, en que orden y que pasa cuando algo falla.
"""
import numpy as np
import pytest

from core import analisis as ca
from vision import ocr_client


@pytest.fixture
def an():
    return ca.Analizador(seed_equity=1)


def crop(h=200, w=300):
    return np.zeros((h, w, 3), dtype=np.uint8)


def tsv(texto, conf=96):
    """Una fila TSV de tesseract a nivel PALABRA, que es la unica que
    parse_tsv_lines mira (columna 0 = 5)."""
    return "\t".join(["5", "1", "1", "1", "1", "1", "0", "0", "40", "12",
                      str(conf), texto])


REF = (10, 10, 200, 100, False)


# --- la forma de un Analisis -------------------------------------------------

def test_a_dict_produce_EXACTAMENTE_la_forma_de_los_JSON_grabados():
    """Las 26 sesiones de testing/ tienen esta forma. Cambiarla las invalidaria
    todas, y con ellas la regresion de oro."""
    d = ca.Analisis(state={"a": 1}, recommendation={"action": "FOLD"}, hand={"h": 1},
                    equity={"e": 1}, hand_result={"w": "x"}, duracion_analisis_s=0.5).a_dict()
    assert set(d) == {"duracion_analisis_s", "state", "recommendation", "hand",
                      "equity", "hand_result"}
    assert d["duracion_analisis_s"] == 0.5
    assert d["state"] == {"a": 1}


def test_un_analisis_recien_creado_solo_exige_el_state():
    d = ca.Analisis(state={}).a_dict()
    assert all(d[k] is None for k in ("recommendation", "hand", "equity", "hand_result"))


def test_los_contadores_de_vigilancia_viajan_con_su_periodo():
    """Van dentro del state para poder juzgar DESPUES si la vigilancia estuvo
    haciendo su trabajo en esa sesion."""
    d = ca.Vigilancia(ticks=100, capsulas_ocr=8, saltadas=3).a_dict()
    assert d == {"ticks": 100, "capsulas_ocr": 8, "saltadas": 3,
                 "periodo_s": ca.VIGILANCIA_PERIODO_S}


# --- la entrada: ruta o array ------------------------------------------------

def test_una_ruta_no_se_vuelve_a_codificar(an, tmp_path):
    """analyze_layout quiere una RUTA y find_reference un ARRAY. Con una ruta de
    entrada -el replay- no hay que reescribir el PNG."""
    import cv2
    p = tmp_path / "f.png"
    cv2.imwrite(str(p), crop())
    ruta, bgr = an._como_ruta_y_array(str(p))
    assert ruta == str(p)
    assert bgr.shape == (200, 300, 3)


def test_un_array_se_vuelca_al_fichero_temporal_del_analizador(tmp_path):
    an = ca.Analizador(tmp_frame=str(tmp_path / "tmp.png"))
    img = crop()
    ruta, bgr = an._como_ruta_y_array(img)
    assert ruta == an.tmp_frame
    assert bgr is img, "el array se pasa tal cual, sin releerlo del disco"


def test_una_imagen_ilegible_lo_dice_en_vez_de_seguir_con_None(an):
    """cv2.imread devuelve None sin lanzar. Seguir con eso reventaria mucho mas
    tarde y en otro sitio."""
    with pytest.raises(ValueError, match="no se pudo leer"):
        an._como_ruta_y_array("/no/existe/nada.png")


# --- fallos acotados ---------------------------------------------------------

def test_un_fallo_de_la_equity_no_tumba_el_frame(an, monkeypatch):
    """La equity es lo ULTIMO y lo mas opcional del ciclo: si revienta, el resto
    del analisis -que incluye la recomendacion- tiene que llegar al HUD igual."""
    monkeypatch.setattr(ca.engine, "postflop_equity",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert an._equity_de({"board": ["2c", "5c", "9d"]}) is None


def test_la_semilla_de_equity_llega_al_motor(an, monkeypatch):
    """Sin ella la misma entrada da un numero distinto cada vez y ningun test de
    equity seria reproducible."""
    visto = {}
    monkeypatch.setattr(ca.engine, "postflop_equity",
                        lambda state, seed=None: visto.update(seed=seed) or {"ok": 1})
    an._equity_de({})
    assert visto["seed"] == 1


# --- el lazo rapido: vigilar -------------------------------------------------

class WatchFalso:
    """Doble de SeatWatch: dice que asientos han cambiado."""

    def __init__(self, cambios=(), lanza=False):
        self._cambios = list(cambios)
        self._lanza = lanza
        self.llamadas = 0

    def cambios(self, crop, ref):
        self.llamadas += 1
        if self._lanza:
            raise RuntimeError("boom")
        return list(self._cambios)


def test_sin_referencia_del_tapete_no_se_mira_nada(an):
    """El lazo rapido reutiliza la referencia del ULTIMO analisis completo en vez
    de recalcularla (29 ms, que a 10 Hz serian el 29% de un nucleo). Mientras no
    haya habido uno bueno, no hay donde mirar."""
    an.watch = WatchFalso(["UL"])
    an._ref = None
    an.vigilar(crop())
    assert an.watch.llamadas == 0


def test_si_no_ha_cambiado_ninguna_capsula_no_se_gasta_OCR(an):
    """Es el caso normal: la mesa esta quieta la mayor parte del tiempo."""
    an.watch = WatchFalso([])
    an._ref = REF
    an.vigilar(crop())
    assert an.vigilancia.capsulas_ocr == 0
    assert an.vigilancia.saltadas == 0


def test_un_fallo_mirando_las_capsulas_no_tumba_el_lazo(an):
    """Vigilar es una ayuda: si falla, se pierde un cartel, no la sesion."""
    an.watch = WatchFalso(["UL"], lanza=True)
    an._ref = REF
    an.vigilar(crop())            # no lanza
    assert an.vigilancia.capsulas_ocr == 0


def test_el_verbo_leido_en_una_capsula_llega_al_registro_de_acciones(an):
    """Es la razon de ser del lazo rapido: el cliente tapa el nick con el verbo
    justo cuando ese jugador actua, y el cartel dura menos que un ciclo lento."""
    an.watch = WatchFalso(["UL"])
    an._ref = REF
    anterior = ocr_client.usar_backend(
        lambda jobs: [tsv("Subir")] * len(jobs))
    try:
        an.vigilar(crop())
    finally:
        ocr_client.usar_backend(anterior)
    assert an.vigilancia.capsulas_ocr == 1
    acciones = an.action_log.acciones()["acciones"]
    assert any(a["seat"] == "UL" for a in acciones), acciones


def test_un_fallo_del_OCR_tampoco_tumba_el_lazo(an):
    an.watch = WatchFalso(["UL"])
    an._ref = REF
    anterior = ocr_client.usar_backend(
        lambda jobs: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        an.vigilar(crop())        # no lanza
    finally:
        ocr_client.usar_backend(anterior)


# --- el tope de seguridad ----------------------------------------------------

def test_dos_miradas_seguidas_NO_encadenan_dos_OCR(an, monkeypatch):
    """El tope existe porque un frame muy movido encadenaria OCRs y se comeria la
    maquina: es el sintoma de lag que ya se arreglo una vez. La segunda se cuenta
    como saltada, no se pierde en silencio."""
    an.watch = WatchFalso(["UL"])
    an._ref = REF
    reloj = [1000.0]
    monkeypatch.setattr(ca.time, "monotonic", lambda: reloj[0])
    anterior = ocr_client.usar_backend(lambda jobs: [""] * len(jobs))
    try:
        an.vigilar(crop())
        reloj[0] += ca.VIGILANCIA_OCR_MIN_S / 2      # demasiado pronto
        an.vigilar(crop())
    finally:
        ocr_client.usar_backend(anterior)
    assert an.vigilancia.capsulas_ocr == 1
    assert an.vigilancia.saltadas == 1


def test_pasado_el_tope_se_vuelve_a_mirar(an, monkeypatch):
    an.watch = WatchFalso(["UL"])
    an._ref = REF
    reloj = [1000.0]
    monkeypatch.setattr(ca.time, "monotonic", lambda: reloj[0])
    anterior = ocr_client.usar_backend(lambda jobs: [""] * len(jobs))
    try:
        an.vigilar(crop())
        reloj[0] += ca.VIGILANCIA_OCR_MIN_S * 2
        an.vigilar(crop())
    finally:
        ocr_client.usar_backend(anterior)
    assert an.vigilancia.capsulas_ocr == 2
    assert an.vigilancia.saltadas == 0


def test_varias_capsulas_cambiadas_se_resuelven_en_UNA_pasada(an):
    """Las tres van en el mismo `run()`, que las reparte entre procesos: el coste
    de un OCR es sobre todo arrancar el trabajo, asi que encadenar tres pasadas
    en serie costaria el triple. Que `run()` las TROCEE por dentro es justo lo
    que quiere -es el paralelismo, medido en ocr_client.run: 3,85 s -> 1,18 s con
    8 procesos-, de ahi que aqui se cuente el total y no el numero de trozos."""
    an.watch = WatchFalso(["UL", "UR", "ML"])
    an._ref = REF
    trozos = []
    anterior = ocr_client.usar_backend(lambda jobs: trozos.append(len(jobs)) or [""] * len(jobs))
    try:
        an.vigilar(crop())
    finally:
        ocr_client.usar_backend(anterior)
    assert sum(trozos) == 3, f"tres capsulas encoladas, {sum(trozos)} resueltas"
    assert an.vigilancia.capsulas_ocr == 3


# --- tick: el frame del lazo rapido ------------------------------------------

def test_un_tick_cuenta_guarda_el_frame_y_vigila(an):
    an.watch = WatchFalso([])
    an._ref = REF
    img = crop()
    an.tick(img)
    assert an.vigilancia.ticks == 1
    assert an.watch.llamadas == 1
    guardado = an.buffer.ultimo()
    assert guardado is not None and guardado["t"] is not None
    assert guardado["frame"] is not img, "el buffer guarda COPIAS: el stream reescribe el suyo"


def test_el_frame_se_guarda_aunque_no_haya_referencia(an):
    """El buffer sirve para mirar hacia atras cuando algo se detecta tarde, asi
    que tiene que llenarse desde el primer frame, antes de que la referencia
    exista."""
    an.watch = WatchFalso(["UL"])
    an._ref = None
    an.tick(crop())
    assert an.vigilancia.ticks == 1
    assert an.buffer.ultimo() is not None


def test_los_ticks_se_acumulan(an):
    an.watch = WatchFalso([])
    an._ref = REF
    for _ in range(5):
        an.tick(crop())
    assert an.vigilancia.ticks == 5
    assert an.vigilancia.a_dict()["ticks"] == 5
