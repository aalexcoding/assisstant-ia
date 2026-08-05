"""
Fase 0 SIN GTK: el mismo calibrador, con la ventana de opencv.

Existe porque en Mac no hay PyGObject todavia y sin recuadro calibrado no
arranca nada: ni alpha.py, ni la grabacion de muestras, ni el analisis. Hace
exactamente lo mismo que select_region.py -captura un frame de referencia, deja
dibujar el rectangulo de la mesa y lo guarda en pixeles del frame original- y
sobre todo AVISA IGUAL cuando en el recuadro no se ve una mesa, porque la
decision de que es un recuadro valido esta en calibration/recuadro.py y la usan
los dos.

Uso: .venv/bin/python -m calibration.select_region_cv
Controles: arrastrar para dibujar, ENTER o ESPACIO para aceptar, ESC para salir.
"""
import cv2

from capture import pantalla
from calibration import recuadro as rc

TITULO = "Dibuja el recuadro de la mesa - ENTER acepta, ESC sale"


def _pedir_rect_con_opencv(vista):
    """Un rectangulo dibujado sobre la vista, o None si el usuario salio.

    cv2.selectROI devuelve (0,0,0,0) tanto con ESC como con un clic sin
    arrastrar; las dos cosas significan lo mismo aqui: no hay recuadro."""
    rect = cv2.selectROI(TITULO, vista, showCrosshair=False, fromCenter=False)
    cv2.destroyAllWindows()
    cv2.waitKey(1)                        # en macOS la ventana no se cierra sin esto
    x, y, w, h = (int(v) for v in rect)
    if w <= 5 or h <= 5:
        return None
    return (x, y, w, h)


def calibrar(frame, pedir_rect, log=print):
    """Pide recuadros hasta tener uno bueno. Devuelve el rect en pixeles del
    frame original, o None si el usuario se fue.

    NO GUARDA A LA PRIMERA UN RECUADRO SIN MESA, igual que el calibrador de GTK:
    avisa y vuelve a preguntar. Si el usuario dibuja OTRA VEZ un recuadro sin
    mesa, se guarda: manda el, que puede tener un motivo (un tema de mesa que el
    detector no conoce todavia). Lo que no puede pasar es que se guarde en
    silencio, porque entonces el fallo aparece media hora despues jugando y en
    forma de "no se encuentra la mesa en este frame".
    """
    alto, ancho = frame.shape[:2]
    escala = rc.escala_de_vista(ancho, alto)
    vista = frame if escala == 1.0 else cv2.resize(
        frame, (int(ancho * escala), int(alto * escala)), interpolation=cv2.INTER_AREA)

    avisado = False
    while True:
        rect_vista = pedir_rect(vista)
        if rect_vista is None:
            return None
        rect = rc.a_coordenadas_de_frame(rect_vista, escala)
        if rc.hay_mesa(frame, rect) or avisado:
            return rect
        log(rc.AVISO_SIN_MESA + " Dibuja otro, o vuelve a dibujar ahi para"
                                " guardarlo igual.")
        avisado = True


def main():
    # SIEMPRE se pregunta QUE PANTALLA: calibrar es justo el momento de decidir
    # donde esta la mesa. El analisis en marcha no pregunta nada y usa esta.
    print("Capturando frame de referencia...")
    frame = pantalla.un_frame(elegir_pantalla=True)
    alto, ancho = frame.shape[:2]
    print(f"Frame de {ancho}x{alto}. Arrastra sobre la mesa y pulsa ENTER (ESC para salir).")

    rect = calibrar(frame, _pedir_rect_con_opencv)
    if rect is None:
        print("Sin recuadro: no se ha guardado nada.")
        return 1

    rc.save_region((ancho, alto), rect)
    print(f"Guardado en {rc.CONFIG_PATH}: {rect}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
