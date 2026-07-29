# Mesa de 8: los ocho asientos, medidos

Estado: **geometría medida, sin cablear**. La app sigue leyendo seis asientos.

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

Zonas de nameplate en fracciones del núcleo del tapete `(x0, y0, x1, y1)`,
sacadas de 349 frames. El nameplate mide 0,36 × 0,24 del núcleo, igual que en la
mesa de 6.

    TOPC  (+0.33, -0.28, +0.69, -0.04)    98 % de los frames
    UL    (-0.14, -0.12, +0.22, +0.11)    82 %
    UR    (+0.77, -0.12, +1.13, +0.12)    93 %
    ML    (-0.23, +0.32, +0.13, +0.56)    93 %
    MR    (+0.89, +0.32, +1.25, +0.56)    98 %
    DL    (-0.14, +0.81, +0.22, +1.05)    52 %
    DR    (+0.77, +0.82, +1.13, +1.06)    90 %
    HERO  (+0.32, +1.01, +0.68, +1.25)    96 %

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

## Lo que falta antes de cablearlo

- **El barrido sobredetecta**: 7,83 candidatos por frame en la mesa de 8 y 9,12
  en una de 6, donde como mucho hay seis. Los falsos salen de la interfaz del
  cliente (pestañas, casillas, botones). Sobre la sesión entera el ruido se
  diluye al agrupar, pero para usarlo EN VIVO hay que limpiarlo. El filtro obvio
  y sin medir: exigir tapete alrededor, que es lo que un nameplate tiene y una
  pestaña no.
- **Decidir qué disposición está en uso.** Con las dos tablas escritas, la de 6 y
  la de 8, hay que elegir una por sesión. El barrido puede hacerlo: cuenta
  cúmulos y mira si hay uno o dos por lateral.
- **El GUI ofrece 2/3/6/9 y no 8** (`_MESA_OPCIONES`). Es una línea.
- La parte de DECISIÓN ya lo soporta entero: `SEATING_BY_N[8]` da
  `BTN, SB, BB, EP2, MP1, MP2, HJ, CO`, derivado por cuánta gente habla después
  de ti contra los rangos de 9-max digitalizados.
