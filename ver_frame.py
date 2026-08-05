"""
Dibuja sobre un frame lo que el algoritmo ESTA MIRANDO y lo que ha leido.

    .venv/bin/python ver_frame.py captura.png                   # una imagen suelta
    .venv/bin/python ver_frame.py testing/sesion-<fecha> 485    # un frame de una sesion
    .venv/bin/python ver_frame.py captura.png --calentar testing/sesion-<fecha>

PARA QUE SIRVE. Cuando algo se lee mal, la pregunta util no es "que ha dicho la
app" -eso ya esta en el JSON- sino "de DONDE lo ha sacado". Esto pinta cada zona
en su sitio sobre la imagen y la colorea segun si encontro algo, asi que un
numero leido de donde no debe se ve de un vistazo en vez de deducirse.

Es la contrapartida de replay.py: replay compara CIFRAS entre lo grabado y lo que
sale hoy; esto enseña la GEOMETRIA de una sola lectura.

LO IMPORTANTE, Y ES LA PARTE QUE MAS ENGAÑA: la referencia del tapete NO se
calcula bien con un frame suelto. En vivo se fija con la mediana de las primeras
diez lecturas buenas de la sesion (seat_map.ReferenciaFijada), asi que un frame
analizado EN FRIO puede colocar todas las zonas desplazadas y hacer creer que hay
un bug de deteccion donde solo hay un encuadre mal estimado. Paso de verdad
depurando el all-in de sesion-2026-07-28_012453/0485: en frio la zona del board
caia por DEBAJO de las cartas.

Por eso, cuando se le da una carpeta de sesion, la referencia se calienta con los
frames anteriores igual que en vivo, y cuando se le da una imagen suelta se avisa
por pantalla de que va en frio (o se le pasa --calentar con una sesion del mismo
encuadre).
"""
import argparse
import glob
import json
import os

import cv2

from vision import seat_map

TESTING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testing")

# BGR. Un color por familia de zona, para poder mirar una sola cosa a la vez.
AZUL, VERDE, ROJO, AMARILLO, MAGENTA, CIAN = ((255, 160, 0), (0, 220, 0), (0, 0, 255),
                                              (0, 220, 220), (255, 0, 255), (255, 255, 0))
GRIS = (150, 150, 150)

# (etiqueta, zona, color) de lo que no depende del asiento
ZONAS_FIJAS = [
    ("board", seat_map.BOARD_ZONE, AMARILLO),
    ("bote", seat_map.POT_ZONE, ROJO),
    ("cartas hero", seat_map.HERO_CARDS_ZONE, CIAN),
    ("chat", seat_map.CHAT_ZONE, GRIS),
    ("botones", seat_map.ACTION_ZONE, GRIS),
]


def _caja(vis, px, color, etiqueta, grosor=2):
    x0, y0, x1, y1 = px
    if x1 <= x0 or y1 <= y0:
        return                                  # zona fuera de la imagen
    cv2.rectangle(vis, (x0, y0), (x1, y1), color, grosor)
    y = y0 + 18 if y0 < 20 else y0 - 6
    cv2.putText(vis, etiqueta, (x0 + 3, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)


def referencia_de(img, sesion=None, hasta=None):
    """La referencia del tapete, calentada como en vivo si hay sesion.

    Devuelve (ref, en_frio). Sin sesion no hay nada que calentar y se avisa: las
    zonas pueden salir desplazadas y no es culpa de los detectores."""
    if not sesion:
        return seat_map.find_reference(img), True
    refc = seat_map.ReferenciaFijada()
    rutas = sorted(glob.glob(os.path.join(sesion, "[0-9]*.png")),
                   key=lambda p: int(os.path.basename(p)[:-4]))
    for r in rutas:
        if hasta is not None and int(os.path.basename(r)[:-4]) > hasta:
            break
        previo = cv2.imread(r)
        if previo is not None:
            refc.de(previo)
    return refc.de(img), refc.fijada is None


def pintar(img, ref):
    """Devuelve (imagen anotada, {asiento: que se encontro})."""
    vis = img.copy()
    x0, y0, w, h = ref[0], ref[1], ref[2], ref[3]
    cv2.rectangle(vis, (x0, y0), (x0 + w, y0 + h), (255, 255, 255), 2)
    cv2.putText(vis, "nucleo del tapete", (x0 + 4, y0 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

    for etiqueta, zona, color in ZONAS_FIJAS:
        _caja(vis, seat_map.zone_to_px(ref, zona, img.shape), color, etiqueta)

    # las dos señales de "quien esta en la mano", cada una con su color, para ver
    # CUAL de las dos respondio en este frame
    dorsos = seat_map.detect_in_hand_seats(img, ref)
    reveladas = seat_map.revealed_pair_seats(img, ref)

    hallazgos = {}
    for nombre in seat_map.SEATS:
        _caja(vis, seat_map.zone_to_px(ref, seat_map.SEATS[nombre]["plate"], img.shape),
              AZUL, f"plate {nombre}")
        if nombre in seat_map.SEAT_BET_ZONES:
            _caja(vis, seat_map.zone_to_px(ref, seat_map.SEAT_BET_ZONES[nombre], img.shape),
                  GRIS, f"apuesta {nombre}", grosor=1)
        if nombre in seat_map.CARD_BACK_ZONES:
            m = seat_map.REVELADA_MARGEN
            zx0, zy0, zx1, zy1 = seat_map.CARD_BACK_ZONES[nombre]
            px = seat_map.zone_to_px(ref, (zx0 - m, zy0 - m, zx1 + m, zy1 + m), img.shape)
            if nombre in reveladas:
                que, color = "BOCA ARRIBA", VERDE
            elif nombre in dorsos:
                que, color = "dorso", AMARILLO
            else:
                que, color = "nada", MAGENTA
            _caja(vis, px, color, f"{nombre}: {que}")
            hallazgos[nombre] = que
    return vis, hallazgos


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("entrada", help="un PNG, o la carpeta de una sesion de testing/")
    ap.add_argument("frame", nargs="?", type=int,
                    help="numero de frame, si `entrada` es una carpeta de sesion")
    ap.add_argument("--calentar", help="sesion con la que calentar la referencia "
                                       "si `entrada` es un PNG suelto")
    ap.add_argument("-o", "--salida", default="zonas.png")
    ap.add_argument("--olmocr", action="store_true",
                    help="pide ademas una SEGUNDA OPINION a olmOCR sobre este "
                         "frame (~8 s, necesita el servidor local; ver "
                         "docs/OCR-OLMOCR-MEDICION.md)")
    args = ap.parse_args()

    sesion, hasta = args.calentar, None
    if os.path.isdir(args.entrada):
        if args.frame is None:
            ap.error("con una carpeta de sesion hay que decir que frame mirar")
        sesion, hasta = args.entrada, args.frame
        png = os.path.join(args.entrada, f"{args.frame:04d}.png")
    else:
        png = args.entrada

    img = cv2.imread(png)
    if img is None:
        print(f"no se pudo leer {png}")
        return 1

    ref, en_frio = referencia_de(img, sesion, hasta)
    if en_frio:
        print("AVISO: referencia EN FRIO (un frame suelto no basta para fijarla).\n"
              "       Las zonas pueden salir desplazadas; usa --calentar con una\n"
              "       sesion del mismo encuadre para verlas donde van de verdad.")
    vis, hallazgos = pintar(img, ref)
    cv2.imwrite(args.salida, vis)

    print(f"\nnucleo del tapete: x={ref[0]} y={ref[1]} ancho={ref[2]} alto={ref[3]}"
          f"{'  (fallback)' if ref[4] else ''}")
    print("\nasientos:")
    for nombre, que in sorted(hallazgos.items()):
        print(f"   {nombre:5} {que}")

    ruta_json = png[:-4] + ".json"
    if os.path.exists(ruta_json):
        try:
            st = json.load(open(ruta_json)).get("state") or {}
        except (OSError, ValueError):
            st = {}
        if st:
            print("\nlo que la app grabo de este frame:")
            print(f"   cartas={st.get('hero_cards')}  board={st.get('board')}  "
                  f"bote={st.get('pot')}  posicion={st.get('hero_position')}")
            for p in st.get("players") or []:
                print(f"   {p.get('seat'):5} {str(p.get('name'))[:14]:14} "
                      f"stack={str(p.get('stack')):8} bet={str(p.get('bet')):8} "
                      f"in_hand={p.get('in_hand')}")
    if args.olmocr:
        segunda_opinion(img)

    print(f"\n-> {args.salida}")
    return 0


def segunda_opinion(img):
    """Lo que un modelo de vision lee de este mismo frame.

    SOLO PARA ESTUDIAR UN CASO, nunca en vivo: son ~8 s por frame contra los
    ~0,3 s del ciclo entero, o sea que como OCR de la partida no cabe (la
    medicion completa esta en docs/OCR-OLMOCR-MEDICION.md). Lo que si hace es
    dar una lectura INDEPENDIENTE cuando algo se lee raro y no esta claro si el
    fallo es del OCR o de la geometria: si el modelo lee bien lo que la app no
    lee, el recorte esta donde debe y el problema es el OCR; si tampoco lo lee,
    mira la zona pintada."""
    from vision import ocr_vlm
    ok, motivo = ocr_vlm.disponible()
    if not ok:
        print(f"\nsegunda opinion no disponible: {motivo}")
        print(f"   arrancalo con:  ollama serve  &&  ollama pull {ocr_vlm.MODELO}")
        return
    print("\nsegunda opinion (olmOCR, tarda unos segundos)...")
    try:
        r = ocr_vlm.leer_mesa(img)
    except Exception as e:                       # noqa: BLE001
        print(f"   fallo: {e}")
        return
    print(f"   bote: {r['bote']}   ({r['segundos']:.1f} s)")
    for nombre, importe in r["jugadores"].items():
        print(f"   {nombre[:20]:20} {importe}")


if __name__ == "__main__":
    raise SystemExit(main())
