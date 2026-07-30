"""
Calibración por CONTENIDO: comprobar si las zonas están cortando lo que deben leer.

SE APOYA EN LO QUE HAY, NO LO SUSTITUYE. Las zonas siguen siendo fracciones del
núcleo del tapete (seat_map) y la referencia se sigue fijando igual. Esto no toca
nada de eso: mide si el resultado está bien puesto y dice cuánto habría que
corregir si no lo está.

POR QUE HACE FALTA. `find_reference` no es reproducible frame a frame: el ancho
del núcleo tiene varios modos separados hasta 69 px en la misma mesa quieta -que
es el grosor del marco de madera por los dos lados- y `ReferenciaFijada` se queda
con uno según los primeros frames que le tocaron. Se intentaron cinco formas de
estabilizarlo y ninguna gana (ver REF_MIN_PARA_FIJAR y docs/ANCLAR-LAS-ZONAS.md).
Consecuencia medida: tres zonas distintas acabaron cortando su contenido sin que
nada avisara.

    borde izquierdo del board   536 de 3.241 cajas de carta salían mordidas (16,5%)
    borde superior del board    el 127% de las cartas tocaban el borde
    zona de mano revelada       el asiento UR perdía sus dos cartas SIEMPRE

Las tres se encontraron a mano, una por una, y las tres tenían la misma firma: el
objeto detectado ARRANCA O TERMINA exactamente en el borde de su zona. Esto
convierte ese diagnóstico manual en un instrumento.

LA IDEA ES DEL USUARIO, y su forma original era colgar las zonas del centro del
óvalo en vez del borde. Medido, eso por sí solo es un no-op -es la misma expresión
algebraica- pero la parte de "no depender de que el frame sea pixel perfect" es la
buena, y esta es la versión que se puede añadir sin re-derivar las nueve tablas de
zonas que hay calibradas.

QUE NO HACE. No corrige nada por su cuenta. Devuelve medidas; quien las use
decide. Se mantiene fuera del ciclo de análisis a propósito: la calibración es
algo que se pasa sobre una sesión grabada, no un paso más de cada frame.
"""
# Cuánto tiene que faltarle a una caja para el borde de su zona para considerarla
# CORTADA. En píxeles, no en fracciones: es un margen de decisión sobre una
# medida de píxeles, y con fracciones dependería del tamaño de la zona.
#
# 2 px y no 0 porque el detector devuelve enteros y el borde de la zona también,
# así que una caja que llega justo puede caer en el borde o a un píxel de él sin
# que signifique nada distinto.
HOLGURA_PX = 2

# Cuánta diferencia de ancho entre cajas de la MISMA zona delata un recorte. Las
# cartas de un board miden lo mismo -medido: 82, 82, 83 en un frame real- así que
# una que se queda en el 85% de la más ancha no es una carta más estrecha, es una
# carta mordida. Medido en el caso que lo destapó: 67 px contra 82-83, y en la
# mano revelada de UR, 41 px contra 81.
ANCHO_MIN_RELATIVO = 0.85


def bordes_tocados(caja, zona_px, holgura=HOLGURA_PX):
    """{lado: bool} de los bordes de `zona_px` que toca `caja`.

    `caja` es (x, y, w, h) en píxeles absolutos, como las que devuelve
    table_state._cajas_de_carta. Tocar un borde no prueba que haya recorte -una
    carta puede acabar justo ahí- pero es la condición necesaria, y combinado con
    el ancho relativo lo delata."""
    x, y, w, h = caja
    zx0, zy0, zx1, zy1 = zona_px
    return {"izq": x - zx0 <= holgura,
            "der": zx1 - (x + w) <= holgura,
            "arr": y - zy0 <= holgura,
            "aba": zy1 - (y + h) <= holgura}


def recorte_de_zona(cajas, zona_px, holgura=HOLGURA_PX,
                    ancho_min=ANCHO_MIN_RELATIVO):
    """¿Está esta zona cortando lo que detecta? Devuelve un dict con el veredicto.

    SE EXIGEN LAS DOS COSAS: que la caja toque un borde Y que sea más estrecha que
    sus hermanas. Con una sola no vale:

      - solo tocar el borde da falsos positivos constantes. Medido sobre el corpus,
        el 127% de las cartas de board tocaban el borde superior y solo algunas
        estaban cortadas; y las zonas de nameplate lo tocan el 63-87% de las veces
        porque su máscara coge también las sillas y el fondo oscuro.
      - solo el ancho no dice DONDE está el problema, y sin eso no se puede sugerir
        una corrección.

    `cajas` son (x, y, w, h). Con menos de dos no hay con qué comparar anchos, así
    que se devuelve sin veredicto: es honesto y es el caso del hero, que solo tiene
    dos cartas y a veces una."""
    if len(cajas) < 2:
        return {"recorta": False, "motivo": "menos de dos cajas: nada que comparar",
                "lados": {}, "estrechas": 0, "total": len(cajas)}
    anchos = [c[2] for c in cajas]
    mas_ancha = max(anchos)
    lados = {}
    estrechas = 0
    for caja in cajas:
        if caja[2] >= ancho_min * mas_ancha:
            continue
        estrechas += 1
        for lado, tocado in bordes_tocados(caja, zona_px, holgura).items():
            if tocado:
                lados[lado] = lados.get(lado, 0) + 1
    return {"recorta": bool(lados), "motivo": "", "lados": lados,
            "estrechas": estrechas, "total": len(cajas),
            "ancho_max": mas_ancha,
            "ancho_min": min(anchos)}


def correccion_sugerida(veredicto, zona_frac, ref):
    """Cuánto habría que mover el borde culpable, EN FRACCIONES DEL NUCLEO.

    Devuelve {lado: delta} para sumar a la fracción correspondiente de la zona, o
    {} si no hay recorte. El signo va en la dirección de AGRANDAR la zona por el
    lado que corta, que es la corrección segura: agrandar puede meter ruido -y eso
    se ve en el recuento de cajas- mientras que dejar la carta mordida cambia el
    rango que se lee, que es un error silencioso. Medido: una carta mordida de 67
    px se leía 'A' donde había un '4'.

    La cantidad sale de cuánto le falta a la caja estrecha para tener el ancho de
    sus hermanas, convertido a fracción del núcleo. No se redondea al alza: quien
    lo aplique debería comprobar que con eso basta, porque el temblor de la
    referencia puede pedir más margen del que este frame delata."""
    if not veredicto.get("recorta"):
        return {}
    falta_px = veredicto["ancho_max"] - veredicto["ancho_min"]
    if falta_px <= 0:
        return {}
    ancho_nucleo = max(1, ref[2])
    alto_nucleo = max(1, ref[3])
    out = {}
    for lado in veredicto["lados"]:
        if lado in ("izq", "der"):
            out[lado] = round(falta_px / ancho_nucleo, 4) * (-1 if lado == "izq" else 1)
        else:
            out[lado] = round(falta_px / alto_nucleo, 4) * (-1 if lado == "arr" else 1)
    return out


def escala_de_carta(cajas):
    """El ancho de carta de este frame, o None si no hay dos cajas de acuerdo.

    ES LA MEDIDA MAS ESTABLE QUE HAY para juzgar la escala de la mesa, y por eso
    esta funcion existe. Medido sobre 14 sesiones, desviacion tipica del ancho:

        ancho del nucleo del tapete    12 a 164 px
        ancho de una carta            0,7 a 8,4 px

    Tiene sentido fisico: la carta es un rectangulo de bordes nitidos y el ovalo se
    difumina contra el marco de madera y, en algunos temas, contra un fondo del
    mismo verde que el tapete.

    NO se usa para DEDUCIR el ancho del nucleo, y eso tambien esta medido: la razon
    carta/nucleo va de 0,0749 a 0,0952 entre sesiones (7,2% de desviacion), asi que
    dividir por una constante daria mas error del que hay. Lo que si vale es
    comparar la escala de HOY con la de cuando se calibro: si la carta mide lo
    mismo y el nucleo no, el que se equivoca es el nucleo.

    Se pide acuerdo entre al menos dos cajas -mismo ancho dentro del 15%- para no
    tomar como escala una caja que ya viene mordida."""
    if len(cajas) < 2:
        return None
    anchos = sorted(c[2] for c in cajas)
    mediana = anchos[len(anchos) // 2]
    de_acuerdo = [a for a in anchos if abs(a - mediana) <= 0.15 * mediana]
    if len(de_acuerdo) < 2:
        return None
    return int(sum(de_acuerdo) / len(de_acuerdo))
