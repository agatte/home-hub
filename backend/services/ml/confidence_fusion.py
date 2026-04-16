"""Multi-signal confidence fusion for mode prediction.

Combines confidence scores from multiple detection signals (process
detection, camera presence, audio classification, behavioral predictor,
rule engine) into a single weighted ensemble.  The fused result can
auto-apply mode changes at high confidence or suggest them via the
dashboard at lower thresholds.

Pure Python — no external dependencies beyond the standard library.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("home_hub.ml")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MODES = frozenset({
    "gaming", "working", "watching", "social", "relax",
    "movie", "idle", "away", "sleeping",
})

SIGNAL_SOURCES = ("process", "camera", "audio_ml", "behavioral", "rule_engine")

DEFAULT_WEIGHTS: dict[str, float] = {
    "process": 0.35,
    "camera": 0.20,
    "audio_ml": 0.15,
    "behavioral": 0.20,
    "rule_engine": 0.10,
}

AUTO_APPLY_THRESHOLD = 0.95
OVERRIDE_THRESHOLD = 0.98
SUGGEST_THRESHOLD = 0.70
STALE_SIGNAL_SECONDS = 300  # 5 minutes


@dataclass
class Signal:
    """A single detection signal reading."""

    source: str
    mode: str
    confidence: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConfidenceFusion:
    """Weighted ensemble fusion of multiple mode-detection signals.

    Tracks the latest reading from each signal source, discards stale
    signals, and computes a fused mode prediction with confidence,
    agreement, and action thresholds.
    """

    def __init__(self) -> None:
        self._signals: dict[str, Signal] = {}
        self._weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
        logger.info("ConfidenceFusion initialized with %d sources", len(SIGNAL_SOURCES))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def report_signal(self, source: str, mode: str, confidence: float) -> None:
        """Store the latest reading from a signal source.

        Fire-and-forget — never raises.  Invalid inputs are logged and
        silently dropped.

        Args:
            source: One of SIGNAL_SOURCES.
            mode: Detected mode (must be in VALID_MODES).
            confidence: Confidence score in [0, 1].
        """
        try:
            if source not in SIGNAL_SOURCES:
                logger.warning("Unknown signal source: %s", source)
                return
            if mode not in VALID_MODES:
                logger.warning("Invalid mode from %s: %s", source, mode)
                return
            confidence = max(0.0, min(1.0, float(confidence)))

            self._signals[source] = Signal(
                source=source,
                mode=mode,
                confidence=confidence,
            )
        except Exception:
            logger.exception("Error recording signal from %s", source)

    def compute_fusion(self) -> Optional[dict[str, Any]]:
        """Compute the weighted fusion of all active signals.

        Returns:
            A FusionResult dict if any active signals exist, else None.
        """
        now = datetime.now(timezone.utc)

        # Classify each source as active or stale
        active: dict[str, Signal] = {}
        stale_sources: set[str] = set()
        for src in SIGNAL_SOURCES:
            sig = self._signals.get(src)
            if sig and (now - sig.timestamp).total_seconds() <= STALE_SIGNAL_SECONDS:
                active[src] = sig
            else:
                stale_sources.add(src)

        if not active:
            return None

        # Redistribute stale weights to active sources proportionally
        active_weight_sum = sum(self._weights[s] for s in active)
        if active_weight_sum <= 0:
            return None

        normalized_weights: dict[str, float] = {
            s: self._weights[s] / active_weight_sum for s in active
        }

        # Group votes by mode, sum (weight * confidence) per mode
        mode_scores: dict[str, float] = {}
        for src, sig in active.items():
            w = normalized_weights[src]
            score = w * sig.confidence
            mode_scores[sig.mode] = mode_scores.get(sig.mode, 0.0) + score

        # Winner = mode with highest weighted sum
        fused_mode = max(mode_scores, key=mode_scores.get)  # type: ignore[arg-type]
        fused_confidence = mode_scores[fused_mode]

        # Agreement = fraction of active signals voting for the winner
        agreeing = sum(1 for sig in active.values() if sig.mode == fused_mode)
        agreement = agreeing / len(active)

        # Action thresholds
        auto_apply = fused_confidence >= AUTO_APPLY_THRESHOLD
        can_override = (
            fused_confidence >= OVERRIDE_THRESHOLD and agreement >= 0.80
        )

        # Build per-signal detail dict
        signals_detail: dict[str, dict[str, Any]] = {}
        for src in SIGNAL_SOURCES:
            sig = self._signals.get(src)
            is_stale = src in stale_sources
            if sig:
                signals_detail[src] = {
                    "mode": sig.mode,
                    "confidence": sig.confidence,
                    "weight": self._weights.get(src, 0.0),
                    "stale": is_stale,
                    "agrees": sig.mode == fused_mode and not is_stale,
                    "last_update": sig.timestamp.isoformat(),
                }
            else:
                signals_detail[src] = {
                    "mode": None,
                    "confidence": 0,
                    "weight": self._weights.get(src, 0.0),
                    "stale": True,
                    "agrees": False,
                    "last_update": None,
                }

        return {
            "fused_mode": fused_mode,
            "fused_confidence": round(fused_confidence, 4),
            "agreement": round(agreement, 4),
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

        total = sum(raw.values())
        if total <= 0:
            logger.warning("All accuracy values zero — keeping current weights")
            return

        self._weights = {src: val / total for src, val in raw.items()}
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
