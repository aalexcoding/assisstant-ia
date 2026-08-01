"""Interpolación conservadora entre dos celdas preflop publicadas.

Esta capa no pretende resolver póker ni generar rangos GTO. Solo combina las
frecuencias de dos tablas de la misma familia cuando la profundidad objetivo
queda estrictamente entre ambas. Si los donantes se contradicen demasiado o
alguno deja la mano fuera del árbol, se abstiene.
"""
import re


MAX_DONOR_GAP_BB = 20.0
MAX_TOTAL_VARIATION = 0.50
_EPSILON = 1e-9
_MIX_PART_RE = re.compile(
    r"^(?P<action>.+?)\s+(?P<percentage>\d+(?:[.,]\d+)?)%$",
    re.IGNORECASE,
)


def action_distribution(label):
    """Convierte una etiqueta pura o mixta en ``{acción: probabilidad}``."""
    if not label:
        return None
    text = " ".join(str(label).split())
    parts = re.split(r"\s*/\s*", text)
    if len(parts) == 1:
        return {text.upper(): 1.0}

    distribution = {}
    for part in parts:
        match = _MIX_PART_RE.match(part)
        if match is None:
            return None
        action = match.group("action").strip().upper()
        probability = float(
            match.group("percentage").replace(",", ".")) / 100.0
        if probability < 0:
            return None
        distribution[action] = distribution.get(action, 0.0) + probability
    total = sum(distribution.values())
    if total <= _EPSILON or abs(total - 1.0) > 0.011:
        return None
    return {action: probability / total
            for action, probability in distribution.items()}


def total_variation(first, second):
    """Distancia 0..1 entre dos distribuciones discretas."""
    actions = set(first) | set(second)
    return 0.5 * sum(
        abs(first.get(action, 0.0) - second.get(action, 0.0))
        for action in actions
    )


def _percentage(value):
    rounded = round(value, 1)
    if abs(rounded - round(rounded)) < _EPSILON:
        return str(int(round(rounded)))
    return f"{rounded:.1f}".rstrip("0").rstrip(".")


def format_distribution(distribution):
    """Etiqueta legible y estable; no sortea ni fuerza una acción pura."""
    clean = {
        action: probability
        for action, probability in distribution.items()
        if probability > _EPSILON
    }
    if len(clean) == 1:
        action, probability = next(iter(clean.items()))
        if abs(probability - 1.0) < _EPSILON:
            return action
    return " / ".join(
        f"{action} {_percentage(probability * 100)}%"
        for action, probability in clean.items()
    )


def interpolate_actions(
        lower_action,
        upper_action,
        lower_stack_bb,
        upper_stack_bb,
        target_stack_bb,
):
    """Interpola linealmente o devuelve ``None`` si el salto no es defendible."""
    lower_stack_bb = float(lower_stack_bb)
    upper_stack_bb = float(upper_stack_bb)
    target_stack_bb = float(target_stack_bb)
    gap = upper_stack_bb - lower_stack_bb
    if (
        gap <= 0
        or gap > MAX_DONOR_GAP_BB
        or not lower_stack_bb < target_stack_bb < upper_stack_bb
    ):
        return None

    lower = action_distribution(lower_action)
    upper = action_distribution(upper_action)
    if lower is None or upper is None:
        return None
    if "NOT_IN_RFI" in lower or "NOT_IN_RFI" in upper:
        return None

    disagreement = total_variation(lower, upper)
    if disagreement > MAX_TOTAL_VARIATION + _EPSILON:
        return None

    weight = (target_stack_bb - lower_stack_bb) / gap
    actions = list(lower)
    actions.extend(action for action in upper if action not in lower)
    mixed = {
        action: (
            lower.get(action, 0.0) * (1.0 - weight)
            + upper.get(action, 0.0) * weight
        )
        for action in actions
    }
    mixed = {
        action: round(probability, 10)
        for action, probability in mixed.items()
        if probability > _EPSILON
    }
    confidence = (
        "media-alta" if disagreement <= 0.10
        else "media" if disagreement <= 0.30
        else "media-baja"
    )
    return {
        "action": format_distribution(mixed),
        "action_probabilities": mixed,
        "donor_stack_keys": [lower_stack_bb, upper_stack_bb],
        "donor_actions": {
            f"{lower_stack_bb:g}": lower_action,
            f"{upper_stack_bb:g}": upper_action,
        },
        "interpolation_weight": round(weight, 6),
        "disagreement": round(disagreement, 6),
        "confidence": confidence,
    }
