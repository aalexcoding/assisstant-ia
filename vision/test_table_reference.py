"""
Verificacion de la GUARDA DE REFERENCIA de table_state.analyze_layout().

Todas las zonas del reconocimiento (nameplates, cartas, bote, botones, chat) son
fracciones del nucleo del tapete. Si el ovalo no se detecta, TODAS quedan
desplazadas y lo que salga son lecturas de sitios equivocados: el peor tipo de
salida, porque parece un resultado. Antes se seguia adelante con la "posicion
tipica" como fallback; medido sobre 999 frames de una sesion real, de los 21 que
cayeron en fallback CERO dieron cartas, boton, posicion, stack o recomendacion.

Aqui se fija que analyze_layout CORTA en ese caso, y que el aviso nombra las dos
cosas que el usuario puede arreglar (el tema del tapete y la calibracion). El
caso real que lo motivo: cambiar a un tapete gris oscuro (S=0, V=34) hizo fallar
la deteccion en el 100% de los frames, frente al 98% de acierto con el verde
(S=200, V=115), porque find_reference exige S>=45 y V>=60.

Sin depender de capturas: las imagenes se generan aqui, porque testing/ y
samples*/ estan fuera del repo.

Uso: .venv/bin/python vision/test_table_reference.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import seat_map
import table_state as ts

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


def frame(color_tapete):
    """Un frame 1200x800 con un ovalo grande del color dado sobre fondo casi
    negro, que es la forma del cliente real.

    La PROPORCION importa: el nucleo del tapete real mide entre 2.12 y 2.36 de
    ancho/alto (medido sobre 687 frames de tres sesiones) y find_reference
    rechaza lo que baje de 2.0, porque por debajo de eso lo que ha detectado no
    es el ovalo. El molde tiene que parecerse al cliente, no quedarse justo en
    el limite."""
    img = np.full((800, 1200, 3), 12, dtype=np.uint8)
    if color_tapete is not None:
        cv2.ellipse(img, (600, 400), (480, 215), 0, 0, 360, color_tapete, -1)
    return img


def analizar(img):
    ruta = os.path.join(tempfile.mkdtemp(prefix="test_ref_"), "f.png")
    cv2.imwrite(ruta, img)
    try:
        return ts.analyze_layout(ruta)
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass


# --- un tapete CON COLOR se detecta ---------------------------------------
print("# --- tapete con color ---")
verde = frame((40, 120, 40))            # BGR: verde saturado, como el tema por defecto
ref = seat_map.find_reference(verde)
check("un tapete verde da referencia real, no fallback", ref[4] is False)
check("y el ovalo detectado ocupa la mayor parte del frame",
      ref[2] > 0.5 * verde.shape[1] and ref[3] > 0.3 * verde.shape[0])

# --- un tapete GRIS/OSCURO no, y ahi esta el fallo real --------------------
print("\n# --- tapete gris oscuro (el caso que rompio la app) ---")
gris = frame((45, 45, 45))               # BGR gris: saturacion CERO
ref_gris = seat_map.find_reference(gris)
check("un tapete gris no se detecta: saturacion cero, no pasa S>=45",
      ref_gris[4] is True)

st = analizar(gris)
check("analyze_layout CORTA en vez de analizar con las zonas desplazadas",
      st["players"] == [] and st["hero_cards"] == [] and st["board"] == [])
check("y no llega ni a hacer OCR (no hay lineas de chat)", st["chat_lines"] == [])
aviso = " ".join(st["warnings"])
check("el aviso dice que no se encuentra la mesa", "no se encuentra la mesa" in aviso)
check("y nombra el tapete oscuro como causa", "OSCURO" in aviso or "oscuro" in aviso)
check("y la recalibracion como la otra causa", "recalibra" in aviso)
check("el esquema sigue siendo un GameState valido",
      st["stack_unit"] == "bb" and "pot" in st and "to_call" in st)

# --- sin tapete de ninguna clase ------------------------------------------
print("\n# --- frame sin mesa (lobby, escritorio) ---")
st = analizar(frame(None))
check("un frame sin mesa tampoco inventa nada",
      st["players"] == [] and any("no se encuentra la mesa" in w for w in st["warnings"]))

# --- una imagen ilegible sigue avisando de lo suyo -------------------------
print("\n# --- imagen ilegible ---")
st = ts.analyze_layout("/no/existe/ninguna.png")
check("una ruta que no existe da su propio aviso, no el de la mesa",
      any("no se pudo leer la imagen" in w for w in st["warnings"]))

# --- lecturas de OCR con VARIAS LINEAS -------------------------------------
# El pip del palo de la esquina del recorte se cuela en el OCR (el trebol se
# parece a un "4") y tesseract devuelve dos lineas. Antes se descartaba el texto
# entero y la carta se perdia: el usuario lo cazo jugando ("hay un 2 trebol" en
# un board que la app leia con solo 2 cartas). Como el pip esta ARRIBA del rango
# y tesseract emite de arriba abajo, el rango real es la ultima linea valida.
print("\n# --- OCR de rango con varias lineas ---")
from rank_ocr import normalize_rank  # noqa: E402

check("una lectura limpia sigue igual", normalize_rank("K") == "K")
check("el 10 sigue teniendo su caso especial",
      normalize_rank("10") == "10" and normalize_rank("1O") == "10")
check("'4|2' (pip de trebol + rango) da 2, que era el caso real",
      normalize_rank("4\n2") == "2")
check("'4|8' y '4|Q' tambien", normalize_rank("4\n8") == "8" and normalize_rank("4\nQ") == "Q")
check("un 4 de verdad sigue siendo un 4", normalize_rank("4") == "4")
check("si la ultima linea es basura se coge la anterior valida",
      normalize_rank("4\nX") == "4")
check("y si no hay ninguna linea valida, None (no se inventa carta)",
      normalize_rank("X\nZ") is None and normalize_rank("") is None)

# --- ocupacion de asientos: lo que decide TODAS las posiciones --------------
# Las posiciones salen del RECUENTO de asientos ocupados, asi que un asiento de
# mas las desplaza todas y el rango elegido es el de otra posicion. Caso real:
# en un torneo 3-Max la app veia 4 jugadores en el 34% de los frames y llego a
# asignarle al hero la posicion CO, que en una mesa de 3 no existe.
print("\n# --- ocupacion de asientos ---")


def lineas(*textos):
    return [{"text": t, "left": 0, "top": 0, "right": 10, "bottom": 10, "cx": 5, "cy": 5}
            for t in textos]


check("un importe en BB ocupa el asiento", ts._plate_occupied(lineas("69,3 BB")))
check("un nick tambien", ts._plate_occupied(lineas("Dav6934")))
check("y un verbo de accion", ts._plate_occupied(lineas("Igualar")))
check("el 'No ir' del cliente, que va en dos palabras", ts._plate_occupied(lineas("No ir")))
check("tapete vacio -> NO ocupado", ts._plate_occupied(lineas("")) is False)
check("un ENTERO SUELTO ya no ocupa: era de la epoca de las fichas y la textura "
      "de puntos del tapete se OCR-ea como un numero ('60668' en 60 de 60 frames)",
      ts._plate_occupied(lineas("60668")) is False)
check("ni con separador de miles", ts._plate_occupied(lineas("5.892")) is False)

# la fuerza de la evidencia, que es lo que decide cual se suelta si sobran
f = ts._fuerza_ocupacion
check("el hero nunca se suelta", f("HERO", {}, set(), None) == 4)
check("ni el asiento del boton", f("MR", {}, set(), "MR") == 4)
check("un dorso de carta pesa mas que un nombre",
      f("MR", {}, {"MR"}, None) > f("MR", {"name": "pepe"}, set(), None))
check("y un importe en BB tambien",
      f("MR", {"stack": 44.5}, set(), None) > f("MR", {"name": "pepe"}, set(), None))
check("lo mas debil es un asiento sin nada de eso",
      f("MR", {}, set(), None) < f("MR", {"name": "pepe"}, set(), None))

# --- CACHE DE RANGOS (Fase 2) ----------------------------------------------
# El OCR de rango es el 86% del trabajo de un frame (90 de 105 jobs) y una carta
# del board es la MISMA IMAGEN durante toda la calle. La clave es (palo, hash del
# interior del recorte): el interior porque el borde trae tapete y fichas que se
# animan -con el recorte entero solo coincide el 52% de las veces, quitando el
# 15% de margen el 81%-, y el palo para que una colision exija la misma carta.
print("\n# --- cache de rangos ---")
import color_rank_ocr as cro  # noqa: E402


def carta(valor_centro, valor_borde=0):
    """Recorte sintetico de 120x84: un centro que decide el rango y un borde que
    se anima. El centro cubre HOLGADAMENTE el interior que hashea cache_key
    (con margen 0,15 son las filas 18-101 y las columnas 12-71), para que el
    unico cambio del caso "ruido en el borde" quede de verdad fuera."""
    img = np.full((120, 84, 3), valor_borde, dtype=np.uint8)
    img[16:104, 10:74] = valor_centro
    return img


cro.reset_rank_cache()
k1 = cro.cache_key(carta(200), "club")
check("la misma carta da la misma clave", k1 == cro.cache_key(carta(200), "club"))
check("otro palo, otra clave", k1 != cro.cache_key(carta(200), "heart"))
check("otro centro (otro rango), otra clave", k1 != cro.cache_key(carta(150), "club"))
check("RUIDO SOLO EN EL BORDE no cambia la clave: es justo lo que se anima",
      k1 == cro.cache_key(carta(200, valor_borde=77), "club"))
check("un recorte vacio no da clave", cro.cache_key(np.zeros((0, 0, 3), np.uint8), "club") is None)

hay, r = cro.cached_rank(k1)
check("una clave que no se ha guardado no esta en cache", hay is False)
cro.store_rank(k1, "K")
hay, r = cro.cached_rank(k1)
check("guardar y recuperar", hay is True and r == "K")
k2 = cro.cache_key(carta(150), "club")
cro.store_rank(k2, None)
hay, r = cro.cached_rank(k2)
check("tambien se cachea el FALLO (rango None): el OCR es determinista, "
      "reintentarlo daria el mismo None y es el caso mas caro",
      hay is True and r is None)
check("guardar None es distinto de no tener entrada",
      cro.cached_rank(k2)[0] is True and cro.cached_rank(cro.cache_key(carta(99), "spade"))[0] is False)

for i in range(cro.CACHE_MAX + 5):
    cro.store_rank(("x", bytes([i % 256, i // 256])), "A")
check("la cache esta acotada, no crece sin limite en una sesion larga",
      len(cro._RANK_CACHE) <= cro.CACHE_MAX)
cro.reset_rank_cache()
check("reset la vacia", not cro._RANK_CACHE)

# --- REPARTO DE JOBS DE OCR POR IDIOMA -------------------------------------
# Cargar el modelo espanol cuesta ~0,26 s y solo dos jobs del frame lo necesitan
# (chat y botones). Con el reparto intercalado caian en procesos DISTINTOS y el
# modelo se cargaba dos veces; juntandolos en un trozo propio, el lote baja de
# 1,202 s a 0,888 s (-26%). Lo que NO puede cambiar es que cada job reciba su
# propio resultado, en su propio sitio.
print("\n# --- reparto de jobs de OCR ---")
from ocr_client import OcrBatch, MAX_PROCS  # noqa: E402

repartir = OcrBatch.__dict__["_repartir"].__func__


def pares(n_spa, n_eng):
    jobs = [{"lang": "spa", "id": f"s{i}"} for i in range(n_spa)]
    jobs += [{"id": f"e{i}"} for i in range(n_eng)]
    return list(enumerate(jobs))


real = pares(2, 103)
trozos = repartir(real)
check("los jobs en espanol van TODOS en el mismo trozo",
      sum(1 for t in trozos if any(j.get("lang") == "spa" for _i, j in t)) == 1)
check("y ese trozo no lleva nada mas",
      all(j.get("lang") == "spa" for t in trozos
          for _i, j in t if any(x.get("lang") == "spa" for _y, x in t)))
check("no se pasa del numero de procesos", len(trozos) <= MAX_PROCS)
check("no se pierde ni se duplica ningun job",
      sorted(i for t in trozos for i, _j in t) == list(range(len(real))))

solo_eng = repartir(pares(0, 50))
check("sin jobs de idioma no se desperdicia un trozo",
      len(solo_eng) == min(MAX_PROCS, 50)
      and sorted(i for t in solo_eng for i, _j in t) == list(range(50)))
uno = repartir(pares(0, 1))
check("con un solo job, un solo trozo", len(uno) == 1 and len(uno[0]) == 1)
solo_spa = repartir(pares(3, 0))
check("solo jobs en espanol: un trozo con los tres",
      len(solo_spa) == 1 and len(solo_spa[0]) == 3)

# --- EL VERBO NO ES UN NOMBRE ----------------------------------------------
# Cuando un jugador actua, el cliente le sustituye el nick por lo que ha hecho,
# asi que leerlo como nombre le cambia el nombre justo cuando hace algo. Medido
# sobre una sesion real: 362 de 6264 nombres leidos (6%) eran un verbo.
print("\n# --- verbo de accion vs nombre ---")
for t in ("Pasar", "Igualar", "Apostar", "Subir", "Ausente", "All-in", "all in", "No ir"):
    check(f"{t!r} se reconoce como verbo, no como nombre", ts.es_verbo_de_accion(t))
for t in ("BerniBeau", "over590", "makeao31", "44,5 BB", ""):
    check(f"{t!r} NO es un verbo", ts.es_verbo_de_accion(t) is False)

n, stk, acc = ts._seat_plate_name_stack(lineas("Dav6934", "69,3"))
check("un nameplate normal da nombre y no accion", n == "Dav6934" and acc is None)
n, stk, acc = ts._seat_plate_name_stack(lineas("Igualar"))
check("un nameplate con el verbo NO devuelve nombre", n is None)
check("y devuelve el verbo aparte, que es informacion util", acc == "Igualar")
n, stk, acc = ts._seat_plate_name_stack(lineas("All-in"))
check("'All-in' con guion tampoco se cuela como nombre", n is None and acc == "All-in")

# --- ETIQUETAS DE POSICION SEGUN CUANTOS JUGADORES HAY ---------------------
# La equivalencia es por CUANTOS JUGADORES QUEDAN DETRAS, no por el nombre del
# asiento: es lo que determina la anchura de un rango de apertura. La tabla
# estaba escrita a mano y a partir de 6 jugadores le daba EP1 al primero en
# hablar, pero EP1 de una mesa de 9 tiene OCHO detras y el primero de una de 6
# solo tiene CINCO. Medido a 20bb: se servia un 17,0% de las manos donde tocaba
# un 25,0%, en todas las manos abiertas desde esa posicion.
print("\n# --- etiquetas de posicion por numero de jugadores ---")
CANON = seat_map.CANON9


def orden_de_habla(n):
    """SEATING_BY_N empieza en el BOTON; preflop se habla empezando tras la BB."""
    v = seat_map.SEATING_BY_N[n]
    corte = max(0, n - 3)
    return v[len(v) - corte:] + v[:len(v) - corte]


for n in range(2, 10):
    habla = orden_de_habla(n)
    detras = [CANON.index("BB") - CANON.index(p) for p in habla]
    check(f"con {n} jugadores, los que quedan detras son {list(range(n - 1, -1, -1))}",
          detras == list(range(n - 1, -1, -1)))

check("con 6 jugadores el primero en hablar es MP2, no EP1 "
      "(EP1 tiene 8 detras; en una mesa de 6 solo hay 5)",
      orden_de_habla(6)[0] == "MP2")
check("con 7, MP1", orden_de_habla(7)[0] == "MP1")
check("con 8, EP2", orden_de_habla(8)[0] == "EP2")
check("con 9 si es EP1: es la mesa para la que estan digitalizados los rangos",
      orden_de_habla(9)[0] == "EP1")
check("heads-up: el boton ES la ciega pequeña, habla primero y tiene un rival "
      "detras, igual que la SB de una mesa de 9",
      orden_de_habla(2) == ["SB", "BB"])

for n in (3, 4, 5, 9):
    check(f"la fila de {n} jugadores, que ya era correcta, no cambia",
          orden_de_habla(n)[-3:] == ["BTN", "SB", "BB"])
check("todas las filas acaban en BTN SB BB",
      all(orden_de_habla(n)[-3:] == ["BTN", "SB", "BB"] for n in range(3, 10)))
check("y SEATING_BY_N empieza SIEMPRE por el asiento del boton",
      all(seat_map.SEATING_BY_N[n][0] == "BTN" for n in range(3, 10)))

import dealer_button  # noqa: E402
check("dealer_button usa LA MISMA tabla, no una copia que pueda discrepar",
      dealer_button.SEATING_BY_N is seat_map.SEATING_BY_N)

# --- un FONDO CLARO se confunde con el tapete y hay que detectarlo ----------
print("\n# --- fondo claro alrededor de la mesa ---")
# Premisa rota: find_reference separa el ovalo del fondo "casi negro". Con un
# tema de fondo olivo (H=44, S=80) pasa el 42% del frame y el mayor blob acaba
# siendo fondo y tapete pegados: nucleo (192, 0, 980, 629), o sea tocando el
# borde de arriba. Todas las zonas quedan desplazadas y -lo que lo destapo- los
# dorsos caen fuera, asi que no se detecta ningun rival y la equity no se calcula
# nunca.
claro = np.full((800, 1200, 3), (60, 110, 90), dtype=np.uint8)   # fondo olivo
cv2.ellipse(claro, (600, 400), (480, 215), 0, 0, 360, (40, 140, 60), -1)
ref_claro = seat_map.find_reference(claro)
check("con el fondo claro pegado al tapete NO se da una referencia real",
      ref_claro[4] is True)
st = analizar(claro)
check("y analyze_layout corta el frame en vez de leer sitios equivocados",
      any("no se encuentra la mesa" in w for w in st["warnings"]))
check("el aviso nombra el fondo claro, que es lo que el usuario puede cambiar",
      any("FONDO" in w and "claro" in w for w in st["warnings"]))

alto = np.full((800, 1200, 3), 12, dtype=np.uint8)
cv2.ellipse(alto, (600, 400), (300, 380), 0, 0, 360, (40, 120, 40), -1)
check("un blob demasiado alto para ser el ovalo tampoco vale",
      seat_map.find_reference(alto)[4] is True)

pegado = np.full((800, 1200, 3), 12, dtype=np.uint8)
cv2.ellipse(pegado, (600, 300), (480, 310), 0, 0, 360, (40, 120, 40), -1)
check("ni uno que llega al borde de arriba del frame",
      seat_map.find_reference(pegado)[4] is True)

# --- la referencia se FIJA una vez y se reutiliza ---------------------------
print("\n# --- referencia fijada por sesion ---")
# El tapete no se mueve mientras juegas. Fijarlo rescata entero el tema de fondo
# claro, donde el ovalo solo se detecta bien en el 14% de los frames: analizados
# 19 -> 132 de 132, y la equity 0 -> 27.
rf = seat_map.ReferenciaFijada()
verde2 = frame((40, 120, 40))
check("mientras no hay suficientes lecturas no hay nada fijado", rf.fijada is None)
for _ in range(seat_map.REF_MIN_PARA_FIJAR):
    rf.de(verde2)
check(f"tras {seat_map.REF_MIN_PARA_FIJAR} lecturas buenas queda fijada", rf.fijada is not None)

roto = np.full((800, 1200, 3), (60, 110, 90), dtype=np.uint8)   # fondo claro
cv2.ellipse(roto, (600, 400), (480, 215), 0, 0, 360, (40, 140, 60), -1)
check("un frame donde el ovalo NO se detecta ya no corta: se usa la fijada",
      rf.de(roto)[4] is False)
check("y la que se devuelve es la fijada, no una inventada",
      tuple(rf.de(roto)[:4]) == rf.fijada)

antes = rf.fijada
movido = np.full((800, 1200, 3), 12, dtype=np.uint8)
cv2.ellipse(movido, (600, 300), (350, 155), 0, 0, 360, (40, 120, 40), -1)
for _ in range(seat_map.REF_SEGUIDAS_PARA_REFIJAR - 1):
    rf.de(movido)
check("unas pocas lecturas discrepantes NO mueven la fijada (son ruido)",
      rf.fijada == antes)
rf.de(movido)
check("pero si son sostenidas se vuelve a fijar: la ventana se ha movido",
      rf.fijada != antes)

rf2 = seat_map.ReferenciaFijada()
for _ in range(seat_map.REF_MIN_PARA_FIJAR):
    rf2.de(verde2)
base = rf2.fijada
casi = np.full((800, 1200, 3), 12, dtype=np.uint8)
cv2.ellipse(casi, (600, 400), (475, 213), 0, 0, 360, (40, 120, 40), -1)   # ~1% menor
for _ in range(seat_map.REF_SEGUIDAS_PARA_REFIJAR * 2):
    rf2.de(casi)
check("una variacion dentro de la tolerancia no re-fija nada: es el ruido "
      "normal de la deteccion (0-4,5% medido)", rf2.fijada == base)

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
