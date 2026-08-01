"""Fallback explícito para la opción de la BB con varios limpers.

No es una tabla GTO ni forma parte de las capturas ZeroS del usuario. Cubre solo
el hueco que puede resolverse sin fingir precisión:

* AA/KK construyen bote por valor incluso contra varios limpers;
* el resto hace CHECK, que es una acción legal y gratuita, marcada como fallback
  de baja confianza porque puede dejar escapar otros raises rentables.

El tamaño sigue la guía pública citada en ``SOURCE_URL``: 3 BB de base, una BB
por limper y una BB adicional por estar fuera de posición. No se extrapola esa
regla a otras posiciones ni a situaciones donde ya hubo una subida.
"""

from decision.preflop.lookup import normalize_hand


SOURCE_NAME = "Preflop Wizard — Poker Isolation Raise Strategy"
SOURCE_URL = "https://www.preflopwizard.app/blog/poker-iso-raise-strategy"
PREMIUM_VALUE = frozenset({"AA", "KK"})


def iso_size_bb(limpers):
    """Tamaño total de la subida, o None si el recuento no es utilizable."""
    if isinstance(limpers, bool) or not isinstance(limpers, int) or limpers < 2:
        return None
    return float(4 + limpers)  # 3 base + limpers + 1 OOP


def recommend(hero_cards, stack_bb, limpers):
    """Devuelve una recomendación trazable solo para BB con 2+ limpers."""
    size = iso_size_bb(limpers)
    hand = normalize_hand(hero_cards)
    if size is None or hand is None:
        return None
    if not isinstance(stack_bb, (int, float)) or isinstance(stack_bb, bool):
        return None
    if stack_bb <= 0:
        return None

    assumptions = [
        f"se observaron {limpers} limpers y ninguna subida",
        "el fallback solo considera AA/KK como raises multiway demostrados",
        "no incorpora perfiles rivales, ICM ni riesgo de limp-reraise",
    ]
    if hand in PREMIUM_VALUE:
        action = "ALL IN" if stack_bb <= size else (
            f"RAISE OVER LIMPERS ({size:g} BB)")
        return {
            "action": action,
            "source": "public_heuristic",
            "source_name": SOURCE_NAME,
            "source_url": SOURCE_URL,
            "confidence": "media",
            "donor": SOURCE_NAME,
            "assumptions": assumptions,
            "limpers": limpers,
            "iso_size_bb": size,
            "fallback": False,
        }

    return {
        "action": "CHECK",
        "source": "safety_default",
        "source_name": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "confidence": "baja",
        "donor": "fallback legal de la opción de la BB",
        "assumptions": assumptions + [
            "CHECK no afirma que la mano carezca de un raise rentable; falta una tabla multiway",
        ],
        "limpers": limpers,
        "iso_size_bb": size,
        "fallback": True,
    }
