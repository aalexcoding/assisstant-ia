"""
Vigilancia rapida de los nameplates, para no perderse lo que hacen los rivales.

EL PROBLEMA. Cuando un jugador actua, el cliente le sustituye el nick por lo que
ha hecho ("Pasar", "Igualar", "Subir") y lo quita al poco. Medido sobre una
sesion real, ese cartel dura MENOS DE 1,5 s, que es del orden del ciclo de
analisis completo (~1,0 s). O sea que el muestreo lento se pierde acciones, y las
acciones son justo lo que falta para reconstruir la mano (decision/action_log.py).

LA IDEA. Capturar mucho mas rapido que el analisis, pero sin ANALIZAR: de cada
frame solo se mira si alguna capsula de nameplate ha CAMBIADO, y eso se resuelve
con un hash de sus pixeles. Solo cuando cambia se paga un OCR, y solo el de esa
capsula (1 job), no el frame entero (105).

COSTES MEDIDOS, que es lo que hace viable la idea:

    hashear los 6 nameplates          0,8 ms por frame   <- se puede hacer a 10 Hz
    OCR de UN nameplate               ~60 ms             <- solo cuando cambia
    ciclo de analisis entero          ver core.analisis  <- lo que se evita

El coste del ciclo completo NO SE REPITE AQUI a proposito. Estuvo escrito como
"~950 ms" y el repo llego a tener tres cifras distintas y ninguna medida -"2-4 s"
en el README, "0,7 s" en gui.py y esta-, que es como se acaba razonando sobre un
numero que ya no existe. Vive en un solo sitio, core/analisis.py (bloque del
LATIDO), y ademas se mide en caliente en cada sesion porque depende de la
maquina, la ventana y el mazo.

MARGENES DE LA CAPSULA. Se hashea el INTERIOR de la zona (se descarta
MARGEN_HASH por lado) por la misma razon que en la cache de rangos: el borde pilla
tapete y fichas que se animan, y sin recortarlo el hash cambia siempre y la
vigilancia no sirve de nada.

Este modulo NO captura ni hace OCR: recibe recortes y dice QUE MIRAR. Asi se
puede probar sin portal, sin GTK y sin tesseract.
"""
import hashlib

from vision import seat_map

# Fraccion que se descarta por cada lado antes de hashear. El borde de la zona
# del nameplate incluye tapete, avatar y la marca de bounty, que se animan.
MARGEN_HASH = 0.10

# Franja de la capsula que se vigila, en fraccion de su alto. Solo la parte de
# ARRIBA, que es donde va el NOMBRE y por tanto donde aparece el verbo de la
# accion; abajo va el STACK, que cambia por su cuenta cada vez que se mueven
# fichas y dispararia un OCR sin que nadie haya actuado. Medido sobre 80 frames:
# la capsula entera da 3,6 cambios por frame y esta franja 1,9-2,2.
BANDA_NOMBRE = (0.00, 0.45)

# Cuantos frames se guardan del pasado inmediato. Diez a ~0,1 s es un segundo de
# historia, que es mas que la duracion del cartel de accion, asi que basta para
# no perderse ninguno entre dos analisis completos.
BUFFER_MAX = 10


def _hash_zona(bgr, caja, banda=BANDA_NOMBRE):
    x0, y0, x1, y1 = caja
    h, w = bgr.shape[:2]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    sub = bgr[y0:y1, x0:x1]
    if sub.size == 0:
        return None
    sh = sub.shape[0]
    sub = sub[int(sh * banda[0]):int(sh * banda[1])]
    if sub.size == 0:
        return None
    sh, sw = sub.shape[:2]
    dy, dx = int(sh * MARGEN_HASH), int(sw * MARGEN_HASH)
    interior = sub[dy:sh - dy, dx:sw - dx]
    if interior.size == 0:
        return None
    return hashlib.blake2b(interior.tobytes(), digest_size=8).digest()


def huellas(bgr, ref, seats=None):
    """{asiento: hash} de las capsulas de nameplate de este frame."""
    seats = seats or seat_map.SEATS
    out = {}
    for name in seats:
        caja = seat_map.zone_to_px(ref, seats[name]["plate"], bgr.shape)
        h = _hash_zona(bgr, caja)
        if h is not None:
            out[name] = h
    return out


class SeatWatch:
    """Lleva la ultima huella conocida de cada asiento y dice cuales han
    cambiado. Un objeto por sesion de captura."""

    def __init__(self, seats=None):
        # la DISPOSICION de la mesa (6 o 8 plazas). Se fija al crear el objeto,
        # que es una por sesion de captura: dentro de una sesion la mesa no
        # cambia de tamaño, y si cambiara habria que empezar de cero igual.
        self._seats = seats or seat_map.SEATS
        self._ultimas = {}
        self._ultimas_completas = {}
        self._pendientes = set()

    def cambios(self, bgr, ref):
        """Asientos cuya capsula ha cambiado respecto a la ultima vez.

        La PRIMERA vez que se ve un asiento NO cuenta como cambio: no hay nada
        con que comparar, y darlo por cambiado haria OCR-ear los seis asientos en
        el primer frame de cada sesion sin ninguna razon."""
        nuevas = huellas(bgr, ref, self._seats)
        cambiados = [s for s, h in nuevas.items()
                     if s in self._pendientes
                     or (s in self._ultimas and self._ultimas[s] != h)]
        self._ultimas.update(nuevas)
        self._pendientes.clear()
        return cambiados

    def re_censar(self):
        """Marca las seis capsulas como PENDIENTES: la proxima mirada las devuelve
        TODAS, hayan cambiado un pixel o no.

        Para el arranque de una mano. Entre manos cambia quien esta sentado -en
        Zoom el cliente te cambia de mesa, asi que el ocupante de un asiento puede
        ser otra persona- y hay que volver a leer los seis nombres aunque la
        imagen se parezca.

        NO CONFUNDIR CON olvidar(), que hace lo CONTRARIO y por eso no vale aqui:
        olvidar borra las huellas, y como la primera vez que se ve un asiento no
        cuenta como cambio, la mirada siguiente devolveria CERO asientos. Usar
        olvidar() para re-censar dejaria la mesa sin leer justo cuando mas falta
        hace."""
        self._pendientes = set(self._seats)

    def cambios_completos(self, bgr, ref):
        """Cambios en nombre o stack, aptos para invalidar una caché completa."""
        nuevos = {s: _hash_zona(
            bgr, seat_map.zone_to_px(ref, self._seats[s]["plate"], bgr.shape),
            banda=(0.0, 1.0)) for s in self._seats}
        cambiados = [s for s, h in nuevos.items()
                     if h is not None and (s not in self._ultimas_completas
                                           or self._ultimas_completas[s] != h)]
        self._ultimas_completas.update(nuevos)
        return cambiados

    def olvidar(self):
        """Para empezar de cero: sesion nueva o recuadro recalibrado.

        Es lo correcto ahi y solo ahi: si el encuadre cambia, las huellas viejas
        son de otras cajas y compararlas no significa nada. Para el arranque de
        una mano lo que se quiere es re_censar()."""
        self._ultimas.clear()
        self._ultimas_completas.clear()
        self._pendientes.clear()


class FrameBuffer:
    """Anillo de los ultimos frames capturados.

    Guarda COPIAS: el buffer del stream se reescribe en la lectura siguiente, asi
    que sin copiar lo que quedaria guardado no seria lo que se vio. Al pasarse
    del tamaño se descarta el mas viejo, que es lo que evita que una sesion larga
    se coma la memoria."""

    def __init__(self, maxlen=BUFFER_MAX):
        self.maxlen = maxlen
        self._items = []

    def añadir(self, bgr, t=None, meta=None):
        self._items.append({"frame": bgr.copy(), "t": t, "meta": meta or {}})
        if len(self._items) > self.maxlen:
            self._items.pop(0)
        return len(self._items)

    def ultimo(self):
        return self._items[-1] if self._items else None

    def todos(self):
        return list(self._items)

    def vaciar(self):
        self._items.clear()

    def __len__(self):
        return len(self._items)
