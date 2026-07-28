"""
Fase 4.4: ESTUDIO POST-MANO. Cuando una mano termina, busca en las
transcripciones de los videos los trozos que hablan de situaciones parecidas.

QUE ES Y QUE NO ES. Esto NO es consejo sobre la mano que acabas de jugar. Lo que
devuelve es prosa recuperada de un video por parecido semantico: puede hablar de
un board parecido con stacks distintos, o de la idea general y no de tu caso.
Presentarlo como "deberias haber hecho X" seria afirmar algo inverificable sobre
una mano concreta, que es justo lo que este proyecto evita.

Por eso vive AQUI, en el post-mano, y no en el motor de decision:

  - la mano ya ha terminado, asi que no hay ninguna accion que condicionar;
  - la latencia no importa (la primera consulta carga el modelo y tarda segundos);
  - y el encuadre honesto es "mira este minuto de este video", con el video y el
    timestamp delante, para que se pueda comprobar.

LA CONSULTA se construye de lo que se sabe de la mano terminada: el board que se
llego a ver, la mano ganadora tal y como la escribio el cliente en el chat, y si
el hero llego al showdown. Es poco, pero es lo unico verificable: inventar
detalles ("tenias iniciativa", "el rival era agresivo") para enriquecer la
busqueda seria meter en la consulta cosas que no se han observado.

describir() es puro y se puede probar sin indice ni modelo.
"""

# Cuantos trozos se ofrecen. Pocos: son minutos de video que hay que ver, y una
# lista larga no se mira.
K_POR_DEFECTO = 3

# Por debajo de esta similitud no se enseña nada. El indice SIEMPRE devuelve los k
# mas parecidos, aunque el mas parecido no se parezca en nada; sin umbral, una
# mano rara acabaria con tres referencias irrelevantes presentadas como si
# vinieran a cuento.
SIMILITUD_MINIMA = 0.45


def describir(board=None, mano_ganadora=None, hero_en_showdown=None, calle=None):
    """Texto de consulta a partir de lo que se sabe de la mano terminada.

    Solo entra lo OBSERVADO. Nada de suponer iniciativa, tipo de rival ni
    intenciones: eso enriqueceria la busqueda a cambio de buscar una mano que no
    es la que se jugo."""
    partes = []
    cartas = [c for c in (board or []) if c]
    if cartas:
        partes.append("board " + " ".join(cartas))
        partes.append(_textura(cartas))
    if calle:
        partes.append(calle)
    if mano_ganadora:
        partes.append(f"mano ganadora {mano_ganadora}")
    if hero_en_showdown is True:
        partes.append("mano que llega a showdown")
    elif hero_en_showdown is False:
        partes.append("mano que se gana sin showdown")
    return " ".join(p for p in partes if p).strip()


_PALOS = {"h": "corazones", "d": "diamantes", "c": "treboles", "s": "picas"}
_ALTAS = {"A", "K", "Q", "J", "T"}


def _textura(cartas):
    """Dos rasgos del board que sí se pueden leer de las cartas, sin suponer
    nada: si hay pareja y si hay proyecto de color."""
    rangos = [c[:-1] for c in cartas]
    palos = [c[-1].lower() for c in cartas]
    rasgos = []
    if len(set(rangos)) < len(rangos):
        rasgos.append("board emparejado")
    mas_comun = max((palos.count(p) for p in set(palos)), default=0)
    if mas_comun >= 3:
        rasgos.append("board monocolor")
    elif mas_comun == 2:
        rasgos.append("board con dos del mismo palo")
    else:
        rasgos.append("board rainbow")
    if sum(1 for r in rangos if r in _ALTAS) >= 2:
        rasgos.append("board con cartas altas")
    return " ".join(rasgos)


def buscar(texto, k=K_POR_DEFECTO, minimo=SIMILITUD_MINIMA):
    """Trozos de video parecidos, o [] si no hay indice o nada supera el umbral.

    Nunca lanza: si falta el indice o el modelo, el panel de estudio se queda
    vacio y la app sigue. Es una ayuda para despues, no parte del analisis."""
    if not texto:
        return []
    try:
        from decision.rag import query
        crudos = query.search(texto, k=k)
    except SystemExit:
        return []            # query._load_index sale si no hay indice construido
    except Exception:        # noqa: BLE001 - falta fastembed, modelo sin descargar...
        return []
    salida = []
    for r in crudos:
        try:
            score = float(r.get("score", 0))
        except (TypeError, ValueError):
            continue
        if score < minimo:
            continue
        salida.append({
            "video": r.get("video"),
            "inicio_s": float(r.get("start_time") or 0),
            "fin_s": float(r.get("end_time") or 0),
            "texto": (r.get("text") or "").strip(),
            "score": score,
        })
    return salida


def estudiar(board=None, mano_ganadora=None, hero_en_showdown=None, calle=None,
             k=K_POR_DEFECTO):
    """describir() + buscar(). Devuelve {"consulta", "referencias"}."""
    texto = describir(board, mano_ganadora, hero_en_showdown, calle)
    return {"consulta": texto, "referencias": buscar(texto, k=k)}


def minuto(segundos):
    """72.4 -> '1:12', para poder saltar al punto del video."""
    s = int(segundos or 0)
    return f"{s // 60}:{s % 60:02d}"
