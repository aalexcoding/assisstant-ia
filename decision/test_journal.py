import json

from decision.journal import DecisionJournal


def test_el_diario_guarda_una_decision_en_jsonl(tmp_path):
    path = tmp_path / "decisions.jsonl"
    diary = DecisionJournal(path=str(path), active=True)
    diary.record({"image": "f.png", "hero_cards": ["Ah", "Kd"], "board": []},
                 {"action": "FOLD", "stack_bb": 20.0, "facing_used": "open_raise"}, None)
    row = json.loads(path.read_text().strip())
    assert row["image"] == "f.png"
    assert row["action"] == "FOLD"
    assert row["stack_bb"] == 20.0


def test_el_diario_apagado_no_crea_archivo(tmp_path):
    path = tmp_path / "decisions.jsonl"
    DecisionJournal(path=str(path), active=False).record({}, None, "faltan cartas")
    assert not path.exists()


def test_el_diario_conserva_procedencia_y_stack_efectivo(tmp_path):
    path = tmp_path / "decisions.jsonl"
    diary = DecisionJournal(path=str(path), active=True)
    diary.record(
        {"image": "f.png", "board": []},
        {"action": "CALL", "stack_bb": 30.0, "effective_stack_bb": 10.0,
         "facing_used": "call_vs_open_push", "source": "supplemental_chart"},
        None,
    )
    row = json.loads(path.read_text().strip())
    assert row["source"] == "supplemental_chart"
    assert row["effective_stack_bb"] == 10.0
