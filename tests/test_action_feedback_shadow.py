"""Synthetic oracles are separate from submitted events; no live services/fixtures."""

from dataclasses import FrozenInstanceError, asdict, replace
from math import inf, nan

import pytest

from backend.services.ml.action_feedback_shadow import (
    DAY,
    Context,
    Decision,
    ExpectedLink,
    Feedback,
    assess,
)

C = Context("brightness", "2", "working", "evening", "desk", "fictional-v1")
NOW = 10 * DAY


def fixture():
    decisions = tuple(Decision(f"d{i}", f"s{i}", C, (i + 1) * DAY, 180,
                               (i + 1) * DAY, 0.95, owner="automation", house="Home") for i in range(5))
    events = tuple(Feedback(f"e{i}", f"d{i}", f"s{i}", C, (i + 1) * DAY + 60,
                            (i + 1) * DAY + 60, "fictional_explicit_ui",
                            "fictional_owner", "correct", 140) for i in range(5))
    # Construct from independent literal expectations, never the incoming event.
    oracle = {
        f"e{i}": ExpectedLink(
            Decision(f"d{i}", f"s{i}", C, (i + 1) * DAY, 180, (i + 1) * DAY, 0.95, owner="automation", house="Home"),
            Feedback(f"e{i}", f"d{i}", f"s{i}", C, (i + 1) * DAY + 60,
                     (i + 1) * DAY + 60, "fictional_explicit_ui", "fictional_owner",
                     "correct", 140),
        ) for i in range(5)
    }
    return decisions, events, oracle


def evaluate(decisions=None, events=None, oracle=None, now=NOW, context=C):
    d, e, o = fixture()
    return assess(context, d if decisions is None else decisions,
                  e if events is None else events, o if oracle is None else oracle, now=now)


def test_review_only_and_immutable():
    result = evaluate()
    assert result.status == "human_review_suggestion"
    assert result.review_brightness == 140
    assert result.evidence_scope == "unverified_offline_claims"
    assert set(asdict(result)) == {
        "status", "review_brightness", "reasons", "counters", "evidence_scope",
    }
    with pytest.raises(FrozenInstanceError):
        result.status = "auto"


@pytest.mark.parametrize("field,value", [
    ("source", "ws"), ("actor", "other"), ("source_at", 0),
    ("decision_id", "other"), ("session_id", "other"),
    ("kind", "accept"), ("brightness", 139), ("at", DAY + 61),
    ("context", replace(C, policy_id="other")),
])
def test_independent_oracle_rejects_tampered_submission(field, value):
    d, e, o = fixture()
    result = evaluate(d, (replace(e[0], **{field: value}),) + e[1:], o)
    assert result.review_brightness is None


@pytest.mark.parametrize("field,value,reason", [
    ("owner", "manual", "ownership_or_temporary_context"),
    ("owner", "scene", "ownership_or_temporary_context"),
    ("owner", "ScreenSync", "ownership_or_temporary_context"),
    ("owner", "transit", "ownership_or_temporary_context"),
    ("owner", "unknown", "ownership_or_temporary_context"),
    ("owner", "automation+manual", "ownership_or_temporary_context"),
    ("house", "Away", "ownership_or_temporary_context"),
    ("house", "Sleeping", "ownership_or_temporary_context"),
    ("house", "WindingDown", "ownership_or_temporary_context"),
    ("house", "unknown", "ownership_or_temporary_context"),
    ("temporary", True, "ownership_or_temporary_context"),
    ("experiment", True, "ownership_or_temporary_context"),
    ("context_at", DAY - 61, "identity_source_or_freshness_mismatch"),
    ("confidence", 0.89, "invalid_value_or_context_confidence"),
    ("confidence", nan, "invalid_value_or_context_confidence"),
    ("confidence", inf, "invalid_value_or_context_confidence"),
    ("confidence", True, "invalid_value_or_context_confidence"),
    ("brightness", 255, "invalid_value_or_context_confidence"),
    ("at", -1, "invalid_timestamp"),
])
def test_even_matching_claims_must_pass_policy(field, value, reason):
    d, e, o = fixture()
    changed = replace(d[0], **{field: value})
    o["e0"] = ExpectedLink(changed, e[0])
    result = evaluate((changed,) + d[1:], e, o)
    assert reason in result.reasons
    assert result.review_brightness is None


@pytest.mark.parametrize("field,value,reason", [
    ("kind", "slider", "not_explicit_outcome"),
    ("kind", "silent", "not_explicit_outcome"),
    ("kind", "fusion_agreement", "not_explicit_outcome"),
    ("source", "ws", "identity_source_or_freshness_mismatch"),
    ("actor", "automation", "identity_source_or_freshness_mismatch"),
    ("source_at", DAY, "identity_source_or_freshness_mismatch"),
    ("at", DAY - 1, "identity_source_or_freshness_mismatch"),
    ("at", DAY + 601, "identity_source_or_freshness_mismatch"),
    ("at", NOW + 1, "invalid_timestamp"),
    ("at", nan, "invalid_timestamp"),
    ("at", True, "invalid_timestamp"),
    ("session_id", "wrong", "identity_source_or_freshness_mismatch"),
    ("brightness", 0, "invalid_value_or_context_confidence"),
    ("brightness", 255, "invalid_value_or_context_confidence"),
    ("brightness", True, "invalid_value_or_context_confidence"),
    ("brightness", 180, "not_explicit_outcome"),
])
def test_unusable_feedback_even_with_fixture_match(field, value, reason):
    d, e, o = fixture()
    changed = replace(e[0], **{field: value})
    o["e0"] = ExpectedLink(d[0], changed)
    result = evaluate(d, (changed,) + e[1:], o)
    assert reason in result.reasons
    assert result.review_brightness is None


def test_accept_is_explicit_and_not_a_correction():
    d, e, o = fixture()
    accepts = tuple(replace(row, kind="accept", brightness=180) for row in e)
    oracle = {row.event_id: ExpectedLink(decision, row)
              for decision, row in zip(d, accepts)}
    result = evaluate(d, accepts, oracle)
    assert result.review_brightness == 180
    assert dict(result.counters)["accept"] == 5
    assert "correction" not in dict(result.counters)


@pytest.mark.parametrize("kind", ["reject", "reverse"])
def test_negative_demotes_and_cannot_be_outvoted_by_passive_rows(kind):
    d, e, o = fixture()
    negative = replace(e[-1], event_id="negative", kind=kind, at=5 * DAY + 90)
    o["negative"] = ExpectedLink(d[-1], negative)
    passive = tuple(replace(e[-1], event_id=f"passive{i}", kind="silent") for i in range(30))
    assert evaluate().review_brightness == 140
    result = evaluate(d, e + (negative,) + passive, o)
    assert result.review_brightness is None
    assert "negative_feedback_window_veto" in result.reasons
    # Veto remains across repeated reevaluation, rather than graduating next tick.
    assert "negative_feedback_window_veto" in evaluate(d, e + (negative,), o,
                                                       now=20 * DAY).reasons


def test_dedupe_drag_replay_and_input_order():
    d, e, o = fixture()
    drag = tuple(replace(e[0], event_id=f"drag{i}", at=DAY + 61 + i,
                         source_at=DAY + 61 + i, brightness=138 + i) for i in range(3))
    o.update({row.event_id: ExpectedLink(d[0], row) for row in drag})
    rows = e + e + drag
    result = evaluate(d, rows, o)
    assert result.review_brightness == 140
    assert dict(result.counters)["samples"] == 5
    assert result == evaluate(tuple(reversed(d)), tuple(reversed(rows)), o)
    assert evaluate(d[:1], (e[0],) * 100, o).review_brightness is None


def test_sparse_days_and_sessions():
    d, e, o = fixture()
    assert evaluate(d, e[:4], o).review_brightness is None
    same_day_d = tuple(replace(row, at=DAY, context_at=DAY) for row in d)
    same_day_e = tuple(replace(row, at=DAY + 60, source_at=DAY + 60) for row in e)
    oracle = {row.event_id: ExpectedLink(decision, row)
              for decision, row in zip(same_day_d, same_day_e)}
    assert evaluate(same_day_d, same_day_e, oracle).review_brightness is None


def test_expiry_and_invalid_evaluation_time():
    assert evaluate(now=40 * DAY).review_brightness is None
    for now in (-1, True, nan, inf, "today"):
        assert evaluate(now=now).reasons == ("invalid_evaluation_time",)


def test_noise_and_conflicting_feedback():
    d, e, o = fixture()
    noisy = replace(e[0], brightness=200)
    o["e0"] = ExpectedLink(d[0], noisy)
    assert "inconsistent_outcomes" in evaluate(d, (noisy,) + e[1:], o).reasons
    o["e0"] = ExpectedLink(d[0], e[0])
    accept = replace(e[0], event_id="accept", kind="accept", brightness=180)
    o["accept"] = ExpectedLink(d[0], accept)
    assert "conflicting_feedback" in evaluate(d, e + (accept,), o).reasons
    assert "conflicting_event_identity" in evaluate(d, e + (noisy,), o).reasons
    assert "conflicting_decision_identity" in evaluate(d + (replace(d[0], brightness=120),),
                                                        e, o).reasons


@pytest.mark.parametrize("field,value", [
    ("action_id", "color"), ("light_id", "3"), ("mode", "gaming"),
    ("period", "night"), ("zone", "bed"), ("policy_id", "other-policy"),
])
def test_context_and_policy_isolation(field, value):
    assert evaluate(context=replace(C, **{field: value})).review_brightness is None


def test_unlinked_manual_change_is_never_policy_dissatisfaction():
    result = evaluate(oracle={})
    assert result.review_brightness is None
    assert "negative" not in dict(result.counters)
    assert "correction" not in dict(result.counters)
    assert dict(result.counters)["unlinked"] == 5


def test_no_evidence_and_self_attestation_cannot_claim_real_verification():
    assert evaluate(events=()).review_brightness is None
    d, e, _ = fixture()
    self_asserted = {row.event_id: ExpectedLink(decision, row)
                     for decision, row in zip(d, e)}
    assert evaluate(d, e, self_asserted).evidence_scope == "unverified_offline_claims"


def test_one_session_cannot_multiply_across_decisions():
    d, e, _ = fixture()
    decisions = tuple(replace(row, session_id="one") for row in d)
    events = tuple(replace(row, session_id="one") for row in e)
    oracle = {row.event_id: ExpectedLink(decision, row)
              for decision, row in zip(decisions, events)}
    result = evaluate(decisions, events, oracle)
    assert dict(result.counters)["samples"] == 1
    assert result.review_brightness is None


def test_conflicting_identity_order_is_deterministic():
    d, e, o = fixture()
    rows = e + (replace(e[0], brightness=200),)
    assert evaluate(d, rows, o) == evaluate(d, tuple(reversed(rows)), o)


def test_other_policy_conflict_does_not_poison_matching_policy():
    d, e, o = fixture()
    unrelated = replace(d[0], context=replace(C, policy_id="other"))
    assert evaluate(d + (unrelated, replace(unrelated, brightness=99)), e, o) == evaluate()


def test_hysteresis_expires_without_reusing_old_positive_evidence():
    d, e, o = fixture()
    negative = replace(e[0], event_id="no", kind="reject")
    o["no"] = ExpectedLink(d[0], negative)
    result = evaluate(d, e + (negative,), o, now=40 * DAY)
    assert "negative_feedback_window_veto" not in result.reasons
    assert result.review_brightness is None


def test_hue_range_is_technical_only():
    d, e, _ = fixture()
    for value in (1, 254):
        rows = tuple(replace(row, brightness=value) for row in e)
        oracle = {row.event_id: ExpectedLink(decision, row)
                  for decision, row in zip(d, rows)}
        result = evaluate(d, rows, oracle)
        assert result.review_brightness == value
        assert result.status == "human_review_suggestion"


def test_quick_counter_correction_is_uncertain_without_explicit_reversal_label():
    d, e, o = fixture()
    counter = replace(e[0], event_id="counter", at=DAY + 90,
                      source_at=DAY + 90, brightness=170)
    o["counter"] = ExpectedLink(d[0], counter)
    result = evaluate(d, e + (counter,), o)
    assert result.review_brightness is None
    assert "unstable_repeated_correction" in result.reasons


def test_omitted_ownership_defaults_fail_closed():
    d, e, o = fixture()
    incomplete = Decision("d0", "s0", C, DAY, 180, DAY, 0.95)
    assert incomplete.owner == "unknown" and incomplete.house == "unknown"
    o["e0"] = ExpectedLink(incomplete, e[0])
    result = evaluate((incomplete,) + d[1:], e, o)
    assert result.review_brightness is None
    assert "ownership_or_temporary_context" in result.reasons


def test_missing_policy_id_is_abstention_not_exception():
    context = replace(C, policy_id=None)
    assert evaluate(context=context).reasons == ("outside_fictional_scope",)
