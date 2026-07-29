"""
Grabacion de sesiones de TESTING: guarda cada frame analizado junto con TODO lo
que la app calculo a partir de el, emparejados por nombre, para poder revisar
despues por que la app dijo lo que dijo y seguir ajustandola.

    testing/sesion-2026-07-25_193012/
        _sesion.json      metadatos de la sesion (inicio, intervalo, recuadro, commit)
        _notas.jsonl      indice de los momentos que el usuario marco (si hay)
        0001.png          el frame tal cual se analizo
        0001.json         todo lo calculado de ESE frame
        0002.png
        0002.json
        ...

La dupla es por NOMBRE (mismo numero, distinta extension), que es lo que hace que
se pueda abrir el PNG y el JSON de al lado sin tener que cruzar timestamps.

Que va en el JSON de cada frame: el GameState completo -incluidos los warnings,
que suelen ser lo mas informativo cuando algo sale mal-, la recomendacion o el
motivo de abstenerse, la evaluacion de mano, el resumen de la mano anterior leido
del chat, y la equity postflop. La equity se calcula AQUI aunque todavia no se
muestre en el HUD: es justo el numero que hay que contrastar contra frames reales
antes de enseñarlo, asi que grabarlo es el paso previo a cablearlo.

NOTAS. `anotar()` pega un texto del usuario a un frame ya guardado. Son las
etiquetas que le faltan al proyecto: cada una es un caso real, elegido porque
algo no cuadraba, con el frame y el estado calculado al lado.

Este modulo no importa GTK a proposito: asi se puede grabar y revisar una sesion
desde un script sin levantar la ventana, y se puede testear.
"""
import json
import os
import subprocess
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TESTING_DIR = os.path.join(BASE_DIR, "testing")


def _commit_actual():
    """Hash corto del commit, para saber con que version se grabo la sesion.
    None si no se puede averiguar (no es un repo, git no esta, etc.)."""
    try:
        out = subprocess.run(["git", "-C", BASE_DIR, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def _serializable(obj):
    """Convierte a algo que json pueda escribir. Los GameState traen numpy
    (float32 de los importes en BB, int de las areas), que json no sabe volcar;
    perder la sesion entera por eso seria absurdo."""
    if isinstance(obj, dict):
        return {str(k): _serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_serializable(v) for v in obj]
    if isinstance(obj, (str, bool, int, float)) or obj is None:
        return obj
    for attr in ("item", "tolist"):          # numpy escalares y arrays
        if hasattr(obj, attr):
            try:
                return _serializable(getattr(obj, attr)())
            except Exception:  # noqa: BLE001
                pass
    return str(obj)


class TestingSession:
    """Una carpeta de sesion. Se crea al empezar a grabar y se cierra al parar.

    Ningun fallo escribiendo debe tumbar el analisis en vivo: si un frame no se
    puede guardar se cuenta como error y se sigue. Grabar es una ayuda, no la
    funcion de la app.
    """

    def __init__(self, interval=None, region=None, root=None, now=None, prefix="sesion"):
        marca = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(now or time.time()))
        self.dir = os.path.join(root or TESTING_DIR, f"{prefix}-{marca}")
        os.makedirs(self.dir, exist_ok=True)
        self.n = 0
        self.errores = 0
        self.notas = []          # numeros de frame que el usuario marco
        self._t0 = time.time()
        # guardar se llama desde el hilo de analisis y anotar desde el hilo de la
        # UI (el usuario pulsa "Marcar situacion" mientras el lazo sigue). Sin el
        # candado, dos self.n += 1 a la vez darian el mismo numero y una dupla
        # pisaria a la otra, y dos volcados simultaneos de _sesion.json podrian
        # entrelazarse y dejarlo corrupto. NO es reentrante a proposito: ningun
        # metodo lo toma dos veces (los que llaman a _escribir_meta lo hacen
        # SIEMPRE fuera de su propio with).
        self._lock = threading.Lock()
        self.meta = {
            "inicio": marca,
            "intervalo_s": interval,
            "recuadro": region,
            "commit": _commit_actual(),
        }
        self._escribir_meta()

    def _escribir_meta(self):
        with self._lock:
            self.meta["frames"] = self.n
            self.meta["errores"] = self.errores
            self.meta["notas"] = list(self.notas)
            self.meta["duracion_s"] = round(time.time() - self._t0, 1)
            try:
                with open(os.path.join(self.dir, "_sesion.json"), "w") as fh:
                    json.dump(_serializable(self.meta), fh, ensure_ascii=False, indent=2)
            except OSError:
                pass

    def guardar(self, crop, datos, write_png):
        """Guarda la dupla PNG + JSON de un frame. `write_png(ruta)` es quien
        escribe la imagen (lo hace el llamador para no traer opencv aqui).
        Devuelve el numero de frame, o None si no se pudo guardar."""
        with self._lock:
            self.n += 1
            n = self.n
        stem = f"{n:04d}"
        try:
            write_png(os.path.join(self.dir, stem + ".png"))
            payload = {"n": n, "t": time.time(),
                       "hora": time.strftime("%H:%M:%S"), "png": stem + ".png"}
            payload.update(datos)
            with open(os.path.join(self.dir, stem + ".json"), "w") as fh:
                json.dump(_serializable(payload), fh, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001 - grabar nunca debe tumbar el analisis
            with self._lock:
                self.errores += 1
            return None
        if n % 10 == 0:
            self._escribir_meta()
        return n

    def anotar(self, n, texto):
        """Pega una nota escrita por el usuario al frame `n`, que ya tiene que
        estar guardado. Devuelve True si se pudo escribir dentro del JSON.

        Se escribe en DOS sitios a proposito:
          - dentro del JSON del frame, para que la dupla siga siendo
            autocontenida: se abre el PNG y al lado esta TODO, nota incluida;
          - y en el indice `_notas.jsonl` de la sesion, para ver de un vistazo
            todos los momentos marcados sin abrir frame por frame.

        Releer-modificar-reescribir el JSON es aceptable porque son ficheros de
        ~2 KB y las notas van a ritmo humano, no una por frame.

        Un fallo aqui no tumba nada: la nota es una ayuda para revisar despues.
        """
        texto = (texto or "").strip()
        if not texto or not n:
            return False
        ruta = os.path.join(self.dir, f"{n:04d}.json")
        ok = False
        try:
            with open(ruta) as fh:
                datos = json.load(fh)
            # varias notas sobre el mismo frame se acumulan, no se pisan
            anterior = datos.get("nota")
            datos["nota"] = f"{anterior}\n{texto}" if anterior else texto
            with open(ruta, "w") as fh:
                json.dump(datos, fh, ensure_ascii=False, indent=2)
            ok = True
        except (OSError, ValueError):
            pass
        try:
            with open(os.path.join(self.dir, "_notas.jsonl"), "a") as fh:
                fh.write(json.dumps({"n": n, "png": f"{n:04d}.png", "t": time.time(),
                                     "hora": time.strftime("%H:%M:%S"), "nota": texto},
                                    ensure_ascii=False) + "\n")
        except OSError:
            pass
        with self._lock:
            if n not in self.notas:
                self.notas.append(n)
        self._escribir_meta()
        return ok

    def cerrar(self):
        self._escribir_meta()
        return self.dir


def resumen(directorio):
    """Lee una carpeta de sesion y devuelve un resumen agregado, para saber de un
    vistazo que dio esa sesion sin abrir los frames uno a uno."""
    frames = sorted(f for f in os.listdir(directorio)
                    if f.endswith(".json") and not f.startswith("_"))
    total = len(frames)
    con_cartas = con_reco = postflop = con_equity = 0
    motivos = {}
    notas = []
    # acciones vistas por mano: es LA medida de si la vigilancia rapida cumple.
    # La referencia con muestreo de 1,48 s eran 5,7 por mano, y una mano de 3-max
    # tiene tipicamente 4-8 acciones.
    manos = set()
    acciones_max = {}
    vigilancia = {}
    ciclos = []
    etapas = {}
    for nombre in frames:
        try:
            with open(os.path.join(directorio, nombre)) as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        st = d.get("state") or {}
        if len(st.get("hero_cards") or []) == 2:
            con_cartas += 1
        if d.get("recommendation"):
            con_reco += 1
        if st.get("board"):
            postflop += 1
        if d.get("equity"):
            con_equity += 1
        if not d.get("recommendation"):
            for w in (st.get("warnings") or [])[-1:]:
                motivos[w] = motivos.get(w, 0) + 1
        # las notas se leen de los frames y no de _notas.jsonl: dentro del frame
        # es donde son autoritativas (el indice es una comodidad, y puede faltar
        # si fallo su escritura). Es lo mas valioso de una sesion, asi que van
        # enteras en el resumen, no contadas.
        if d.get("nota"):
            notas.append({"n": d.get("n"), "png": d.get("png"), "hora": d.get("hora"),
                          "nota": d["nota"]})
        if d.get("duracion_analisis_s"):
            ciclos.append(d["duracion_analisis_s"])
        # desglose por etapa (ver table_state._Reloj). Se acumula por etapa para
        # poder decir DONDE se va el tiempo, que es lo unico que permite juzgar
        # una optimizacion. Las sesiones grabadas antes de que existiera el reloj
        # no traen la clave y simplemente no aportan.
        for etapa, seg in (st.get("tiempos") or {}).items():
            etapas.setdefault(etapa, []).append(seg)
        mano = st.get("mano_seguida")
        if mano is not None:
            manos.add(mano)
            # solo si el frame TRAE el historial. Una sesion grabada antes de que
            # existiera no tiene la clave, y contarla como 0 acciones diria "no se
            # vio nada" cuando lo cierto es "no se midio": son cosas distintas y
            # confundirlas haria creer que hay una regresion donde no la hay.
            if "acciones" in st:
                acc = (st.get("acciones") or {}).get("acciones") or []
                # se queda el maximo por mano: el historial CRECE dentro de la
                # mano, asi que el ultimo frame de cada una es el que la resume
                acciones_max[mano] = max(acciones_max.get(mano, 0), len(acc))
        if st.get("vigilancia"):
            vigilancia = st["vigilancia"]
    return {
        "directorio": directorio,
        "frames": total,
        "con_2_cartas": con_cartas,
        "con_recomendacion": con_reco,
        "postflop": postflop,
        "con_equity": con_equity,
        "motivos_de_abstencion": dict(sorted(motivos.items(), key=lambda kv: -kv[1])),
        "notas": notas,
        "manos": len(manos),
        "acciones_por_mano": (round(sum(acciones_max.values()) / len(acciones_max), 1)
                              if acciones_max else None),
        "vigilancia": vigilancia,
        "ciclo_medio_s": round(sum(ciclos) / len(ciclos), 2) if ciclos else None,
        # LA MEDIANA NO BASTA. El hueco entre analisis es donde vive el lazo
        # rapido, y lo que decide si cabe es el p95, no el p50: medido sobre
        # cinco sesiones, el p95 va de 1,4x a 2,1x la mediana. Con el p50 la
        # mitad de los frames se queda sin hueco.
        "ciclo_p50_s": _percentil(ciclos, 50),
        "ciclo_p95_s": _percentil(ciclos, 95),
        # donde se va el tiempo, por etapa (ver table_state._Reloj)
        "etapas_p50_s": {k: _percentil(v, 50) for k, v in sorted(etapas.items())},
    }


def _percentil(valores, q):
    """Percentil por interpolacion nula (el elemento, no una media entre dos).

    Sin numpy a proposito: este modulo lo importa la GUI y no tiene por que
    arrastrar la dependencia solo para esto."""
    if not valores:
        return None
    orden = sorted(valores)
    i = min(len(orden) - 1, int(len(orden) * q / 100))
    return round(orden[i], 3)
