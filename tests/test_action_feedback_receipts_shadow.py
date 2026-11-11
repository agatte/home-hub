"""Synthetic joins only: even forging every stream cannot authenticate a user."""

import ast
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path

import pytest

from backend.services.ml import action_feedback_receipts_shadow as module
from scripts.demo_action_feedback_receipts_shadow import C, NOW, fictional_batch


def run(batch=None):
    return module.evaluate(C, *(fictional_batch() if batch is None else batch), now=NOW)


def mutate(stream, field, value):
    batch = list(fictional_batch())
    batch[stream] = (replace(batch[stream][0], **{field: value}),) + batch[stream][1:]
    return batch


def test_before_after_and_permanent_limits():
    assert run(fictional_batch(2)).status == "abstain"
    result = run()
    assert result.review_brightness == 140
    assert result.status == "human_review_suggestion"
    assert result.evidence_scope == "unverified_offline_claims"
    assert set(asdict(result)) == {"status", "review_brightness", "reasons", "counters", "evidence_scope"}
    with pytest.raises(FrozenInstanceError):
        fictional_batch()[0][0].stamp.at = 0


@pytest.mark.parametrize("field,value", [
    ("brightness", 139), ("actor", "intruder"), ("kind", "accept"),
    ("session_id", "replayed"), ("decision_id", "d1"), ("event_id", "forged"),
    ("source", "credential-looking-string"), ("at", NOW + 1),
    ("context", replace(C, policy_id="other")),
])
def test_forged_submitted_payload(field, value):
    assert run(mutate(4, field, value)).review_brightness is None


@pytest.mark.parametrize("stream", range(5))
def test_missing_or_duplicate_receipt(stream):
    batch = list(fictional_batch())
    batch[stream] = batch[stream][1:]
    assert run(batch).status == "abstain"
    batch = list(fictional_batch())
    batch[stream] += (batch[stream][0],)
    assert run(batch).status == "abstain"


@pytest.mark.parametrize("field,value", [
    ("acknowledged", False), ("acknowledged", None), ("acknowledged", 1),
    ("owner_receipt_id", "missing"),
])
def test_no_accepted_final_ack(field, value):
    assert run(mutate(1, field, value)).status == "abstain"


@pytest.mark.parametrize("field,value", [
    ("owner", "manual"), ("owner", "ScreenSync"), ("owner", "transit"),
    ("owner", "scene"), ("owner", "automation+manual"), ("owner", "unknown"),
    ("house", "Away"), ("house", "Winding Down"), ("house", "Sleeping"),
    ("authoritative", False), ("context_at", 31 * 86400 - 61),
    ("response_context_at", 31 * 86400 + 29),
    ("context_at", 31 * 86400 + 1), ("through", 31 * 86400 + 59),
])
def test_owner_and_feedback_context(field, value):
    assert run(mutate(2, field, value)).status == "abstain"


@pytest.mark.parametrize("field,value", [
    ("owner_qualified", False), ("owner_qualified", 1),
    ("interaction", "slider"), ("interaction", "scene_selection"),
    ("interaction", "silence"), ("apply_receipt_id", "ack1"),
    ("owner_receipt_id", "owner1"),
])
def test_ui_independent_qualification(field, value):
    assert run(mutate(3, field, value)).status == "abstain"


@pytest.mark.parametrize("producer", range(4))
@pytest.mark.parametrize("field,value", [
    ("complete", False), ("continuous", False), ("start", NOW - 100),
    ("end", NOW - 1), ("receipt_ids", ()),
])
def test_partial_gapped_or_torn_coverage(producer, field, value):
    batch = list(fictional_batch())
    claims = list(batch[5])
    claims[producer] = replace(claims[producer], **{field: value})
    batch[5] = tuple(claims)
    assert run(batch).status == "abstain"


@pytest.mark.parametrize("stream", range(4))
@pytest.mark.parametrize("field,value", [
    ("at", NOW + 1), ("at", -1), ("captured_at", NOW + 1),
    ("captured_at", 0), ("captured_at", 31 * 86400 + 100),
    ("sequence", 2), ("sequence", True),
])
def test_clock_skew_stale_capture_and_sequence_gaps(stream, field, value):
    batch = fictional_batch()
    stamp = replace(batch[stream][0].stamp, **{field: value})
    assert run(mutate(stream, "stamp", stamp)).status == "abstain"


@pytest.mark.parametrize("field,value", [
    ("temporary", True), ("experiment", True), ("session_id", ""),
    ("house", "Away"), ("owner", "manual"), ("confidence", .5),
    ("context", replace(C, zone="bed")), ("context", replace(C, policy_id="other")),
])
def test_even_correlated_producer_changes_are_screened(field, value):
    batch = list(fictional_batch())
    for stream in (0, 1, 2):
        rows = batch[stream]
        batch[stream] = (replace(rows[0], decision=replace(rows[0].decision, **{field: value})),) + rows[1:]
    assert run(batch).status == "abstain"


@pytest.mark.parametrize("kind", ["reverse", "reject", "slider", "scene", "silent"])
def test_negative_or_passive_cannot_qualify_even_matching_payload(kind):
    batch = list(fictional_batch())
    batch[3] = batch[3][:-1] + (replace(batch[3][-1], response=replace(batch[3][-1].response, kind=kind)),)
    batch[4] = batch[4][:-1] + (replace(batch[4][-1], kind=kind),)
    result = run(batch)
    assert result.status == "abstain"
    if kind in {"reverse", "reject"}:
        assert "negative_feedback_window_veto" in result.reasons


def test_post_ack_takeover_not_discarded_even_with_five_positives():
    batch = list(fictional_batch())
    owner = batch[2][-1]
    extra = replace(owner, stamp=module.Stamp("takeover", 6, owner.stamp.at + 30,
                                            owner.through), owner="manual")
    batch[2] += (extra,)
    batch[5] = tuple(replace(c, receipt_ids=c.receipt_ids + ("takeover",))
                     if c.producer == "owner" else c for c in batch[5])
    assert "ambiguous_owner_timeline" in run(batch).reasons


def test_input_permutations_deterministic():
    batch = fictional_batch()
    for shift in range(5):
        shuffled = tuple(rows[shift:] + rows[:shift] for rows in batch[:5]) + (tuple(reversed(batch[5])),)
        assert run(shuffled) == run(batch)


def test_conflicting_ids_and_cross_session_ack():
    batch = fictional_batch()
    conflict = replace(batch[1][0].decision, session_id="s1")
    assert run(mutate(1, "decision", conflict)).status == "abstain"
    assert run(mutate(4, "event_id", "e1")).status == "abstain"


def test_no_runtime_imports_or_permission_interface():
    tree = ast.parse(Path(module.__file__).read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert imports == ["dataclasses", "backend.services.ml.action_feedback_shadow"]
    assert not any(isinstance(n, ast.Import) for n in ast.walk(tree))
    assert "permission" not in asdict(run())


def test_forging_all_streams_still_never_authenticates_real_owner():
    # The passing batch is itself a total forgery: strings/booleans are no credentials.
    assert run().evidence_scope == "unverified_offline_claims"


def test_reversal_veto_after_five_positive_responses():
    batch = list(fictional_batch())
    old = batch[3][-1]
    event = replace(old.response, event_id="reversal", kind="reverse")
    receipt = replace(old, stamp=replace(old.stamp, receipt_id="reversal-ui", sequence=6),
                      response=event)
    batch[3] += (receipt,)
    batch[4] += (event,)
    batch[5] = tuple(replace(c, receipt_ids=c.receipt_ids + ("reversal-ui",))
                     if c.producer == "ui" else c for c in batch[5])
    result = run(batch)
    assert "negative_feedback_window_veto" in result.reasons
    assert result.review_brightness is None


@pytest.mark.parametrize("field,value", [("source_at", 0), ("actor", "other"),
                                         ("source", "slider"), ("session_id", "")])
def test_matching_ui_and_payload_still_need_fresh_qualified_response(field, value):
    batch = list(fictional_batch())
    event = replace(batch[4][0], **{field: value})
    batch[4] = (event,) + batch[4][1:]
    batch[3] = (replace(batch[3][0], response=event),) + batch[3][1:]
    assert run(batch).status == "abstain"


def test_sequence_reordered_against_capture_time():
    batch = list(fictional_batch())
    rows = batch[0]
    batch[0] = (replace(rows[0], stamp=replace(rows[0].stamp, sequence=2)),
                replace(rows[1], stamp=replace(rows[1].stamp, sequence=1))) + rows[2:]
    batch[5] = (replace(batch[5][0], receipt_ids=("intent1", "intent0", "intent2", "intent3", "intent4")),) + batch[5][1:]
    assert "inconsistent_capture_order" in run(batch).reasons


@pytest.mark.parametrize("stream,field", [(0, "at"), (3, "at"), (2, "through")])
def test_non_integer_clock_is_abstention(stream, field):
    batch = list(fictional_batch())
    if stream == 0:
        batch[0] = (replace(batch[0][0], decision=replace(batch[0][0].decision, at="bad")),) + batch[0][1:]
    elif stream == 3:
        batch[3] = (replace(batch[3][0], response=replace(batch[3][0].response, at=True)),) + batch[3][1:]
    else:
        batch[2] = (replace(batch[2][0], through="bad"),) + batch[2][1:]
    assert run(batch).status == "abstain"


def late_response_batch(*, refresh_response_context: bool):
    """Long explicit responses need an independently fresh response observation."""
    batch = list(fictional_batch())
    new_owners, new_ui, new_submitted = [], [], []
    for owner, ui, payload in zip(batch[2], batch[3], batch[4]):
        later = owner.decision.at + 540  # still within original 600-second limit
        new_owners.append(replace(
            owner,
            stamp=replace(owner.stamp, captured_at=later),
            through=later,
            response_context_at=later if refresh_response_context
                                else owner.decision.at + 60,
        ))
        new_ui.append(replace(
            ui,
            stamp=replace(ui.stamp, at=later, captured_at=later),
            response=replace(ui.response, at=later, source_at=later),
        ))
        new_submitted.append(replace(payload, at=later, source_at=later))
    batch[2] = tuple(new_owners)
    batch[3] = tuple(new_ui)
    batch[4] = tuple(new_submitted)
    return batch


def test_nine_minute_explicit_response_can_qualify_with_fresh_owner_endpoint():
    assert run(late_response_batch(refresh_response_context=True)).review_brightness == 140


def test_nine_minute_response_cannot_reuse_stale_owner_endpoint():
    result = run(late_response_batch(refresh_response_context=False))
    assert result.status == "abstain"
    assert "receipt_identity_ack_owner_or_ui_mismatch" in result.reasons


def test_missing_or_future_response_context_endpoint_abstains():
    for value in (None, True, NOW + 1):
        assert run(mutate(2, "response_context_at", value)).status == "abstain"
