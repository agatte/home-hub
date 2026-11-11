"""Dormant SOURCE-ONLY synthetic capture contract; never import from runtime.

Caller flags are fictional test claims, NOT authentication or a real consent grant.
No clock, IO, registration, adapters, persistence, or application interface exists.
"""

from dataclasses import dataclass

from backend.services.ml.action_feedback_receipts_shadow import (
    ApplyReceipt, Coverage, DecisionReceipt, OwnerSnapshot, Stamp, UIReceipt, evaluate,
)
from backend.services.ml.action_feedback_shadow import (
    DAY, WINDOW, Assessment, Context, Decision, Feedback,
)


@dataclass(frozen=True)
class SyntheticConsent:
    context: Context
    principal: str
    starts: int
    expires: int
    verbs: tuple[str, ...]
    explicit: bool = False
    historical_backfill: bool = False


@dataclass(frozen=True)
class SyntheticPort:
    """Isolated trusted-side fixture input, never client JSON or real security."""

    session: object
    producer: str
    source_verified: bool = False
    principal: str | None = None
    actor_verified: bool = False


@dataclass(frozen=True)
class OfflineBundle:
    context: Context
    decisions: tuple[DecisionReceipt, ...]
    applies: tuple[ApplyReceipt, ...]
    owners: tuple[OwnerSnapshot, ...]
    responses: tuple[UIReceipt, ...]
    submitted: tuple[Feedback, ...]
    sealed_at: int

    @property
    def evidence_scope(self) -> str:
        """Fixed unverified label; no caller-supplied verified status exists."""
        return "unverified_offline_claims"

    def evaluate_offline(self, *, synthetic_full_window_coverage: bool = False) -> Assessment:
        """Explicit fixture fabrication only; a short session proves no coverage."""
        if synthetic_full_window_coverage is not True:
            return Assessment("abstain", None, ("coverage_unknown",), ())
        streams = (self.decisions, self.applies, self.owners, self.responses)
        coverage = tuple(
            Coverage(name, self.sealed_at - WINDOW, self.sealed_at, True, True,
                     tuple(r.stamp.receipt_id for r in rows))
            for name, rows in zip(("decision", "apply", "owner", "ui"), streams)
        )
        return evaluate(self.context, *streams, self.submitted, coverage, now=self.sealed_at)


def _integer(value: object, low: int, high: int) -> bool:
    return type(value) is int and low <= value <= high


def _scope(context: object) -> bool:
    return type(context) is Context and (
        context.action_id, context.light_id, context.mode, context.period, context.zone
    ) == ("brightness", "2", "working", "evening", "desk") and (
        isinstance(context.policy_id, str) and 0 < len(context.policy_id) <= 80
    )


class CaptureSession:
    """Default OFF. Only synthetic_for_tests can open an in-memory session.

    Sequential single-thread fixture API. A failed record destroys the entire
    batch, including prior positives. Clear/revoke/cancel are terminal. Restart
    means a fresh object identity; old ports cannot be reused. Not a security
    boundary against Python callers mutating internals or fabricating all ports.
    """

    def __init__(self) -> None:
        self.identity = object()
        self._consent = None
        self._limit = 0
        self._last = -1
        self._reason = "disabled"
        self._rows = {name: [] for name in ("decision", "apply", "owner", "ui")}
        self._submitted = []
        self._ids = set()
        self._revisions = {}
        self._sessions = set()

    @classmethod
    def synthetic_for_tests(cls, consent: SyntheticConsent, *, max_events: int = 80):
        """Caller booleans never enable real capture or establish real consent."""
        session = cls()
        if (type(consent) is SyntheticConsent and _scope(consent.context)
                and consent.principal == "fictional_owner" and consent.explicit is True
                and consent.historical_backfill is False
                and _integer(consent.starts, WINDOW, 253402300799)
                and _integer(consent.expires, consent.starts + 1, consent.starts + 7 * DAY)
                and type(consent.verbs) is tuple and bool(consent.verbs)
                and all(type(v) is str and v in {"accept", "correct", "reject", "reverse"}
                        for v in consent.verbs)
                and len(set(consent.verbs)) == len(consent.verbs)
                and _integer(max_events, 4, 100)):
            session._consent = consent
            session._limit = max_events
            session._last = consent.starts
            session._reason = "synthetic_active"
        return session

    @property
    def state(self) -> str:
        return self._reason

    @property
    def retained_events(self) -> int:
        return sum(len(rows) for rows in self._rows.values())

    def revoke(self) -> None:
        self._stop("revoked")

    def clear(self) -> None:
        self._stop("cleared")

    def cancel(self) -> None:
        """Also required on capture gap, takeover, owner conflict or restart."""
        self._stop("cancelled_or_capture_gap")

    def _stop(self, reason: str) -> bool:
        self._consent = None
        self._reason = reason
        for rows in self._rows.values():
            rows.clear()
        self._submitted.clear()
        self._ids.clear()
        self._revisions.clear()
        self._sessions.clear()
        return False

    def _record(self, producer, row, port, revision, now, submitted=None):
        if self._consent is None:
            return False
        c = self._consent
        try:
            expected_type = {"decision": DecisionReceipt, "apply": ApplyReceipt,
                             "owner": OwnerSnapshot, "ui": UIReceipt}[producer]
            if type(row) is not expected_type or type(port) is not SyntheticPort:
                return self._stop("malformed_record")
            s = row.stamp
            d = row.response if producer == "ui" else row.decision
            if type(s) is not Stamp or type(d) is not (Feedback if producer == "ui" else Decision):
                return self._stop("malformed_record")
            if (port.session is not self.identity or port.producer != producer
                    or port.source_verified is not True
                    or (producer == "ui" and (port.actor_verified is not True
                                               or port.principal != c.principal))
                    or not _integer(now, self._last, c.expires - 1)
                    or not _integer(s.at, c.starts, now)
                    or not _integer(s.captured_at, now, now)
                    or not _integer(revision, 0, 2**63 - 1)
                    or type(d.context) is not Context or d.context != c.context
                    or type(s.receipt_id) is not str or not 0 < len(s.receipt_id) <= 80
                    or s.receipt_id in self._ids
                    or not _integer(s.sequence, len(self._rows[producer]) + 1,
                                    len(self._rows[producer]) + 1)
                    or self.retained_events >= self._limit):
                return self._stop("boundary_time_scope_replay_or_capacity")
            if any(s.at < previous.stamp.at for previous in self._rows[producer][-1:]):
                return self._stop("producer_order_reversed")
            decision_id = d.decision_id
            origins = {r.decision.decision_id: r.decision for r in self._rows["decision"]}
            if producer == "decision":
                if (decision_id in origins or d.session_id in self._sessions
                        or not isinstance(decision_id, str) or not 0 < len(decision_id) <= 80
                        or not isinstance(d.session_id, str) or not 0 < len(d.session_id) <= 80
                        or d.at != s.at or d.owner != "automation" or d.house != "Home"
                        or d.temporary is not False or d.experiment is not False
                        or not _integer(d.brightness, 1, 254)
                        or type(d.confidence) not in (int, float) or not .9 <= d.confidence <= 1
                        or not _integer(d.context_at, d.at - 60, d.at)):
                    return self._stop("invalid_decision")
                self._revisions[decision_id] = revision
                self._sessions.add(d.session_id)
            else:
                origin = origins.get(decision_id)
                if origin is None or self._revisions[decision_id] != revision:
                    return self._stop("missing_decision_or_owner_revision_changed")
                if producer != "ui" and d != origin:
                    return self._stop("final_intent_changed")
                if producer == "apply":
                    if (row.acknowledged is not True or not origin.at <= s.at <= origin.at + 600
                            or any(r.decision.decision_id == decision_id for r in self._rows["apply"])):
                        return self._stop("failed_partial_or_duplicate_ack")
                elif producer == "owner":
                    if (not any(r.decision == origin and r.owner_receipt_id == s.receipt_id
                                for r in self._rows["apply"])
                            or row.owner != "automation" or row.house != "Home"
                            or row.authoritative is not True
                            or not s.at <= origin.at <= row.through == now <= origin.at + 600
                            or not _integer(row.context_at, origin.at - 60, origin.at)
                            or not _integer(row.response_context_at, now - 30, now)
                            or any(r.decision == origin for r in self._rows["owner"])):
                        return self._stop("owner_conflict_gap_or_stale_context")
                else:
                    if (type(submitted) is not Feedback or submitted != d
                            or d.actor != port.principal or d.source != "fictional_explicit_ui"
                            or d.kind not in c.verbs or d.at != s.at
                            or row.owner_qualified is not True
                            or row.interaction != "explicit_decision_response"
                            or not origin.at <= d.at <= now <= origin.at + 600
                            or d.session_id != origin.session_id
                            or not _integer(d.source_at, now - 30, now)
                            or not _integer(d.brightness, 1, 254)
                            or any(r.response.decision_id == decision_id for r in self._rows["ui"])
                            or not any(r.stamp.receipt_id == row.apply_receipt_id
                                       and r.decision == origin
                                       and r.owner_receipt_id == row.owner_receipt_id
                                       for r in self._rows["apply"])
                            or not any(r.stamp.receipt_id == row.owner_receipt_id
                                       and r.decision == origin and r.through == now
                                       for r in self._rows["owner"])):
                        return self._stop("unqualified_or_conflicting_ui")
                    self._submitted.append(submitted)
            if now - (row.through if producer == "owner" else s.at) > 30:
                return self._stop("stale_capture")
            self._rows[producer].append(row)
            self._ids.add(s.receipt_id)
            self._last = now
            return True
        except (AttributeError, TypeError, ValueError, KeyError):
            return self._stop("malformed_record")

    def decision(self, row: DecisionReceipt, port: SyntheticPort, *, revision: int, now: int) -> bool:
        return self._record("decision", row, port, revision, now)

    def final_ack(self, row: ApplyReceipt, port: SyntheticPort, *, revision: int, now: int) -> bool:
        return self._record("apply", row, port, revision, now)

    def owner_context(self, row: OwnerSnapshot, port: SyntheticPort, *, revision: int, now: int) -> bool:
        return self._record("owner", row, port, revision, now)

    def explicit_feedback(self, row: UIReceipt, port: SyntheticPort, submitted: Feedback,
                          *, revision: int, now: int) -> bool:
        return self._record("ui", row, port, revision, now, submitted)

    def seal(self, *, now: int) -> OfflineBundle | None:
        """Terminal export, no evaluator call; incomplete batches are destroyed."""
        c = self._consent
        if c is None:
            return None
        if (not _integer(now, self._last, c.expires - 1)
                or not self._rows["decision"]
                or len({len(rows) for rows in self._rows.values()}) != 1):
            self._stop("expired_or_incomplete_batch")
            return None
        bundle = OfflineBundle(c.context, *(tuple(rows) for rows in self._rows.values()),
                               tuple(self._submitted), now)
        self._stop("sealed")
        return bundle
