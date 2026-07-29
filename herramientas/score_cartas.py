#!/usr/bin/env python3
"""
LA VARA DE MEDIR EL RECONOCIMIENTO DE CARTAS.

docs/PENDIENTE.md lo pedia asi: "Falta un score_samples.py que compare contra
etiquetas y diga si un cambio de umbral mejora o rompe. Sin eso no se pueden
tocar con seguridad los ~15 umbrales". Esto es eso.

EL PROBLEMA DE FONDO: hay ~15.000 frames grabados y CERO etiquetas. Etiquetar a
mano es caro, y etiquetar con el propio detector seria fijar su error en piedra
(el mismo argumento por el que el atlas de glifos se etiqueto a ojo a proposito;
ver vision/color_rank_ocr). Asi que la puntuacion sale de señales que NO
DEPENDEN DEL DETECTOR:

  1. CONSISTENCIA CONSIGO MISMO. Dentro de una mano el board solo añade cartas y
     las del hero no cambian. Que una carta ya vista desaparezca o mute no puede
     pasar en el juego: es siempre un fallo de lectura. No hace falta saber que
     carta era.

  2. LAS REGLAS DEL JUEGO. Un board tiene 0, 3, 4 o 5 cartas; ninguna carta esta
     en dos sitios a la vez ni repetida.

  3. EL REPARTO DE RANGOS. En un mazo justo cada rango es el 7,7% y las figuras
     el 23,1%. Una desviacion grande en una sesion larga no es mala suerte: es un
     rango que no se sabe leer. Asi se cazo que J/Q/K eran el 3,6% con el mazo
     de figuras ilustradas.

  4. EL CHAT, que es la unica ETIQUETA DE VERDAD y ademas gratis: el cliente
     escribe "9Bicho tiene doble pareja, dieces y cuatros", y eso lo produce
     PokerStars, no el detector. Ver _contradice_al_chat para el criterio exacto
     y por que es una comprobacion de una sola direccion.

Uso:

    herramientas/score_cartas.py                      # todas las sesiones, de los JSON
    herramientas/score_cartas.py testing/sesion-XXX   # una
    herramientas/score_cartas.py --reanalizar         # re-ejecuta el pipeline

SIN --reanalizar puntua LO GRABADO, o sea el codigo que habia cuando se grabo.
Sirve de linea base y es instantaneo. CON --reanalizar vuelve a pasar las
imagenes por el pipeline actual, que es lo que hace falta para responder "¿mi
cambio de umbral mejora o rompe?". Es lento (~0,6 s por frame), asi que se
combina con --muestra.
"""
import argparse
import glob
import json
import os
import random
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import invariantes as inv          # noqa: E402

RANGOS = "23456789TJQKA"
FIGURAS = "JQK"
FRAC_JUSTA = 1 / 13
FRAC_FIGURAS = 3 / 13

# Como nombra el cliente cada rango en castellano. El plural es lo que aparece en
# "pareja de X" / "trio de X"; el singular suelto no se usa para nada aqui.
NOMBRE_A_RANGO = {
    "doses": "2", "treses": "3", "cuatros": "4", "cincos": "5", "seises": "6",
    "sietes": "7", "ochos": "8", "nueves": "9", "dieces": "T",
    "jotas": "J", "jacks": "J", "damas": "Q", "reinas": "Q",
    "reyes": "K", "ases": "A",
}
# cuantas cartas del mismo rango implica cada jugada nombrada
CUANTAS = {"pareja": 2, "doble pareja": 2, "trio": 3, "poker": 4}


def _rangos_nombrados(frase):
    """[(rango, cuantas)] que la frase del chat afirma. Lista vacia si la frase
    no nombra ninguna jugada por rango (color, escalera, carta alta...)."""
    if not frase:
        return []
    f = frase.lower().replace("í", "i").replace("ó", "o").replace("é", "e")
    cuantas = None
    for jugada, n in CUANTAS.items():
        if jugada in f:
            cuantas = n if cuantas is None else max(cuantas, n)
    if cuantas is None:
        return []
    return [(NOMBRE_A_RANGO[p], cuantas)
            for p in re.findall(r"[a-z]+", f) if p in NOMBRE_A_RANGO]


def _contradice_al_chat(board, frase):
    """¿El board leido contradice lo que el cliente escribio en el chat?

    ES UNA COMPROBACION DE UNA SOLA DIRECCION, y por eso es solida. Si el chat
    dice "doble pareja, dieces y cuatros", el ganador tiene DOS dieces; el board
    puede aportar cero, uno o los dos, pero NO PUEDE APORTAR TRES, porque
    entonces el ganador tendria trio y el cliente habria escrito "trio". Asi que:

        board.count(rango) > cuantas   ->   el detector se invento una carta

    Al reves no vale: que el board no tenga ningun diez es perfectamente normal
    (los dos van en la mano del ganador, que no se ve). Por eso no se cuenta como
    fallo, aunque sea tentador.

    Vale igual quien gane, no hace falta que sea el hero, que es lo que la hace
    util: el chat nombra la jugada ganadora de cualquiera."""
    for rango, cuantas in _rangos_nombrados(frase):
        if sum(1 for c in board if c and c[0].upper() == rango) > cuantas:
            return True
    return False


def _frames_grabados(carpeta):
    for ruta in sorted(glob.glob(os.path.join(carpeta, "[0-9]*.json")),
                       key=lambda p: int(os.path.basename(p)[:-5])):
        try:
            with open(ruta) as f:
                yield json.load(f)
        except (OSError, ValueError):
            continue                       # se estaba escribiendo, o quedo truncado


def _frames_reanalizados(carpeta, muestra, semilla):
    from core.analisis import Analizador
    pngs = sorted(glob.glob(os.path.join(carpeta, "[0-9]*.png")),
                  key=lambda p: int(os.path.basename(p)[:-4]))
    if muestra and len(pngs) > muestra:
        # LA MUESTRA ES UN TROZO SEGUIDO DESDE EL PRINCIPIO, no uno de cada N.
        # Dos motivos, y el primero lo descubrio esta misma herramienta al
        # estrenarse: los invariantes de serie comparan frames CONSECUTIVOS, y
        # cogiendo uno de cada cuatro entre dos "consecutivos" caben tres frames
        # en los que el board puede crecer y la mano cambiar legitimamente. La
        # sesion del 29-07 a las 07:04 daba asi 2,77% de board_pierde_carta
        # contra 1,52% de la linea base, o sea que parecia haber empeorado
        # cuando lo unico que habia pasado es que se comparaban frames lejanos.
        #
        # Y segundo: desde el principio y no desde el medio porque el Analizador
        # arranca vacio. Empezar en mitad de la sesion le quita la historia que
        # tenia -referencia fijada, voto de asientos, voto del boton- y mide algo
        # que en produccion no ocurre nunca. Es el mismo motivo por el que la
        # regresion de oro descarta los trozos sueltos (ver corpus.es_fragmento).
        pngs = pngs[:muestra]
    an = Analizador(seed_equity=1, tmp_frame=f"/tmp/score_cartas_{os.getpid()}.png")
    for p in pngs:
        try:
            r = an.analizar(p)
        except Exception:                  # noqa: BLE001
            continue
        yield {"state": r.state, "recommendation": r.recommendation,
               "hand_result": getattr(r, "hand_result", None)}


def puntua(carpeta, reanalizar=False, muestra=0, semilla=1):
    """Devuelve (n_frames, n_pares, Counter de fallos, Counter de rangos).

    El Counter de rangos lleva UNA muestra por mano (el board mas largo que
    se le vio), no una por frame; ver el comentario de boards_por_mano."""
    random.seed(semilla)
    fuente = (_frames_reanalizados(carpeta, muestra, semilla) if reanalizar
              else _frames_grabados(carpeta))
    fallos, rangos = Counter(), Counter()
    boards_por_mano = {}
    n = pares = 0
    previo = None
    for d in fuente:
        st = d.get("state") or {}
        if inv._sin_mesa(st):
            previo = None                  # sin mesa no hay serie que continuar
            continue
        n += 1
        for clave, _detalle in inv.de_frame(st, d.get("recommendation")):
            fallos[clave] += 1
        # EL REPARTO DE RANGOS SE CUENTA POR MANO, NO POR FRAME. Un board se ve
        # en decenas de frames seguidos, asi que contarlo una vez por frame no
        # mide el mazo: mide cuanto duro cada mano. Se guarda el board MAS LARGO
        # de cada mano y al final se cuenta ese, que es una muestra por reparto.
        #
        # No es un detalle: sobre los primeros 300 frames de una sesion el
        # reparto por frame daba 8,4% de figuras y por mano 20,2% -la misma
        # sesion, el mismo codigo-. El primero decia que las figuras seguian
        # perdiendose y el segundo que ya no.
        mano = st.get("mano_seguida")
        board = [c for c in (st.get("board") or []) if c]
        if mano is not None and len(board) > len(boards_por_mano.get(mano, [])):
            boards_por_mano[mano] = board
        elif mano is None:
            for carta in board:            # sin numero de mano no hay agrupacion
                if carta[0].upper() in RANGOS:
                    rangos[carta[0].upper()] += 1
        frase = (d.get("hand_result") or {}).get("winning_hand")
        if frase:
            fallos["_chat_comprobado"] += 1
            if _contradice_al_chat(st.get("board") or [], frase):
                fallos["contradice_al_chat"] += 1
        actual = (st, d.get("recommendation"))
        if previo is not None:
            pares += 1
            for clave, _detalle in inv.de_serie(previo, actual):
                fallos[clave] += 1
        previo = actual
    for board in boards_por_mano.values():
        for carta in board:
            if carta[0].upper() in RANGOS:
                rangos[carta[0].upper()] += 1
    return n, pares, fallos, rangos


# Las que hablan de CARTAS. Las demas (jugadores_cambian, posicion_cambia...)
# tambien salen de de_frame/de_serie pero miden otra cosa y aqui solo harian
# ruido; para esas esta tests/test_invariantes_corpus.py.
DE_FRAME = ["board_ilegal", "board_repetido", "carta_en_dos_sitios", "hero_repetida"]
DE_SERIE = ["board_pierde_carta", "hero_cambia_de_cartas"]


def informe(filas):
    anchos = "  ".join(f"{k[:13]:>13}" for k in DE_FRAME + DE_SERIE)
    print(f"{'sesion':24} {'frames':>7} {'pares':>6}  {anchos}  {'chat':>12}  {'J/Q/K':>7}")
    tot_n = tot_p = 0
    tot_f, tot_r = Counter(), Counter()
    for nombre, n, pares, fallos, rangos in filas:
        tot_n += n; tot_p += pares; tot_f.update(fallos); tot_r.update(rangos)
        print(f"{nombre[:24]:24} {n:7} {pares:6}  " + _celdas(n, pares, fallos, rangos))
    if len(filas) > 1:
        print(f"{'TOTAL':24} {tot_n:7} {tot_p:6}  " + _celdas(tot_n, tot_p, tot_f, tot_r))
    fig = sum(tot_r[r] for r in FIGURAS)
    tot = sum(tot_r.values()) or 1
    print(f"\nreparto de rangos ({tot} cartas de board; en un mazo justo, "
          f"{FRAC_JUSTA:.1%} cada uno)")
    print("   " + "  ".join(f"{r}:{tot_r[r] / tot:.1%}" for r in RANGOS))
    print(f"   figuras J/Q/K = {fig / tot:.1%}   (justo: {FRAC_FIGURAS:.1%})")


def _celdas(n, pares, fallos, rangos):
    out = []
    for k in DE_FRAME:
        out.append(f"{fallos[k] / max(n, 1):12.2%} " if n else f"{'-':>13}")
    for k in DE_SERIE:
        out.append(f"{fallos[k] / max(pares, 1):12.2%} " if pares else f"{'-':>13}")
    comprobados = fallos["_chat_comprobado"]
    chat = (f"{fallos['contradice_al_chat']}/{comprobados}" if comprobados else "-")
    tot = sum(rangos.values())
    fig = sum(rangos[r] for r in FIGURAS) / tot if tot else None
    return ("".join(out) + f"  {chat:>12}  "
            + (f"{fig:6.1%} " if fig is not None else f"{'-':>7}"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("carpetas", nargs="*", help="sesiones; por defecto, todas")
    p.add_argument("--reanalizar", action="store_true",
                   help="vuelve a pasar las imagenes por el pipeline ACTUAL "
                        "(lento) en vez de puntuar lo grabado")
    p.add_argument("--muestra", type=int, default=0,
                   help="con --reanalizar, cuantos frames por sesion como mucho")
    p.add_argument("--semilla", type=int, default=1)
    p.add_argument("--min-frames", type=int, default=50,
                   help="se saltan las carpetas mas cortas (notas sueltas)")
    a = p.parse_args(argv)

    carpetas = a.carpetas or sorted(
        d for d in glob.glob(os.path.join("testing", "*"))
        if os.path.isdir(d) and os.path.basename(d)[0] != "_")
    filas = []
    for c in carpetas:
        if len(glob.glob(os.path.join(c, "[0-9]*.json"))) < a.min_frames:
            continue
        n, pares, fallos, rangos = puntua(c, a.reanalizar, a.muestra, a.semilla)
        if n:
            filas.append((os.path.basename(c.rstrip("/")), n, pares, fallos, rangos))
    if not filas:
        print("nada que puntuar", file=sys.stderr)
        return 1
    informe(filas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
