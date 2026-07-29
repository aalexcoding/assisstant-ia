# Mesa de 8: los ocho asientos, medidos

Estado: **cableado y jugable**. Elige **8-Max** en el selector "Mesa" de la
ventana antes de darle a Iniciar.

Medido de punta a punta sobre dos sesiones reales de 8-max, reproduciendo los
mismos frames con una disposición y con la otra.

Sesión del 29-07 a las 20:12 (171 frames, ocho jugadores en la mesa):

| | auto (=6) | **8-Max** |
|---|---|---|
| asientos leídos por frame | 4,69 | **6,34** |
| jugadores en mano | 1,01 | **3,81** |
| recomendaciones | 94 | **111** |
| nicks distintos | **2** | **10** (8 reales + 2 variantes de OCR) |

Sesión del 29-07 a las 19:17 (160 frames):

| | disposición de 6 | **disposición de 8** |
|---|---|---|
| asientos leídos por frame | 3,89 | **7,64** |
| jugadores en mano | 1,02 | **3,71** |
| recomendaciones | 16 | **33** |
| nicks distintos | **1** (solo el hero) | **8** (todos) |

## Qué falla hoy

`seat_map.SEATS` define seis zonas fijas, fracciones del núcleo del tapete
calibradas sobre una mesa de 6. En una de 8 no faltan dos zonas: **las que hay
caen en el sitio equivocado**.

| | mesa de 6 (lo que hay) | mesa de 8 (medido) |
|---|---|---|
| lado izquierdo | **un** asiento en y = +0,72 | **dos**: y = +0,44 y y = +0,93 |
| lado derecho | **un** asiento en y = +0,72 | **dos**: y = +0,44 y y = +0,95 |

El asiento de 6-max en +0,72 cae en el HUECO entre los dos de 8-max. De ahí que
`ML` y `MR` aterricen en tapete vacío y que dos jugadores queden invisibles.

Medido sobre la sesión del 29-07 a las 19:05 (381 frames) y las 19:17 (430):

    asientos leídos por frame     4,62   (hay 6-8 ocupados)
    frames con las cartas del hero  19 %
    frames con recomendación        10 %
    posición del hero              CO 51, SB 23, MP2 22, BB 6, HJ 4, BTN 3
    nicks leídos                   alex_delg ... y "Manos", "Frases", "Mesav",
                                   "Color", que son PESTAÑAS del cliente

## Los ocho asientos

**TRES POR CADA LADO Y DOS ENFRENTADOS**, que es como lo describe el usuario y es
lo que la medición reprodujo por su cuenta, sin saberlo de antemano.

Zonas de nameplate en fracciones del núcleo del tapete `(x0, y0, x1, y1)`,
sacadas de 349 frames. El nameplate mide 0,36 × 0,24 del núcleo, igual que en la
mesa de 6.

                        (x0, y0, x1, y1)                centro      visto
    ENFRENTADOS
      TOPC     (+0.33, -0.28, +0.69, -0.04)      (+0.51, -0.16)      98 %
      HERO     (+0.32, +1.01, +0.68, +1.25)      (+0.50, +1.13)      96 %
    LADO IZQUIERDO
      UL       (-0.14, -0.12, +0.22, +0.11)      (+0.04, -0.01)      82 %
      ML       (-0.23, +0.32, +0.13, +0.56)      (-0.05, +0.44)      93 %
      DL       (-0.14, +0.81, +0.22, +1.05)      (+0.04, +0.93)      52 %
    LADO DERECHO
      UR       (+0.77, -0.12, +1.13, +0.12)      (+0.95, +0.00)      93 %
      MR       (+0.89, +0.32, +1.25, +0.56)      (+1.07, +0.44)      98 %
      DR       (+0.77, +0.82, +1.13, +1.06)      (+0.95, +0.94)      90 %

LOS DOS DEL MEDIO SOBRESALEN, y ese detalle es la mejor señal de que la medición
es real y no ruido ajustado: ML está en -0,05 y MR en +1,07, mientras sus vecinos
de arriba y abajo están en +0,04 y +0,95. Es la panza del óvalo. Unas posiciones
inventadas habrían salido alineadas en columna.

`DL` sale en el 52 % y no en el 90 % porque ese asiento estuvo vacío buena parte
de las dos sesiones, no porque se lea peor.

Verificación a ojo en `casos/mesa8_ocho_asientos_localizados.png`: un frame con
los ocho asientos ocupados (todos poniendo ante) y las ocho zonas encima de su
nameplate, incluida la del jugador *Ausente*.

## Cómo se localizaron

Barriendo, no preguntando en sitios fijos. Misma idea que se usó con el disco del
dealer cuando se pasó de seis puntos fijos a un barrido de la mesa.

1. Máscara de cápsula (`CAPSULA_S_MAX/V_MAX`, ya medidos: un asiento vacío da
   0,005 y uno ocupado 0,357-0,443).
2. **Ventana deslizante del tamaño de un nameplate, con centro menos entorno.**
   Buscar componentes de la máscara NO vale: la cápsula se funde con las sillas,
   con la de al lado y con cualquier panel oscuro que caiga en el recuadro
   (medido: 458×284 para una cápsula de 429×113, y dos cápsulas en un blob de
   737×219). Y solo con el centro, cualquier mancha oscura grande puntúa alto en
   todas sus posiciones. Restando el anillo, una mancha uniforme puntúa ~0.
3. Acumular candidatos de cientos de frames y agrupar. Un frame suelto no basta:
   un asiento vacío no da cápsula.

## Lo que queda

- **El barrido sobredetecta**: 7,83 candidatos por frame en la mesa de 8 y 9,12
  en una de 6, donde como mucho hay seis. Los falsos salen de la interfaz del
  cliente (pestañas, casillas, botones). Sobre la sesión entera el ruido se
  diluye al agrupar, pero para usarlo EN VIVO hay que limpiarlo. El filtro obvio
  y sin medir: exigir tapete alrededor, que es lo que un nameplate tiene y una
  pestaña no.
- **La disposición la eliges tú en el selector "Mesa"**, no se detecta sola. Es
  deliberado: una disposición equivocada no falla de forma visible -lee nombres
  donde no hay nadie y deja jugadores invisibles- y eso desplaza TODAS las
  posiciones, que salen del recuento de asientos ocupados. Detectarla sola queda
  para cuando el barrido sea fiable frame a frame.
- **Las mesas de 7 y 9 siguen sin tabla.** Caen a la de 6, que es lo que hacían
  antes. La de 9 está capturada en `casos/` a la espera de medirla igual.
- **Las zonas de APUESTA siguen siendo derivadas y sin validar.** Se asume por
  cómo se usan: el importe leído ahí nunca crea una subida, solo atribuye una que
  el botón "Igualar" ya ha demostrado que existe, así que una zona mal puesta
  hace que no se atribuya, no que se invente.
- **Las zonas de DORSO ya están validadas** (sesión del 29-07 a las 20:12, 162
  frames de una mesa de 8 real). DL y DR, que entraron derivadas y sin
  comprobar, se comportan como las medidas:

        asiento   p50    p90    % sobre el umbral (0,10)
        UL       0,286  0,286        57 %
        UR       0,359  0,359        57 %
        DL       0,187  0,191        51 %   <- era la dudosa
        DR       0,232  0,232        58 %   <- era la dudosa

  Bimodales igual que las demás -0 cuando no hay cartas- y por encima del
  umbral. Tienen MENOS MARGEN que las medidas (1,9× el umbral frente a 2,9×), o
  sea que se pueden centrar mejor; funcionan, pero son la primera candidata si
  algún día se afinan.
- La parte de DECISIÓN ya lo soporta entero: `SEATING_BY_N[8]` da
  `BTN, SB, BB, EP2, MP1, MP2, HJ, CO`, derivado por cuánta gente habla después
  de ti contra los rangos de 9-max digitalizados.
