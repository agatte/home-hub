"""No-argument, fictional, deterministic #131 demo; stdout is the only output."""

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.ml.action_feedback_shadow import (
    DAY,
    Context,
    Decision,
    ExpectedLink,
    Feedback,
    assess,
)


def main() -> None:
    context = Context("brightness", "2", "working", "evening", "desk", "fictional-v1")
    decisions = tuple(
        Decision(f"d{i}", f"s{i}", context, (i + 1) * DAY, 180, (i + 1) * DAY, 0.95, owner="automation", house="Home")
        for i in range(5)
    )
    events = tuple(
        Feedback(f"e{i}", d.decision_id, d.session_id, context, d.at + 60, d.at + 60,
                 "fictional_explicit_ui", "fictional_owner", "correct", 140 + i % 3)
        for i, d in enumerate(decisions)
    )
    # Fixture oracle only. This intentionally does NOT demonstrate real verification.
    expected = {e.event_id: ExpectedLink(d, e) for d, e in zip(decisions, events)}
    reversal = replace(events[-1], event_id="reversal", kind="reverse", at=5 * DAY + 90)
    expected[reversal.event_id] = ExpectedLink(decisions[-1], reversal)
    cases = {
        "before": events[:2],
        "after": events,
        "ambiguous": events + (replace(events[-1], event_id="unlinked-slider"),),
        "reversed": events + (reversal,),
    }
    print(json.dumps({
        "fictional_only": True,
        "results": {name: asdict(assess(context, decisions, rows, expected, now=6 * DAY))
                    for name, rows in cases.items()},
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
