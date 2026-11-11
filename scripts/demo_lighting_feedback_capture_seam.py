"""Deterministic fictional fixtures only; no real consent, capture or provenance."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.ml.action_feedback_receipts_shadow import (
    ApplyReceipt, DecisionReceipt, OwnerSnapshot, Stamp, UIReceipt,
)
from backend.services.ml.action_feedback_shadow import DAY, Context, Decision, Feedback
from backend.services.ml.lighting_feedback_capture_seam import (
    CaptureSession, SyntheticConsent, SyntheticPort,
)

C = Context("brightness", "2", "working", "evening", "desk", "fictional-v1")
START = 31 * DAY
END = 36 * DAY


def consent():
    return SyntheticConsent(C, "fictional_owner", START, END,
                            ("accept", "correct", "reject", "reverse"), explicit=True)


def records(i):
    at = START + i * DAY

    def intent():
        return Decision(f"d{i}", f"s{i}", C, at, 180, at, .95,
                        owner="automation", house="Home")

    def response():
        return Feedback(f"e{i}", f"d{i}", f"s{i}", C, at + 60, at + 60,
                        "fictional_explicit_ui", "fictional_owner", "correct", 140)

    return (
        DecisionReceipt(Stamp(f"d-receipt{i}", i + 1, at, at), intent()),
        ApplyReceipt(Stamp(f"ack{i}", i + 1, at + 1, at + 1), intent(), True, f"owner{i}"),
        OwnerSnapshot(Stamp(f"owner{i}", i + 1, at, at + 60), intent(), at + 60,
                      "automation", "Home", at, at + 60, True),
        UIReceipt(Stamp(f"ui{i}", i + 1, at + 60, at + 60), response(), f"ack{i}",
                  f"owner{i}", True, "explicit_decision_response"),
        # Independent submission literal; never used to construct producer oracle.
        Feedback(f"e{i}", f"d{i}", f"s{i}", C, at + 60, at + 60,
                 "fictional_explicit_ui", "fictional_owner", "correct", 140),
    )


def ports(session):
    return tuple(SyntheticPort(session.identity, name, True, "fictional_owner", True)
                 for name in ("decision", "apply", "owner", "ui"))


def feed(session, rows, *, revision=1):
    p = ports(session)
    return (
        session.decision(rows[0], p[0], revision=revision, now=rows[0].stamp.captured_at),
        session.final_ack(rows[1], p[1], revision=revision, now=rows[1].stamp.captured_at),
        session.owner_context(rows[2], p[2], revision=revision, now=rows[2].stamp.captured_at),
        session.explicit_feedback(rows[3], p[3], rows[4], revision=revision,
                                  now=rows[3].stamp.captured_at),
    )


def fictional_bundle():
    session = CaptureSession.synthetic_for_tests(consent())
    for i in range(5):
        assert all(feed(session, records(i)))
    return session.seal(now=END - 1)


def main():
    inactive = CaptureSession()
    assert not any(feed(inactive, records(0)))
    gap = CaptureSession.synthetic_for_tests(consent())
    feed(gap, records(0))
    gap.cancel()
    bundle = fictional_bundle()
    print(json.dumps({
        "source_only": True, "real_capture": False,
        "evidence_scope": "unverified_offline_claims",
        "default": {"state": inactive.state, "retained": inactive.retained_events},
        "gap": {"state": gap.state, "bundle": gap.seal(now=END - 1)},
        "ordinary_short_session": asdict(bundle.evaluate_offline()),
        "fabricated_30_day_coverage": asdict(bundle.evaluate_offline(
            synthetic_full_window_coverage=True)),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
