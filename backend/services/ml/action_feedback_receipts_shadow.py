"""Pure fictional receipt joins. Supplied streams are NOT authenticated evidence.

Even complete matching streams can all be forged by a malicious caller. No IO,
clock, runtime registration, physical observation or actuation permission exists.
"""

from dataclasses import dataclass

from backend.services.ml.action_feedback_shadow import (
    WINDOW, Assessment, Context, Decision, ExpectedLink, Feedback, assess,
)


@dataclass(frozen=True)
class Stamp:
    receipt_id: str
    sequence: int
    at: int
    captured_at: int


@dataclass(frozen=True)
class DecisionReceipt:
    stamp: Stamp
    decision: Decision


@dataclass(frozen=True)
class ApplyReceipt:
    stamp: Stamp
    decision: Decision  # independent final-writer copy of the accepted intent
    acknowledged: bool
    owner_receipt_id: str


@dataclass(frozen=True)
class OwnerSnapshot:
    stamp: Stamp
    decision: Decision
    through: int  # inclusive continuous ownership/context interval claim
    owner: str
    house: str
    context_at: int  # fresh at originating decision
    response_context_at: int  # independently fresh near UI response
    authoritative: bool


@dataclass(frozen=True)
class UIReceipt:
    stamp: Stamp
    response: Feedback  # independent UI-producer record, not submitted payload
    apply_receipt_id: str
    owner_receipt_id: str
    owner_qualified: bool  # illustration of a future authenticated UI boundary
    interaction: str


@dataclass(frozen=True)
class Coverage:
    producer: str
    start: int
    end: int
    complete: bool
    continuous: bool
    receipt_ids: tuple[str, ...]  # producer sequence order, not arrival order


def _int(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def evaluate(
    context: Context,
    decisions: tuple[DecisionReceipt, ...],
    applies: tuple[ApplyReceipt, ...],
    owners: tuple[OwnerSnapshot, ...],
    responses: tuple[UIReceipt, ...],
    submitted: tuple[Feedback, ...],
    coverage: tuple[Coverage, ...],
    *,
    now: int,
) -> Assessment:
    """All supplied evidence belongs to one bounded batch; never filter bad rows.

    Coverage must claim the entire assessor window, including quiet periods and
    negatives through now. These claims cannot prove real-world completeness.
    Strict duplicates abstain, even identical replays. Input order is irrelevant;
    producer sequences and timestamps must agree. No universal policy is defined.
    """
    reasons: set[str] = set()

    def stop() -> Assessment:
        return Assessment("abstain", None, tuple(sorted(reasons)), ())

    if not _int(now, WINDOW, 253402300799):
        reasons.add("invalid_evaluation_time")
        return stop()
    streams = {"decision": decisions, "apply": applies, "owner": owners, "ui": responses}
    if len(coverage) != 4 or {c.producer for c in coverage} != set(streams):
        reasons.add("coverage_producers_missing_or_duplicate")
        return stop()
    all_ids: list[str] = []
    for claim in coverage:
        rows = streams[claim.producer]
        stamps = tuple(r.stamp for r in rows)
        if any(not _int(s.sequence, 1, len(rows)) for s in stamps):
            reasons.add("producer_sequence_gap")
            continue
        ordered = sorted(stamps, key=lambda s: s.sequence)
        ids = tuple(s.receipt_id for s in ordered)
        all_ids.extend(ids)
        if (
            claim.complete is not True or claim.continuous is not True
            or not _int(claim.start, 0, now - WINDOW)
            or not _int(claim.end, now, now)
            or claim.receipt_ids != ids
            or [s.sequence for s in ordered] != list(range(1, len(rows) + 1))
        ):
            reasons.add("incomplete_or_torn_coverage")
        for row in rows:
            s = row.stamp
            end = row.through if isinstance(row, OwnerSnapshot) else s.at
            if not _int(end, now - WINDOW, now):
                reasons.add("invalid_owner_interval")
                continue
            if (
                not isinstance(s.receipt_id, str) or not s.receipt_id.strip()
                or not _int(s.at, now - WINDOW, now)
                or not _int(s.captured_at, end, min(now, end + 30))
            ):
                reasons.add("invalid_or_stale_capture")
        if all(type(s.at) is int and type(s.captured_at) is int for s in ordered):
            if any(a.at > b.at or a.captured_at > b.captured_at
                   for a, b in zip(ordered, ordered[1:])):
                reasons.add("inconsistent_capture_order")
    if len(set(all_ids)) != len(all_ids):
        reasons.add("duplicate_receipt_identity")
    if reasons:
        return stop()

    ds = {r.decision.decision_id: r for r in decisions}
    aps = {r.stamp.receipt_id: r for r in applies}
    os = {r.stamp.receipt_id: r for r in owners}
    ui = {r.response.event_id: r for r in responses}
    payload = {r.event_id: r for r in submitted}
    if (len(ds) != len(decisions) or len(ui) != len(responses)
            or len(payload) != len(submitted)):
        reasons.add("duplicate_decision_or_response_identity")
    if set(ui) != set(payload):
        reasons.add("response_coverage_mismatch")
    if any(r.decision.context != context for r in (*decisions, *applies, *owners)):
        reasons.add("mixed_context_batch")
    if any(r.response.context != context for r in responses):
        reasons.add("mixed_context_batch")
    expected: dict[str, ExpectedLink] = {}
    used_applies: set[str] = set()
    used_owners: set[str] = set()
    used_decisions: set[str] = set()
    for receipt in responses:
        event = receipt.response
        origin = ds.get(event.decision_id)
        ack = aps.get(receipt.apply_receipt_id)
        owner = os.get(receipt.owner_receipt_id)
        if origin is None or ack is None or owner is None:
            reasons.add("missing_join_receipt")
            continue
        d = origin.decision
        if not all(_int(t, 0, now) for t in (
            d.at, event.at, owner.through, owner.context_at,
            owner.response_context_at,
        )):
            reasons.add("invalid_join_timestamp")
            continue
        used_decisions.add(d.decision_id)
        used_applies.add(ack.stamp.receipt_id)
        used_owners.add(owner.stamp.receipt_id)
        if (
            payload.get(event.event_id) != event or ack.decision != d or owner.decision != d
            or ack.owner_receipt_id != owner.stamp.receipt_id
            or event.session_id != d.session_id or not d.session_id
            or origin.stamp.at != d.at or receipt.stamp.at != event.at
            or ack.acknowledged is not True
            or not d.at <= ack.stamp.at <= event.at <= d.at + 600
            or not origin.stamp.captured_at <= ack.stamp.captured_at <= receipt.stamp.captured_at
            or not owner.stamp.at <= d.at <= event.at <= owner.through
            or not owner.stamp.captured_at <= receipt.stamp.captured_at
            or not _int(owner.through, owner.stamp.at, now)
            or not _int(owner.context_at, max(0, d.at - 60), d.at)
            or not _int(owner.response_context_at, max(d.at, event.at - 30), event.at)
            or owner.authoritative is not True
            or owner.owner != "automation" or owner.house != "Home"
            or receipt.owner_qualified is not True
            or receipt.interaction != "explicit_decision_response"
            or event.kind not in {"accept", "correct", "reject", "reverse"}
            or event.actor != "fictional_owner" or event.source != "fictional_explicit_ui"
        ):
            reasons.add("receipt_identity_ack_owner_or_ui_mismatch")
            continue
        # Expected side comes exclusively from corroborated producer receipts.
        # Submitted payload is compared above, never copied into this map.
        expected[event.event_id] = ExpectedLink(d, event)
    if (used_decisions != set(ds) or used_applies != set(aps) or used_owners != set(os)):
        reasons.add("extraneous_or_conflicting_provenance")
    # Two snapshots for one decision are ambiguous, including ABA/takeover claims.
    if len({r.decision.decision_id for r in owners}) != len(owners):
        reasons.add("ambiguous_owner_timeline")
    if len({r.decision.decision_id for r in applies}) != len(applies):
        reasons.add("ambiguous_final_write")
    if reasons:
        return stop()
    return assess(context, tuple(r.decision for r in decisions), submitted, expected, now=now)
