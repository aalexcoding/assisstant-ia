"""
Guía postflop a partir de las heurísticas GTO publicadas.

QUÉ AÑADE Y QUÉ NO. Hasta ahora el postflop de esta app era una PROBABILIDAD
(decision/equity.py) y un PRECIO (decision/postflop_math.py), y decide() se
abstenía de dar una acción porque no hay rango postflop digitalizado. Sigue sin
haberlo: lo que hay aquí no es un solver ni una tabla, son las reglas públicas
que sí están enunciadas con números, aplicadas explícitamente y con su fuente.

Dos ramas, que son dos preguntas distintas:

  DEFENSA (hay una apuesta que igualar). Aquí la aritmética es cerrada: el
  precio fija la equity que hace falta (pot odds), el tamaño del rival fija
  cuántos foldeos necesitaba su farol (alpha), cuánto tiene que defender el
  hero como RANGO (MDF) y con qué mezcla de valor y farol es equilibrado ese
  tamaño. La acción sale de comparar la equity estimada con el precio.

  C-BET (no hay apuesta que enfrentar y el hero fue el agresor preflop). Aquí
  no hay aritmética cerrada: la fuente ordena texturas de "se apuesta más" a
  "se apuesta menos" y asocia tamaños. Se traduce esa ordenación a una banda de
  frecuencia y a un tamaño, y se dice que es una banda, no una frecuencia de
  solver.

LO QUE SIGUE SIENDO FALSO Y HAY QUE DECIR. La equity que entra aquí es equity
de ALL-IN contra rangos de ENTRADA al bote (ver el docstring de
decision/equity.py): no descuenta que quien apuesta el turn tiene un rango más
fuerte que quien simplemente entró preflop, ni descuenta la equity que no se
llega a realizar por estar fuera de posición. Es, típicamente, un TECHO. Por eso
el umbral de CALL exige un margen sobre el precio y por eso un empate técnico se
etiqueta como marginal en vez de convertirse en una orden.

Tampoco hay ICM, ni rake, ni lectura del rival, ni historial de esta calle más
allá de lo que el log vio.

Fuentes:
  https://blog.gtowizard.com/mdf-alpha/
  https://blog.gtowizard.com/flop-heuristics-ip-c-betting-in-cash-games/
  https://blog.gtowizard.com/the-mechanics-of-c-bet-sizing/
"""
from decision import action_log, board_texture, gto
from decision.preflop.actions import translate_into

FUENTE_NOMBRE = "GTO Wizard (MDF & Alpha · Flop Heuristics · C-Bet Sizing)"
FUENTES_URL = (
    "https://blog.gtowizard.com/mdf-alpha/",
    "https://blog.gtowizard.com/flop-heuristics-ip-c-betting-in-cash-games/",
    "https://blog.gtowizard.com/the-mechanics-of-c-bet-sizing/",
)

# Orden de habla POSTFLOP, que no es el preflop: las ciegas abren la calle y el
# botón la cierra. Se nombra aparte de engine._ORDEN_PREFLOP justo por eso.
ORDEN_POSTFLOP = ("SB", "BB", "EP1", "EP2", "MP1", "MP2", "HJ", "CO", "BTN")
_INDICE_POSTFLOP = {p: i for i, p in enumerate(ORDEN_POSTFLOP)}

# Margen que se exige SOBRE el precio para llamar CALL a un call. No es una
# constante de teoría: es el descuento explícito de un sesgo conocido y medido
# en el propio repo -la equity es de all-in contra rangos de entrada, así que
# sobreestima-. Entre el precio y el precio+margen la acción se etiqueta
# MARGINAL CALL en vez de CALL, para que el usuario vea que es un empate
# técnico y no una decisión clara. Por debajo del precio no hace falta margen
# ninguno: pagar ya es -EV incluso creyéndose la equity entera.
MARGEN_CALL_PP = 5.0

# Equity a partir de la cual se propone SUBIR por valor en vez de pagar. Alta a
# propósito: la equity es un techo y una subida se paga con la parte alta del
# rango del rival, así que el 67% teórico de "vas por delante de su rango de
# apuesta" no basta para justificarla con este dato.
EQUITY_SUBIDA_VALOR = 0.70

# Multiplicador de la subida por valor sobre la apuesta del rival. 3x es el
# tamaño de referencia habitual; se expone su alpha para que el número no se
# tome como una recomendación sin coste.
MULTIPLICADOR_SUBIDA = 3.0

_BANDAS = (
    (3, "muy alta", "por encima del 70% del rango"),
    (1, "alta", "en torno al 55-70% del rango"),
    (0, "media", "en torno al 40-55% del rango"),
    (-2, "baja", "en torno al 25-40% del rango"),
    (-99, "muy baja", "por debajo del 25% del rango"),
)


def _numero(valor):
    return (isinstance(valor, (int, float))
            and not isinstance(valor, bool))


def _positivo(valor):
    return _numero(valor) and valor > 0


def _rivales(state):
    return [p for p in state.get("players") or []
            if p.get("in_hand") and not p.get("is_hero")]


def posicion_relativa(hero_position, rivales):
    """'IP' si el hero habla el último de los que siguen, 'OOP' si no.

    None cuando falta la posición del hero o la de algún rival vivo: sin saber
    quién cierra la calle no se puede decir si hay posición, y suponerla a
    favor sería justo el error que infla una c-bet.
    """
    if hero_position not in _INDICE_POSTFLOP:
        return None
    indices = []
    for rival in rivales:
        posicion = rival.get("position")
        if posicion not in _INDICE_POSTFLOP:
            return None
        indices.append(_INDICE_POSTFLOP[posicion])
    if not indices:
        return None
    return "IP" if _INDICE_POSTFLOP[hero_position] > max(indices) else "OOP"


def _puntos_textura(textura):
    """Ordenación cualitativa de la fuente traducida a puntos.

    Cada sumando es una frase del artículo, no un ajuste libre:
      conexión   desconectado se apuesta mucho; con proyecto de escalera,
                 moderado; conectado, menos.
      palos      arcoíris es la frecuencia más alta; con proyecto de color
                 baja; monocolor baja "drásticamente".
      emparejado los boards emparejados se apuestan bastante MÁS que los no
                 emparejados.
      carta alta los boards de carta alta se apuestan más, con la excepción
                 explícita del as, que se apuesta menos.
    """
    detalle = []
    puntos = 0

    por_conexion = {"desconectado": 2, "proyecto_escalera": 0, "conectado": -2}
    valor = por_conexion[textura["conexion"]]
    puntos += valor
    detalle.append((f"conexión {textura['conexion']}", valor))

    # Por el HECHO (cuántas cartas del mismo palo hay) y no por la etiqueta: en
    # un flop "monocolor" son tres y en un turn se llaman "tres_del_palo", pero
    # es la misma situación -alguien con dos de ese palo tiene color- y merece
    # el mismo castigo. Atarlo al nombre hacía que el turn se apostase grande en
    # un board donde el color ya está servido.
    mismo_palo = textura["max_cartas_mismo_palo"]
    valor = 1 if mismo_palo <= 1 else 0 if mismo_palo == 2 else -3
    puntos += valor
    detalle.append((f"palos {textura['palos']}", valor))

    if textura["emparejado"]:
        puntos += 1
        detalle.append(("board emparejado", 1))

    por_alta = {"as": -1, "broadway_alto": 1, "broadway_bajo": 1,
                "medio": 0, "bajo": 0}
    valor = por_alta[textura["carta_alta_categoria"]]
    if valor:
        puntos += valor
        detalle.append((f"carta alta {textura['carta_alta']}", valor))
    return puntos, detalle


def _banda(puntos):
    for umbral, etiqueta, glosa in _BANDAS:
        if puntos >= umbral:
            return etiqueta, glosa
    return _BANDAS[-1][1], _BANDAS[-1][2]


def _tamano_cbet(textura, rivales_vivos):
    """(pct_del_bote, motivo, alternativa_polarizada).

    El orden de las reglas importa y es el de la fuente: lo que empuja hacia
    ABAJO manda sobre lo que empuja hacia arriba, porque quien se equivoca de
    tamaño grande en un board que no lo admite paga mucho más caro que quien se
    queda corto.
    """
    if textura["color_posible"]:
        return 33, ("con el color ya posible la fuente pide bajar frecuencia Y "
                    "tamaño"), None
    if textura["emparejado"]:
        return 33, ("los boards emparejados se apuestan más a menudo pero con "
                    "tamaño pequeño: el trío está en los dos rangos"), None
    if rivales_vivos >= 2:
        return 33, ("bote multiway: se conserva el tamaño pequeño porque cada "
                    "rival extra recorta el farol permitido"), None
    if textura["conexion"] == "conectado":
        return 66, ("board conectado: la escalera ya está en el rango del "
                    "defensor, así que se sube de tamaño para proteger pero no "
                    "se sobreapuesta"), None
    if textura["conexion"] == "proyecto_escalera":
        return 66, ("con OESD posible la fuente aumenta el 66% por protección"), None
    return 33, ("board desconectado: rango fusionado y tamaño pequeño"), 130


def _accion_bet(tamano_bb):
    return f"BET ({tamano_bb:g} BB)" if tamano_bb is not None else "BET"


def _es_agresor_preflop(state, secuencia):
    """True/False si se sabe de quién era la iniciativa, None si no.

    El resumen se recibe hecho desde engine.guia_postflop -que ya lo calcula una
    vez por frame- pero se recalcula si no viene, para que el módulo funcione
    suelto (tests, replay) sin depender de que alguien haya pasado antes.
    """
    resumen = secuencia if secuencia is not None else state.get("preflop_action")
    if not isinstance(resumen, dict):
        resumen = action_log.estado_preflop(state)
    if resumen.get("agresiones_observadas") in (None, 0):
        return False if resumen.get("nivel") == "sin_agresion_observada" else None
    return resumen.get("ultimo_agresor_seat") == "HERO"


def _hero_entra_limpio(state):
    """True si el hero no ha puesto nada en esta calle todavía.

    Decide si la subida por valor puede proponer un tamaño. El múltiplo 3x
    describe una SUBIDA sobre la apuesta del rival; si el hero ya apostó y le
    han subido, lo que tiene delante es una resubida y ese múltiplo daría un
    importe que no corresponde a nada. Ante la duda (el campo no viene en las
    sesiones antiguas) se supone que NO entra limpio, porque equivocarse hacia
    el lado de no proponer tamaño solo cuesta una línea de texto.
    """
    hero = next((p for p in state.get("players") or [] if p.get("is_hero")), None)
    if hero is None:
        return False
    puesto = hero.get("committed_calle")
    return _numero(puesto) and puesto <= 0


def _equity_de(equity_resultado):
    valor = (equity_resultado or {}).get("equity")
    if _numero(valor) and 0.0 <= valor <= 1.0:
        return float(valor)
    return None


def _base(state, textura, posicion, rivales_vivos, agresor):
    return {
        "calle": textura["calle"],
        "textura": textura,
        "textura_texto": board_texture.describir(textura),
        "posicion": posicion,
        "rivales_vivos": rivales_vivos,
        "hero_es_agresor_preflop": agresor,
        "source": "gto_heuristics",
        "source_name": FUENTE_NOMBRE,
        "source_urls": list(FUENTES_URL),
        "assumptions": [],
        "warnings": [],
    }


def _defensa(state, resultado, equity_estimada):
    """Rama con apuesta enfrente: precio, MDF y acción."""
    bote = state.get("pot")
    pagar = state.get("to_call")
    if not _positivo(bote) or not _positivo(pagar):
        resultado["motivo"] = (
            "hay una apuesta que igualar pero no se leyeron con fiabilidad el "
            "bote y el importe a pagar; sin los dos no hay precio que calcular")
        return resultado

    bote_antes = gto.bote_antes_de(bote, pagar)
    if bote_antes is None:
        resultado["motivo"] = (
            f"el bote leído ({bote:g} BB) no es mayor que el importe a pagar "
            f"({pagar:g} BB). PokerStars dibuja el bote CON la apuesta del rival "
            "dentro, así que una de las dos lecturas está mal y con ellas "
            "saldrían un alpha y un MDF inventados")
        resultado["warnings"].append(
            "bote y to_call incoherentes: no se calcula la matemática de defensa")
        return resultado

    requerida = gto.equity_requerida(pagar, bote)
    resumen = gto.resumen(pagar, bote_antes)
    resultado["spot"] = "defensa"
    resultado["precio"] = {
        "bote_mostrado_bb": round(float(bote), 2),
        "pagar_bb": round(float(pagar), 2),
        "bote_final_bb": round(float(bote) + float(pagar), 2),
        "equity_requerida": round(requerida, 4),
        "tamano_rival_pct": resumen["tamano_pct"],
        "alpha_rival": resumen["alpha"],
        "mdf": resumen["mdf"],
        "ratio_valor_farol_equilibrado": resumen["ratio_valor_farol"],
        "fraccion_farol_equilibrada": resumen["fraccion_farol"],
    }
    resultado["assumptions"].append(
        "el bote mostrado ya incluye la apuesta del rival (convenio PokerStars)")
    resultado["assumptions"].append(
        "el MDF es una propiedad del RANGO y supone faroles sin equity; en flop "
        "y turn la defensa correcta es MENOR que el MDF")

    explicacion_mdf = (
        f"Su apuesta de {resumen['tamano_pct']:.0f}% del bote necesita que se "
        f"foldee el {100 * resumen['alpha']:.0f}% para ser rentable de farol, "
        f"así que como rango hay que seguir con el {100 * resumen['mdf']:.0f}% "
        f"(MDF). En equilibrio ese tamaño se apuesta con "
        f"{resumen['ratio_valor_farol']:.1f} combos de valor por cada farol."
    )

    if equity_estimada is None:
        resultado["motivo"] = (
            "se calcula el precio y la matemática de defensa, pero sin equity "
            "estimada no se convierte en una acción")
        resultado["reasoning"] = explicacion_mdf
        return resultado

    margen_pp = 100.0 * (equity_estimada - requerida)
    resultado["precio"]["equity_estimada"] = round(equity_estimada, 4)
    resultado["precio"]["margen_pp"] = round(margen_pp, 1)

    if equity_estimada < requerida:
        resultado["action"] = "FOLD"
        veredicto = (
            f"Tu {100 * equity_estimada:.0f}% estimado queda por debajo del "
            f"{100 * requerida:.0f}% que pide el precio ({margen_pp:+.0f} puntos), "
            "y esa equity es un techo: se calcula contra rangos de ENTRADA, no "
            "contra el rango con el que se apuesta esta calle.")
    elif equity_estimada >= EQUITY_SUBIDA_VALOR and _hero_entra_limpio(state):
        subida = MULTIPLICADOR_SUBIDA * pagar
        alpha_subida = gto.alpha_de_subida(subida, bote)
        resultado["action"] = f"RAISE ({subida:g} BB)"
        resultado["subida"] = {
            "a_bb": round(float(subida), 2),
            "multiplo_de_la_apuesta": MULTIPLICADOR_SUBIDA,
            "alpha": round(alpha_subida, 4) if alpha_subida is not None else None,
        }
        resultado["assumptions"].append(
            "la subida usa el múltiplo de referencia 3x, no un tamaño de solver")
        veredicto = (
            f"Con un {100 * equity_estimada:.0f}% estimado frente al "
            f"{100 * requerida:.0f}% requerido vas muy por delante del precio: "
            f"el valor está en subir, no en pagar. Subir a {subida:g} BB "
            "arriesga esa cantidad para ganar un bote de "
            f"{bote:g} BB"
            + (f", así que necesita un {100 * alpha_subida:.0f}% de foldeos "
               "para ser rentable ya solo como farol."
               if alpha_subida is not None else "."))
    elif margen_pp >= MARGEN_CALL_PP:
        resultado["action"] = "CALL"
        veredicto = (
            f"Tu {100 * equity_estimada:.0f}% estimado supera el "
            f"{100 * requerida:.0f}% que pide el precio por {margen_pp:+.0f} "
            "puntos, margen suficiente para absorber que la equity esté "
            "calculada contra rangos de entrada.")
        if equity_estimada >= EQUITY_SUBIDA_VALOR:
            veredicto += (
                " Con esta equity el valor estaría en subir, pero ya has "
                "apostado en esta calle: lo que tienes delante es una RESUBIDA "
                "y el múltiplo de referencia 3x no describe su tamaño, así que "
                "no se propone uno.")
    else:
        resultado["action"] = "MARGINAL CALL"
        veredicto = (
            f"Tu {100 * equity_estimada:.0f}% estimado apenas cubre el "
            f"{100 * requerida:.0f}% del precio ({margen_pp:+.0f} puntos). Es un "
            f"empate técnico: por debajo de {MARGEN_CALL_PP:.0f} puntos de margen "
            "el sesgo conocido de la equity (calculada contra rangos de entrada) "
            "puede darle la vuelta.")

    resultado["reasoning"] = f"{veredicto} {explicacion_mdf}"
    resultado["confidence"] = (
        "media: el precio y el MDF son exactos; la acción depende de una equity "
        "estimada contra rangos de entrada, sin realización de equity ni ICM")
    return resultado


def _cbet(state, resultado, textura, posicion, rivales_vivos, equity_estimada):
    """Rama sin apuesta enfrente: frecuencia y tamaño de continuación."""
    resultado["spot"] = "cbet"
    puntos, detalle = _puntos_textura(textura)
    if rivales_vivos >= 2:
        # No sale de la fuente, que es heads-up: es un recorte conservador y se
        # dice. Cada rival extra multiplica las manos que continúan, así que la
        # frecuencia de continuación cae y el farol permitido se estrecha.
        puntos -= 2
        detalle.append((f"{rivales_vivos} rivales vivos (ajuste propio)", -2))
        resultado["assumptions"].append(
            "el recorte por bote multiway es un ajuste conservador propio: la "
            "fuente resuelve heads-up")

    # LA BANDA DE FRECUENCIA ES UN RESULTADO DE FLOP, y solo se da en el flop.
    # La fuente se titula "Flop Heuristics" y ordena texturas por cuánto se
    # apuesta EN EL FLOP; en turn y river la frecuencia correcta depende además
    # de qué carta ha caído, de cómo se partió el rango en la calle anterior y
    # de cuántas apuestas quedan, nada de lo cual se está mirando aquí.
    #
    # El TAMAÑO sí se conserva en las tres calles: las reglas de sizing son
    # sobre lo que el board permite al defensor -no se sobreapuesta donde hay
    # escalera servida, se apuesta pequeño con el color posible- y eso no deja
    # de ser cierto porque haya caído otra carta. Y alpha y el ratio son
    # aritmética del bote, exactos en cualquier calle.
    es_flop = textura["calle"] == "flop"
    etiqueta, glosa = _banda(puntos) if es_flop else (None, None)
    pct, motivo_tamano, alternativa = _tamano_cbet(textura, rivales_vivos)

    bote = state.get("pot")
    tamano_bb = round(bote * pct / 100.0, 2) if _positivo(bote) else None
    resumen = gto.resumen(tamano_bb, bote) if tamano_bb and _positivo(bote) else None

    resultado["cbet"] = {
        "tamano_pct_del_bote": pct,
        "tamano_bb": tamano_bb,
        "motivo_tamano": motivo_tamano,
        "alternativa_polarizada_pct": alternativa,
        "banda_frecuencia": etiqueta,
        "banda_glosa": glosa,
        "puntos_textura": puntos if es_flop else None,
        "detalle_textura": (
            [{"factor": f, "puntos": p} for f, p in detalle] if es_flop else []),
    }
    if resumen is not None:
        resultado["cbet"].update(
            alpha=resumen["alpha"],
            ratio_valor_farol=resumen["ratio_valor_farol"],
            fraccion_farol=resumen["fraccion_farol"],
        )

    resultado["action"] = _accion_bet(tamano_bb)
    partes = []
    if es_flop:
        partes.append(
            f"Board {board_texture.describir(textura)}: frecuencia de "
            f"continuación {etiqueta} ({glosa}).")
    else:
        partes.append(
            f"Board {board_texture.describir(textura)}. NO se da frecuencia: la "
            f"heurística importada es de FLOP y esto es el {textura['calle']}, "
            "donde además pesan la carta que ha caído y cómo se partió el rango "
            "en la calle anterior, que aquí no se miran. Lo que sigue valiendo "
            "es el tamaño y la aritmética del bote.")
        resultado["assumptions"].append(
            f"en {textura['calle']} solo se traslada el criterio de TAMAÑO; la "
            "banda de frecuencia se omite porque la fuente resuelve el flop")
    partes.append(
        f"Tamaño {pct}% del bote"
        + (f" ({tamano_bb:g} BB)" if tamano_bb is not None else "")
        + f" — {motivo_tamano}.")
    if resumen is not None:
        partes.append(
            f"A ese tamaño el farol necesita un {100 * resumen['alpha']:.0f}% de "
            f"foldeos y el rango que apuesta se equilibra con "
            f"{resumen['ratio_valor_farol']:.1f} combos de valor por farol.")
    if alternativa is not None:
        partes.append(
            f"En este board la fuente admite además la línea polarizada de "
            f"{alternativa}% del bote; no se recomienda por defecto porque exige "
            "ventaja de nuts, que aquí no se ha comprobado.")
    if equity_estimada is not None:
        partes.append(
            f"Tu equity estimada es {100 * equity_estimada:.0f}%: "
            + ("estás en la parte de valor de ese rango."
               if equity_estimada >= 0.55 else
               "estás en la parte de farol, así que esta mano solo apuesta "
               "dentro del cupo de faroles que permite el ratio de arriba."))
    if posicion == "OOP":
        partes.append(
            "OJO: estás FUERA de posición y la fuente resuelve la c-bet EN "
            "posición; fuera de posición la frecuencia correcta es menor.")

    resultado["reasoning"] = " ".join(partes)
    matices = []
    if not es_flop:
        matices.append(f"criterio de flop trasladado al {textura['calle']}")
    if posicion != "IP":
        matices.append("la fuente resuelve la c-bet en posición")
    resultado["confidence"] = (
        ("media" if not matices else
         "media-baja" if len(matices) == 1 else "baja")
        + ": heurística pública de c-bet en cash"
        + (f" ({'; '.join(matices)})" if matices else "")
        + ("; banda de frecuencia, no frecuencia de solver" if es_flop else ""))
    if es_flop:
        resultado["assumptions"].append(
            "las bandas de frecuencia traducen la ordenación cualitativa de la "
            "fuente; no son porcentajes publicados")
    if not _positivo(bote):
        resultado["warnings"].append(
            "no se leyó el bote: el tamaño va en porcentaje pero no en BB")
    return resultado


def evaluar(state, equity_resultado=None, secuencia=None):
    """Guía GTO postflop del frame, o None si no hay postflop que juzgar.

    ``equity_resultado`` es lo que devuelve engine.postflop_equity(). Sin él se
    siguen dando textura, precio y MDF -que no dependen de las cartas del
    hero-, pero no una acción.
    """
    board = state.get("board") or []
    textura = board_texture.clasificar(board)
    if textura is None:
        return None
    if len(state.get("hero_cards") or []) != 2 or state.get("hero_cards_dimmed"):
        return None

    rivales = _rivales(state)
    hero_position = state.get("hero_position")
    posicion = posicion_relativa(hero_position, rivales)
    agresor = _es_agresor_preflop(state, secuencia)
    resultado = _base(state, textura, posicion, len(rivales), agresor)
    equity_estimada = _equity_de(equity_resultado)

    if not rivales:
        resultado["motivo"] = (
            "no se detecta ningún rival con cartas: la mano pudo terminar o "
            "estar en showdown")
        return resultado

    if state.get("facing") == "bet" and _positivo(state.get("to_call")):
        return translate_into(_defensa(state, resultado, equity_estimada))

    if agresor is False:
        resultado["spot"] = "sin_iniciativa"
        resultado["motivo"] = (
            "el hero no fue el agresor preflop, así que esto no es una c-bet "
            "sino un donk-bet o un check-detrás. Las heurísticas importadas "
            "cubren la continuación del AGRESOR y no se extrapolan")
        return resultado
    if agresor is None:
        resultado["spot"] = "sin_iniciativa"
        resultado["motivo"] = (
            "no se pudo determinar quién fue el agresor preflop en el historial "
            "observado; sin saber de quién es la iniciativa no se recomienda "
            "una continuación")
        return resultado

    resultado = _cbet(state, resultado, textura, posicion,
                      len(rivales), equity_estimada)
    if state.get("facing") is None:
        resultado["warnings"].append(
            "no se leyeron los botones de acción: puede que no sea tu turno")
    return translate_into(resultado)
