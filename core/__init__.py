"""El nucleo de la app: un ciclo de analisis de un frame, sin GUI.

    from core import Analizador

    an = Analizador(max_players=6)
    res = an.analizar(frame)        # array BGR o ruta de imagen
    res.recommendation, res.equity, res.state

Lo consumen la GUI (gui.py), el lazo de diagnostico (alpha.py), el replay de
sesiones grabadas (replay.py) y la suite de tests. Es el mismo codigo en los
cuatro: si el analisis cambia, cambia para todos a la vez.
"""
from core.analisis import (VIGILANCIA_OCR_MIN_S, VIGILANCIA_PERIODO_S,
                           Analisis, Analizador, Vigilancia)

__all__ = ["Analisis", "Analizador", "Vigilancia",
           "VIGILANCIA_OCR_MIN_S", "VIGILANCIA_PERIODO_S"]
