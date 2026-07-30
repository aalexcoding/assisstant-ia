# De qué colgar las zonas (y por qué el centro del óvalo no basta)

Idea del usuario: *"al detectar el óvalo, que se determine el centro y a partir de
ahí posicionar todo lo demás, para que no se dependa de que el frame sea pixel
perfect"*.

El problema que ataca es real y está medido: `find_reference` no es reproducible
frame a frame, y las zonas que se cuelgan de ella acabaron cortando cartas tres
veces (borde izquierdo del board, borde superior del board, zona de mano
revelada).

## El centro SÍ es más estable

Desviación típica en píxeles sobre 14 sesiones, 200 frames cada una:

| magnitud | desviación | peor sesión |
|---|---|---|
| borde izquierdo `x0` | 39,1 px | 148,9 |
| ancho `w` | **73,7 px** | 164,0 |
| **centro x** | **37,1 px** | 77,9 |
| borde superior `y0` | 33,5 px | 80,7 |
| alto `h` | 41,9 px | 81,1 |
| **centro y** | **19,1 px** | 40,7 |

El centro vertical es casi el doble de estable que el borde, y el ancho es la
magnitud PEOR de todas.

## Pero anclar al centro, por sí solo, no cambia nada

Es álgebra, no una cuestión empírica:

    anclado al borde:   x0 + f·w
    anclado al centro:  cx + (f−0,5)·w  =  x0 + w/2 + f·w − 0,5·w  =  x0 + f·w

Son la misma expresión. Medido sobre el borde izquierdo del board (fracción 0,22),
la desviación de dónde cae la zona es **35,7 px con las dos formas**, idéntica.

La razón es que una zona depende de DOS cosas: el origen y la escala. Cambiar el
origen del borde al centro no toca la escala, y la escala es `w`, que es
precisamente la magnitud más inestable.

## La parte que sí falta: una ESCALA estable

Y ahí hay un candidato medido: **el ancho de una carta**.

| | ancho del núcleo | ancho de carta |
|---|---|---|
| desviación típica | 12 a 164 px | **0,7 a 8,4 px** |
| mediana de la desviación | ~68 px sobre ~1000 (6,8 %) | ~3,4 px sobre ~85 (**4,0 %**) |
| valores distintos por sesión | 4 a 25 | **4 a 9** |

Fijada por sesión —igual que se fija hoy la referencia— la escala por carta
quedaría con un error de ~1-2 % frente al 3-4 % del óvalo: **9-18 px en vez de
27-36** sobre una mesa de 900 px, que es justo por debajo del umbral en el que una
zona empieza a morder.

Tiene sentido físico: el cliente dibuja la carta con un tamaño fijo para un tamaño
de ventana dado, y la carta es un rectángulo de bordes nítidos. El óvalo, en
cambio, se difumina contra el marco de madera y contra un fondo que en algunos
temas es del mismo verde que el tapete.

## La forma completa de la idea

    origen  = centro del óvalo          (37 px de desviación en x, 19 en y)
    escala  = ancho de carta / referencia   (~1-2 % una vez fijada)
    zona    = origen + offset · escala

## Lo que costaría, y por qué no se ha hecho todavía

Las tres tablas por asiento de las tres disposiciones (6, 8 y 9 plazas) están
expresadas hoy en fracciones del núcleo, y se han medido una por una a lo largo de
esta campaña. Cambiar la parametrización las invalida todas: habría que volver a
derivarlas, y el trabajo de medición es la mitad de lo que hay hecho.

Además hay un huevo-y-gallina: para medir el ancho de carta hace falta la zona del
board, que hoy se cuelga del óvalo. Es resoluble —el óvalo da la escala aproximada,
la carta la afina, y se fija por sesión— pero es una secuencia nueva.

**Mientras no se haga, la estrategia es MARGEN en las zonas, no precisión en la
referencia**, y eso ya está aplicado donde se midió que hacía falta.
