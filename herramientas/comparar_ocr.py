#!/usr/bin/env python3
"""
LA VARA DE MEDIR EL OCR: tesseract contra olmOCR, sobre los frames grabados.

Es la PUERTA de la migracion a olmOCR. Mientras esto no diga que el modelo lee
mejor -y dentro de que presupuesto de tiempo-, cambiar el OCR seria cambiar la
pieza mas cara de la app a ciegas.

EL PROBLEMA DE FONDO ES EL MISMO QUE EN score_cartas.py: hay miles de frames y
CERO etiquetas. Lo que el corpus guarda como "state" no es la verdad, es lo que
leyo TESSERACT, o sea uno de los dos que se estan comparando. Puntuar contra eso
solo mediria "cuanto se parece olmOCR a tesseract", que es justo lo contrario de
lo que hace falta saber. Asi que se puntua con señales que NO DEPENDEN DE NINGUN
OCR:

  1. ESTABILIDAD DEL NICK. Un jugador no se cambia el nombre a mitad de sesion.
     Para cada asiento se toma su lectura MAYORITARIA en la sesion y se mide que
     fraccion de frames la repite. No hace falta saber cual es el nick de verdad:
     un motor que lee 'maru341' el 95% de las veces y 'aru341' el 5% es mejor que
     uno que va 60/40, y las dos cifras salen sin etiquetar nada.

  2. SALTOS IMPOSIBLES DE STACK. Un stack cambia por lo que se apuesta, y vuelve
     a subir solo ganando un bote. Que un stack pase de 196,8 a 6,8 y VUELVA a
     196,8 en el frame siguiente no es una jugada: es una lectura mala. Esta es
     la señal que caza el fallo del commit 266f72c -"tu stack se leia 6,8 donde
     ponia 196,8"- y no sale de ningun detector, sale de las reglas del juego.

  3. COBERTURA. Cuantos asientos con nombre y con stack se leen por frame. Un
     motor que se abstiene siempre no tiene saltos imposibles y no por eso es
     mejor: la abstencion tambien se paga (sin stack no hay profundidad y sin
     profundidad no hay recomendacion).

  4. LATENCIA. Va en el informe con el mismo peso que lo demas, porque de nada
     sirve leer perfecto si la recomendacion llega cuando ya has actuado.

Los DESACUERDOS se vuelcan a un JSON con la ruta del PNG de cada uno, para poder
mirarlos a ojo: cuando los dos motores dicen cosas distintas, la unica verdad
disponible es la imagen.

Uso:

    herramientas/comparar_ocr.py --n 30            # 30 frames muestreados
    herramientas/comparar_ocr.py --n 100 --semilla 42
    herramientas/comparar_ocr.py --solo-tesseract  # linea base, sin modelo

OJO CON EL TIEMPO: cada frame es una llamada al modelo, ~6,6 s en este Mac. 30
frames son ~3,5 min; 100 son ~11.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import cv2

from tests import corpus
from vision import ocr_vlm

SALIDA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "testing", "_comparar_ocr.local.json")

# Un stack que cae por debajo de esta fraccion del anterior y VUELVE a subir por
# encima de ella en el frame siguiente no es una jugada posible: no se puede
# perder el 90% del stack y recuperarlo. Es deliberadamente conservador -un
# all-in perdido y un bote ganado son cambios grandes de verdad-, asi que lo que
# cuenta aqui es la VUELTA, no la caida.
CAIDA_SOSPECHOSA = 0.5


def normalizar_nombre(n):
    """Los nicks se comparan sin acentos ni mayusculas: los dos motores difieren
    ahi de forma sistematica (tesseract pierde tildes, el modelo las pone) y esa
    diferencia no es un error de lectura del NOMBRE, que es lo que se mide."""
    if not n:
        return ""
    n = n.strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"),
                 ("ã", "a"), ("õ", "o"), ("ñ", "n"), ("ç", "c")):
        n = n.replace(a, b)
    return re.sub(r"[^a-z0-9_]", "", n)


def normalizar_importe(v):
    """'196,8 BB' -> 196.8. Devuelve None si no hay un numero dentro.

    Los estados del cliente ('Ausente', 'Sin conexion') NO son importes y se
    quedan en None a proposito: leerlos es informacion, pero como stack seria
    inventarse una profundidad."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(v).replace(".", ","))
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _de_state(state):
    jugadores = {}
    for p in state.get("players", []):
        nombre = normalizar_nombre(p.get("name"))
        if nombre:
            jugadores[nombre] = normalizar_importe(p.get("stack"))
    return {"jugadores": jugadores, "bote": normalizar_importe(state.get("pot"))}


def lectura_grabada(fr):
    """Lo que leyo tesseract EN EL MOMENTO DE GRABAR.

    OJO CON ESTO, que ya salio caro una vez: el state grabado es del commit con
    el que se jugo, no del de hoy. La sesion 2026-08-04_210545 se grabo con
    1e93ddf, o sea el commit ANTERIOR a 266f72c ("tu stack se leia 6,8 donde
    ponia 196,8"), asi que puntuar contra ella mide un tesseract que ya no
    existe y le regala a cualquier rival los fallos que se arreglaron ayer. Es
    el mismo cuidado que se toma la regresion de oro del E2E, que solo compara
    contra sesiones del MISMO commit. Para comparar de verdad: --reanalizar."""
    return _de_state(fr.state)


def lecturas_reanalizadas(frames, calentamiento=()):
    """Lo que lee tesseract HOY, volviendo a pasar los PNG por el pipeline.

    UN Analizador POR SESION y en orden, como el E2E: la memoria entre frames
    -referencia del tapete, plantilla del boton, rastreador- es de la sesion, y
    reproducir frames sueltos con un Analizador compartido daria un resultado que
    no se parece al de una partida.

    CALENTAMIENTO: reproducir un trozo suelto ARRANCA EN FRIO, y en frio la app
    lee mucho menos porque todavia no ha fijado la referencia del tapete ni sabe
    que mesa es. En vivo eso ya habia pasado hacia rato. Los frames de
    calentamiento se analizan y NO se puntuan; es lo mismo que avisa
    corpus.es_fragmento para la regresion de oro."""
    from core import Analizador
    por_sesion, salida = {}, []
    for fr in calentamiento:
        an = por_sesion.setdefault(fr.sesion, Analizador(seed_equity=1))
        try:
            an.analizar(fr.png)
        except Exception:                                   # noqa: BLE001
            pass
    for fr in frames:
        an = por_sesion.setdefault(fr.sesion, Analizador(seed_equity=1))
        t0 = time.perf_counter()
        try:
            res = an.analizar(fr.png)
            lec = _de_state(res.state)
        except Exception:                                   # noqa: BLE001
            lec = {"jugadores": {}, "bote": None}
        lec["segundos"] = time.perf_counter() - t0
        salida.append((fr, lec))
    for an in por_sesion.values():
        an.cerrar()
    return salida


def lectura_vlm(fr):
    """Lo que lee olmOCR del mismo PNG, en una sola llamada."""
    bgr = cv2.imread(fr.png)
    if bgr is None:
        return None
    r = ocr_vlm.leer_mesa(bgr)
    jugadores = {}
    for nombre, importe in r["jugadores"].items():
        clave = normalizar_nombre(nombre)
        if clave:
            jugadores[clave] = normalizar_importe(importe)
    return {"jugadores": jugadores, "bote": normalizar_importe(r["bote"]),
            "segundos": r["segundos"], "crudo": r["crudo"]}


# --- las señales que no dependen de ningun OCR -------------------------------

def estabilidad_de_nicks(lecturas_por_sesion):
    """Fraccion de apariciones que coinciden con la lectura mayoritaria.

    Se agrupa por nick "casi igual" (mismo prefijo de 4 letras y longitud
    parecida) porque justamente lo que se busca es cuantas VARIANTES de un mismo
    nombre produce cada motor: 'maru341' y 'aru341' tienen que caer en el mismo
    grupo para que se vea que uno de los dos es una variante mala."""
    familias = defaultdict(Counter)
    for jugadores in lecturas_por_sesion:
        for nombre in jugadores:
            clave = None
            for existente in familias:
                if _mismo_jugador(existente, nombre):
                    clave = existente
                    break
            familias[clave or nombre][nombre] += 1
    total = aciertos = 0
    variantes = {}
    for clave, cuenta in familias.items():
        n = sum(cuenta.values())
        mayoritaria, veces = cuenta.most_common(1)[0]
        total += n
        aciertos += veces
        if len(cuenta) > 1:
            variantes[mayoritaria] = dict(cuenta)
    return (aciertos / total if total else 0.0), variantes


def _mismo_jugador(a, b):
    if a == b:
        return True
    if abs(len(a) - len(b)) > 2:
        return False
    corto, largo = sorted((a, b), key=len)
    return corto in largo or (len(corto) >= 4 and corto[:4] == largo[:4])


def saltos_imposibles(serie):
    """Cuenta caidas grandes de stack que se DESHACEN al frame siguiente.

    serie: lista de (n_frame, stack) de UN jugador, en orden. Perder medio stack
    es normal; perderlo y recuperarlo en el frame de al lado no lo es."""
    n = 0
    for (_, a), (_, b), (_, c) in zip(serie, serie[1:], serie[2:]):
        if a and b and c and b < a * CAIDA_SOSPECHOSA and c > a * CAIDA_SOSPECHOSA:
            n += 1
    return n


def metricas(nombre_motor, lecturas):
    """lecturas: [(frame, {"jugadores": {...}, "bote": x})]"""
    por_sesion = defaultdict(list)
    series = defaultdict(list)
    con_nombre = con_stack = con_bote = 0
    for fr, lec in lecturas:
        por_sesion[fr.sesion].append(lec["jugadores"])
        con_nombre += len(lec["jugadores"])
        con_stack += sum(1 for v in lec["jugadores"].values() if v is not None)
        con_bote += 1 if lec["bote"] is not None else 0
        for nombre, stack in lec["jugadores"].items():
            series[(fr.sesion, nombre)].append((fr.n, stack))

    estabilidad, variantes = 0.0, {}
    pesos = 0
    for sesion, lista in por_sesion.items():
        e, v = estabilidad_de_nicks(lista)
        peso = sum(len(x) for x in lista)
        estabilidad += e * peso
        pesos += peso
        variantes.update(v)
    estabilidad = estabilidad / pesos if pesos else 0.0

    saltos = sum(saltos_imposibles(sorted(s)) for s in series.values())
    frames = len(lecturas) or 1
    return {
        "motor": nombre_motor,
        "frames": len(lecturas),
        "nombres_por_frame": round(con_nombre / frames, 2),
        "stacks_por_frame": round(con_stack / frames, 2),
        "frames_con_bote": f"{con_bote}/{len(lecturas)}",
        "estabilidad_nick": round(estabilidad, 3),
        "variantes_de_nick": variantes,
        "saltos_imposibles": saltos,
    }


def informe(m):
    print(f"\n  {m['motor']}")
    print(f"    nombres leidos por frame ....... {m['nombres_por_frame']}")
    print(f"    stacks leidos por frame ........ {m['stacks_por_frame']}")
    print(f"    frames con bote ................ {m['frames_con_bote']}")
    print(f"    estabilidad del nick ........... {m['estabilidad_nick']:.1%}"
          f"  ({len(m['variantes_de_nick'])} nicks con variantes)")
    print(f"    saltos imposibles de stack ..... {m['saltos_imposibles']}")
    for bueno, cuenta in list(m["variantes_de_nick"].items())[:6]:
        print(f"       {bueno}: {cuenta}")


def frames_seguidos(n, semilla=None, calentamiento=0):
    """N frames CONSECUTIVOS de una sesion, no una muestra dispersa.

    Hace falta para la señal 2 (saltos imposibles de stack): entre dos frames
    muestreados al azar pueden haber pasado diez manos, y entonces cualquier
    cambio de stack es posible y la señal no dice nada. Entre dos frames seguidos
    -0,1 s de diferencia- un stack que baja a la decima parte y vuelve solo puede
    ser una lectura mala."""
    import random
    todos = [fr for fr in corpus.todos(exigir_png=True)]
    por_sesion = defaultdict(list)
    for fr in todos:
        por_sesion[fr.sesion].append(fr)
    if not por_sesion:
        return []
    rnd = random.Random(semilla)
    sesion = rnd.choice(sorted(por_sesion))
    lista = sorted(por_sesion[sesion], key=lambda f: f.n)
    if len(lista) <= n:
        return [], lista
    desde = rnd.randrange(calentamiento, len(lista) - n)
    return lista[max(0, desde - calentamiento):desde], lista[desde:desde + n]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--n", type=int, default=30, help="frames a muestrear")
    ap.add_argument("--semilla", type=int, default=None)
    ap.add_argument("--modo", choices=("estratificado", "seguidos"),
                    default="estratificado",
                    help="estratificado: variedad de casos (cobertura y nicks). "
                         "seguidos: frames consecutivos de una sesion, que es lo "
                         "unico con lo que la continuidad de stack significa algo")
    ap.add_argument("--solo-tesseract", action="store_true",
                    help="linea base sin llamar al modelo")
    ap.add_argument("--calentar", type=int, default=60,
                    help="frames previos que se analizan SIN puntuar, para que "
                         "el trozo no arranque en frio (solo con --modo seguidos "
                         "y --reanalizar)")
    ap.add_argument("--reanalizar", action="store_true",
                    help="vuelve a pasar los PNG por el pipeline de HOY en vez "
                         "de leer el state grabado. Es lo unico honesto si la "
                         "sesion se grabo con otro commit")
    args = ap.parse_args()

    if not args.solo_tesseract:
        ok, motivo = ocr_vlm.disponible()
        if not ok:
            print(f"No hay modelo de vision: {motivo}")
            print("Arrancalo con:  ollama serve  &&  ollama pull "
                  + ocr_vlm.MODELO)
            return 1

    calentamiento = []
    if args.modo == "seguidos":
        calentamiento, frames = frames_seguidos(args.n, semilla=args.semilla,
                                                calentamiento=args.calentar)
    else:
        frames = corpus.muestrear(n=args.n, semilla=args.semilla, volcar=False)
    if not frames:
        print(f"no hay frames con PNG en {corpus.RAIZ}")
        return 1
    frames.sort(key=lambda f: (f.sesion, f.n))
    print(f"{len(frames)} frames ({args.modo}) de "
          f"{len({f.sesion for f in frames})} sesiones")

    # SI LA SESION ES DE OTRO COMMIT, comparar contra lo grabado mide un
    # tesseract que ya no existe. Se avisa fuerte porque el aviso es justo lo que
    # falto la primera vez que se corrio esto.
    ahora = corpus.commit_actual()
    otros = sorted({fr.commit for fr in frames if fr.commit and fr.commit != ahora})
    if otros and not args.reanalizar:
        print(f"\n  AVISO: hay frames grabados con {', '.join(otros)} y el arbol "
              f"esta en {ahora}.\n  Lo grabado NO es el tesseract de hoy: usa "
              f"--reanalizar o estaras midiendo fallos ya arreglados.\n")

    if args.reanalizar:
        print(f"  reanalizando con el pipeline de hoy "
              f"({len(calentamiento)} frames de calentamiento sin puntuar)...",
              file=sys.stderr)
        tess = lecturas_reanalizadas(frames, calentamiento)
    else:
        tess = [(fr, lectura_grabada(fr)) for fr in frames]

    vlm, desacuerdos, tiempos = [], [], []
    if not args.solo_tesseract:
        for i, fr in enumerate(frames):
            lec = lectura_vlm(fr)
            if lec is None:
                continue
            vlm.append((fr, lec))
            tiempos.append(lec["segundos"])
            print(f"\r  {i + 1}/{len(frames)}  {lec['segundos']:.1f}s  "
                  f"{len(lec['jugadores'])} nameplates", end="", file=sys.stderr)
            g = dict(tess[i][1]["jugadores"])
            v = lec["jugadores"]
            solo_v = {k: v[k] for k in v if k not in g}
            solo_g = {k: g[k] for k in g if k not in v}
            distintos = {k: [g[k], v[k]] for k in g if k in v and g[k] != v[k]}
            if solo_v or solo_g or distintos:
                desacuerdos.append({
                    "frame": fr.id, "png": fr.png,
                    "solo_olmocr": solo_v, "solo_tesseract": solo_g,
                    "stack_distinto": distintos,
                    "bote": [tess[i][1]["bote"], lec["bote"]],
                })
        print(file=sys.stderr)

    print("\n" + "=" * 66)
    m_tess = metricas("tesseract " + ("(reanalizado con el codigo de hoy)"
                                      if args.reanalizar else "(lo grabado en vivo)"),
                      tess)
    if args.reanalizar:
        t = sorted(l["segundos"] for _f, l in tess)
        print(f"\n  ciclo completo con tesseract: p50 {t[len(t)//2]:.2f}s  "
              f"p95 {t[max(0, int(len(t)*0.95)-1)]:.2f}s")
    informe(m_tess)
    resultado = {"frames": len(frames), "tesseract": m_tess}

    if vlm:
        m_vlm = metricas(f"olmOCR ({ocr_vlm.MODELO.split('/')[-1]})", vlm)
        informe(m_vlm)
        tiempos.sort()
        p50 = tiempos[len(tiempos) // 2]
        p95 = tiempos[max(0, int(len(tiempos) * 0.95) - 1)]
        print(f"    latencia por frame ............. p50 {p50:.1f}s  p95 {p95:.1f}s")
        print(f"\n  desacuerdos en {len(desacuerdos)}/{len(vlm)} frames "
              f"(volcados en {os.path.relpath(SALIDA)})")
        resultado["olmocr"] = m_vlm
        resultado["latencia_s"] = {"p50": p50, "p95": p95}
        resultado["desacuerdos"] = desacuerdos

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w") as f:
        json.dump(resultado, f, indent=1, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
