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

def test_un_tick_cuenta_y_vigila(an):
    an.watch = WatchFalso([])
    an._ref = REF
    an.tick(crop())
    assert an.vigilancia.ticks == 1
    assert an.watch.llamadas == 1


def test_sin_referencia_el_tick_no_dispara_nada(an):
    """Con la mesa tapada o sin fijar todavia, la zona de botones cae desplazada
    y el detector diria cualquier cosa. Mejor no mirar."""
    an.watch = WatchFalso(["UL"])
    an._ref = None
    assert an.tick(crop()) is None
    assert an.vigilancia.ticks == 1


def test_los_ticks_se_acumulan(an):
    an.watch = WatchFalso([])
    an._ref = REF
    for _ in range(5):
        an.tick(crop())
    assert an.vigilancia.ticks == 5
    assert an.vigilancia.a_dict()["ticks"] == 5


# --- el chat se lee ESPACIADO, no en cada frame ------------------------------
#
# Es el job de OCR mas caro del ciclo: medido con un A/B sobre los mismos 60
# frames de sesion-2026-07-29_003632, ciclo p50 1,003 s -> 0,739 s, o sea
# -264 ms por frame (26%), con las MISMAS 24 recomendaciones y cero diferencias
# en los campos comparados por replay.py sobre 200 frames.
#
# Y lo que se saca del chat -quien gano la mano anterior y su numero- cambia UNA
# VEZ POR MANO, no diez veces por segundo. Sobre 300 frames: se pasa de leer el
# chat en 298 a leerlo en 15, y los frames que llevan hand_result siguen siendo
# 299 de 299, porque el ultimo resumen se conserva.


class LayoutFalso:
    """Doble de table_state.analyze_layout: apunta con que leer_chat se le llamo."""

    def __init__(self):
        self.llamadas = []

    def __call__(self, ruta, **kw):
        self.llamadas.append(kw.get("leer_chat"))
        return {"hero_cards": [], "board": [], "players": [], "warnings": [],
                "stack_unit": "bb", "chat_lines": []}


@pytest.fixture
def layout(monkeypatch):
    doble = LayoutFalso()
    monkeypatch.setattr(ca.ts, "analyze_layout", doble)
    return doble


def test_los_primeros_frames_SI_leen_el_chat(an, layout, tmp_path):
    """Para que el panel "Mano anterior" no arranque en blanco."""
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    for _ in range(ca.CHAT_FRAMES_INICIALES):
        an.analizar(p)
    assert all(layout.llamadas), layout.llamadas


def test_despues_deja_de_leerlo_en_cada_frame(an, layout, tmp_path):
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    for _ in range(ca.CHAT_FRAMES_INICIALES + 6):
        an.analizar(p)
    assert layout.llamadas[-1] is False
    assert sum(1 for x in layout.llamadas if x) <= ca.CHAT_FRAMES_INICIALES + 1


def test_al_cerrarse_una_mano_se_pide_el_chat_PARA_EL_SIGUIENTE(an, layout, tmp_path):
    """La frontera se detecta DESPUES de analyze_layout, asi que este frame ya no
    puede leerlo. Y da igual: la linea "X gana el bote" tarda en aparecer."""
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    for _ in range(ca.CHAT_FRAMES_INICIALES + 3):
        an.analizar(p)
    assert layout.llamadas[-1] is False
    an._mano_vista = 999            # simula que el rastreador abre otra mano
    an.analizar(p)
    assert layout.llamadas[-1] is False, "el frame de la frontera NO lo lee"
    an.analizar(p)
    assert layout.llamadas[-1] is True, "el siguiente SI"


def test_el_guardarrail_lo_fuerza_aunque_no_haya_frontera(an, layout, tmp_path, monkeypatch):
    """Por si el detector de frontera enmudece -mesa parada, tapete que deja de
    reconocerse-: el panel no puede quedarse congelado sin que nadie se entere."""
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    reloj = [1000.0]
    monkeypatch.setattr(ca.time, "monotonic", lambda: reloj[0])
    for _ in range(ca.CHAT_FRAMES_INICIALES + 3):
        an.analizar(p)
    assert layout.llamadas[-1] is False
    reloj[0] += ca.CHAT_MAX_S + 1
    an.analizar(p)
    assert layout.llamadas[-1] is True


def test_el_ultimo_resumen_de_mano_se_conserva_entre_lecturas(an, monkeypatch, tmp_path):
    """Un frame sin lectura NO significa "no hay mano anterior", significa "no se
    ha vuelto a mirar". Tratarlos igual dejaria el panel en blanco entre manos."""
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    monkeypatch.setattr(ca.ts, "analyze_layout", LayoutFalso())
    monkeypatch.setattr(ca.hr, "parse_hand_result",
                        lambda lineas: {"winner": "pepe", "hand_number": "123"})
    primero = an.analizar(p)
    assert primero.hand_result["winner"] == "pepe"
    monkeypatch.setattr(ca.hr, "parse_hand_result", lambda lineas: None)
    for _ in range(8):
        res = an.analizar(p)
    assert res.hand_result is not None, "el panel se habria vaciado"
    assert res.hand_result["winner"] == "pepe"


# --- la referencia del tapete: UNA sola, y la MISMA para los dos lazos -------
#
# Dos arreglos en uno, y el segundo es el que importa:
#
#   1. find_reference se llamaba DOS VECES por frame -aqui y dentro de
#      referencia.de() en analyze_layout-. 17 ms medidos, tirados.
#   2. Y no daban lo mismo: analyze_layout usa la referencia FIJADA (mediana de
#      las primeras lecturas buenas) y esto usaba la CRUDA de este frame, asi que
#      el lazo rapido hasheaba y OCR-eaba cajas DISTINTAS de las que el lento
#      juzgaba. El nombre que leia uno no era del asiento que contaba el otro.

def test_el_lazo_rapido_usa_la_referencia_FIJADA_del_lento(an, monkeypatch, tmp_path):
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    monkeypatch.setattr(ca.ts, "analyze_layout", LayoutFalso())
    an.referencia._fija = (11, 22, 333, 444)
    an.analizar(p)
    assert an._ref == (11, 22, 333, 444, False)


def test_sin_referencia_fijada_todavia_el_rapido_no_mira(an, monkeypatch, tmp_path):
    """Mientras no haya suficientes lecturas buenas no hay donde mirar, y mirar
    en el sitio equivocado es peor que no mirar: las zonas estarian desplazadas y
    el verbo leido seria de otro asiento."""
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    monkeypatch.setattr(ca.ts, "analyze_layout", LayoutFalso())
    assert an.referencia.fijada is None
    an.analizar(p)
    assert an._ref is None


def test_analizar_no_vuelve_a_buscar_la_referencia_por_su_cuenta(an, monkeypatch, tmp_path):
    """La busca analyze_layout, a traves de ReferenciaFijada. Una segunda llamada
    aqui son 17 ms por frame y ademas abre la puerta a que se descuadren."""
    import cv2
    p = str(tmp_path / "f.png")
    cv2.imwrite(p, crop())
    monkeypatch.setattr(ca.ts, "analyze_layout", LayoutFalso())
    llamadas = []
    monkeypatch.setattr(ca.seat_map, "find_reference",
                        lambda bgr: llamadas.append(1) or (0, 0, 1, 1, True))
    an.analizar(p)
    assert llamadas == [], "analizar() no debe llamar a find_reference"


# --- el disparo por TURNO -----------------------------------------------------
#
# La idea es del usuario: lo que importa para recomendar es que le toque a el, y
# eso se ve porque el cliente pinta los botones de accion. Antes se analizaba
# cada N segundos "por si acaso", lo que gastaba ciclos en frames sin nada que
# decidir y casi nunca caia en el turno del hero: medido sobre 1.011 frames,
# tenia botones en 216 y la app solo leia `facing` en 89. O sea que decidia a
# ciegas en el 59% de sus propios turnos.

def test_cuando_aparecen_los_botones_se_pide_analizar(an, monkeypatch):
    an.watch = WatchFalso([])
    an._ref = REF
    monkeypatch.setattr(ca.seat_map, "hay_botones", lambda bgr, ref: True)
    assert an.tick(crop()) == "turno"


def test_mientras_DURA_el_turno_no_se_vuelve_a_pedir(an, monkeypatch):
    """Se dispara por FLANCO, no por estado. Los botones siguen en pantalla todo
    el turno, y re-analizar cada 0,1 s seria peor que analizar por reloj."""
    an.watch = WatchFalso([])
    an._ref = REF
    monkeypatch.setattr(ca.seat_map, "hay_botones", lambda bgr, ref: True)
    assert an.tick(crop()) == "turno"
    assert an.tick(crop()) is None
    assert an.tick(crop()) is None


def test_al_acabar_el_turno_y_volver_se_pide_otra_vez(an, monkeypatch):
    an.watch = WatchFalso([])
    an._ref = REF
    hay = [True]
    monkeypatch.setattr(ca.seat_map, "hay_botones", lambda bgr, ref: hay[0])
    assert an.tick(crop()) == "turno"
    hay[0] = False
    assert an.tick(crop()) is None
    hay[0] = True
    assert an.tick(crop()) == "turno", "la siguiente vez que te toque"


def test_sin_botones_no_se_pide_nada(an, monkeypatch):
    an.watch = WatchFalso([])
    an._ref = REF
    monkeypatch.setattr(ca.seat_map, "hay_botones", lambda bgr, ref: False)
    assert an.tick(crop()) is None


def test_un_fallo_del_detector_no_tumba_el_lazo(an, monkeypatch):
    """El lazo rapido es una ayuda: si el detector revienta, se pierde un disparo,
    no la sesion. El latido de fondo sigue cubriendo."""
    an.watch = WatchFalso([])
    an._ref = REF
    monkeypatch.setattr(ca.seat_map, "hay_botones",
                        lambda bgr, ref: (_ for _ in ()).throw(RuntimeError("boom")))
    assert an.tick(crop()) is None


# --- EL CONTRATO ENTRE LOS DOS LAZOS ----------------------------------------
#
# Lo que el lazo rapido posee es IRREPRODUCIBLE EN FRIO: tick() solo lo llama
# gui.py, y replay.py, alpha.py y toda la suite llaman unicamente a analizar().
# Ni la regresion de oro ni replay --diff pueden volver a producirlo. Ese es el
# limite exacto de lo que puede poseer, y por eso la linea que no puede cruzar
# es la DECISION: si un tick pudiera moverla, la app tomaria en vivo decisiones
# que ninguna herramienta puede reproducir despues para averiguar por que.
#
# El nombre si se comparte, y es seguro porque no entra en la decision: solo se
# pinta (ver hand_tracker.observar_nombre).

CAMPOS_QUE_DECIDEN = ("hero_position", "to_call", "facing", "hero_cards", "board")


def test_los_ticks_NO_pueden_cambiar_la_decision(an, layout, monkeypatch):
    """N ticks entre dos analisis tienen que dar exactamente el mismo estado que
    cero ticks. Es la linea que separa "el rapido ayuda" de "el rapido manda"."""
    an.watch = WatchFalso(["UL", "MR"])
    an._ref = REF
    sin_ticks = an.analizar(crop()).state

    otro = ca.Analizador(seed_equity=1)
    otro.watch = WatchFalso(["UL", "MR"])
    otro._ref = REF
    reloj = [1000.0]
    monkeypatch.setattr(ca.time, "monotonic", lambda: reloj[0])
    anterior = ocr_client.usar_backend(lambda jobs: [tsv("pepito")] * len(jobs))
    try:
        for _ in range(8):
            reloj[0] += ca.VIGILANCIA_OCR_MIN_S * 2     # que ninguno se salte
            otro.vigilar(crop())
    finally:
        ocr_client.usar_backend(anterior)
    con_ticks = otro.analizar(crop()).state

    for campo in CAMPOS_QUE_DECIDEN:
        assert sin_ticks.get(campo) == con_ticks.get(campo), campo
    assert len(sin_ticks.get("players") or []) == len(con_ticks.get("players") or [])


def test_los_ticks_tampoco_sientan_a_nadie_en_la_mesa(an, layout, monkeypatch):
    """El caso concreto que rompe la mayoria: asientos_estables() se calcula con
    _frames, que cuenta frames LENTOS. Un asiento que solo ha visto el rapido no
    puede entrar en el conjunto estable."""
    an.watch = WatchFalso(["UL", "MR", "TOPC"])
    an._ref = REF
    an.analizar(crop())
    antes = set(an.tracker.asientos_estables())
    reloj = [1000.0]
    monkeypatch.setattr(ca.time, "monotonic", lambda: reloj[0])
    anterior = ocr_client.usar_backend(lambda jobs: [tsv("fulanito")] * len(jobs))
    try:
        for _ in range(20):
            reloj[0] += ca.VIGILANCIA_OCR_MIN_S * 2
            an.vigilar(crop())
    finally:
        ocr_client.usar_backend(anterior)
    assert set(an.tracker.asientos_estables()) == antes


# --- el LATIDO se mide, no se elige -----------------------------------------

def test_sin_medidas_el_latido_es_el_suelo():
    """Arrancar latiendo rapido no hace daño: los primeros ciclos son justo los
    que hay que medir."""
    r = ca.Ritmo()
    assert r.periodo_s == ca.PERIODO_MIN_S
    assert "midiendo" in r.etiqueta()


def test_el_latido_deja_hueco_al_ciclo_Y_a_la_vigilancia():
    """El suelo natural del latido es el propio ciclo; encima se reservan unos
    ticks, que es lo unico que justifica que el lazo rapido exista."""
    r = ca.Ritmo()
    for _ in range(20):
        r.anota(0.8)
    assert r.periodo_s == pytest.approx(
        0.8 + ca.TICKS_MIN_ENTRE_ANALISIS * ca.VIGILANCIA_PERIODO_S)


def test_manda_el_p95_y_no_el_p50():
    """Con un p50, la mitad de los analisis no cabe en su hueco y el lazo rapido
    se queda sin correr. Medido sobre las sesiones grabadas, p95/p50 va de 1,4 a
    2,1: esa dispersion es justo lo que un p50 se comeria."""
    r = ca.Ritmo()
    for _ in range(19):
        r.anota(0.5)
    r.anota(2.0)                       # un ciclo lento de cada veinte
    assert r.periodo_s > 0.5 + ca.TICKS_MIN_ENTRE_ANALISIS * ca.VIGILANCIA_PERIODO_S


def test_solo_cuentan_los_ciclos_RECIENTES():
    """Si la ventana cambia de tamaño o la maquina se carga, el ritmo tiene que
    seguirlo; una media de toda la sesion tardaria en enterarse."""
    r = ca.Ritmo()
    for _ in range(ca.RITMO_MUESTRAS * 2):
        r.anota(3.0)
    lento = r.periodo_s
    for _ in range(ca.RITMO_MUESTRAS):
        r.anota(0.4)
    assert r.periodo_s < lento
    assert r.total == ca.RITMO_MUESTRAS * 3, "se cuentan todos aunque solo pesen los ultimos"


def test_una_duracion_imposible_no_ensucia_la_medida():
    r = ca.Ritmo()
    for mala in (0, -1, None, "medio segundo"):
        r.anota(mala)
    assert r.periodo_s == ca.PERIODO_MIN_S and r.total == 0


def test_el_latido_fijo_manda_sobre_lo_medido():
    """La salida de emergencia: reproducir la cadencia de una sesion vieja. No
    esta en la ventana a proposito, solo en la linea de ordenes."""
    r = ca.Ritmo(fijo=2.5)
    for _ in range(20):
        r.anota(0.3)
    assert r.periodo_s == 2.5
    assert "latido fijo" in r.etiqueta()


def test_la_etiqueta_dice_las_tres_cifras_que_importan():
    r = ca.Ritmo()
    for _ in range(10):
        r.anota(0.7)
    txt = r.etiqueta()
    assert "0.70 s/analisis" in txt and "p95" in txt and "Hz" in txt
