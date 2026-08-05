"""
El corpus de regresion: los frames que la app ya ha grabado jugando de verdad.

NO SE VERSIONA NADA. Ni imagenes ni estados: el corpus no es una carpeta de
fixtures sino una SELECCION que se recalcula en cada ejecucion sobre lo que haya
en testing/. Son 26 sesiones y ~9.200 frames, 14 GB en disco; meter aunque sea
una fraccion en git multiplicaria el repo por cien para congelar unos frames que
mañana estaran peor elegidos que los de la sesion de esta noche.

MUESTREO ESTRATIFICADO, no los primeros N. Una sesion son cientos de frames casi
identicos: coger los 500 primeros seria mirar cinco minutos de una partida y
dejar fuera el bote dividido, las cartas apagadas, el mazo de glifo y la mitad de
los motivos de abstencion. `estratos()` etiqueta cada frame por lo que TIENE de
interesante y el reparto da cuota a cada etiqueta, empezando por las raras.

REPRODUCIBILIDAD. La seleccion va sembrada y cada pasada vuelca
testing/_seleccion.local.json con exactamente que frames tocaron, asi que un test
rojo se puede repetir tal cual con --corpus-seleccion. Sin eso, un fallo sobre
una muestra distinta cada vez no habria forma de perseguirlo.
"""
import glob
import json
import os
import random
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass

RAIZ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "testing")
SELECCION = os.path.join(RAIZ, "_seleccion.local.json")

# Cuantos frames por defecto. 500 es lo que cabe en un E2E de unos minutos a
# ~0,55 s/frame; los tests de solo-JSON no muestrean, recorren los 9.200.
N_POR_DEFECTO = 500


@dataclass(frozen=True)
class Frame:
    """Un frame grabado: la imagen y TODO lo que la app calculo de ella."""
    sesion: str
    n: int
    png: str
    ruta_json: str
    datos: dict
    commit: str | None = None      # con que version del codigo se grabo
    # LA CARPETA, para poder leer su _sesion.json. Hace falta porque reproducir
    # el frame necesita la MISMA disposicion de mesa con la que se grabo: desde
    # que hay tablas de 8 y 9 plazas, max_players elige la geometria.
    carpeta: str = ""

    @property
    def state(self):
        return self.datos.get("state") or {}

    @property
    def recommendation(self):
        return self.datos.get("recommendation")

    @property
    def id(self):
        return f"{self.sesion}/{self.n:04d}"


def commit_actual():
    """El commit del arbol de trabajo, o None si no se puede saber."""
    try:
        out = subprocess.run(["git", "-C", os.path.dirname(RAIZ), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def meta_de_sesion(carpeta, _cache={}):
    """El _sesion.json de una sesion: commit, max_players, recuadro, intervalo.

    HACE FALTA PARA REPRODUCIRLA. `max_players` no es solo un tope de asientos:
    desde que hay tablas de 8 y 9 plazas, ELIGE LA GEOMETRIA (seat_map.zonas).
    Reproducir una sesion de 9 con la disposicion de 6 no compara la app contra
    si misma, compara dos apps distintas, y eso es lo que rompio la regresion de
    oro en cuanto se grabo la primera sesion de 9: 4 tests rojos sin que nada
    estuviera mal."""
    if carpeta not in _cache:
        try:
            with open(os.path.join(carpeta, "_sesion.json")) as f:
                _cache[carpeta] = json.load(f) or {}
        except (OSError, ValueError):
            _cache[carpeta] = {}
    return _cache[carpeta]


def plataforma_de_sesion(carpeta):
    """En que sistema se grabo una sesion ("linux", "darwin"...).

    LAS SESIONES ANTIGUAS NO LO GUARDAN, y para ellas la respuesta es "linux":
    todo lo que hay grabado hasta el 05-08-2026 se jugo en la maquina de Linux,
    que era la unica que ejecutaba la app. A partir de ahi lo escribe
    testing_session (meta["plataforma"]).
    """
    return meta_de_sesion(carpeta).get("plataforma", "linux")


def plataforma_actual():
    return sys.platform


def _commit_de_sesion(carpeta):
    """El commit con el que se grabo una sesion.

    Sirve para separar lo que se puede comparar CAMPO A CAMPO -las sesiones
    grabadas con este mismo codigo- de lo que no: una sesion de hace tres
    commits difiere legitimamente y compararla seria un test que falla por haber
    arreglado algo."""
    return meta_de_sesion(carpeta).get("commit")


def sesiones(raiz=RAIZ):
    return sorted(d for d in glob.glob(os.path.join(raiz, "*"))
                  if os.path.isdir(d) and os.path.basename(d)[0] != "_")


def es_fragmento(frames):
    """¿Estos frames son un TROZO suelto sacado de mitad de una sesion?

    Importa para todo lo que REPRODUZCA los frames en frio. Reproducir una sesion
    entera es la misma cuenta que la original: el Analizador arranca vacio igual
    que arranco alli y va acumulando lo mismo. Reproducir un trozo NO lo es, y no
    hay forma de arreglarlo: al analisis le falta la historia que tenia delante
    -el voto de asientos, el del boton, los nombres, la referencia fijada-, asi
    que puede dar otro resultado sin que nada este roto.

    EL CASO: las carpetas notas-* guardan UN frame, el que el usuario marco
    mientras jugaba. La regresion de oro las comparaba y una fallaba siempre
    (hero_position 'SB' grabado contra 'BTN' reproducido). Un test que no puede
    pasar nunca no protege nada: acaba tapando una regresion de verdad.

    Se detecta por el numero de MANO del primer frame, no por el nombre de la
    carpeta. Toda sesion de verdad empieza en la mano 1 -el rastreador arranca
    ahi-, asi que un primer frame que ya dice mano 8 o mano 16 esta declarando
    por si solo que hubo analisis antes que aqui no esta. Medido sobre el corpus:
    las 9 sesiones empiezan en la mano 1, y las 2 notas en la 8 y la 16."""
    if not frames:
        return False
    primero = min(frames, key=lambda f: f.n)
    mano = (primero.state or {}).get("mano_seguida")
    return isinstance(mano, int) and mano > 1


def _cargar(ruta_json, exigir_png=True):
    n = int(os.path.basename(ruta_json)[:-5])
    carpeta = os.path.dirname(ruta_json)
    png = os.path.join(carpeta, f"{n:04d}.png")
    if exigir_png and not os.path.exists(png):
        return None            # hubo sesiones en que fallo la escritura del PNG
    try:
        with open(ruta_json) as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None            # se estaba escribiendo, o quedo truncado
    return Frame(sesion=os.path.basename(carpeta), n=n, png=png, carpeta=carpeta,
                 ruta_json=ruta_json, datos=datos,
                 commit=_commit_de_sesion(carpeta))


def todos(raiz=RAIZ, exigir_png=False):
    """Todos los frames grabados. Sin exigir_png sirve para los tests de solo
    JSON, que son los que pueden permitirse recorrer el corpus entero."""
    out = []
    for d in sesiones(raiz):
        for ruta in sorted(glob.glob(os.path.join(d, "[0-9]*.json")),
                           key=lambda p: int(os.path.basename(p)[:-5])):
            fr = _cargar(ruta, exigir_png=exigir_png)
            if fr is not None:
                out.append(fr)
    return out


def estratos(fr):
    """Que tiene ESTE frame de interesante. Un frame puede caer en varios.

    Las etiquetas son el espacio de comportamiento que el corpus tiene que
    cubrir: si una no aparece en la muestra, hay una rama de la app que los tests
    de imagen no ejercitan."""
    st, rec = fr.state, fr.recommendation
    res = fr.datos.get("hand_result") or {}
    etiquetas = set()

    board = st.get("board") or []
    etiquetas.add(f"board_{len(board)}" if len(board) in (0, 3, 4, 5) else "board_ilegal")
    etiquetas.add("facing_" + str(st.get("facing")))

    if st.get("hero_cards_dimmed"):
        etiquetas.add("cartas_apagadas")
    if len(st.get("hero_cards") or []) == 2:
        etiquetas.add("hero_con_cartas")
    if st.get("posiciones_asentadas") is False:
        etiquetas.add("posiciones_sin_asentar")
    if st.get("to_call"):
        etiquetas.add("con_to_call")
    if (st.get("acciones") or {}).get("acciones"):
        etiquetas.add("con_historial_de_acciones")

    vivos = sum(1 for p in st.get("players") or [] if p.get("in_hand"))
    if vivos >= 3:
        etiquetas.add("multiway")

    if res.get("split"):
        etiquetas.add("bote_dividido")
    elif res.get("winner"):
        etiquetas.add("mano_resuelta")

    if rec:
        etiquetas.add("con_recomendacion")
        etiquetas.add("facing_usado_" + str(rec.get("facing_used")))
        if rec.get("source") == "derived":
            etiquetas.add("recomendacion_derivada")
        if rec.get("extrapolated") or "extrapolad" in str(rec.get("reasoning", "")):
            etiquetas.add("stack_extrapolado")
    else:
        motivo = (st.get("warnings") or ["sin_motivo"])[-1]
        etiquetas.add("abstiene:" + str(motivo)[:45])

    if fr.datos.get("equity"):
        etiquetas.add("con_equity")
    return etiquetas


def muestrear(n=N_POR_DEFECTO, semilla=None, raiz=RAIZ, volcar=True):
    """`n` frames estratificados por `estratos()`, con su PNG en disco.

    El reparto va de la etiqueta MAS RARA a la mas comun y cada una se lleva su
    cuota de entre los frames que aun no han entrado, asi que un caso que solo
    aparece dos veces en 9.200 frames entra seguro y uno que aparece en 6.000 no
    se come la muestra."""
    poblacion = todos(raiz, exigir_png=True)
    if not poblacion:
        return []
    if n >= len(poblacion):
        return poblacion

    rng = random.Random(semilla)
    por_etiqueta = defaultdict(list)
    for fr in poblacion:
        for e in estratos(fr):
            por_etiqueta[e].append(fr)

    # cuota base para que ninguna etiqueta se quede fuera, y el resto proporcional
    orden = sorted(por_etiqueta, key=lambda e: len(por_etiqueta[e]))
    base = max(1, n // (len(orden) * 3))
    elegidos, vistos = [], set()
    for etiqueta in orden:
        disponibles = [f for f in por_etiqueta[etiqueta] if f.id not in vistos]
        if not disponibles:
            continue
        cuota = min(len(disponibles), base, max(0, n - len(elegidos)))
        for fr in rng.sample(disponibles, cuota):
            elegidos.append(fr)
            vistos.add(fr.id)
        if len(elegidos) >= n:
            break

    # lo que falte hasta n, al azar entre el resto: la cobertura ya esta cubierta
    resto = [f for f in poblacion if f.id not in vistos]
    if len(elegidos) < n and resto:
        for fr in rng.sample(resto, min(n - len(elegidos), len(resto))):
            elegidos.append(fr)
            vistos.add(fr.id)

    elegidos.sort(key=lambda f: (f.sesion, f.n))
    if volcar:
        _volcar(elegidos, semilla, raiz)
    return elegidos


def _volcar(frames, semilla, raiz):
    """Deja constancia de que frames tocaron, para poder repetir la ejecucion.

    Un fallo sobre una muestra distinta cada vez no se puede perseguir."""
    try:
        with open(os.path.join(raiz, "_seleccion.local.json"), "w") as f:
            json.dump({"semilla": semilla, "n": len(frames),
                       "frames": [[fr.sesion, fr.n] for fr in frames]}, f, indent=1)
    except OSError:
        pass                    # dejar constancia es una ayuda, no un requisito


def cargar_seleccion(ruta, raiz=RAIZ):
    """Los frames de una seleccion volcada antes, para repetir una ejecucion."""
    with open(ruta) as f:
        datos = json.load(f)
    out = []
    for sesion, n in datos["frames"]:
        fr = _cargar(os.path.join(raiz, sesion, f"{n:04d}.json"))
        if fr is not None:
            out.append(fr)
    return out


def resumen(frames):
    """Cuantos frames cubren cada etiqueta. Para poder mirar de un vistazo si la
    muestra deja alguna rama sin ejercitar."""
    cuenta = defaultdict(int)
    for fr in frames:
        for e in estratos(fr):
            cuenta[e] += 1
    return dict(sorted(cuenta.items(), key=lambda kv: -kv[1]))
