"""Fully fictional no-argument example; stdout only, no capture/authentication."""

import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.ml.action_feedback_receipts_shadow import (
    ApplyReceipt, Coverage, DecisionReceipt, OwnerSnapshot, Stamp, UIReceipt, evaluate,
)
from backend.services.ml.action_feedback_shadow import DAY, WINDOW, Context, Decision, Feedback

C = Context("brightness", "2", "working", "evening", "desk", "fictional-v1")
NOW = 40 * DAY


def fictional_batch(count=5):
    """Separate producer literals intentionally agree; none proves a real source."""
    decisions, applies, owners, responses, submitted = [], [], [], [], []
    for i in range(count):
        at = (31 + i) * DAY
        def intent():
            return Decision(f"d{i}", f"s{i}", C, at, 180, at, .95,
                            owner="automation", house="Home")
        decisions.append(DecisionReceipt(Stamp(f"intent{i}", i + 1, at, at), intent()))
        applies.append(ApplyReceipt(Stamp(f"ack{i}", i + 1, at + 1, at + 1),
                                    intent(), True, f"owner{i}"))
        owners.append(OwnerSnapshot(Stamp(f"owner{i}", i + 1, at, at + 60), intent(),
                                    at + 60, "automation", "Home", at, at + 60, True))
        responses.append(UIReceipt(
            Stamp(f"ui{i}", i + 1, at + 60, at + 60),
            Feedback(f"e{i}", f"d{i}", f"s{i}", C, at + 60, at + 60,
                     "fictional_explicit_ui", "fictional_owner", "correct", 140),
            f"ack{i}", f"owner{i}", True, "explicit_decision_response"))
        # Submitted API-like payload is a separate literal, never an oracle.
        submitted.append(Feedback(f"e{i}", f"d{i}", f"s{i}", C, at + 60, at + 60,
                                  "fictional_explicit_ui", "fictional_owner", "correct", 140))
    streams = tuple(map(tuple, (decisions, applies, owners, responses)))
    coverage = tuple(Coverage(name, NOW - WINDOW, NOW, True, True,
                             tuple(r.stamp.receipt_id for r in rows))
                     for name, rows in zip(("decision", "apply", "owner", "ui"), streams))
    return (*streams, tuple(submitted), coverage)


def main():
    batch = fictional_batch()
    no_ack = list(batch)
    no_ack[1] = (replace(batch[1][0], acknowledged=False),) + batch[1][1:]
    partial = list(batch)
    partial[5] = (replace(batch[5][0], continuous=False),) + batch[5][1:]
    reversal = list(batch)
    reversal[3] = batch[3][:-1] + (replace(batch[3][-1], response=replace(
        batch[3][-1].response, kind="reverse")),)
    reversal[4] = batch[4][:-1] + (replace(batch[4][-1], kind="reverse"),)
    cases = {"before_two": fictional_batch(2), "after_five": batch,
             "missing_final_ack": no_ack, "partial_coverage": partial, "reversal": reversal}
    print(json.dumps({"fictional_only": True, "evidence_scope": "unverified_offline_claims",
                      "results": {k: asdict(evaluate(C, *v, now=NOW)) for k, v in cases.items()}},
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
