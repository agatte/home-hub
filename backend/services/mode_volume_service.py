"""
ModeVolumeService — drives Sonos volume via per-mode curves on mode changes.

Registered as a mode-change callback in ``bootstrap.py`` alongside MusicMapper
and AmbientSoundService. On each transition:

  1. Read the current Sonos volume + transport state.
  2. Resolve the persisted ``mode_volume_curves`` config (or defaults).
  3. Call ``compute_mode_volume`` (pure policy).
  4. If not skipped, kick ``sonos.ramp_volume`` as a background task so the
     callback chain stays fast.

Deferral: if TTS is mid-speak we wait once (5s) and retry — TTS's
duck-and-resume snapshots the volume on entry and restores in its finally
block, so a concurrent ramp would be clobbered.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from backend.api.routes.routines import load_setting

from backend.services.mode_volume_policy import (
    MODE_VOLUME_DEFAULTS,
    VolumeDecision,
    compute_mode_volume,
)

logger = logging.getLogger("home_hub.mode_volume_service")

MODE_VOLUME_CURVES_KEY = "mode_volume_curves"

# Transport states that mean "Sonos is not actively playing audio." We skip
# the ramp in these states (no point fading silence) but always honor the
# sleeping→0 case (defensive — if Sonos somehow resumes mid-sleep, we want 0).
_SILENT_TRANSPORT_STATES = frozenset({"STOPPED", "NO_MEDIA_PRESENT", ""})

# When TTS is mid-speak we defer once and retry. One-shot only — never a loop.
_TTS_DEFER_SECONDS = 5.0


class ModeVolumeService:
    """Applies per-mode Sonos volume curves on mode-change."""

    def __init__(
        self,
        sonos_service: Any,
        automation_engine: Any,
        tts_service: Optional[Any] = None,
        ambient_sound_service: Optional[Any] = None,
    ) -> None:
        self._sonos = sonos_service
        self._automation = automation_engine
        self._tts = tts_service
        # When ambient is mirroring rain/fireplace/etc on the Sonos, ambient
        # owns the per-mode volume policy (its `_sonos_mode_volume_overrides`
        # are tuned for ambient noise levels, which are intentionally
        # different from music levels — e.g. working music=12 but working
        # ambient=22). Skip our music-tier fade in that case so the two
        # services don't tug-of-war over the speaker.
        self._ambient_sound = ambient_sound_service

    async def on_mode_change(self, mode: str) -> None:
        """Mode-change callback. Single-arg contract per AutomationEngine."""
        try:
            await self._apply(mode)
        except Exception as exc:  # noqa: BLE001 — callback never raises
            logger.error("ModeVolumeService failed for mode=%s: %s", mode, exc, exc_info=True)

    async def _apply(self, mode: str) -> None:
        if not getattr(self._sonos, "connected", False):
            logger.debug("mode_volume: skipped (sonos disconnected) mode=%s", mode)
            return

        # Ambient mirroring owns Sonos volume — its _sync_sonos_volume already
        # re-applied the per-mode ambient override during the same callback
        # fan-out. Ramping the music curve over it would clobber the ambient
        # baseline within seconds.
        if (
            self._ambient_sound is not None
            and getattr(self._ambient_sound, "_sonos_ambient_active", False)
        ):
            logger.info(
                "mode_volume: skipped mode=%s reason=ambient_active "
                "(ambient owns Sonos volume policy)",
                mode,
            )
            return

        # Defer once if TTS is actively speaking — duck-and-resume snapshots
        # the volume on entry and restores on exit, so a ramp now would be
        # clobbered. One retry, then proceed regardless.
        if self._tts is not None and getattr(self._tts, "is_speaking", False):
            logger.debug("mode_volume: deferring %.1fs for TTS mode=%s", _TTS_DEFER_SECONDS, mode)
            await asyncio.sleep(_TTS_DEFER_SECONDS)

        config = await load_setting(MODE_VOLUME_CURVES_KEY) or {}
        time_period = self._automation._get_time_period()
        dnd = self._automation.is_dnd_active()

        status = await self._sonos.get_status()
        current_volume = int(status.get("volume", 0))
        transport_state = str(status.get("state", "")).upper()

        decision: VolumeDecision = compute_mode_volume(
            mode,
            time_period=time_period,
            dnd=dnd,
            current_volume=current_volume,
            config=config,
        )

        if decision.skip:
            logger.info(
                "mode_volume: skipped mode=%s reason=%s (current=%d)",
                mode, decision.reason, current_volume,
            )
            return

        # Skip when Sonos is stopped — except sleeping, which always wants 0
        # in case Sonos resumes unexpectedly.
        if transport_state in _SILENT_TRANSPORT_STATES and mode != "sleeping":
            logger.info(
                "mode_volume: skipped mode=%s reason=transport_silent state=%s",
                mode, transport_state,
            )
            return

        logger.info(
            "mode_volume: ramping mode=%s %d→%d over %.1fs (%d steps) reason=%s",
            mode, current_volume, decision.target,
            decision.fade_steps * decision.fade_interval,
            decision.fade_steps, decision.reason,
        )
        # Background task — don't block the mode-change callback chain.
        asyncio.create_task(
            self._sonos.ramp_volume(
                decision.target,
                steps=decision.fade_steps,
                interval=decision.fade_interval,
            )
        )

    @staticmethod
    def merged_config(persisted: Optional[dict[str, dict[str, int]]]) -> dict[str, dict[str, int]]:
        """Return defaults merged with persisted overrides for read endpoints."""
        out: dict[str, dict[str, int]] = {k: dict(v) for k, v in MODE_VOLUME_DEFAULTS.items()}
        if persisted:
            for mode, overrides in persisted.items():
                if mode in out:
                    out[mode].update(overrides)
                else:
                    out[mode] = dict(overrides)
        return out
