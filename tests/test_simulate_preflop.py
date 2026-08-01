from simulate_preflop import (
    _difference_label,
    _source_label,
    _spans,
    _summarize_actions,
)


def test_spans_compacta_frames_consecutivos():
    assert _spans([7, 3, 1, 2, 8, 8]) == "0001-0003, 0007-0008"


def test_fuente_distingue_heuristica_y_fallback():
    assert _source_label({
        "action": "RAISE OVER LIMPERS (7 BB)",
        "source": "public_heuristic",
        "confidence": "media",
    }) == "RAISE OVER LIMPERS (7 BB) [guía pública; confianza media]"
    assert _source_label({
        "action": "CHECK",
        "source": "safety_default",
        "confidence": "baja",
    }) == "CHECK [fallback legal; confianza baja]"
    assert _source_label({
        "action": "CALL 75% / ALL IN 25%",
        "source": "interpolated_chart",
        "confidence": "media-baja",
    }) == (
        "CALL 75% / ALL IN 25% "
        "[interpolada; confianza media-baja]"
    )


def test_resumen_no_inventa_accion_si_no_hay_recomendaciones():
    assert _summarize_actions([]) == "sin recomendación fiable"


def test_diferencia_incluye_motivo_de_abstencion():
    assert _difference_label(
        {"action": "CALL", "source": "chart"},
        None,
        "el spot es multiway",
    ) == "CALL → sin recomendación (el spot es multiway)"


def test_no_hay_diferencia_si_accion_y_fuente_son_iguales():
    old = {"action": "fold", "source": "chart"}
    new = {"action": "fold", "source": "chart"}
    assert _difference_label(old, new, None) is None
