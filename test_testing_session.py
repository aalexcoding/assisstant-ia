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

    # --- notas: marcar una situacion rara mientras se juega ---------------------
    # Lo que de verdad protege esta seccion: que la nota acabe DENTRO del JSON
    # del frame (la dupla tiene que seguir siendo autocontenida) y que no pise
    # nada de lo que ya se habia calculado de ese frame.
    ses3 = tss.TestingSession(root=raiz, now=2)
    ses3.guardar(None, {"state": {"hero_cards": ["Ah", "Kd"], "pot": np.float32(3.75)},
                        "recommendation": {"action": "FOLD"}},
                 lambda ruta: open(ruta, "wb").write(b"png"))
    ses3.guardar(None, {"state": {}}, lambda ruta: open(ruta, "wb").write(b"png"))

    ok = ses3.anotar(1, "  aqui recomendo FOLD con AK y no lo entiendo  ")
    check("anotar devuelve True cuando escribe", ok)
    with open(os.path.join(ses3.dir, "0001.json")) as fh:
        d = json.load(fh)
    check("la nota va DENTRO del JSON del frame, con el texto limpio",
          d["nota"] == "aqui recomendo FOLD con AK y no lo entiendo")
    check("y no pisa nada de lo ya calculado de ese frame",
          d["state"]["hero_cards"] == ["Ah", "Kd"] and d["recommendation"]["action"] == "FOLD"
          and d["png"] == "0001.png")

    check("hay un indice _notas.jsonl a nivel de sesion",
          os.path.exists(os.path.join(ses3.dir, "_notas.jsonl")))
    with open(os.path.join(ses3.dir, "_notas.jsonl")) as fh:
        idx = [json.loads(l) for l in fh if l.strip()]
    check("el indice apunta al frame y a su PNG",
          len(idx) == 1 and idx[0]["n"] == 1 and idx[0]["png"] == "0001.png")

    with open(os.path.join(ses3.dir, "_sesion.json")) as fh:
        meta3 = json.load(fh)
    check("_sesion.json guarda que frames se marcaron", meta3["notas"] == [1])

    # dos notas sobre el mismo frame se acumulan: pisar la primera seria perder
    # justo lo que el usuario se molesto en escribir
    ses3.anotar(1, "y ademas el bote sale mal")
    with open(os.path.join(ses3.dir, "0001.json")) as fh:
        d = json.load(fh)
    check("una segunda nota sobre el mismo frame se acumula, no lo pisa",
          d["nota"].splitlines() == ["aqui recomendo FOLD con AK y no lo entiendo",
                                     "y ademas el bote sale mal"])
    with open(os.path.join(ses3.dir, "_sesion.json")) as fh:
        check("y el frame no se duplica en la lista de marcados",
              json.load(fh)["notas"] == [1])

    check("una nota vacia no se guarda", ses3.anotar(1, "   ") is False)
    check("ni una nota sin frame", ses3.anotar(None, "algo") is False)
    check("anotar un frame que no existe devuelve False sin lanzar",
          ses3.anotar(99, "algo") is False)

    r3 = tss.resumen(ses3.dir)
    check("el resumen lista las notas enteras, que es lo mas valioso de la sesion",
          len(r3["notas"]) == 1 and r3["notas"][0]["n"] == 1
          and "no lo entiendo" in r3["notas"][0]["nota"])
    check("y no inventa notas donde no las hay",
          all(f["n"] != 2 for f in r3["notas"]))

    # --- la medida que decide si la vigilancia rapida cumple ------------------
    # acciones vistas por mano. La referencia con muestreo de 1,48 s eran 5,7, y
    # una mano de 3-max tiene tipicamente 4-8 acciones.
    ses4 = tss.TestingSession(root=raiz, now=4)
    for n, (mano, nacc) in enumerate([(1, 1), (1, 3), (2, 2), (2, 5), (2, 4)], 1):
        ses4.guardar(None, {"state": {"mano_seguida": mano, "warnings": [],
                                      "acciones": {"acciones": [{}] * nacc},
                                      "vigilancia": {"ticks": 100 * n, "capsulas_ocr": 7 * n}},
                            "duracion_analisis_s": 0.7},
                     lambda ruta: open(ruta, "wb").write(b"png"))
    r4 = tss.resumen(ses4.dir)
    check("el resumen cuenta las manos seguidas", r4["manos"] == 2)
    check("y las acciones por mano, cogiendo el MAXIMO de cada una (el historial "
          "crece dentro de la mano, asi que el ultimo frame la resume)",
          r4["acciones_por_mano"] == 4.0)      # (3 + 5) / 2
    check("y el ciclo medio", r4["ciclo_medio_s"] == 0.7)
    check("y el estado de la vigilancia rapida",
          r4["vigilancia"]["ticks"] == 500 and r4["vigilancia"]["capsulas_ocr"] == 35)
    r_vacio = tss.resumen(ses2.dir)
    check("una sesion sin esos datos no revienta ni inventa un numero",
          r_vacio["manos"] == 0 and r_vacio["acciones_por_mano"] is None)

    # "no se midio" NO es "no se vio nada": una sesion grabada antes de que
    # existiera el historial tiene manos pero no acciones, y contarla como 0
    # haria creer que hay una regresion donde no la hay.
    ses5 = tss.TestingSession(root=raiz, now=5)
    for _ in range(3):
        ses5.guardar(None, {"state": {"mano_seguida": 1, "warnings": []}},
                     lambda ruta: open(ruta, "wb").write(b"png"))
    r5 = tss.resumen(ses5.dir)
    check("una sesion vieja cuenta sus manos pero NO inventa 0 acciones",
          r5["manos"] == 1 and r5["acciones_por_mano"] is None)

    # --- marcar sin modo testing: carpeta aparte creada al vuelo ---------------
    notas = tss.TestingSession(root=raiz, now=3, prefix="notas")
    check("la sesion de solo-notas va a notas-<fecha>, no a sesion-<fecha>",
          os.path.basename(notas.dir).startswith("notas-"))
    n = notas.guardar(None, {"state": {}}, lambda ruta: open(ruta, "wb").write(b"png"))
    check("y guarda duplas igual que una sesion normal",
          n == 1 and notas.anotar(1, "esto canta"))
finally:
    shutil.rmtree(raiz, ignore_errors=True)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
