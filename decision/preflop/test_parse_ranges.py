from decision.preflop.parse_ranges import store_threebet_spot


class _DigitizerStub:
    def __init__(self):
        self.failures = []


def test_una_posicion_ocr_duplicada_no_sobrescribe_el_primer_spot():
    dig = _DigitizerStub()
    result = {"threebet_call": {"20": {}}}
    first = {"CALL": ["AA"]}
    duplicate = {"fold": ["AA"]}

    assert store_threebet_spot(
        dig, result, "20", "BB", "MP1", first, "first.png") is True
    assert store_threebet_spot(
        dig, result, "20", "BB", "MP1", duplicate, "duplicate.png") is False

    assert result["threebet_call"]["20"]["BB"]["MP1"] is first
    assert len(dig.failures) == 1
    assert "posición duplicada BB vs MP1" in dig.failures[0][1]
