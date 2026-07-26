"""
Vigilante de una sesion EN CURSO: avisa de los frames que merece mirar.

    .venv/bin/python vigilar_sesion.py            # la sesion mas reciente, en vivo
    .venv/bin/python vigilar_sesion.py --repasar testing/sesion-<fecha>

Solo LEE la carpeta que la GUI va escribiendo (`testing/sesion-<fecha>/`), asi que
no toca la captura ni compite por el stream del portal: la app sigue a lo suyo.

Escribe UNA LINEA por hallazgo, con el numero de frame y la ruta del PNG, para
poder abrir la imagen y comprobarlo con los ojos. Ese emparejamiento es el punto:
un aviso sin el frame al lado no se puede verificar.

SELECTIVO A PROPOSITO. Una anomalia dura decenas de frames -un board mal leido
sigue mal leido mientras no cambie la calle-, asi que se avisa UNA VEZ por racha
y no en cada frame. Sin eso, un solo fallo generaria cien avisos y el vigilante
seria ruido.

Lo que se vigila, en dos grupos:

  CONTRADICCIONES  cosas que no pueden pasar en una mano de verdad, asi que son
                   bugs siempre (board con carta repetida, una carta del hero
                   tambien en el board, un raiser que habla despues del hero,
                   mas jugadores de los que caben, el numero de asientos o la
                   posicion cambiando a mitad de mano).
  A REVISAR        cosas correctas pero que conviene verificar con la imagen: una
                   recomendacion DERIVADA (la capa de la Fase E, que no sale de
                   sus tablas) y un motivo de abstencion que no se habia visto
                   antes en esta sesion.
"""
import argparse
import glob
import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import testing_session as tss

ORDEN_PREFLOP = ("EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB")

# Cada cuanto se mira si hay frames nuevos. La app escribe uno cada ~0,7 s, asi
# que mirar mas a menudo no adelanta nada y solo gasta.
ESPERA_S = 1.0


def _cartas(st):
    return " ".join(st.get("hero_cards") or []) or "-"


def _resumen(d):
    st = d.get("state") or {}
    r = d.get("recommendation") or {}
    partes = [f"{_cartas(st)}"]
    if st.get("hero_position"):
        partes.append(st["hero_position"])
    if st.get("board"):
        partes.append("board " + " ".join(st["board"]))
    if r.get("action"):
        partes.append(f"-> {r['action']}")
    return "  ".join(partes)


def hallazgos(d, memoria):
    """Motivos por los que este frame merece mirarse. Lista vacia = nada que ver.

    `memoria` guarda lo ya avisado para no repetirse (ver el docstring del
    modulo): se muta."""
    st = d.get("state") or {}
    if any("encuentra la mesa" in w or "ovalo" in w for w in st.get("warnings") or []):
        return []                       # sin mesa no hay nada que verificar
    out = []
    mano = st.get("mano_seguida")
    board = st.get("board") or []
    hero = st.get("hero_cards") or []

    # --- contradicciones ---------------------------------------------------
    if len(set(board)) < len(board):
        out.append(("BUG", f"board con carta repetida: {board}"))
    if set(board) & set(hero):
        out.append(("BUG", f"carta tuya tambien en el board: "
                           f"{sorted(set(board) & set(hero))}"))
    hp, vs = st.get("hero_position"), st.get("vs_position")
    if hp in ORDEN_PREFLOP and vs in ORDEN_PREFLOP \
            and ORDEN_PREFLOP.index(vs) >= ORDEN_PREFLOP.index(hp):
        out.append(("BUG", f"la subida se atribuye a {vs}, que habla DESPUES que {hp}"))

    n = len(st.get("players") or [])
    prev = memoria.get("jugadores")
    if prev and prev[0] == mano and prev[1] != n:
        out.append(("BUG", f"el numero de jugadores cambia dentro de la mano: "
                           f"{prev[1]} -> {n}"))
    memoria["jugadores"] = (mano, n)

    prev = memoria.get("posicion")
    if prev and prev[0] == mano and hp and prev[1] and prev[1] != hp:
        out.append(("BUG", f"tu posicion cambia dentro de la mano: {prev[1]} -> {hp}"))
    if hp:
        memoria["posicion"] = (mano, hp)

    # --- a revisar ---------------------------------------------------------
    r = d.get("recommendation") or {}
    if r.get("source") == "derived":
        clave = ("derivada", mano, r.get("action"))
        if clave not in memoria["vistos"]:
            memoria["vistos"].add(clave)
            out.append(("REVISAR", f"recomendacion DERIVADA {r['action']} "
                                   f"[{r.get('confidence')}] de {r.get('donor')}"))
    if not r:
        w = (st.get("warnings") or [None])[-1]
        # si ya se ha avisado como BUG de lo mismo, no se repite: el motivo de
        # abstencion suele ser la redaccion larga de la contradiccion que se
        # acaba de nombrar
        ya = any(t == "BUG" for t, _x in out)
        if w and not ya and w[:45] not in memoria["motivos"]:
            memoria["motivos"].add(w[:45])
            out.append(("REVISAR", f"motivo de abstencion nuevo: {w[:110]}"))

    # una racha del mismo motivo se avisa UNA vez
    finales = []
    for tipo, texto in out:
        clave = (tipo, texto[:60])
        if memoria.get("ultimo_motivo") == clave:
            continue
        finales.append((tipo, texto))
    if finales:
        memoria["ultimo_motivo"] = (finales[-1][0], finales[-1][1][:60])
    elif not out:
        memoria["ultimo_motivo"] = None
    return finales


def emitir(directorio, d, tipo, texto):
    png = os.path.join(directorio, d.get("png") or "")
    print(f"[{tipo}] frame {d.get('n'):04d} {d.get('hora','')} | {texto} | "
          f"{_resumen(d)} | {png}", flush=True)


def procesar(directorio, desde=0, seguir=True):
    memoria = {"vistos": set(), "motivos": set()}
    vistos = set()
    ultimo_aviso = time.time()      # si no, la señal de vida salta nada mas arrancar
    while True:
        fs = sorted(glob.glob(os.path.join(directorio, "[0-9]*.json")),
                    key=lambda p: int(os.path.basename(p)[:-5]))
        nuevos = [f for f in fs if f not in vistos
                  and int(os.path.basename(f)[:-5]) >= desde]
        for f in nuevos:
            vistos.add(f)
            try:
                with open(f) as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue                # se esta escribiendo; se vera en la vuelta siguiente
            for tipo, texto in hallazgos(d, memoria):
                emitir(directorio, d, tipo, texto)
                ultimo_aviso = time.time()
        if not seguir:
            return 0
        # señal de vida cada pocos minutos, para saber que sigue mirando
        if time.time() - ultimo_aviso > 300:
            print(f"[VIVO] {len(vistos)} frames revisados, sin novedades", flush=True)
            ultimo_aviso = time.time()
        time.sleep(ESPERA_S)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("directorio", nargs="?", help="carpeta de sesion (por defecto, la ultima)")
    ap.add_argument("--repasar", action="store_true",
                    help="revisa lo ya grabado y sale, en vez de quedarse mirando")
    args = ap.parse_args()

    d = args.directorio
    if not d:
        ses = sorted(glob.glob(os.path.join(tss.TESTING_DIR, "sesion-*")))
        if not ses:
            print(f"no hay sesiones en {tss.TESTING_DIR}", flush=True)
            return 1
        d = ses[-1]
    d = d.rstrip("/")
    print(f"[INICIO] vigilando {os.path.basename(d)}", flush=True)
    return procesar(d, seguir=not args.repasar)


if __name__ == "__main__":
    raise SystemExit(main())
