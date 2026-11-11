"""Isolated synthetic ports are test claims, never real authentication."""

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from backend.services.ml import lighting_feedback_capture_seam as module
from scripts.demo_lighting_feedback_capture_seam import (
    C, END, START, consent, feed, fictional_bundle, ports, records,
)


def session(**kwargs):
    return module.CaptureSession.synthetic_for_tests(consent(), **kwargs)


def test_default_off_and_no_implicit_consent():
    s = module.CaptureSession()
    assert not any(feed(s, records(0)))
    assert s.state == "disabled"
    assert s.retained_events == 0
    assert s.seal(now=END - 1) is None


@pytest.mark.parametrize("field,value", [
    ("explicit", False), ("explicit", 1), ("historical_backfill", True),
    ("principal", "client_owner"), ("principal", None), ("starts", True),
    ("expires", START), ("expires", END + 10 * 86400),
    ("verbs", ()), ("verbs", ("slider",)), ("verbs", ("accept", "accept")),
])
def test_consent_preflight(field, value):
    s = module.CaptureSession.synthetic_for_tests(replace(consent(), **{field: value}))
    assert not any(feed(s, records(0)))
    assert s.retained_events == 0


@pytest.mark.parametrize("field,value", [
    ("light_id", "3"), ("action_id", "color"), ("mode", "sleeping"),
    ("period", "night"), ("zone", "bed"), ("policy_id", ""),
])
def test_scope_preflight(field, value):
    s = module.CaptureSession.synthetic_for_tests(
        replace(consent(), context=replace(C, **{field: value})))
    assert s.state == "disabled"


@pytest.mark.parametrize("field,value", [
    ("source_verified", False), ("source_verified", 1), ("producer", "ui"),
    ("session", object()),
])
def test_independent_source_boundary(field, value):
    s = session()
    assert not s.decision(records(0)[0], replace(ports(s)[0], **{field: value}),
                          revision=1, now=START)
    assert s.retained_events == 0


@pytest.mark.parametrize("field,value", [
    ("principal", None), ("principal", "intruder"), ("actor_verified", False),
    ("source_verified", False),
])
def test_explicit_principal_only_on_trusted_fixture_port(field, value):
    s = session()
    r = records(0)
    p = ports(s)
    assert s.decision(r[0], p[0], revision=1, now=START)
    assert s.final_ack(r[1], p[1], revision=1, now=START + 1)
    assert s.owner_context(r[2], p[2], revision=1, now=START + 60)
    assert not s.explicit_feedback(r[3], replace(p[3], **{field: value}), r[4],
                                   revision=1, now=START + 60)
    assert s.retained_events == 0


@pytest.mark.parametrize("field,value", [
    ("actor", "intruder"), ("source", "client_json"), ("brightness", 141),
    ("session_id", "replay"), ("decision_id", "forged"), ("kind", "reverse"),
])
def test_submission_never_becomes_oracle(field, value):
    s = session()
    r = list(records(0))
    r[4] = replace(r[4], **{field: value})
    assert not all(feed(s, r))
    assert s.retained_events == 0


@pytest.mark.parametrize("owner", ["manual", "ScreenSync", "transit", "scene", "unknown"])
@pytest.mark.parametrize("stream", [0, 2])
def test_nonautomation_owner(owner, stream):
    s = session()
    r = list(records(0))
    if stream == 0:
        r[0] = replace(r[0], decision=replace(r[0].decision, owner=owner))
    else:
        r[2] = replace(r[2], owner=owner)
    assert not all(feed(s, r))
    assert s.retained_events == 0


@pytest.mark.parametrize("house", ["Away", "Sleeping", "Winding Down"])
@pytest.mark.parametrize("stream", [0, 2])
def test_house_state(house, stream):
    r = list(records(0))
    if stream == 0:
        r[0] = replace(r[0], decision=replace(r[0].decision, house=house))
    else:
        r[2] = replace(r[2], house=house)
    s = session()
    assert not all(feed(s, r))
    assert s.retained_events == 0


@pytest.mark.parametrize("value", [False, None, 1, "partial"])
def test_final_ack_must_be_exact_success(value):
    s = session()
    r = list(records(0))
    r[1] = replace(r[1], acknowledged=value)
    assert not all(feed(s, r))
    assert s.retained_events == 0


@pytest.mark.parametrize("stream", [1, 2, 3])
def test_final_writer_and_response_revalidate_revision(stream):
    s = session()
    r = records(0)
    p = ports(s)
    assert s.decision(r[0], p[0], revision=1, now=START)
    if stream >= 2:
        assert s.final_ack(r[1], p[1], revision=1, now=START + 1)
    if stream == 3:
        assert s.owner_context(r[2], p[2], revision=1, now=START + 60)
        accepted = s.explicit_feedback(r[3], p[3], r[4], revision=2, now=START + 60)
    elif stream == 2:
        accepted = s.owner_context(r[2], p[2], revision=2, now=START + 60)
    else:
        accepted = s.final_ack(r[1], p[1], revision=2, now=START + 1)
    assert not accepted
    assert s.retained_events == 0


@pytest.mark.parametrize("now", [START - 1, END, END + 1, True, None, float("nan")])
def test_time_and_expiration(now):
    s = session()
    assert not s.decision(records(0)[0], ports(s)[0], revision=1, now=now)
    assert s.retained_events == 0


@pytest.mark.parametrize("method", ["clear", "revoke", "cancel"])
def test_terminal_clear_revoke_gap(method):
    s = session()
    assert all(feed(s, records(0)))
    getattr(s, method)()
    assert not any(feed(s, records(1)))
    assert s.retained_events == 0
    assert s.seal(now=END - 1) is None


def test_session_identity_replay_and_duplicate():
    a, b = session(), session()
    assert a.identity is not b.identity
    assert not b.decision(records(0)[0], ports(a)[0], revision=1, now=START)
    assert all(feed(a, records(0)))
    assert not a.decision(records(0)[0], ports(a)[0], revision=1, now=START + 60)
    assert a.retained_events == 0


@pytest.mark.parametrize("limit", [4, 7, 19])
def test_overflow_invalidates_entire_batch(limit):
    s = session(max_events=limit)
    for i in range(5):
        feed(s, records(i))
    assert s.retained_events == 0
    assert s.seal(now=END - 1) is None


@pytest.mark.parametrize("bad", [None, {}, "input", object()])
def test_malformed_records_fail_closed(bad):
    s = session()
    assert not s.decision(bad, ports(s)[0], revision=1, now=START)
    assert s.retained_events == 0


def test_capture_order_incomplete_and_sealed_terminal():
    s = session()
    r = records(0)
    assert not s.final_ack(r[1], ports(s)[1], revision=1, now=START + 1)
    s = session()
    assert s.decision(r[0], ports(s)[0], revision=1, now=START)
    assert s.seal(now=START) is None
    s = session()
    assert all(feed(s, r))
    bundle = s.seal(now=START + 60)
    assert bundle is not None and s.state == "sealed" and s.retained_events == 0
    assert not any(feed(s, records(1)))


def test_unknown_coverage_and_fabricated_five_decision_review():
    b = fictional_bundle()
    assert b.evaluate_offline().reasons == ("coverage_unknown",)
    result = b.evaluate_offline(synthetic_full_window_coverage=True)
    assert result.status == "human_review_suggestion"
    assert result.review_brightness == 140
    assert result.evidence_scope == "unverified_offline_claims"


def test_reverse_veto_even_with_fabricated_coverage():
    s = session()
    for i in range(5):
        r = list(records(i))
        if i == 4:
            r[3] = replace(r[3], response=replace(r[3].response, kind="reverse"))
            r[4] = replace(r[4], kind="reverse")
        assert all(feed(s, r))
    assert "negative_feedback_window_veto" in s.seal(now=END - 1).evaluate_offline(
        synthetic_full_window_coverage=True).reasons


def test_request_does_not_evaluate(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("automatic evaluation")
    monkeypatch.setattr(module, "evaluate", forbidden)
    assert fictional_bundle() is not None


def test_no_runtime_or_io_imports():
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert set(imports) == {"dataclasses", "backend.services.ml.action_feedback_shadow",
                            "backend.services.ml.action_feedback_receipts_shadow"}
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))


@pytest.mark.parametrize("stream,field,value", [
    (0, "stamp", None), (0, "decision", {}),
    (1, "owner_receipt_id", "wrong"),
    (2, "authoritative", False), (2, "through", START + 59),
    (2, "context_at", START - 61), (2, "response_context_at", START),
    (3, "owner_receipt_id", "wrong"), (3, "apply_receipt_id", "wrong"),
    (3, "interaction", "slider"), (3, "owner_qualified", False),
])
def test_malformed_or_tampered_producer(stream, field, value):
    s = session()
    r = list(records(0))
    r[stream] = replace(r[stream], **{field: value})
    # Call directly for malformed stamp (the harness itself reads timestamps).
    if stream == 0:
        assert not s.decision(r[0], ports(s)[0], revision=1, now=START)
    else:
        assert not all(feed(s, r))
    assert s.retained_events == 0


@pytest.mark.parametrize("field,value", [
    ("brightness", 170), ("context", replace(C, policy_id="other")),
    ("session_id", "other"), ("house", "Away"),
])
def test_final_writer_independent_intent(field, value):
    s = session()
    r = list(records(0))
    r[1] = replace(r[1], decision=replace(r[1].decision, **{field: value}))
    assert not all(feed(s, r))
    assert s.retained_events == 0


@pytest.mark.parametrize("mutation", ["gap", "reversed", "stale", "duplicate_session"])
def test_sequence_gap_reversal_stale_capture_and_session_reuse(mutation):
    s = session()
    assert all(feed(s, records(0)))
    r = records(1)[0]
    now = r.stamp.at
    if mutation == "gap":
        r = replace(r, stamp=replace(r.stamp, sequence=3))
    elif mutation == "reversed":
        now = START
    elif mutation == "stale":
        now += 31
        r = replace(r, stamp=replace(r.stamp, captured_at=now))
    else:
        r = replace(r, decision=replace(r.decision, session_id="s0"))
    assert not s.decision(r, ports(s)[0], revision=1, now=now)
    assert s.retained_events == 0


def test_scope_and_expiry_after_prior_positive():
    for change in ("context", "expiry"):
        s = session()
        assert all(feed(s, records(0)))
        r = records(1)[0]
        if change == "context":
            r = replace(r, decision=replace(r.decision, context=replace(C, light_id="3")))
            assert not s.decision(r, ports(s)[0], revision=1, now=r.stamp.at)
        else:
            assert s.seal(now=END) is None
        assert s.retained_events == 0


def test_export_immutable_and_original_producer_order():
    from dataclasses import FrozenInstanceError
    b = fictional_bundle()
    assert [r.decision.decision_id for r in b.decisions] == [f"d{i}" for i in range(5)]
    with pytest.raises(FrozenInstanceError):
        b.sealed_at = END
    assert b.submitted[0] == b.responses[0].response
    assert b.submitted[0] is not b.responses[0].response


def test_offline_bundle_cannot_be_mislabeled_verified():
    bundle = fictional_bundle()
    assert bundle.evidence_scope == "unverified_offline_claims"
    with pytest.raises(TypeError):
        replace(bundle, evidence_scope="verified")
    assert bundle.evaluate_offline().evidence_scope == "unverified_offline_claims"
