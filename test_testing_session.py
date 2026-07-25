"""
Verificacion del grabador de sesiones de testing (testing_session.py).

Lo importante que se comprueba: que la DUPLA existe siempre (mismo nombre para
el PNG y el JSON, que es lo que permite abrir uno y mirar el otro), que un fallo
guardando NO tumba la sesion -grabar es una ayuda, no la funcion de la app- y
que los tipos de numpy que trae el GameState no revientan el volcado a JSON.

Script suelto, sin pytest (el proyecto no lo usa).
Uso: .venv/bin/python test_testing_session.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import testing_session as tss

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


raiz = tempfile.mkdtemp(prefix="test_testing_")
try:
    # --- una sesion normal ----------------------------------------------------
    ses = tss.TestingSession(interval=2.0, region={"x": 1, "y": 2, "width": 3, "height": 4},
                             root=raiz)
    check("la carpeta se llama sesion-<fecha>", os.path.basename(ses.dir).startswith("sesion-"))
    check("y se crea", os.path.isdir(ses.dir))
    check("con metadatos desde el principio",
          os.path.exists(os.path.join(ses.dir, "_sesion.json")))

    escritos = []
    n = ses.guardar(None, {"state": {"hero_cards": ["Ah", "Kd"], "warnings": []},
                           "recommendation": {"action": "FOLD"}},
                    lambda ruta: escritos.append(ruta) or open(ruta, "wb").write(b"png"))
    check("guardar devuelve el numero de frame", n == 1)
    check("escribe el PNG con el nombre esperado",
          escritos and os.path.basename(escritos[0]) == "0001.png")
    check("y el JSON de al lado, MISMO nombre distinta extension",
          os.path.exists(os.path.join(ses.dir, "0001.json")))

    with open(os.path.join(ses.dir, "0001.json")) as fh:
        d = json.load(fh)
    check("el JSON apunta a su PNG", d["png"] == "0001.png")
    check("lleva hora legible", ":" in d["hora"])
    check("y todo lo calculado del frame",
          d["state"]["hero_cards"] == ["Ah", "Kd"] and d["recommendation"]["action"] == "FOLD")

    # --- numeracion correlativa ----------------------------------------------
    for _ in range(3):
        ses.guardar(None, {"state": {}}, lambda ruta: open(ruta, "wb").write(b"png"))
    check("numeracion correlativa con relleno a 4 cifras",
          os.path.exists(os.path.join(ses.dir, "0004.png")))
    check("cada PNG tiene su JSON",
          sorted(f[:-4] for f in os.listdir(ses.dir) if f.endswith(".png"))
          == sorted(f[:-5] for f in os.listdir(ses.dir)
                    if f.endswith(".json") and not f.startswith("_")))

    # --- tipos de numpy: el GameState los trae y json no sabe volcarlos ------
    n = ses.guardar(None, {"state": {"pot": np.float32(3.75),
                                     "n": np.int64(5),
                                     "arr": np.array([1, 2])}},
                    lambda ruta: open(ruta, "wb").write(b"png"))
    check("un GameState con tipos de numpy se guarda igual", n == 5)
    with open(os.path.join(ses.dir, "0005.json")) as fh:
        d = json.load(fh)
    check("float32 -> float", abs(d["state"]["pot"] - 3.75) < 1e-6)
    check("int64 -> int y array -> lista",
          d["state"]["n"] == 5 and d["state"]["arr"] == [1, 2])

    # --- un fallo guardando no puede tumbar el analisis en vivo --------------
    def revienta(_ruta):
        raise OSError("disco lleno")

    antes = ses.errores
    n = ses.guardar(None, {"state": {}}, revienta)
    check("si no se puede escribir, devuelve None en vez de lanzar", n is None)
    check("y lo cuenta como error", ses.errores == antes + 1)
    n = ses.guardar(None, {"state": {}}, lambda ruta: open(ruta, "wb").write(b"png"))
    check("la sesion sigue viva despues del fallo", n == 7)

    # --- cierre ---------------------------------------------------------------
    carpeta = ses.cerrar()
    with open(os.path.join(carpeta, "_sesion.json")) as fh:
        meta = json.load(fh)
    check("los metadatos finales cuadran",
          meta["frames"] == 7 and meta["errores"] == 1 and meta["intervalo_s"] == 2.0)
    check("y guardan el recuadro con el que se grabo", meta["recuadro"]["width"] == 3)
    check("y el commit, para saber con que version se grabo",
          "commit" in meta)

    # --- resumen ---------------------------------------------------------------
    r = tss.resumen(carpeta)
    check("el resumen cuenta los frames guardados", r["frames"] == 6)   # el fallido no dejo json
    check("y detecta los que tienen recomendacion", r["con_recomendacion"] == 1)

    # --- dos sesiones no chocan ------------------------------------------------
    ses2 = tss.TestingSession(root=raiz, now=1)
    check("dos sesiones van a carpetas distintas", ses2.dir != ses.dir)
finally:
    shutil.rmtree(raiz, ignore_errors=True)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
