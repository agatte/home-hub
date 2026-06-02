"""
Source-trust registry — per-source data-validity ("sanity") tracking.

Complements :class:`HeartbeatRegistry`. Heartbeat answers *"is this source
ticking?"*; SourceTrust answers *"is the data it's producing trustworthy?"*.
A source can be live (heartbeat green, data flowing) while emitting garbage —
the motivating incident: the 2026-05-27 camera relocation pinned ``ema_lux`` to
~49.5 for five days, silently poisoning the behavioral predictor (``watching``
accuracy → 0%). Liveness never caught it because the camera kept polling at
2s cadence the whole time. See ``project_predictor_lux_distribution_shift``.

Each source registers a sanity *predicate* and pushes *observations* once per
poll iteration via :meth:`observe`. :meth:`verdict` runs the predicate over the
rolling observation window and returns trusted/untrusted + a reason;
:meth:`snapshot` returns all verdicts for ``/health`` and ``/api/vitals``.

The class is pure data — no I/O, no async — so it can be instantiated once in
``bootstrap.py`` and injected into each service via a setter (mirrors
``app.state.heartbeats``). Liveness (heartbeat age) and circuit-breaker state
are merged in at the ``/health`` layer, where both are already available; this
class owns *sanity* only.

**Fail-open by design.** An unregistered source, or a registered source without
enough fresh samples to judge, is reported **trusted**. The ML quarantine gate
must never drop real training data on a hunch — only a predicate that positively
trips, or an explicit ``mark(..., trusted=False)``, yields untrusted.

Tests in ``tests/test_source_trust.py`` lock the predicate + window math.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Callable, Deque, Optional

# A predicate inspects the (chronological) observation window and returns
# ``(trusted, reason, metrics)``. ``reason`` is a stable slug for the digest /
# watcher to key on (e.g. "lux_variance_collapse"); ``metrics`` is diagnostic
# context surfaced in /health.
Predicate = Callable[[list["_Observation"], datetime], "tuple[bool, str, dict]"]

DEFAULT_WINDOW_SECONDS = 300.0
DEFAULT_MAX_SAMPLES = 300

# --- camera sanity tunables ---------------------------------------------------
# Need a minimum of evidence before judging — a freshly-(re)started camera or a
# brief window must read trusted, not be quarantined on two frames.
CAMERA_MIN_SAMPLES = 30
CAMERA_MIN_SPAN_SECONDS = 120.0
# Smoothed lux carries sensor noise; a population stddev below this over 2+ min
# while presence is *changing* means the reading is frozen/decoupled from the
# room (the 5/27 "≈49.5 always" signature), not merely a steady-lit room.
LUX_VARIANCE_EPSILON = 0.5
# Median lux this far outside the calibrated baseline band is physically
# implausible (stuck-at-zero / runaway sensor), independent of presence.
LUX_IMPLAUSIBLE_LOW_FACTOR = 0.1
LUX_IMPLAUSIBLE_HIGH_FACTOR = 5.0

# --- generic variance-collapse tunables (audio classifier, etc.) --------------
AUDIO_MIN_SAMPLES = 20
AUDIO_SCORE_VARIANCE_EPSILON = 1e-3


@dataclass
class _Observation:
    at: datetime
    value: dict


@dataclass
class _Source:
    name: str
    window_seconds: float
    max_samples: int
    predicate: Optional[Predicate]
    observations: Deque[_Observation] = field(default_factory=deque)
    # Explicit operator/remediator override. When set, it wins over the
    # predicate until cleared — this backs the ``set_source_trust`` remediation
    # action and manual quarantine. Sticky (no auto-expiry); reversible via
    # ``clear_mark``.
    manual_trusted: Optional[bool] = None
    manual_reason: Optional[str] = None
    manual_at: Optional[datetime] = None


class SourceTrust:
    """In-memory map of source name → rolling observations + sanity verdict."""

    def __init__(self) -> None:
        self._sources: dict[str, _Source] = {}
        self._lock = Lock()

    def register(
        self,
        name: str,
        *,
        predicate: Optional[Predicate] = None,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_samples: int = DEFAULT_MAX_SAMPLES,
    ) -> None:
        """Register a source with an optional sanity predicate.

        A source with ``predicate=None`` is always trusted (it only exists so
        it shows up in ``snapshot`` for completeness). Re-registering preserves
        any existing observation window so a cadence/predicate tweak at runtime
        doesn't blind a concurrent anomaly.
        """
        if window_seconds <= 0:
            raise ValueError(f"window_seconds must be positive, got {window_seconds}")
        if max_samples <= 0:
            raise ValueError(f"max_samples must be positive, got {max_samples}")
        with self._lock:
            existing = self._sources.get(name)
            obs: Deque[_Observation] = (
                existing.observations if existing else deque(maxlen=max_samples)
            )
            # deque maxlen is immutable; rebuild if the cap changed.
            if obs.maxlen != max_samples:
                obs = deque(obs, maxlen=max_samples)
            self._sources[name] = _Source(
                name=name,
                window_seconds=float(window_seconds),
                max_samples=int(max_samples),
                predicate=predicate,
                observations=obs,
                manual_trusted=existing.manual_trusted if existing else None,
                manual_reason=existing.manual_reason if existing else None,
                manual_at=existing.manual_at if existing else None,
            )

    def deregister(self, name: str) -> None:
        """Drop a source — used when an opt-in service (camera) is disabled or
        paused, so it isn't judged during legitimate downtime."""
        with self._lock:
            self._sources.pop(name, None)

    def observe(self, name: str, value: dict, *, now: Optional[datetime] = None) -> None:
        """Append one observation for a registered source. No-op for unknown
        names (keeps callers safe during teardown races). Prunes anything older
        than the source's window so the predicate only sees recent evidence."""
        if now is None:
            now = datetime.now(timezone.utc)
        with self._lock:
            src = self._sources.get(name)
            if src is None:
                return
            src.observations.append(_Observation(at=now, value=dict(value)))
            self._prune(src, now)

    def mark(self, name: str, *, trusted: bool, reason: str) -> None:
        """Set an explicit trust override that wins over the predicate.

        Backs the ``set_source_trust`` remediation action and manual quarantine.
        No-op for unknown names. Sticky until :meth:`clear_mark`."""
        with self._lock:
            src = self._sources.get(name)
            if src is None:
                return
            src.manual_trusted = bool(trusted)
            src.manual_reason = reason
            src.manual_at = datetime.now(timezone.utc)

    def clear_mark(self, name: str) -> None:
        """Drop an explicit override, returning the source to predicate-driven
        judgement. No-op for unknown names."""
        with self._lock:
            src = self._sources.get(name)
            if src is None:
                return
            src.manual_trusted = None
            src.manual_reason = None
            src.manual_at = None

    def verdict(self, name: str, *, now: Optional[datetime] = None) -> dict:
        """Return the current trust verdict for one source.

        Shape: ``{name, trusted, reason, sample_count, last_observation_at,
        manual, metrics}``. Unknown sources are reported trusted (fail-open) so
        the ML quarantine gate never drops data for a source it isn't tracking.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        with self._lock:
            src = self._sources.get(name)
            if src is None:
                return {
                    "name": name,
                    "trusted": True,
                    "reason": "untracked",
                    "sample_count": 0,
                    "last_observation_at": None,
                    "manual": False,
                    "metrics": {},
                }
            return self._verdict_locked(src, now)

    def snapshot(self, *, now: Optional[datetime] = None) -> list[dict]:
        """Per-source verdicts for ``/health`` + ``/api/vitals``. Sorted by name
        for stable output. ``now`` is injectable for tests."""
        if now is None:
            now = datetime.now(timezone.utc)
        with self._lock:
            rows = [self._verdict_locked(src, now) for src in self._sources.values()]
        rows.sort(key=lambda r: r["name"])
        return rows

    def clear(self) -> None:
        """Drop all sources. Used by tests for isolation."""
        with self._lock:
            self._sources.clear()

    # --- internals (call under lock) -----------------------------------------

    def _prune(self, src: _Source, now: datetime) -> None:
        cutoff = now.timestamp() - src.window_seconds
        while src.observations and src.observations[0].at.timestamp() < cutoff:
            src.observations.popleft()

    def _verdict_locked(self, src: _Source, now: datetime) -> dict:
        self._prune(src, now)
        observations = list(src.observations)
        last_at = observations[-1].at if observations else None
        base = {
            "name": src.name,
            "sample_count": len(observations),
            "last_observation_at": last_at.isoformat() if last_at else None,
        }
        # Explicit override wins.
        if src.manual_trusted is not None:
            return {
                **base,
                "trusted": src.manual_trusted,
                "reason": src.manual_reason or (
                    "marked_trusted" if src.manual_trusted else "marked_untrusted"
                ),
                "manual": True,
                "metrics": {},
            }
        # No predicate → always trusted (presence-only entry).
        if src.predicate is None:
            return {**base, "trusted": True, "reason": "no_predicate", "manual": False, "metrics": {}}
        try:
            trusted, reason, metrics = src.predicate(observations, now)
        except Exception as exc:  # predicate bug must never crash /health
            return {
                **base,
                "trusted": True,
                "reason": f"predicate_error:{type(exc).__name__}",
                "manual": False,
                "metrics": {},
            }
        return {
            **base,
            "trusted": bool(trusted),
            "reason": reason,
            "manual": False,
            "metrics": metrics or {},
        }


# ---------------------------------------------------------------------------
# Built-in predicates
# ---------------------------------------------------------------------------


def camera_sanity(observations: list[_Observation], now: datetime) -> "tuple[bool, str, dict]":
    """Sanity predicate for the camera lane.

    Each observation value carries ``{ema_lux, baseline_lux, calibrated,
    present, consecutive_absent}``. Trips (returns untrusted) on:

    * ``uncalibrated`` — camera reports it has no lux baseline yet.
    * ``lux_variance_collapse`` — smoothed lux is effectively frozen
      (population stddev < ``LUX_VARIANCE_EPSILON``) over 2+ min while presence
      *toggled* between present/absent. This is the 2026-05-27 "≈49.5 always"
      signature: the reading decoupled from the room.
    * ``lux_implausible`` — median lux sits far outside the calibrated baseline
      band, independent of presence (stuck-at-zero / runaway sensor).

    Fail-open: insufficient samples or span → trusted.
    """
    n = len(observations)
    if n < CAMERA_MIN_SAMPLES:
        return True, "insufficient_samples", {"samples": n, "need": CAMERA_MIN_SAMPLES}

    latest = observations[-1].value
    if latest.get("calibrated") is False:
        return False, "uncalibrated", {"samples": n}

    span = (observations[-1].at - observations[0].at).total_seconds()
    if span < CAMERA_MIN_SPAN_SECONDS:
        return True, "insufficient_span", {"span_seconds": round(span, 1)}

    lux_values = [
        float(o.value["ema_lux"])
        for o in observations
        if o.value.get("ema_lux") is not None
    ]
    if len(lux_values) < CAMERA_MIN_SAMPLES:
        return True, "insufficient_lux_samples", {"lux_samples": len(lux_values)}

    presence_flags = {bool(o.value.get("present")) for o in observations}
    presence_toggled = len(presence_flags) > 1
    stdev_lux = statistics.pstdev(lux_values)
    median_lux = statistics.median(lux_values)

    metrics = {
        "lux_stdev": round(stdev_lux, 3),
        "lux_median": round(median_lux, 2),
        "presence_toggled": presence_toggled,
        "span_seconds": round(span, 1),
        "samples": n,
    }

    if stdev_lux < LUX_VARIANCE_EPSILON and presence_toggled:
        return False, "lux_variance_collapse", metrics

    baseline = latest.get("baseline_lux")
    if baseline:
        baseline = float(baseline)
        low, high = (
            baseline * LUX_IMPLAUSIBLE_LOW_FACTOR,
            baseline * LUX_IMPLAUSIBLE_HIGH_FACTOR,
        )
        if median_lux < low or median_lux > high:
            return False, "lux_implausible", {**metrics, "baseline": round(baseline, 2)}

    return True, "ok", metrics


def variance_collapse_predicate(
    value_key: str,
    *,
    min_samples: int,
    epsilon: float,
) -> Predicate:
    """Factory: a predicate that trips when a scalar series goes flat.

    Used for the audio classifier (top-score variance collapse — the abandoned
    YAMNet ``speech_multiple`` gate showed a flat ~0.088, the tell of a stuck
    model). Generic enough to reuse for any source whose health shows up as
    "the number stopped moving."
    """

    def _predicate(observations: list[_Observation], now: datetime) -> "tuple[bool, str, dict]":
        values = [
            float(o.value[value_key])
            for o in observations
            if o.value.get(value_key) is not None
        ]
        if len(values) < min_samples:
            return True, "insufficient_samples", {"samples": len(values), "need": min_samples}
        stdev = statistics.pstdev(values)
        metrics = {"stdev": round(stdev, 6), "samples": len(values), "key": value_key}
        if stdev < epsilon:
            return False, "variance_collapse", metrics
        return True, "ok", metrics

    return _predicate
