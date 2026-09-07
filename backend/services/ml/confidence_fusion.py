"""Multi-signal confidence fusion for mode prediction.

Combines confidence scores from multiple detection signals (process
detection, camera presence, audio classification, rule engine) into
a single weighted ensemble. The fused result exposes confidence and
agreement-derived diagnostic flags for shadow observation; it does not
actuate production mode changes.

Pure Python — no external dependencies beyond the standard library.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("home_hub.ml")

_LOCAL_TZ = ZoneInfo("America/Indiana/Indianapolis")


def _is_late_night_local() -> bool:
    """True during the evening-to-dawn window when process detection is
    least reliable (stale dev tools left open, etc.). Matches the
    automation engine's late_night_start_hour=22 / wake_hour=6 defaults.
    """
    hour = datetime.now(_LOCAL_TZ).hour
    return hour >= 22 or hour < 6

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MODES = frozenset({
    "gaming", "working", "watching", "social", "relax",
    "cooking", "idle", "sleeping",
})

SIGNAL_SOURCES = (
    "process", "camera", "audio_ml", "rule_engine",
)

# Lane history:
#   - Behavioral (LightGBM) lane removed 2026-04-27 after a single-class
#     collapse audit (898/898 → one class, 0.64% real accuracy).
#   - Presence lane removed when the home/away concept was retired in
#     favor of Hue's native geofencing (iOS Shortcut webhooks were too
#     unreliable).
# Pre-removal weights with presence summed to 1.0:
#   process 0.344, camera 0.196, audio_ml 0.147, rule_engine 0.098,
#   presence 0.215. Dropping presence and dividing the rest by 0.785
#   preserves their relative ratios while keeping the sum = 1.0.
DEFAULT_WEIGHTS: dict[str, float] = {
    "process":     0.438,
    "camera":      0.250,
    "audio_ml":    0.187,
    "rule_engine": 0.125,
}

# Floor applied by update_weights_from_accuracy: each lane keeps at least this
# fraction of its DEFAULT_WEIGHTS value before re-normalization. The nightly
# accuracy-based tuner otherwise starves the camera/audio_ml lanes — they vote
# presence/ambient (correctly) rather than the dominant process mode, so their
# raw mode-match accuracy is structurally low (~8-9%), which would drive process
# toward ~0.62 and the other lanes toward zero, making fusion effectively
# process-only. See digests/2026-05-25.md 15:45 ET fusion-lane audit.
WEIGHT_FLOOR_FRACTION = 0.5

AUTO_APPLY_THRESHOLD = 0.95
OVERRIDE_THRESHOLD = 0.92
SUGGEST_THRESHOLD = 0.70
STALE_SIGNAL_SECONDS = 300  # 5 minutes

# Late-night decay applied to the process-detection lane. Stale dev tools
# (terminals, editors) left open at night mislead process detection into
# reporting "working" when the user is actually winding down, so we let
# the other signals carry more weight.
LATE_NIGHT_PROCESS_WEIGHT_FACTOR = 0.6

# Max sub-factors surfaced per lane (keeps the analytics constellation readable).
# Bumped 4 → 5 in Phase 2 of multi-camera fusion so the camera lane can carry
# the existing 4 pips (presence/zone/posture/lux) PLUS a ``presence_sources``
# attribution pip naming the live presence sources (latitude / desktop / …).
# That attribution is what fusion-lane-auditor keys on to assert both cameras
# are contributing.
MAX_FACTORS_PER_LANE = 5


def _clean_factors(
    factors: Optional[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Normalize a caller-supplied factor list into a safe shape.

    Drops malformed entries, clamps ``impact`` to [0, 1], coerces
    ``stale`` to bool, and truncates to MAX_FACTORS_PER_LANE.
    """
    if not factors:
        return []
    cleaned: list[dict[str, Any]] = []
    for f in factors:
        if not isinstance(f, dict):
            continue
        key = f.get("key")
        if not isinstance(key, str) or not key:
            continue
        try:
            impact = max(0.0, min(1.0, float(f.get("impact", 0.5))))
        except (TypeError, ValueError):
            impact = 0.5
        value = f.get("value")
        display = f.get("display")
        if display is None:
            display = "" if value is None else str(value)
        cleaned.append({
            "key": key,
            "label": str(f.get("label") or key),
            "value": value,
            "display": str(display),
            "impact": round(impact, 3),
            "stale": bool(f.get("stale", False)),
        })
        if len(cleaned) >= MAX_FACTORS_PER_LANE:
            break
    return cleaned


@dataclass
class Signal:
    """A single detection signal reading."""

    source: str
    mode: str
    confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Sub-factors the lane considered when voting. Each entry:
    # {"key": str, "label": str, "value": any, "display": str,
    #  "impact": float in [0,1], "stale": bool}
    # Surfaced to the analytics constellation UI; not used for fusion math.
    factors: list[dict[str, Any]] = field(default_factory=list)


class ConfidenceFusion:
    """Weighted ensemble fusion of multiple mode-detection signals.

    Tracks the latest reading from each signal source, discards stale
    signals, and computes a fused mode prediction with confidence,
    agreement, and action thresholds.
    """

    def __init__(self) -> None:
        self._signals: dict[str, Signal] = {}
        self._weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
        # SourceTrust registry — injected in bootstrap. An untrusted lane is
        # dropped from the vote immediately (a stronger, faster signal than the
        # 300s staleness timeout): a live-but-garbage camera shouldn't keep
        # voting presence into the fused mode while we wait for it to go stale.
        # None → fail-open (every lane trusted), so existing tests are inert.
        self._source_trust: Any = None
        logger.info("ConfidenceFusion initialized with %d sources", len(SIGNAL_SOURCES))

    def set_source_trust_registry(self, registry: Any) -> None:
        """Inject the SourceTrust registry (called from bootstrap)."""
        self._source_trust = registry

    def _is_untrusted(self, source: str) -> bool:
        """True only when SourceTrust has a positive untrusted verdict for the
        source. Fail-open: no registry / untracked source / error → trusted."""
        if self._source_trust is None:
            return False
        try:
            return not self._source_trust.verdict(source).get("trusted", True)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def report_signal(
        self,
        source: str,
        mode: str,
        confidence: float,
        factors: Optional[list[dict[str, Any]]] = None,
        timestamp: Optional[datetime] = None,
    ) -> None:
        """Store the latest reading from a signal source.

        Fire-and-forget — never raises.  Invalid inputs are logged and
        silently dropped.

        Args:
            source: One of SIGNAL_SOURCES.
            mode: Detected mode (must be in VALID_MODES).
            confidence: Confidence score in [0, 1].
            factors: Optional list of sub-factor dicts surfaced to the
                analytics constellation UI. Each entry should include
                keys ``key``, ``label``, ``value``, ``display``, ``impact``
                (float in [0,1]) and optionally ``stale``. Capped at
                ``MAX_FACTORS_PER_LANE``.
        """
        try:
            if source not in SIGNAL_SOURCES:
                logger.warning("Unknown signal source: %s", source)
                return
            if mode not in VALID_MODES:
                logger.warning("Invalid mode from %s: %s", source, mode)
                return
            confidence = max(0.0, min(1.0, float(confidence)))

            if timestamp is not None and timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            self._signals[source] = Signal(
                source=source,
                mode=mode,
                confidence=confidence,
                timestamp=timestamp or datetime.now(timezone.utc),
                factors=_clean_factors(factors),
            )
        except Exception:
            logger.exception("Error recording signal from %s", source)

    def clear_signal(self, source: str) -> None:
        """Remove one lane's current vote without changing other lane ages.

        Process-semantic retractions use this before restoring any retained
        semantic voter.  The caller can then report that retained signal with
        its original timestamp instead of accidentally making old evidence
        fresh again.
        """
        if source not in SIGNAL_SOURCES:
            logger.warning("Unknown signal source: %s", source)
            return
        self._signals.pop(source, None)

    def compute_fusion(self) -> Optional[dict[str, Any]]:
        """Compute the weighted fusion of all active signals.

        Returns:
            A FusionResult dict if any active signals exist, else None.
        """
        now = datetime.now(timezone.utc)

        # Classify each source as active, stale, or untrusted. An untrusted
        # lane (SourceTrust verdict, e.g. camera lux frozen) is excluded from
        # the vote exactly like a stale one — but immediately, not after the
        # 300s staleness window. Tracked separately so signal detail can show
        # *why* a present-but-mute lane isn't counting.
        active: dict[str, Signal] = {}
        stale_sources: set[str] = set()
        untrusted_sources: set[str] = set()
        for src in SIGNAL_SOURCES:
            sig = self._signals.get(src)
            fresh = bool(sig) and (now - sig.timestamp).total_seconds() <= STALE_SIGNAL_SECONDS
            if sig and self._is_untrusted(src):
                untrusted_sources.add(src)
            elif fresh:
                active[src] = sig
            else:
                stale_sources.add(src)

        if not active:
            return None

        # Apply a late-night decay on the process lane before normalization.
        effective_weights = {
            s: (
                self._weights[s] * LATE_NIGHT_PROCESS_WEIGHT_FACTOR
                if s == "process" and _is_late_night_local()
                else self._weights[s]
            )
            for s in active
        }

        # Redistribute stale weights to active sources proportionally
        active_weight_sum = sum(effective_weights.values())
        if active_weight_sum <= 0:
            return None

        # Support is effective lane weight × confidence. Keep fused_confidence
        # on its historical active-capacity scale, while exposing confidence-aware
        # consensus and evidence coverage separately (#190).
        support_by_source = {
            src: effective_weights[src] * sig.confidence
            for src, sig in active.items()
        }
        total_support = sum(support_by_source.values())
        contributor_count = sum(1 for value in support_by_source.values() if value > 0)
        abstention_count = len(active) - contributor_count

        mode_support: dict[str, float] = {}
        for src, sig in active.items():
            support = support_by_source[src]
            if support > 0:
                mode_support[sig.mode] = mode_support.get(sig.mode, 0.0) + support

        if total_support > 0 and mode_support:
            fused_mode: Optional[str] = max(mode_support, key=mode_support.get)
            winning_support = mode_support[fused_mode]
            fused_confidence = winning_support / active_weight_sum
            consensus = winning_support / total_support
            coverage = total_support / active_weight_sum
            evidence_status = "sufficient"
        else:
            fused_mode = None
            winning_support = 0.0
            fused_confidence = 0.0
            consensus = 0.0
            coverage = 0.0
            evidence_status = "insufficient"

        # ``agreement`` remains as a compatibility alias, but schema v2 makes
        # clear that it now means support consensus rather than lane headcount.
        agreement = consensus

        # Action flags remain shadow telemetry only (AutomationEngine has no
        # fusion writer path). All-zero evidence can never qualify.
        auto_apply = evidence_status == "sufficient" and fused_confidence >= AUTO_APPLY_THRESHOLD
        can_override = (
            evidence_status == "sufficient"
            and fused_confidence >= OVERRIDE_THRESHOLD
            and consensus >= 0.80
        )

        # Build per-signal detail dict
        signals_detail: dict[str, dict[str, Any]] = {}
        for src in SIGNAL_SOURCES:
            sig = self._signals.get(src)
            is_untrusted = src in untrusted_sources
            # Staleness and trust are separate reasons a lane can be excluded.
            # Keep both truthful so older boolean consumers do not mislabel a
            # fresh-but-untrusted source as stale; vote_status remains the v2
            # reason code for new consumers.
            is_stale = src in stale_sources
            if sig:
                support = support_by_source.get(src, 0.0) if not is_stale else 0.0
                if is_untrusted:
                    vote_status = "untrusted"
                    agrees: Optional[bool] = False
                elif is_stale:
                    vote_status = "stale"
                    agrees = False
                elif support <= 0:
                    vote_status = "abstains"
                    agrees = None
                elif sig.mode == fused_mode:
                    vote_status = "agrees"
                    agrees = True
                else:
                    vote_status = "disagrees"
                    agrees = False
                signals_detail[src] = {
                    "mode": sig.mode,
                    "confidence": sig.confidence,
                    "weight": self._weights.get(src, 0.0),
                    "effective_weight": effective_weights.get(src, 0.0),
                    "support": round(support, 6),
                    "vote_status": vote_status,
                    "stale": is_stale,
                    "untrusted": is_untrusted,
                    "agrees": agrees,
                    "last_update": sig.timestamp.isoformat(),
                    "factors": list(sig.factors),
                }
            else:
                signals_detail[src] = {
                    "mode": None,
                    "confidence": 0,
                    "weight": self._weights.get(src, 0.0),
                    "effective_weight": 0.0,
                    "support": 0.0,
                    "vote_status": "stale",
                    "stale": True,
                    "untrusted": False,
                    "agrees": False,
                    "last_update": None,
                    "factors": [],
                }

        return {
            "schema_version": 2,
            "agreement_semantics": "support_consensus_v2",
            "evidence_status": evidence_status,
            "fused_mode": fused_mode,
            "fused_confidence": round(fused_confidence, 4),
            "agreement": round(agreement, 4),
            "consensus": round(consensus, 4),
            "coverage": round(coverage, 4),
            "winning_support": round(winning_support, 6),
            "total_support": round(total_support, 6),
            "available_weight_capacity": round(active_weight_sum, 6),
            "contributor_count": contributor_count,
            "abstention_count": abstention_count,
            "active_signals": len(active),
            "total_signals": len(SIGNAL_SOURCES),
            "auto_apply": auto_apply,
            "can_override": can_override,
            "signals": signals_detail,
            "timestamp": now.isoformat(),
        }

    def update_weights_from_accuracy(
        self, accuracy_by_source: dict[str, float],
    ) -> None:
        """Update signal weights based on measured accuracy.

        Normalizes the provided accuracy values so weights sum to 1.0.
        Sources not present in *accuracy_by_source* fall back to their
        DEFAULT_WEIGHTS value.

        Args:
            accuracy_by_source: Mapping of source name to accuracy (0-1).
        """
        raw: dict[str, float] = {}
        for src in SIGNAL_SOURCES:
            raw[src] = accuracy_by_source.get(src, DEFAULT_WEIGHTS[src])

        if sum(raw.values()) <= 0:
            logger.warning("All accuracy values zero — keeping current weights")
            return

        # Floor each lane at half its design weight before normalizing, so a
        # structurally-low-accuracy lane (camera/audio_ml measure presence, not
        # mode) can't be starved toward zero by a high-accuracy process lane.
        floored = {
            src: max(val, DEFAULT_WEIGHTS[src] * WEIGHT_FLOOR_FRACTION)
            for src, val in raw.items()
        }
        total = sum(floored.values())
        self._weights = {src: val / total for src, val in floored.items()}
        logger.info(
            "Fusion weights updated: %s",
            {s: round(w, 3) for s, w in self._weights.items()},
        )

    def get_state(self) -> dict[str, Any]:
        """Return current fusion state for API/debugging."""
        fusion = self.compute_fusion()
        return {
            "weights": dict(self._weights),
            "signal_count": len(self._signals),
            "sources": list(SIGNAL_SOURCES),
            "latest_fusion": fusion,
            "thresholds": {
                "auto_apply": AUTO_APPLY_THRESHOLD,
                "override": OVERRIDE_THRESHOLD,
                "suggest": SUGGEST_THRESHOLD,
                "stale_seconds": STALE_SIGNAL_SECONDS,
            },
        }

    def health(self) -> dict[str, Any]:
        """Health entry for the /health ml block.

        Fusion itself is deterministic — the only meaningful failure
        mode is "every lane stale" (no signals fresh enough to vote).
        Lane-level staleness is normal: rule_engine is data-gated by
        design and the audio_ml lane is gated on the supervisor flag.
        """
        now = datetime.now(timezone.utc)
        active_sources: list[str] = []
        stale_sources: list[str] = []
        never_reported: list[str] = []
        for src in SIGNAL_SOURCES:
            sig = self._signals.get(src)
            if sig is None:
                never_reported.append(src)
                continue
            age = (now - sig.timestamp).total_seconds()
            if age <= STALE_SIGNAL_SECONDS:
                active_sources.append(src)
            else:
                stale_sources.append(src)

        if active_sources:
            status = "healthy"
        elif self._signals:
            # Every lane has reported at some point but nothing is fresh.
            status = "unhealthy"
        else:
            # Boot transient — no lane has reported yet.
            status = "idle"

        return {
            "status": status,
            "active_sources": active_sources,
            "stale_sources": stale_sources,
            "never_reported": never_reported,
        }
