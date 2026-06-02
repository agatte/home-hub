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
# Camera sanity is judged over a LONG horizon. The hard lesson (2026-06-02,
# first hour in prod): a 5-min variance window false-positives whenever the room
# is steadily lit and the person is just moving in and out of frame — flat lux +
# toggling presence looks identical to a decoupled sensor over minutes. The
# genuine 2026-05-27 fault held ONE lux value for *days*; a healthy camera over
# ~90 min almost always sees lighting actually change (lamp on/off, dimming,
# day→evening). So `lux_variance_collapse` now requires the freeze to PERSIST
# ~90 min while presence still toggles. The fast checks (uncalibrated,
# implausible) keep a short horizon — they read the latest sample / recent
# median and need no long buffer. Detection latency for a real decoupling rises
# from minutes to ~90 min, which is still a massive win over the 5-DAY miss it
# was built to catch, and the quarantine gate's only cost in the meantime is a
# few dropped training rows (retrained nightly).
CAMERA_WINDOW_SECONDS = 7200.0        # 2h observation buffer (holds the 90-min span + margin)
CAMERA_MAX_SAMPLES = 4000             # ~2h at the 2s poll, with headroom
CAMERA_MIN_SAMPLES = 30               # floor before any judgement at all
CAMERA_RECENT_SAMPLES = 60            # ~2 min — window for the responsive implausibility median
# lux_variance_collapse: the freeze must persist at least this long, with at
# least this many samples, while presence toggles, before we distrust the lane.
LUX_COLLAPSE_MIN_SPAN_SECONDS = 5400.0   # 90 min
LUX_COLLAPSE_MIN_SAMPLES = 600           # ~20 min of frames even allowing camera pauses
# Smoothed lux carries sensor noise; a population stddev below this across the
# long window (with presence changing) is a frozen/decoupled reading.
LUX_VARIANCE_EPSILON = 0.5
# Median lux this far outside the calibrated baseline band is physically
# implausible (stuck-at-zero / runaway sensor), independent of presence.
LUX_IMPLAUSIBLE_LOW_FACTOR = 0.1
LUX_IMPLAUSIBLE_HIGH_FACTOR = 5.0

# --- generic variance-collapse tunables (audio classifier, etc.) --------------
AUDIO_MIN_SAMPLES = 20
AUDIO_SCORE_VARIANCE_EPSILON = 1e-3
# The audio_ml lane is fed by ambient_monitor POSTs at its SHADOW_LOG_INTERVAL
# (30s) steady-state cadence. The 300s registry default holds only ~10 samples —
# below AUDIO_MIN_SAMPLES — so the predicate could never reach quorum and would
# fail-open forever. A 30-min window holds ≥20 samples with margin. (Same
# default-fallback trap that defeated camera's lux_variance_collapse — see
# camera_service._register_camera_sanity.)
AUDIO_WINDOW_SECONDS = 1800.0
AUDIO_MAX_SAMPLES = 200


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

    * ``uncalibrated`` — camera reports it has no lux baseline yet (fast).
    * ``lux_implausible`` — RECENT median lux sits far outside the calibrated
      baseline band (stuck-at-zero / runaway sensor), independent of presence.
      Uses the last ``CAMERA_RECENT_SAMPLES`` so it reacts in ~2 min.
    * ``lux_variance_collapse`` — smoothed lux is frozen (population stddev <
      ``LUX_VARIANCE_EPSILON``) across a LONG horizon (≥ ``LUX_COLLAPSE_MIN_SPAN``)
      while presence keeps toggling. This is the decoupled-sensor signature
      (2026-05-27 "≈49.5 for days"). The long horizon is deliberate: a steady-lit
      room with a person sitting still reads flat over minutes but virtually
      never over 90 min, whereas a decoupled sensor stays flat indefinitely.

    Fail-open: insufficient evidence at any stage → trusted.
    """
    n = len(observations)
    if n < CAMERA_MIN_SAMPLES:
        return True, "insufficient_samples", {"samples": n, "need": CAMERA_MIN_SAMPLES}

    latest = observations[-1].value
    if latest.get("calibrated") is False:
        return False, "uncalibrated", {"samples": n}

    span = (observations[-1].at - observations[0].at).total_seconds()
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
    # Responsive implausibility: judge the RECENT median, not the whole 2h, so a
    # sensor that lurches to a stuck-at-zero/runaway value is caught in ~2 min.
    recent_lux = lux_values[-CAMERA_RECENT_SAMPLES:]
    recent_median = statistics.median(recent_lux)

    metrics = {
        "lux_stdev": round(stdev_lux, 3),
        "lux_median": round(median_lux, 2),
        "recent_lux_median": round(recent_median, 2),
        "presence_toggled": presence_toggled,
        "span_seconds": round(span, 1),
        "lux_samples": len(lux_values),
    }

    # Fast: physically implausible recent reading vs the calibrated baseline.
    baseline = latest.get("baseline_lux")
    if baseline:
        baseline = float(baseline)
        low, high = (
            baseline * LUX_IMPLAUSIBLE_LOW_FACTOR,
            baseline * LUX_IMPLAUSIBLE_HIGH_FACTOR,
        )
        if recent_median < low or recent_median > high:
            return False, "lux_implausible", {**metrics, "baseline": round(baseline, 2)}

    # Slow: variance collapse requires a SUSTAINED freeze, not a few steady
    # minutes. This is the guard against the 2026-06-02 false positive (4 min of
    # steady ~35 lux while settling in post-boot tripped the old 5-min window).
    if (
        span >= LUX_COLLAPSE_MIN_SPAN_SECONDS
        and len(lux_values) >= LUX_COLLAPSE_MIN_SAMPLES
        and stdev_lux < LUX_VARIANCE_EPSILON
        and presence_toggled
    ):
        return False, "lux_variance_collapse", metrics

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


def register_audio_ml(source_trust: SourceTrust) -> None:
    """Register the ``audio_ml`` lane with its variance-collapse predicate.

    Shared by ``bootstrap`` and the tests so the window sizing can't drift
    (mirrors camera's ``_register_camera_sanity``). The lane has no backend
    service object — it's fed by ``ambient_monitor`` POSTs to
    ``/api/learning/audio-decision`` — so it's registered at bootstrap rather
    than from a service. The window is sized for the monitor's ≤30s shadow-log
    cadence so the predicate can reach ``AUDIO_MIN_SAMPLES``; see the tunable
    comment above. Catches a stuck classifier emitting flat ``top_score`` (the
    abandoned YAMNet ~0.088 tell).
    """
    source_trust.register(
        "audio_ml",
        predicate=variance_collapse_predicate(
            "top_score",
            min_samples=AUDIO_MIN_SAMPLES,
            epsilon=AUDIO_SCORE_VARIANCE_EPSILON,
        ),
        window_seconds=AUDIO_WINDOW_SECONDS,
        max_samples=AUDIO_MAX_SAMPLES,
    )
