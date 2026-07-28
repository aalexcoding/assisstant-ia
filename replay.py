"""
Re-ejecuta una sesion GRABADA, en frio: sin portal de captura, sin GTK y sin
mesa delante.

    .venv/bin/python replay.py                             # la sesion mas reciente
    .venv/bin/python replay.py testing/sesion-<fecha>
    .venv/bin/python replay.py <sesion> --hasta 50 --diff  # compara con lo grabado

PARA QUE SIRVE. Cada carpeta de `testing/sesion-*` tiene la dupla frame+JSON:
el PNG tal cual se analizo y TODO lo que la app calculo de el. Volver a pasar
esos PNG por el mismo Analizador responde a la pregunta que antes no se podia
contestar: ¿este cambio que acabo de hacer altera lo que la app habria dicho en
una partida real? Con --diff se ve frame a frame, y sin --diff es simplemente
una forma de ejercitar el pipeline entero contra material de verdad.

EL DIFF NO ES UNA IGUALDAD ESTRICTA a proposito. Se comparan los campos que
significan algo para el usuario (cartas, board, posicion, unidad, botones y la
accion recomendada); no se comparan ni los tiempos, ni las lineas crudas del
chat, ni la equity, porque son un Monte Carlo y un OCR y cambiarian sin que
nada este mal. Un campo que pasa de un valor a None cuenta como PERDIDA y uno
que aparece como GANANCIA: no es lo mismo dejar de leer algo que empezar a
leerlo, y mezclarlos escondia justo el tipo de regresion que esto busca.

OJO CON EL ESTADO ENTRE FRAMES. Un replay reproduce la sesion DESDE EL PRINCIPIO
con un Analizador limpio, asi que el rastreador y la referencia del tapete se
van formando igual que en vivo. Empezar por la mitad (--desde) da resultados
peores en los primeros frames y es esperable, no un bug.
"""
import argparse
import glob
import json
import os
import time

from core import Analizador

TESTING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testing")

# Lo que se compara en --diff. Son los campos que el usuario ve y sobre los que
# decide; el resto (tiempos, chat crudo, equity) varia legitimamente.
CAMPOS_STATE = ("hero_cards", "board", "hero_position", "stack_unit", "facing",
                "vs_position", "pot", "hero_cards_dimmed")


def sesiones():
    return sorted(glob.glob(os.path.join(TESTING_DIR, "sesion-*")))


def frames(directorio):
    """[(n, ruta_png, datos_grabados), ...] ordenados por numero de frame.

    Un frame sin PNG se salta: hubo sesiones en que la escritura de la imagen
    fallo y solo quedo el JSON, y esos no se pueden re-analizar."""
    salida = []
    for ruta_json in sorted(glob.glob(os.path.join(directorio, "[0-9]*.json")),
                            key=lambda p: int(os.path.basename(p)[:-5])):
        n = int(os.path.basename(ruta_json)[:-5])
        png = os.path.join(directorio, f"{n:04d}.png")
        if not os.path.exists(png):
            continue
        try:
            with open(ruta_json) as f:
                salida.append((n, png, json.load(f)))
        except (OSError, ValueError):
            continue
    return salida


def _accion(datos):
    return (datos.get("recommendation") or {}).get("action")


def comparar(grabado, nuevo):
    """Diferencias entre lo que se grabo y lo que sale ahora.

    Devuelve [(campo, antes, ahora, clase)] con clase en
    perdida / ganancia / cambio."""
    viejo_state = grabado.get("state") or {}
    diffs = []
    for campo in CAMPOS_STATE:
        antes, ahora = viejo_state.get(campo), nuevo.state.get(campo)
        if antes == ahora:
            continue
        clase = ("perdida" if ahora in (None, [], "") else
                 "ganancia" if antes in (None, [], "") else "cambio")
        diffs.append((campo, antes, ahora, clase))
    antes, ahora = _accion(grabado), _accion(nuevo.a_dict())
    if antes != ahora:
        clase = ("perdida" if ahora is None else
                 "ganancia" if antes is None else "cambio")
        diffs.append(("recomendacion", antes, ahora, clase))
    return diffs


def reproducir(directorio, desde=0, hasta=None, diff=False, max_players=None,
               seed_equity=None, verboso=True):
    """Re-analiza la sesion y devuelve un resumen.

    El Analizador es NUEVO: la memoria entre frames se reconstruye igual que en
    vivo, que es la unica forma de que el replay signifique algo."""
    an = Analizador(max_players=max_players, seed_equity=seed_equity,
                    tmp_frame="/tmp/poker_replay_frame.png")
    lote = [f for f in frames(directorio) if f[0] >= desde]
    if hasta is not None:
        lote = lote[:hasta]

    resumen = {"frames": 0, "fallos": 0, "con_recomendacion": 0,
               "perdidas": 0, "ganancias": 0, "cambios": 0, "segundos": 0.0}
    t0 = time.perf_counter()
    for n, png, grabado in lote:
        try:
            res = an.analizar(png)
        except Exception as e:                      # noqa: BLE001
            resumen["fallos"] += 1
            if verboso:
                print(f"[FALLO] frame {n:04d}: {type(e).__name__}: {e}", flush=True)
            continue
        resumen["frames"] += 1
        if res.recommendation:
            resumen["con_recomendacion"] += 1
        if diff:
            for campo, antes, ahora, clase in comparar(grabado, res):
                resumen[clase + "s"] += 1
                if verboso:
                    print(f"[{clase.upper():9}] frame {n:04d} {campo}: "
                          f"{antes!r} -> {ahora!r}", flush=True)
    resumen["segundos"] = round(time.perf_counter() - t0, 2)
    return resumen


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("directorio", nargs="?", help="carpeta de sesion (por defecto, la ultima)")
    ap.add_argument("--desde", type=int, default=0, help="primer numero de frame")
    ap.add_argument("--hasta", type=int, default=None, help="cuantos frames como mucho")
    ap.add_argument("--diff", action="store_true",
                    help="compara con lo grabado y lista las diferencias")
    ap.add_argument("--max-players", type=int, default=None)
    ap.add_argument("--seed-equity", type=int, default=None,
                    help="fija la semilla del Monte Carlo (para poder repetir)")
    args = ap.parse_args()

    d = args.directorio
    if not d:
        todas = sesiones()
        if not todas:
            print(f"no hay sesiones en {TESTING_DIR}")
            return 1
        d = todas[-1]
    d = d.rstrip("/")
    if not os.path.isdir(d):
        print(f"no existe la carpeta {d}")
        return 1

    print(f"[REPLAY] {os.path.basename(d)}")
    r = reproducir(d, desde=args.desde, hasta=args.hasta, diff=args.diff,
                   max_players=args.max_players, seed_equity=args.seed_equity)
    print(f"\n{r['frames']} frames en {r['segundos']}s "
          f"({r['segundos'] / max(r['frames'], 1):.2f}s/frame), "
          f"{r['con_recomendacion']} con recomendacion, {r['fallos']} fallos")
    if args.diff:
        print(f"diferencias: {r['perdidas']} perdidas, {r['ganancias']} ganancias, "
              f"{r['cambios']} cambios")
    return 1 if r["fallos"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
