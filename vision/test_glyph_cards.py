"""
Verificacion del mazo de cara blanca (vision/glyph_card_detector.py) y de que
convive con el de fondo solido sin romperlo.

Lo que de verdad protege:

  1. Que el palo salga del COLOR DE LA TINTA y no del fondo. Es el cambio
     entero: el 26-07-2026 el usuario cambio de mazo y la app se quedo ciega
     267 frames seguidos porque el detector viejo miraba el fondo.
  2. Que las cartas PEGADAS se separen. Sus caras blancas se funden en un solo
     contorno, asi que sin corte por columnas un board de 5 sale como 2 cajas.
  3. Que una carta APAGADA se marque como tal. Apagada significa que el hero ya
     no esta en la mano; tratarla como viva haria recomendar sobre una mano
     abandonada, que es peor que no recomendar.
  4. Que el mazo viejo siga funcionando, incluida la POLARIDAD del OCR de rango:
     los dos mazos comparten el voto y el '10', y solo cambia de donde sale la
     tinta.

Las imagenes se generan aqui (colores medidos sobre capturas reales, ver el
docstring del modulo), asi que el test no depende de tener las capturas.
Uso: .venv/bin/python vision/test_glyph_cards.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2
import numpy as np

import color_card_detector as solido
import color_rank_ocr
import glyph_card_detector as glifo

checks = []


def check(desc, cond):
    checks.append((desc, cond))
    print(("OK  " if cond else "FAIL") + " " + desc)


# colores BGR de la tinta, convertidos de los HSV medidos en cartas reales
TINTA = {
    "heart": (40, 40, 205),      # rojo
    "diamond": (200, 60, 40),    # azul
    "club": (40, 120, 40),       # verde
    "spade": (10, 10, 10),       # negro
}
CARA_VIVA = (255, 255, 255)
CARA_APAGADA = (77, 77, 77)
TAPETE = (90, 150, 110)          # verde del tapete, S~97: no debe votar trebol

ANCHO_CARTA, ALTO_CARTA = 87, 121
HUECO = 7


def mesa(n_cartas, palos, cara=CARA_VIVA, alto=ALTO_CARTA):
    """Franja de tapete con n cartas pegadas (hueco de 7px, como el cliente).

    La carta se dibuja con la disposicion REAL, que es la que hace falta aislar:
    rango pequeño arriba a la izquierda con su pip debajo, rango grande a la
    derecha, y el pip grande DEBAJO del rango grande y casi igual de alto -que
    es justo por lo que no se puede separar por tamaño-."""
    img = np.full((alto + 80, 60 + n_cartas * (ANCHO_CARTA + HUECO) + 60, 3),
                  TAPETE, dtype=np.uint8)
    for i in range(n_cartas):
        x = 60 + i * (ANCHO_CARTA + HUECO)
        cv2.rectangle(img, (x, 40), (x + ANCHO_CARTA - 1, 40 + alto - 1), cara, -1)
        t = TINTA[palos[i]]
        cv2.putText(img, "K", (x + 34, 40 + int(alto * 0.50)),          # rango grande
                    cv2.FONT_HERSHEY_SIMPLEX, alto / 105.0, t, 4)
        cv2.putText(img, "K", (x + 5, 40 + int(alto * 0.22)),           # rango pequeño
                    cv2.FONT_HERSHEY_SIMPLEX, alto / 280.0, t, 2)
        cv2.circle(img, (x + 13, 40 + int(alto * 0.37)),                # pip pequeño
                   max(3, alto // 30), t, -1)
        cv2.circle(img, (x + 52, 40 + int(alto * 0.76)),                # pip grande
                   max(5, alto // 12), t, -1)
    return img


# --- caso: el palo sale de la tinta, con la cara blanca -----------------------
print("\n# --- palo por color de tinta ---")
for palo in ("heart", "diamond", "club", "spade"):
    cajas = glifo.find_card_boxes(mesa(1, [palo]))
    check(f"una carta de {palo} sobre cara blanca se lee {palo}",
          len(cajas) == 1 and cajas[0]["suit"] == palo)

solo_tapete = np.full((ALTO_CARTA, ANCHO_CARTA, 3), TAPETE, dtype=np.uint8)
hsv_t = cv2.cvtColor(solo_tapete, cv2.COLOR_BGR2HSV)
votos = glifo.suit_votes(hsv_t, glifo._cara(hsv_t))
check("el verde del TAPETE no vota trebol (su saturacion no llega a COLOR_S_MIN)",
      votos["club"] == 0)

# --- caso: cartas pegadas ----------------------------------------------------
print("\n# --- separar cartas pegadas ---")
for n in (2, 3, 4, 5):
    palos = ["heart", "spade", "club", "diamond", "heart"][:n]
    cajas = glifo.find_card_boxes(mesa(n, palos))
    check(f"un grupo de {n} cartas pegadas da {n} cajas", len(cajas) == n)
    check(f"  y sus {n} palos salen en orden de izquierda a derecha",
          [c["suit"] for c in cajas] == palos)

cajas = glifo.find_card_boxes(mesa(5, ["heart"] * 5))
check("cinco cartas del MISMO palo tambien se separan (el corte es geometrico, "
      "no por color)", len(cajas) == 5)

# --- caso: carta a medio tirar ----------------------------------------------
print("\n# --- ruido ---")
img = mesa(3, ["heart", "spade", "club"])
cv2.rectangle(img, (img.shape[1] - 45, 40), (img.shape[1] - 5, 40 + ALTO_CARTA - 1),
              CARA_VIVA, -1)
check("un trozo de carta demasiado estrecho (animacion de descarte) se descarta",
      len(glifo.find_card_boxes(img)) == 3)
check("tapete solo no produce ninguna carta",
      glifo.find_card_boxes(np.full((200, 400, 3), TAPETE, dtype=np.uint8)) == [])

# --- caso: apagadas ----------------------------------------------------------
print("\n# --- carta apagada = el hero ya no juega la mano ---")
vivas = glifo.find_card_boxes(mesa(2, ["heart", "club"], cara=CARA_VIVA))
apagadas = glifo.find_card_boxes(mesa(2, ["heart", "club"], cara=CARA_APAGADA))
check("las cartas vivas se detectan", len(vivas) == 2)
check("y NO se marcan como apagadas", not any(c["dimmed"] for c in vivas))
check("las apagadas tambien se detectan (si no, la app se queda ciega el 21% "
      "de los frames)", len(apagadas) == 2)
check("y se marcan como apagadas", all(c["dimmed"] for c in apagadas))
check("con el palo correcto aunque esten apagadas",
      [c["suit"] for c in apagadas] == ["heart", "club"])

# --- caso: proporcion del hero (el nameplate le tapa la mitad de abajo) ------
print("\n# --- las cartas del hero salen recortadas por su nameplate ---")
cortadas = glifo.find_card_boxes(mesa(2, ["spade", "diamond"], alto=73))
check("dos cartas de 87x73 (alto/ancho 0.84) se detectan igual", len(cortadas) == 2)
check("  con su palo", [c["suit"] for c in cortadas] == ["spade", "diamond"])

# --- caso: convivencia con el mazo de fondo solido ---------------------------
print("\n# --- el mazo de fondo solido sigue funcionando ---")
# carta del mazo viejo: fondo salmon (corazon) con el rango en BLANCO
vieja = np.full((ALTO_CARTA + 60, ANCHO_CARTA + 60, 3), TAPETE, dtype=np.uint8)
cv2.rectangle(vieja, (30, 30), (30 + ANCHO_CARTA, 30 + ALTO_CARTA), (80, 90, 245), -1)
cv2.putText(vieja, "K", (55, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 4)
cajas_v = solido.find_card_boxes(vieja)
check("el detector de fondo solido sigue leyendo su mazo", len(cajas_v) == 1)
check("el detector de tinta NO se inventa cartas del mazo viejo "
      "(su cara es de color, no clara)", glifo.find_card_boxes(vieja) == [])

carta_glifo = mesa(1, ["spade"])[40:40 + ALTO_CARTA, 60:60 + ANCHO_CARTA]
m_solid = color_rank_ocr.rank_mask(carta_glifo, "solid")
m_glyph = color_rank_ocr.rank_mask(carta_glifo, "glyph")
check("la mascara de rango del mazo nuevo marca la TINTA, no la cara "
      "(la cara es la mayoria del recorte)", m_glyph.mean() < m_solid.mean())
check("y deja fuera de la mascara la mayor parte de la carta",
      0.02 < (m_glyph > 0).mean() < 0.45)

print("\n# --- aislar el rango grande (el pip mide casi lo mismo) ---")
carta_k = mesa(1, ["club"])[40:40 + ALTO_CARTA, 60:60 + ANCHO_CARTA]
completa = color_rank_ocr.rank_mask(carta_k, "glyph")
aislada = color_rank_ocr.rango_grande_mask(carta_k, "glyph")
check("el rango aislado usa menos tinta que la mascara completa "
      "(se han ido el pip y el rango pequeño)", (aislada > 0).sum() < (completa > 0).sum())
ys_a = np.where(aislada > 0)[0]
ys_c = np.where(completa > 0)[0]
check("y lo que queda esta en la parte de ARRIBA de la carta, que es donde va "
      "el rango", ys_a.max() < ys_c.max())
check("queda algo: aislar no puede dejar la carta en blanco", ys_a.size > 0)
check("en el mazo de fondo solido no se aisla nada (el rango ya domina)",
      np.array_equal(color_rank_ocr.rango_grande_mask(carta_k, "solid"),
                     color_rank_ocr.rank_mask(carta_k, "solid")))

print("\n# --- las 2 cartas del hero se dibujan PEGADAS, sin hueco ---")
def pegadas(palos, alto=73):
    """Dos cartas sin NADA entre ellas, que es como el cliente dibuja la mano del
    hero: el corte por perfil de columnas no las puede separar."""
    img = mesa(len(palos), palos, alto=alto)
    # se tapa el hueco entre cartas con cara, borrando la costura
    for i in range(len(palos) - 1):
        x = 60 + (i + 1) * (ANCHO_CARTA + HUECO) - HUECO
        img[40:40 + alto, x:x + HUECO] = CARA_VIVA
    return img

img = pegadas(["heart", "diamond"])
check("sin decir cuantas hay, un bloque pegado no se puede repartir y no se "
      "inventa nada", len(glifo.find_card_boxes(img)) == 0)
cajas = glifo.find_card_boxes(img, esperadas=2)
check("diciendo que son 2, se reparte el bloque en 2", len(cajas) == 2)
check("  y cada palo sale en su sitio",
      [c["suit"] for c in cajas] == ["heart", "diamond"])
check("  con anchos parecidos (el reparto es a partes iguales)",
      abs(cajas[0]["w"] - cajas[1]["w"]) <= 2)

img = pegadas(["spade", "club"])
ruido = img.copy()
# un resto estrecho con forma valida de carta (una ficha, el disco del boton):
# colarlo como tercera carta era peor que el bug que esto arregla
cv2.rectangle(ruido, (5, 45), (5 + 43, 45 + 60), CARA_VIVA, -1)
cv2.circle(ruido, (26, 75), 9, TINTA["heart"], -1)
check("un resto estrecho de la misma banda NO se cuela como tercera carta",
      len(glifo.find_card_boxes(ruido, esperadas=2)) == 2)

separadas = mesa(2, ["club", "spade"], alto=73)
check("si las 2 cartas YA venian separadas, esperadas=2 no las toca",
      [c["suit"] for c in glifo.find_card_boxes(separadas, esperadas=2)] == ["club", "spade"])
check("y una sola carta visible se queda en una: no se parte por completar 2",
      len(glifo.find_card_boxes(mesa(1, ["heart"], alto=73), esperadas=2)) == 1)
check("el board no declara cuantas cartas hay, asi que sigue separandose solo",
      len(glifo.find_card_boxes(mesa(5, ["heart", "spade", "club", "diamond", "heart"]))) == 5)

print("\n# --- el borde de la carta vecina no puede parecer un '1' ---")
# al cortar por la costura entre cartas pegadas, el borde oscuro entra en el
# recorte como una barra alta y fina pegada al lateral: la forma exacta de un '1'
con_borde = mesa(1, ["spade"])[40:40 + ALTO_CARTA, 60:60 + ANCHO_CARTA].copy()
con_borde[:, 0:3] = (20, 20, 20)
con_borde[:, -3:] = (20, 20, 20)
comps = color_rank_ocr._rank_components(
    color_rank_ocr.rango_grande_mask(con_borde, "glyph"))
check("las barras del lateral no llegan a contarse como glifo de rango",
      all(c[0] > 3 and c[0] + c[2] < ANCHO_CARTA - 3 for c in comps))
check("y por tanto no disparan la deteccion del '10'",
      not color_rank_ocr.is_ten(con_borde, "glyph"))
check("el rango de verdad sigue ahi", len(comps) >= 1)

print("\n# --- las dos vistas del mazo nuevo van sin pip ---")
carta_p = mesa(1, ["diamond"])[40:40 + ALTO_CARTA, 60:60 + ANCHO_CARTA]
cerrada = color_rank_ocr._rank_only_close_img(carta_p, "glyph")
check("la vista de desempate tambien parte del rango aislado: un pip leido como "
      "'0' detras de un rango leido como '1' fabrica dieces fantasma",
      (cerrada[:, :, 0] < 128).sum() > 0)

carta_vieja = vieja[30:30 + ALTO_CARTA, 30:30 + ANCHO_CARTA]
check("con deck='solid' la mascara sigue siendo la de siempre",
      np.array_equal(color_rank_ocr.rank_mask(carta_vieja, "solid"),
                     color_rank_ocr._white_mask(carta_vieja)))
check("el mazo entra en la clave de cache: el mismo recorte no se confunde "
      "entre polaridades",
      color_rank_ocr.cache_key(carta_glifo, "spade", "glyph")
      != color_rank_ocr.cache_key(carta_glifo, "spade", "solid"))

print("\n# --- el disco del dealer, sea del color que sea ---")
# El tema de mesa decide si el disco es claro con la pica roja pequeña o crema
# con la pica roja grande. Exigir que gane el claro dejaba la app sin boton -y
# por tanto sin posiciones y sin recomendaciones- en 44 frames seguidos.
import seat_map

REF = (100, 100, 900, 400, False)


def mesa_con_boton(seat, fondo, pica):
    img = np.full((700, 1200, 3), (60, 110, 70), dtype=np.uint8)   # tapete
    fx, fy = seat_map.SEATS[seat]["button"]
    cx = int(REF[0] + fx * REF[2])
    cy = int(REF[1] + fy * REF[3])
    r = int((seat_map.BUTTON_AREA_FRAC_MIN + seat_map.BUTTON_AREA_FRAC_MAX) / 2
            * REF[2] * REF[3] / np.pi) ** 0.5
    cv2.circle(img, (cx, cy), int(r), fondo, -1)
    cv2.circle(img, (cx, cy), max(2, int(r * pica)), (40, 40, 235), -1)   # pica roja
    return img


claro = mesa_con_boton("UL", (245, 245, 245), 0.52)     # disco blanco, pica pequeña
crema = mesa_con_boton("UL", (205, 235, 245), 0.80)     # disco crema, pica grande
check("el disco CLARO con pica roja se encuentra",
      seat_map.detect_button_seat(claro, REF) == "UL")
check("el disco CREMA con la pica roja dominando tambien",
      seat_map.detect_button_seat(crema, REF) == "UL")
check("y se encuentra en el asiento donde esta, no en otro",
      seat_map.detect_button_seat(mesa_con_boton("MR", (245, 245, 245), 0.52), REF) == "MR")

solo_rojo = mesa_con_boton("UL", (40, 40, 235), 0.0)    # una ficha de apuesta
check("una ficha de UN SOLO color no es el boton (falta el claro)",
      seat_map.detect_button_seat(solo_rojo, REF) is None)
solo_claro = mesa_con_boton("UL", (245, 245, 245), 0.0)
check("un disco claro sin pica tampoco (falta el rojo)",
      seat_map.detect_button_seat(solo_claro, REF) is None)
check("y el tapete pelado no inventa boton",
      seat_map.detect_button_seat(np.full((700, 1200, 3), (60, 110, 70), np.uint8), REF) is None)

print("\n# --- el dorso de las cartas cambia de color con el tema ---")
# Sin dorsos no se sabe cuantos rivales siguen en la mano, y sin eso no hay
# equity: el usuario lo noto como que los porcentajes de ganar/perder habian
# desaparecido. Colores medidos: granate (178,131,127) y naranja (19,255,248).
DORSOS = {"granate": (178, 131, 127), "naranja": (19, 255, 248)}


def mesa_con_dorso(seat, hsv_color):
    img = np.full((700, 1200, 3), (60, 110, 70), dtype=np.uint8)
    bgr = cv2.cvtColor(np.uint8([[list(hsv_color)]]), cv2.COLOR_HSV2BGR)[0][0].tolist()
    x0, y0, x1, y1 = seat_map.zone_to_px(REF, seat_map.CARD_BACK_ZONES[seat], img.shape)
    w, h = x1 - x0, y1 - y0
    cv2.rectangle(img, (x0 + int(w * .12), y0 + int(h * .22)),
                  (x0 + int(w * .88), y0 + int(h * .78)), bgr, -1)
    return img


for nombre, color in DORSOS.items():
    check(f"un dorso {nombre} cuenta como asiento con cartas",
          seat_map.detect_in_hand_seats(mesa_con_dorso("ML", color), REF) == {"ML"})
check("el tapete pelado no da ningun asiento con cartas",
      seat_map.detect_in_hand_seats(
          np.full((700, 1200, 3), (60, 110, 70), np.uint8), REF) == set())
check("y cada dorso se cuenta en SU asiento",
      seat_map.detect_in_hand_seats(mesa_con_dorso("UR", DORSOS["naranja"]), REF) == {"UR"})

n_fail = sum(1 for _, cond in checks if not cond)
print(f"\n{len(checks) - n_fail}/{len(checks)} OK")
if n_fail:
    raise SystemExit(1)
