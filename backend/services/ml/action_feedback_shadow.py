"""Offline #131 experiment. Caller-supplied claims are never real provenance.

No runtime integration, persistence, clock, or actuation interface. Epoch seconds
and independent expected links must be supplied by the evaluator's caller.
"""

from collections import Counter
from dataclasses import dataclass
from statistics import median
from typing import Mapping

DAY = 86400
WINDOW = 30 * DAY


@dataclass(frozen=True)
class Context:
    action_id: str
    light_id: str
    mode: str
    period: str
    zone: str
    policy_id: str


@dataclass(frozen=True)
class Decision:
    decision_id: str
    session_id: str
    context: Context
    at: int
    brightness: int
    context_at: int
    confidence: float
    owner: str = "unknown"
    house: str = "unknown"
    temporary: bool = False
    experiment: bool = False


@dataclass(frozen=True)
class Feedback:
    event_id: str
    decision_id: str
    session_id: str
    context: Context
    at: int
    source_at: int
    source: str
    actor: str
    kind: str
    brightness: int


@dataclass(frozen=True)
class ExpectedLink:
    """Independent fixture oracle, NOT an authentication or verification token.

    Copying a submitted event here only self-attests it. No production adapter
    exists; even an exact match remains an unverified offline claim.
    """

    decision: Decision
    feedback: Feedback


@dataclass(frozen=True)
class Assessment:
    status: str
    review_brightness: int | None
    reasons: tuple[str, ...]
    counters: tuple[tuple[str, int], ...]
    evidence_scope: str = "unverified_offline_claims"


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def assess(
    context: Context,
    decisions: tuple[Decision, ...],
    feedback: tuple[Feedback, ...],
    expected: Mapping[str, ExpectedLink],
    *,
    now: int,
) -> Assessment:
    """Review only: five independent sessions on three UTC days, consistent values.

    One sample per decision AND session collapses drags/replays. Any qualified
    rejection/reversal vetoes for the full 30-day window (temporal hysteresis).
    Any in-scope ambiguity also withholds a candidate. Silence contributes zero.
    """
    counts: Counter[str] = Counter()
    reasons: set[str] = set()

    def result(value: int | None = None) -> Assessment:
        return Assessment(
            "human_review_suggestion" if value is not None else "abstain",
            value, tuple(sorted(reasons)), tuple(sorted(counts.items())),
        )

    if not _integer(now, 0, 253402300799):
        reasons.add("invalid_evaluation_time")
        return result()
    if (
        (context.action_id, context.light_id, context.mode, context.period, context.zone)
        != ("brightness", "2", "working", "evening", "desk")
        or not isinstance(context.policy_id, str)
        or not context.policy_id.strip()
    ):
        reasons.add("outside_fictional_scope")
        return result()

    by_id: dict[str, Decision] = {}
    conflicting_decisions: set[str] = set()
    for decision in decisions:
        if decision.context != context:
            continue
        if decision.decision_id in by_id and by_id[decision.decision_id] != decision:
            reasons.add("conflicting_decision_identity")
            conflicting_decisions.add(decision.decision_id)
        by_id[decision.decision_id] = decision
    unique: dict[str, Feedback] = {}
    conflicting_events: set[str] = set()
    for event in feedback:
        if event.context != context:
            counts["other_context"] += 1
            continue
        if event.event_id in unique:
            counts["duplicate"] += 1
            if unique[event.event_id] != event:
                reasons.add("conflicting_event_identity")
                conflicting_events.add(event.event_id)
        else:
            unique[event.event_id] = event

    qualified: list[Feedback] = []
    for event in unique.values():
        if event.event_id in conflicting_events or event.decision_id in conflicting_decisions:
            counts["conflicting_identity"] += 1
            continue
        decision = by_id.get(event.decision_id)
        link = expected.get(event.event_id)
        if decision is None or link != ExpectedLink(decision, event):
            counts["unlinked"] += 1
            reasons.add("independent_link_missing_or_mismatched")
            continue
        if not all(_integer(t, 0, now) for t in (
            decision.at, decision.context_at, event.at, event.source_at,
        )):
            reasons.add("invalid_timestamp")
            continue
        if event.at < now - WINDOW:
            counts["expired"] += 1
            continue
        if (
            not decision.decision_id or not decision.session_id or not event.event_id
            or decision.context != context or decision.session_id != event.session_id
            or not 0 <= event.at - decision.at <= 600
            or not 0 <= decision.at - decision.context_at <= 60
            or not 0 <= event.at - event.source_at <= 30
            or event.source != "fictional_explicit_ui" or event.actor != "fictional_owner"
        ):
            reasons.add("identity_source_or_freshness_mismatch")
            continue
        if (
            decision.owner != "automation" or decision.house != "Home"
            or decision.temporary is not False or decision.experiment is not False
        ):
            reasons.add("ownership_or_temporary_context")
            continue
        if (
            type(decision.confidence) not in (int, float)
            or not 0.9 <= decision.confidence <= 1
            or not _integer(decision.brightness, 1, 254)
            or not _integer(event.brightness, 1, 254)
        ):
            reasons.add("invalid_value_or_context_confidence")
            continue
        if event.kind in {"reject", "reverse"}:
            counts["negative"] += 1
            reasons.add("negative_feedback_window_veto")
        elif event.kind == "accept" and event.brightness == decision.brightness:
            counts["accept"] += 1
            qualified.append(event)
        elif event.kind == "correct" and abs(event.brightness - decision.brightness) >= 5:
            counts["correction"] += 1
            qualified.append(event)
        else:
            counts["ambiguous"] += 1
            reasons.add("not_explicit_outcome")

    # Last settled value, deterministic tie-break. No drag can manufacture sessions.
    sessions: dict[str, Feedback] = {}
    for event in sorted(qualified, key=lambda e: (e.at, e.event_id)):
        sessions[event.session_id] = event
    counts["samples"] = len(sessions)
    counts["days"] = len({e.at // DAY for e in sessions.values()})
    if len(sessions) < 5 or counts["days"] < 3:
        reasons.add("insufficient_independent_sessions_or_days")
    values = [e.brightness for e in sessions.values()]
    if values and max(values) - min(values) > 10:
        reasons.add("inconsistent_outcomes")
    # Conflicting accept/correct judgments within a decision are uncertainty too.
    for decision_id in {e.decision_id for e in qualified}:
        group = [e for e in qualified if e.decision_id == decision_id]
        if len({e.kind for e in group}) > 1:
            reasons.add("conflicting_feedback")
        # Ignore a brief drag's intermediate values; separated corrections that
        # disagree materially are not a stable preference, even in one session.
        if any(abs(a.at - b.at) > 3 and abs(a.brightness - b.brightness) > 10
               for a in group for b in group):
            reasons.add("unstable_repeated_correction")
    if reasons:
        return result()
    reasons.add("consistent_explicit_outcomes_review_only")
    return result(round(median(values)))
