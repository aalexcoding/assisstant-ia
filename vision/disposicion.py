"""
Que mesa es: la disposicion de asientos, leida del tapete en vez de elegida a
mano en el selector.

QUE SE DETECTA, Y QUE NO. Se detecta LA GEOMETRIA -donde estan las plazas-, no
cuanta gente hay sentada. Son cosas distintas y confundirlas es el error clasico:
un 6-max con tres jugadores sigue siendo un 6-max, y sus tres capsulas caen en
sitios de 6-max. Cuantos hay sentados lo sigue contando table_state frame a
frame; lo que aporta esto es la TABLA con la que mirar.

COMO. Para cada disposicion conocida se pregunta, zona a zona, si ahi hay una
capsula de nameplate anclada (table_state.capsula_px, que ya exige tamaño
plausible, que pise la zona y que su centro caiga dentro), y cuanto se descentra.
La buena explica sus capsulas y las centra; una equivocada pone sus zonas en el
hueco entre dos asientos -que es exactamente lo que le pasa a la de 6 en una mesa
de 8- y ahi no hay capsula, o la hay a medias.

LAS TRES SEÑALES, y hacen falta las tres. Medido sobre las 29 sesiones grabadas
con disposicion conocida:

    contar capsulas a secas                          24 de 29 aciertos
    + descontar lo descentradas que estan            (los 5 fallos son mesas
                                                      casi vacias, y ahi el
                                                      centrado apunta a la buena)
    + PENALIZAR LAS CAPSULAS QUE DEJA SIN EXPLICAR   es lo que separa 6 de 8

La tercera es la que costo encontrar. Una mesa de 6 y una de 8 comparten varios
asientos, asi que la de 8 puntuaba casi como la de 6 en una mesa de 6 (3,07
contra 3,13 en una sesion real) y no habia forma de decidir. Pero la de 8 DEJA
CAPSULAS FUERA: las que estan en los sitios que solo existen en 6. Contando eso,
la misma sesion pasa a 1,12 contra 1,91.

ABSTENERSE ES LA RESPUESTA POR DEFECTO. Si ninguna gana con margen, se devuelve
None y quien llama se queda con lo que diga el usuario. Es deliberado y es la
regla que el proyecto ya se dio cuando quito el "auto" del selector: una
disposicion equivocada NO falla de forma visible -lee nombres donde no hay nadie
y deja jugadores invisibles-, y eso desplaza TODAS las posiciones, que salen del
recuento de asientos ocupados. Mas vale leer de menos con la tabla que el usuario
dice que leer de mas con una adivinada. Con los umbrales elegidos, sobre esas 29
sesiones: 20 aciertos, 9 abstenciones y CERO errores.

LA MESA DE 7 NO ESTA, y no es un olvido: no hay un solo frame de una en el
corpus. Se busco a proposito, barriendo las capsulas de las 53 sesiones grabadas
sin partir de ninguna geometria; las 38 con tapete detectable salen todas de 6, 8
o 9, incluidas las 12 que no llevan la disposicion apuntada en su metadata. Una
final de 7 jugadores no es una mesa de 7 plazas: es una de 9 con dos asientos
vacios, y eso ya esta cubierto -la geometria sale 9 y el recuento, 7-. Si algun
dia aparece una mesa que de verdad no encaje, esto se abstiene en vez de
inventarsela, que es justo lo que hay que hacer con una tabla sin medir.
"""
from vision import seat_map
from vision import table_state

# las que tienen tabla MEDIDA. Ver el docstring para la de 7.
PLAZAS_CANDIDATAS = (6, 8, 9)

# Un asiento vale 1 punto si su capsula esta centrada en la zona, y menos cuanto
# mas descentrada; a partir de medio ancho de zona ya no suma nada. Asi una
# disposicion que "encuentra" la capsula del vecino no puntua como la que la
# tiene donde dice.
DESVIO_NULO = 0.5                  # del ancho de la zona

# Lo que cuesta cada capsula que la disposicion NO explica. Una capsula entra en
# la cuenta comun solo si alguna disposicion la ancla BIEN (calidad >= la mitad),
# para que el ruido de una zona mal puesta no penalice a las demas.
PESO_SIN_EXPLICAR = 0.5
CALIDAD_PARA_CONTAR = 0.5
MISMA_CAPSULA = 0.4                # del ancho de zona: dos anclajes que son uno

# Margenes para decidir. El primero tiene que ganar al segundo por este factor y
# ademas llegar a un minimo: sin el minimo, dos disposiciones que no ven nada
# (0,7 contra 0,4) darian un ganador con un margen enorme y ninguna evidencia, y
# ahi es donde estaban 3 de los 5 fallos del ranking a secas.
#
# Barridos los dos umbrales y el peso sobre las 29 sesiones, la zona sin errores
# es ancha (peso 0,2-0,5 con minimo 2,0-2,5 y margen 1,3-1,6). Se eligen valores
# del centro de esa zona y no del borde: con margen 1,2 se gana un acierto y
# aparece el primer error.
MARGEN = 1.3
PUNTOS_MIN = 2.5

# Frames de evidencia antes de fijar, y frames seguidos con otra ganadora para
# re-fijar. Un frame suelto no basta -entre manos las capsulas se atenuan- y la
# mesa no cambia de tamaño a mitad de sesion, pero el usuario si puede cambiar de
# mesa. Medido: con 15, 20 o 30 frames salen los mismos 20 aciertos; con 40 se
# pierden dos, porque la sesion se acaba antes de juntar la evidencia.
FRAMES_PARA_FIJAR = 20
FRAMES_PARA_REFIJAR = 40


def _anclajes(bgr, ref, plazas):
    """{plazas: [(cx, cy, calidad, ancho_zona)]} de las capsulas que ancla cada
    disposicion, y la lista de capsulas DISTINTAS que ha visto cualquiera."""
    por_plazas = {}
    comunes = []
    for n in plazas:
        anclados = []
        for _nombre, z in seat_map.zonas(n)["seats"].items():
            x0, y0, x1, y1 = seat_map.zone_to_px(ref, z["plate"], bgr.shape)
            capsula = table_state.capsula_px(bgr, (x0, y0, x1, y1))
            if capsula is None:
                continue
            ancho = max(1, x1 - x0)
            cx, cy = (capsula[0] + capsula[2]) / 2, (capsula[1] + capsula[3]) / 2
            desvio = ((cx - (x0 + x1) / 2) ** 2 + (cy - (y0 + y1) / 2) ** 2) ** 0.5
            calidad = max(0.0, 1.0 - (desvio / ancho) / DESVIO_NULO)
            anclados.append((cx, cy, calidad, ancho))
            if calidad >= CALIDAD_PARA_CONTAR and not _ya_esta(cx, cy, ancho, comunes):
                comunes.append((cx, cy, ancho))
        por_plazas[n] = anclados
    return por_plazas, comunes


def _ya_esta(cx, cy, ancho, lista):
    return any(abs(cx - ux) < ancho * MISMA_CAPSULA and abs(cy - uy) < ancho * MISMA_CAPSULA
               for ux, uy, _a in lista)


def puntuar(bgr, ref, plazas=PLAZAS_CANDIDATAS):
    """{plazas: puntos} de este frame. Ver el docstring del modulo."""
    por_plazas, comunes = _anclajes(bgr, ref, plazas)
    puntos = {}
    for n in plazas:
        explicadas = sum(calidad for _cx, _cy, calidad, _a in por_plazas[n])
        sin_explicar = sum(
            0 if _ya_esta(ux, uy, ancho, [(cx, cy, a) for cx, cy, _q, a in por_plazas[n]])
            else 1
            for ux, uy, ancho in comunes)
        puntos[n] = round(explicadas - PESO_SIN_EXPLICAR * sin_explicar, 3)
    return puntos


def decidir(puntos, margen=MARGEN, minimo=PUNTOS_MIN):
    """La disposicion ganadora, o None si no gana con margen suficiente."""
    if not puntos:
        return None
    orden = sorted(puntos.items(), key=lambda kv: -kv[1])
    mejor, punt_mejor = orden[0]
    segundo = orden[1][1] if len(orden) > 1 else 0.0
    if punt_mejor < minimo:
        return None
    if segundo > 0 and punt_mejor < margen * segundo:
        return None
    return mejor


class DisposicionFijada:
    """La disposicion de la sesion: se decide una vez y se mantiene.

    Se acumulan los puntos de varios frames en vez de decidir con uno solo,
    porque un frame suelto no es evidencia: entre manos las capsulas se atenuan, y
    una mesa a la que le faltan jugadores puntua poco en TODAS las disposiciones.
    Con la media de FRAMES_PARA_FIJAR frames la diferencia entre la buena y las
    otras es estable.

    Y se mantiene porque la mesa NO cambia de tamaño dentro de una sesion. Lo que
    si puede cambiar de verdad -en Zoom te cambian de mesa, o el usuario abre otro
    torneo- lo recoge el re-fijado, que exige que otra gane de forma seguida
    durante FRAMES_PARA_REFIJAR frames antes de moverse. Cambiar de disposicion a
    mitad de mano seria peor que no cambiar nunca: desplaza TODAS las posiciones.
    """

    def __init__(self, plazas=PLAZAS_CANDIDATAS):
        self._plazas = tuple(plazas)
        self._acumulado = {n: 0.0 for n in self._plazas}
        self._muestras = 0
        self._fijada = None
        self._candidata = None
        self._discrepantes = 0

    @property
    def fijada(self):
        return self._fijada

    @property
    def muestras(self):
        return self._muestras

    def de(self, bgr, ref):
        """Alimenta un frame y devuelve la disposicion fijada (o None todavia).

        `ref` tiene que ser una referencia BUENA: con el ovalo perdido las zonas
        caen donde no toca y los puntos no significan nada. Quien llama ya sabe si
        el frame se descarta (ver ReferenciaFijada.de), asi que aqui no se vuelve
        a mirar."""
        puntos = puntuar(bgr, ref, self._plazas)
        if self._fijada is None:
            for n, p in puntos.items():
                self._acumulado[n] += p
            self._muestras += 1
            if self._muestras >= FRAMES_PARA_FIJAR:
                medio = {n: v / self._muestras for n, v in self._acumulado.items()}
                self._fijada = decidir(medio)
                # sin ganador claro se EMPIEZA DE CERO en vez de zanjar: la mesa
                # puede estar llenandose y dentro de veinte frames si haber
                # evidencia. Arrastrar los frames flojos del principio solo
                # emborrona la media siguiente.
                self._acumulado = {n: 0.0 for n in self._plazas}
                self._muestras = 0
            return self._fijada

        gana = decidir(puntos)
        if gana is None or gana == self._fijada:
            self._candidata = None
            self._discrepantes = 0
            return self._fijada
        if gana != self._candidata:
            self._candidata = gana
            self._discrepantes = 1
        else:
            self._discrepantes += 1
        if self._discrepantes >= FRAMES_PARA_REFIJAR:
            self._fijada = gana
            self._candidata = None
            self._discrepantes = 0
        return self._fijada
