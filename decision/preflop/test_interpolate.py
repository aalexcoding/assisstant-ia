import pytest

from decision.preflop.interpolate import (
    action_distribution,
    interpolate_actions,
)


def test_parsea_acciones_puras_y_mezclas():
    assert action_distribution("CALL") == {"CALL": 1.0}
    assert action_distribution("CALL 50% / ALL IN 50%") == {
        "CALL": 0.5,
        "ALL IN": 0.5,
    }


def test_dos_donantes_iguales_conservan_una_accion_pura():
    result = interpolate_actions(
        "OPEN RAISE", "OPEN RAISE", 40, 60, 50)
    assert result["action"] == "OPEN RAISE"
    assert result["action_probabilities"] == {"OPEN RAISE": 1.0}
    assert result["confidence"] == "media-alta"


def test_interpola_las_frecuencias_sin_sortear_una_accion():
    result = interpolate_actions(
        "OPEN RAISE",
        "LIMP 50% / OPEN RAISE 50%",
        40,
        60,
        50,
    )
    assert result["action"] == "OPEN RAISE 75% / LIMP 25%"
    assert result["action_probabilities"] == {
        "OPEN RAISE": 0.75,
        "LIMP": 0.25,
    }
    assert result["donor_stack_keys"] == [40.0, 60.0]
    assert result["disagreement"] == 0.5
    assert result["confidence"] == "media-baja"


@pytest.mark.parametrize("target", [35, 65])
def test_no_extrapola(target):
    assert interpolate_actions(
        "FOLD", "CALL", 40, 60, target) is None


def test_rechaza_un_salto_mayor_de_20bb():
    assert interpolate_actions(
        "CALL", "CALL", 60, 100, 80) is None


def test_rechaza_donantes_que_se_contradicen_por_completo():
    assert interpolate_actions(
        "FOLD", "CALL", 40, 50, 45) is None


def test_rechaza_si_la_mano_no_pertenece_al_rfi_de_un_donante():
    assert interpolate_actions(
        "NOT_IN_RFI", "CALL", 40, 50, 45) is None
