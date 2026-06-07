"""Per-room ambient-lux channel — EMA-smoothed brightness + calibrated baseline.

A lightweight store for one room's camera-derived lux. ``CameraService`` owns
the living-room channel in-process (it holds the Latitude camera); this is the
store for rooms whose lux arrives over the network. The **bedroom** channel is
fed by the desktop pc_agent's periodic lux POSTs (D4 — see
``docs/PRESENCE_LIGHTING_SCENARIOS.md`` Part 7.5).

Property names (``ema_lux`` / ``baseline_lux`` / ``last_lux_update``) and the
EMA + stale-reset semantics intentionally mirror ``CameraService`` so the
engine can read either source by the active mode's room with identical
duck-typed logic (Part D).

Part C is store-only: nothing consumes the channel yet, so wiring it up is a
no-op on lighting behavior.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("home_hub.lux_channel")

# Match CameraService (camera_service.py) so both rooms smooth identically.
LUX_EMA_ALPHA = 0.3              # α*raw + (1-α)*ema — ~20s to 95%
LUX_EMA_STALE_RESET_SECONDS = 300  # snap (not blend) after a gap this long

# Forward skew beyond which the STORED ``_last_update`` is invalid by
# construction — mirrors ``presence_fusion.FUTURE_SKEW_TOLERANCE_S``.
# Defense-in-depth behind the route-layer ``clamp_client_timestamp``.
FUTURE_SKEW_TOLERANCE_S = 2.0


class LuxChannel:
    """One room's smoothed ambient lux + calibration baseline.

    ``baseline_lux`` is the calibrated "comfortable bright" anchor (center of
    the brightness-multiplier curve). ``ema_lux`` returns ``None`` until a
    baseline is set, mirroring ``CameraService.ema_lux`` (uncalibrated → no
    usable reading for the engine). ``last_lux_update`` backs staleness checks.
    """

    def __init__(self, room: str, baseline_lux: Optional[float] = None) -> None:
        self.room = room
        self._baseline_lux: Optional[float] = baseline_lux
        self._ema_lux: Optional[float] = None
        self._last_update: Optional[datetime] = None

    def update(
        self, raw_lux: float, *, captured_at: Optional[datetime] = None
    ) -> None:
        """Blend a fresh raw lux sample into the EMA.

        ``captured_at`` (UTC) defaults to now. Out-of-order arrivals (a
        sample older than the last one we kept — clock skew / network
        reorder) are dropped. After a gap ≥ ``LUX_EMA_STALE_RESET_SECONDS``
        (agent restart, all-day absence) the EMA SNAPS to the raw reading
        instead of blending, so the first post-gap sample doesn't average
        yesterday's room light with today's.
        """
        now = captured_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        if self._last_update is not None and now < self._last_update:
            stored_skew_s = (
                self._last_update - datetime.now(timezone.utc)
            ).total_seconds()
            if stored_skew_s <= FUTURE_SKEW_TOLERANCE_S:
                return  # stale / out-of-order — keep the fresher value
            # Stored stamp is future-dated (corrected client clock — see
            # presence_fusion.on_observation) — invalid by construction;
            # accept the new sample instead of wedging the channel.
            logger.warning(
                "%s lux channel: replacing future-stamped last_update "
                "(+%.0fs ahead of server)", self.room, stored_skew_s,
            )
        stale = (
            self._last_update is None
            or (now - self._last_update).total_seconds()
            >= LUX_EMA_STALE_RESET_SECONDS
        )
        if self._ema_lux is None or stale:
            self._ema_lux = float(raw_lux)
        else:
            self._ema_lux = (
                LUX_EMA_ALPHA * float(raw_lux)
                + (1 - LUX_EMA_ALPHA) * self._ema_lux
            )
        self._last_update = now

    def set_baseline(self, baseline_lux: Optional[float]) -> None:
        """Set the calibrated baseline (from a calibration POST)."""
        self._baseline_lux = (
            float(baseline_lux) if baseline_lux is not None else None
        )

    @property
    def ema_lux(self) -> Optional[float]:
        """Smoothed lux, or ``None`` until calibrated (no usable baseline)."""
        if self._baseline_lux is None:
            return None
        return self._ema_lux

    @property
    def baseline_lux(self) -> Optional[float]:
        return self._baseline_lux

    @property
    def last_lux_update(self) -> Optional[datetime]:
        return self._last_update

    @property
    def calibrated(self) -> bool:
        return self._baseline_lux is not None

    def is_fresh(self, max_age_s: float) -> bool:
        """True iff a sample landed within ``max_age_s`` seconds."""
        if self._last_update is None:
            return False
        age = (datetime.now(timezone.utc) - self._last_update).total_seconds()
        return age <= max_age_s

    def status(self) -> dict:
        """Observability snapshot. Exposes the RAW smoothed value even when
        uncalibrated (for shadow-logging before the engine consumes it)."""
        return {
            "room": self.room,
            "ema_lux": round(self._ema_lux, 1) if self._ema_lux is not None else None,
            "baseline_lux": self._baseline_lux,
            "calibrated": self.calibrated,
            "last_update": (
                self._last_update.isoformat() if self._last_update else None
            ),
        }
