"""Contrato de la tabla pública suplementaria CALL VS OPEN-PUSH."""
import itertools

from decision.preflop import open_push
from decision.preflop.lookup import RANKS


def _all_hand_classes():
    hands = set()
    for i, hi in enumerate(RANKS):
        for j, lo in enumerate(RANKS):
            if i == j:
                hands.add(hi + lo)
            elif i < j:
                hands.add(hi + lo + "s")
            else:
                hands.add(lo + hi + "o")
    return hands


def _recommend(cards, hero="BB", vs="HJ", **overrides):
    args = {
        "hero_cards": cards,
        "hero_position": hero,
        "vs_position": vs,
        "effective_stack_bb": 10.0,
        "table_max_players": 8,
        "seated_players": 8,
        "ante_total_bb": 1.0,
    }
    args.update(overrides)
    return open_push.recommend(**args)


def test_tabla_tiene_los_28_spots_de_respuesta_8max():
    table = open_push.ranges()["call_vs_open_push"]["10"]
    assert sum(len(vs) for vs in table.values()) == 28
    expected = {
        (hero, vs)
        for hero_index, hero in enumerate(("EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB"))
        for vs in ("EP2", "MP1", "MP2", "HJ", "CO", "BTN", "SB", "BB")[:hero_index]
    }
    actual = {(hero, vs) for hero, spots in table.items() for vs in spots}
    assert actual == expected


def test_todas_las_celdas_son_manos_validas_y_sin_solapamientos():
    valid = _all_hand_classes()
    for spots in open_push.ranges()["call_vs_open_push"]["10"].values():
        for buckets in spots.values():
            flattened = list(itertools.chain.from_iterable(buckets.values()))
            assert set(flattened) <= valid
            assert len(flattened) == len(set(flattened))


def test_call_fold_y_celda_mixta_se_conservan():
    assert _recommend(["As", "Ah"])["action"] == "CALL"
    assert _recommend(["7s", "2h"])["action"] == "FOLD"
    assert _recommend(["4s", "4h"], hero="BTN", vs="MP2")["action"] == \
        "CALL 50% / FOLD 50%"
    assert _recommend(["Ts", "9s"], hero="BB", vs="BTN")["action"] == \
        "CALL 50% / FOLD 50%"


def test_no_extrapola_formato_profundidad_ante_ni_numero_activo():
    assert _recommend(["As", "Ah"], table_max_players=6) is None
    assert _recommend(["As", "Ah"], seated_players=7) is None
    assert _recommend(["As", "Ah"], effective_stack_bb=11.0) is None
    assert _recommend(["As", "Ah"], ante_total_bb=0.0) is None


def test_metadata_de_procedencia_viaja_con_la_recomendacion():
    result = _recommend(["As", "Ah"])
    assert result["source"] == "supplemental_chart"
    assert result["source_name"] == "8-Max MTT 10BB Tournament Poker Charts"
    assert result["source_url"].startswith("https://rangeconverter.com/")
