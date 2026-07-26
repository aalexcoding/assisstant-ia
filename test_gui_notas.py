"""
Verificacion de la funcion de NOTAS de la GUI: marcar una situacion rara mientras
se juega y anotarla para revisarla despues.

Lo unico que hay que blindar aqui es el motivo por el que la funcion va en DOS
PASOS: el usuario ve la rareza y LUEGO escribe, y con el ciclo en ~1,2 s para
cuando termina la frase ya han pasado varios frames. Si la nota se pegara al
frame del momento de GUARDAR, apuntaria al frame equivocado y la funcion no
serviria para nada. Asi que el test simula justo eso: marcar en el frame 1,
dejar pasar cuatro frames, y escribir la nota al final.

Levanta la ventana sin presentarla, igual que `gui.py --self-test`.
Uso: .venv/bin/python test_gui_notas.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, Gtk

import gui
import testing_session as tss

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def leer(directorio, n):
    with open(os.path.join(directorio, f"{n:04d}.json")) as fh:
        return json.load(fh)


def frame_falso(n):
    """Lo que el hilo de analisis manda a on_frame_ready."""
    return (np.zeros((8, 8, 3), dtype=np.uint8),
            {"state": {"hero_cards": ["Ah", "Kd"], "hero_position": "CO"},
             "recommendation": {"action": "FOLD", "action_en": "FOLD"}},
            n)


def correr(win, raiz):
    # --- sin nada analizado: decirlo, no fallar en silencio -------------------
    check("sin frames analizados el boton de marcar esta apagado",
          not win.mark_button.get_sensitive())
    check("y marcar no hace nada", win._on_marcar() is False and win._marcado is None)
    check("pero avisa de por que", "Iniciar analisis" in win.nota_estado.get_text())

    # --- marcar durante una sesion de testing ---------------------------------
    ses = tss.TestingSession(root=raiz)
    win.sesion = ses
    for n in (1,):
        crop, datos, _ = frame_falso(n)
        ses.guardar(crop, datos, lambda ruta: open(ruta, "wb").write(b"png"))
        win.on_frame_ready(crop, datos, n, ses)

    check("con un frame analizado el boton se enciende", win.mark_button.get_sensitive())
    win._on_marcar()
    check("marcar fija el frame que se estaba viendo",
          win._marcado is not None and win._marcado["n"] == 1)
    check("y la UI dice CUAL, que es lo que hace la funcion usable",
          "0001" in win.nota_estado.get_text())

    # --- EL CASO QUE JUSTIFICA TODO: pasan frames mientras se escribe ---------
    for n in (2, 3, 4, 5):
        crop, datos, _ = frame_falso(n)
        ses.guardar(crop, datos, lambda ruta: open(ruta, "wb").write(b"png"))
        win.on_frame_ready(crop, datos, n, ses)
    check("el marcado NO se mueve aunque sigan llegando frames", win._marcado["n"] == 1)

    win.nota_entry.set_text("recomienda FOLD con AK y no lo entiendo")
    win._on_guardar_nota()
    check("la nota se guarda en el frame MARCADO",
          leer(ses.dir, 1).get("nota") == "recomienda FOLD con AK y no lo entiendo")
    check("y NO en el que se estaba analizando al terminar de escribir",
          leer(ses.dir, 5).get("nota") is None)
    check("el campo se vacia para la siguiente", win.nota_entry.get_text() == "")
    check("y la marca se suelta, para no colgar dos notas del mismo frame sin querer",
          win._marcado is None)

    # --- guardar sin haber marcado: no se pierde el texto, pero se avisa ------
    win.nota_entry.set_text("esto tambien canta")
    win._on_guardar_nota()
    check("sin marca previa la nota va al frame de AHORA", leer(ses.dir, 5).get("nota"))
    check("y se avisa claramente de que puede no ser el de la anomalia",
          "OJO" in win.nota_estado.get_text())

    # --- nota vacia -----------------------------------------------------------
    win.nota_entry.set_text("   ")
    win._on_guardar_nota()
    check("una nota vacia no crea nada", "Escribe la nota" in win.nota_estado.get_text())
    ses.cerrar()

    # --- SIN modo testing: es justo cuando mas falta hace guardar el frame ----
    win.sesion = None
    crop, datos, _ = frame_falso(9)
    win.on_frame_ready(crop, datos, None, None)     # n=None: no se guardo nada
    win.nota_entry.set_text("aqui la posicion sale mal")
    win._on_guardar_nota()
    check("con el modo testing apagado se crea una carpeta de notas al vuelo",
          win.sesion_notas is not None
          and os.path.basename(win.sesion_notas.dir).startswith("notas-"))
    d = leer(win.sesion_notas.dir, 1)
    check("y se guarda el frame marcado con todo lo calculado de el",
          d["state"]["hero_position"] == "CO" and d["recommendation"]["action"] == "FOLD")
    check("con su nota", d.get("nota") == "aqui la posicion sale mal")
    check("y su PNG al lado, para poder mirar la imagen",
          os.path.exists(os.path.join(win.sesion_notas.dir, "0001.png")))

    # una segunda nota sin grabar reutiliza la misma carpeta, no crea una por nota
    carpeta = win.sesion_notas.dir
    crop, datos, _ = frame_falso(10)
    win.on_frame_ready(crop, datos, None, None)
    win.nota_entry.set_text("y otra mas")
    win._on_guardar_nota()
    check("las notas de la misma ejecucion van a la misma carpeta",
          win.sesion_notas.dir == carpeta and leer(carpeta, 2).get("nota") == "y otra mas")

    r = tss.resumen(carpeta)
    check("el resumen de la sesion lista las notas", len(r["notas"]) == 2)

    # --- MODO HUD: la misma ventana, con lo secundario escondido ------------
    # Se mira en plena mano, asi que lo que NO puede pasar es que esconda la
    # recomendacion o la equity, que son justo para lo que se enciende.
    visibles_antes = [p.get_visible() for p in win._paneles_secundarios]
    win.hud_check.set_active(True)
    check("el modo HUD esconde los paneles secundarios",
          all(not p.get_visible() for p in win._paneles_secundarios))
    check("pero NUNCA la recomendacion: es para lo que se enciende",
          win.rec_label.get_parent() is not None)
    check("y el titulo lo dice", "HUD" in win.get_title())
    win.hud_check.set_active(False)
    check("al apagarlo vuelve todo",
          [p.get_visible() for p in win._paneles_secundarios] == visibles_antes)
    check("y el titulo tambien", "HUD" not in win.get_title())


def main():
    raiz = tempfile.mkdtemp(prefix="test_gui_notas_")
    # que las carpetas creadas al vuelo no ensucien el testing/ del repo
    tss.TESTING_DIR = raiz
    app = Gtk.Application(application_id="org.pokerassistant.test_notas",
                          flags=Gio.ApplicationFlags.NON_UNIQUE)

    def on_activate(app):
        win = gui.PokerAssistantWindow(app, 1.2)
        try:
            correr(win, raiz)
        finally:
            app.quit()

    app.connect("activate", on_activate)
    try:
        app.run(None)
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    n_fail = sum(1 for _, cond in checks if not cond)
    print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
    return 1 if (n_fail or not checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
