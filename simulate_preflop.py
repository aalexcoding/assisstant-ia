"""Simula el motor preflop actual sobre estados ya reconocidos de una sesión.

Esta herramienta no vuelve a ejecutar OCR ni pretende reconstruir qué habrían
hecho los rivales ante una acción distinta. Responde a una pregunta más precisa
y reproducible: con la información que quedó guardada en cada frame, ¿qué
recomendación habría mostrado la versión actual?

Uso:

    .venv/bin/python simulate_preflop.py testing/sesion-A testing/sesion-B
    .venv/bin/python simulate_preflop.py --latest 4 --output informe.md
"""

import argparse
import copy
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from decision import engine, journal
from decision.preflop.lookup import normalize_hand


ROOT = Path(__file__).resolve().parent
TESTING_DIR = ROOT / "testing"


@dataclass
class HandSimulation:
    number: int
    first_frame: int
    last_frame: int
    cards: Counter = field(default_factory=Counter)
    positions: Counter = field(default_factory=Counter)
    current: list = field(default_factory=list)
    differences: list = field(default_factory=list)


def _frame_files(session):
    return sorted(
        session.glob("[0-9][0-9][0-9][0-9].json"),
        key=lambda path: int(path.stem),
    )


def _metadata(session):
    try:
        value = json.loads((session / "_sesion.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _source_label(recommendation):
    if not recommendation:
        return None
    action = recommendation.get("action")
    source = recommendation.get("source")
    confidence = recommendation.get("confidence")
    if source == "public_heuristic":
        return f"{action} [guía pública; confianza {confidence}]"
    if source == "safety_default":
        return f"{action} [fallback legal; confianza {confidence}]"
    if str(source).startswith("interpolated_chart"):
        confidence_level = str(confidence or "?").split(":", 1)[0]
        return f"{action} [interpolada; confianza {confidence_level}]"
    return action


def _spans(numbers):
    """Convierte [1, 2, 3, 7] en ``0001-0003, 0007``."""
    if not numbers:
        return ""
    values = sorted(set(numbers))
    groups = []
    start = previous = values[0]
    for number in values[1:]:
        if number == previous + 1:
            previous = number
            continue
        groups.append((start, previous))
        start = previous = number
    groups.append((start, previous))
    return ", ".join(
        f"{start:04d}" if start == end else f"{start:04d}-{end:04d}"
        for start, end in groups
    )


def _summarize_actions(entries):
    grouped = defaultdict(list)
    for frame, label in entries:
        grouped[label].append(frame)
    if not grouped:
        return "sin recomendación fiable"
    return "; ".join(
        f"{label} (f. {_spans(frames)})"
        for label, frames in grouped.items()
    )


def _difference_label(old, new, reason):
    old_label = _source_label(old) or "sin recomendación"
    new_label = _source_label(new) or "sin recomendación"
    if old_label == new_label:
        return None
    if new is None and reason:
        return f"{old_label} → sin recomendación ({reason})"
    return f"{old_label} → {new_label}"


def simulate_session(session):
    """Devuelve la simulación agrupada por ``mano_seguida``."""
    session = Path(session)
    metadata = _metadata(session)
    context = engine.DecisionContext()
    hands = {}

    for path in _frame_files(session):
        try:
            recorded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        state = copy.deepcopy(recorded.get("state") or {})
        hand_number = state.get("mano_seguida")
        if not isinstance(hand_number, int):
            continue

        frame = recorded.get("n")
        if not isinstance(frame, int):
            frame = int(path.stem)
        hand = hands.setdefault(
            hand_number,
            HandSimulation(hand_number, frame, frame),
        )
        hand.last_frame = frame

        cards = state.get("hero_cards") or []
        if len(cards) == 2:
            normalized = normalize_hand(cards)
            if normalized:
                hand.cards[normalized] += 1
            position = state.get("hero_position")
            if position:
                hand.positions[position] += 1

        state["max_players"] = metadata.get("max_players")
        state.setdefault("warnings", [])
        old = recorded.get("recommendation")
        before_warnings = len(state["warnings"])
        new = engine.decide(state, context=context)
        new_label = _source_label(new)
        if new_label:
            hand.current.append((frame, new_label))

        added_warnings = state["warnings"][before_warnings:]
        reason = added_warnings[-1] if new is None and added_warnings else None
        difference = _difference_label(old, new, reason)
        if difference:
            hand.differences.append((frame, difference))
    return metadata, list(hands.values())


def _modal(counter):
    return counter.most_common(1)[0][0] if counter else "no leída"


def _summarize_differences(entries):
    grouped = defaultdict(list)
    for frame, label in entries:
        grouped[label].append(frame)
    if not grouped:
        return "sin cambios"
    return "; ".join(
        f"{label} (f. {_spans(frames)})"
        for label, frames in grouped.items()
    )


def render_markdown(sessions):
    lines = [
        "# Simulación preflop sobre las sesiones recientes",
        "",
        "La simulación reutiliza el estado reconocido que quedó guardado en cada "
        "frame y ejecuta el motor actual. No vuelve a hacer OCR y no estima un "
        "bankroll contrafactual: una acción distinta habría cambiado las "
        "respuestas rivales y el desarrollo posterior.",
        "",
    ]
    total_hands = 0
    total_changed = 0
    for session in sessions:
        metadata, hands = simulate_session(session)
        total_hands += len(hands)
        changed = sum(bool(hand.differences) for hand in hands)
        total_changed += changed
        lines.extend([
            f"## {Path(session).name}",
            "",
            f"{len(hands)} ventanas de mano seguidas por la app; "
            f"{changed} con alguna diferencia de acción o procedencia frente a "
            "la versión grabada.",
            "",
            "| Mano | Frames | Cartas | Pos. | Motor actual | Diferencias |",
            "|---:|:---:|:---:|:---:|:---|:---|",
        ])
        for hand in hands:
            lines.append(
                f"| {hand.number} | {hand.first_frame:04d}-{hand.last_frame:04d} "
                f"| {_modal(hand.cards)} | {_modal(hand.positions)} "
                f"| {_summarize_actions(hand.current)} "
                f"| {_summarize_differences(hand.differences)} |"
            )
        lines.append("")
    lines.extend([
        "## Totales",
        "",
        f"- {len(sessions)} sesiones.",
        f"- {total_hands} ventanas de mano.",
        f"- {total_changed} manos con al menos una diferencia frente a lo grabado.",
        "",
        "Una ventana sin cartas o sin recomendación no se rellena por analogía: "
        "significa que el estado almacenado no permite una decisión fiable con "
        "las tablas disponibles.",
        "",
    ])
    return "\n".join(lines)


def _latest_sessions(count):
    sessions = sorted(path for path in TESTING_DIR.glob("sesion-*") if path.is_dir())
    return sessions[-count:]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sessions", nargs="*", type=Path)
    parser.add_argument("--latest", type=int, default=None,
                        help="usa las N sesiones más recientes")
    parser.add_argument("--output", type=Path,
                        help="guarda el Markdown además de imprimir su ruta")
    args = parser.parse_args()

    sessions = args.sessions
    if args.latest is not None:
        if args.latest <= 0:
            parser.error("--latest debe ser mayor que cero")
        sessions = _latest_sessions(args.latest)
    if not sessions:
        parser.error("indica al menos una sesión o usa --latest N")
    missing = [str(path) for path in sessions if not path.is_dir()]
    if missing:
        parser.error("no existen: " + ", ".join(missing))

    journal.set_enabled(False)
    report = render_markdown(sessions)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(args.output.resolve())
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
