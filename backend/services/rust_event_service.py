"""
Rust event-reaction service — damage "flinch" + sustained "under-fire" glow.

Phase 2 of the Rust lighting profile (Phase 1 = ember palette + luma dimming).
The desktop screen agent watches the screen edges for Rust's red damage
vignette and POSTs ``/api/automation/rust-event {type: "damage", score}``.
This service turns that stream of pings into light reactions on the bedroom
desk lamps (L2 + L5 — the ones in the player's field of view; L1 + kitchen
stay steady ember/moss ambiance):

  • **Flinch** — on a fresh hit (not in cooldown) the lamps do a quick red
    brightness DIP and settle back (~0.6s). Cooldown-gated so a burst of hits
    fires ONE flinch, never a strobe.
  • **Under-fire glow** — while damage keeps arriving, ``under_fire`` stays
    True; the screen-color route reads it and tints the lamps' ember toward a
    steady danger-red instead of re-flashing. A release loop clears it ~2s
    after the last hit, handing the lamps back to the normal luma sync.

All feel knobs (cooldown, release, threshold, flinch/tint colors) are
runtime-tunable via ``apply_config`` (PUT /api/automation/rust-event-config),
persisted in app_settings — the same no-redeploy tuning loop as the brightness
envelope. Detection is finicky (fire / blood / sunset are red too), so the
gate threshold living on this side keeps it tunable without touching the agent.

Coordinates with ScreenSyncService: the flinch borrows each lamp's last
applied brightness as its baseline, and the under-fire tint is applied through
the same ``apply_rust_brightness`` path (a ``damage`` flag), so the two never
fight over the bridge.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from backend.services.automation_engine import AutomationEngine
    from backend.services.hue_service import HueService
    from backend.services.screen_sync import ScreenSyncService
    from backend.services.websocket_manager import WebSocketManager

logger = logging.getLogger("home_hub.rust_event")

# Lamps that react to Rust events — the bedroom desk pair in the player's
# sightline. L1 (living room) + kitchen stay on the steady ember/moss ambiance.
REACT_LIGHT_IDS: tuple[str, ...] = ("2", "5")

# Defaults (all runtime-tunable via apply_config). Tuned conservatively;
# expect to dial these in live against a real firefight.
_DEFAULTS = {
    "enabled": True,
    # Vignette score (sent by the agent) must clear this to count as a hit.
    # The agent only posts above a low floor; this is the real, tunable gate.
    "damage_threshold": 40,
    # No new flinch may fire within this window of the last one (anti-strobe).
    "flinch_cooldown_s": 2.5,
    # under_fire releases this long after the last damage ping.
    "release_s": 2.0,
    # Flinch dip: red hue, high sat, brightness scaled by dip_factor, held
    # briefly, then eased back to the pre-flinch baseline (or the tint if still
    # under fire).
    "flinch_hue": 2000,
    "flinch_sat": 240,
    "flinch_dip_factor": 0.45,
    "flinch_hold_s": 0.4,
    # Sustained under-fire glow: ember shifted toward danger-red, slightly dim.
    "tint_hue": 3500,
    "tint_sat": 215,
    "tint_bri_factor": 0.85,
}


class RustEventService:
    """Drive L2/L5 damage flinch + under-fire glow from agent damage pings."""

    def __init__(
        self,
        hue_service: "HueService",
        screen_sync: "ScreenSyncService",
        automation_engine: "Optional[AutomationEngine]" = None,
        ws_manager: "Optional[WebSocketManager]" = None,
    ) -> None:
        self._hue = hue_service
        self._screen_sync = screen_sync
        # Optional — used only to skip lamps the user is manually holding
        # (manual_light_overrides) in the flinch, mirroring receive_screen_color.
        self._engine = automation_engine
        self._ws = ws_manager
        self._cfg: dict = dict(_DEFAULTS)

        # State (monotonic seconds).
        self._last_damage_at: float = 0.0
        self._flinch_cooldown_until: float = 0.0
        self._under_fire: bool = False
        self._flinching: bool = False
        # Strong ref to the in-flight flinch task so the loop can't GC it
        # mid-restore (RUF006 — every other task in this app is held too).
        self._flinch_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    # Public query API — read by the screen-color route
    # ------------------------------------------------------------------

    @property
    def under_fire(self) -> bool:
        """True while the player is taking sustained damage — the route tints
        the lamps' ember toward danger-red instead of normal ember."""
        return self._under_fire

    def tint_for(self, light_id: str) -> tuple[int, int, float]:
        """Danger-glow ``(hue, sat, bri_factor)`` the route applies while
        under fire. Same for both lamps; the route still runs the luma
        envelope so the glow tracks scene brightness, just red-shifted."""
        return (
            int(self._cfg["tint_hue"]),
            int(self._cfg["tint_sat"]),
            float(self._cfg["tint_bri_factor"]),
        )

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    async def report_damage(
        self, score: float, period: Optional[str] = None,
    ) -> dict:
        """Handle one damage ping from the desktop agent.

        Returns a small status dict (for the route response). No-op when
        disabled or below the tunable threshold. Fires a flinch on a fresh hit
        (cooldown permitting) and marks/refreshes ``under_fire`` so the glow
        holds while damage continues; the release loop clears it on quiet."""
        if not self._cfg["enabled"]:
            return {"reaction": "disabled"}
        if score < self._cfg["damage_threshold"]:
            return {"reaction": "below_threshold", "score": score}

        now = time.monotonic()
        self._last_damage_at = now
        self._under_fire = True

        fired = False
        if now >= self._flinch_cooldown_until and not self._flinching:
            self._flinch_cooldown_until = now + float(self._cfg["flinch_cooldown_s"])
            self._flinch_task = asyncio.create_task(self._do_flinch())
            fired = True

        return {"reaction": "flinch" if fired else "under_fire", "score": score}

    # ------------------------------------------------------------------
    # Flinch + release
    # ------------------------------------------------------------------

    async def _do_flinch(self) -> None:
        """Quick red brightness dip on L2/L5, then ease back to baseline.

        Baseline is each lamp's last applied brightness (borrowed from
        ScreenSyncService) so the dip is relative to where the lamp already
        is. Restores to the under-fire tint if still under fire when the dip
        ends (avoids an ember flicker mid-firefight), else plain ember."""
        self._flinching = True
        try:
            dip_factor = float(self._cfg["flinch_dip_factor"])
            flinch_hue = int(self._cfg["flinch_hue"])
            flinch_sat = int(self._cfg["flinch_sat"])
            # Skip any lamp the user is manually holding — a flinch must not
            # stomp an explicit slider drag (feedback_manual_light_overrides_persist;
            # same gate receive_screen_color uses for the per-frame writes).
            held = (
                self._engine.manual_light_overrides
                if self._engine is not None else set()
            )
            targets = [lid for lid in REACT_LIGHT_IDS if lid not in held]
            baselines: dict[str, int] = {}
            for lid in targets:
                base = int(self._screen_sync.last_applied_bri(lid))
                baselines[lid] = base
                await self._hue.set_light(lid, {
                    "on": True,
                    "hue": flinch_hue,
                    "sat": flinch_sat,
                    "bri": max(1, int(base * dip_factor)),
                    "transitiontime": 2,  # 0.2s snap down — a flinch, not a fade
                })

            await asyncio.sleep(float(self._cfg["flinch_hold_s"]))

            # Restore: to the danger tint if still under fire, else ember.
            if self._under_fire:
                hue, sat, bri_factor = self.tint_for("2")
            else:
                from backend.services.screen_sync import (
                    RUST_EMBER_HUE, RUST_EMBER_SAT,
                )
                hue, sat, bri_factor = RUST_EMBER_HUE, RUST_EMBER_SAT, 1.0
            for lid in targets:
                await self._hue.set_light(lid, {
                    "on": True,
                    "hue": int(hue),
                    "sat": int(sat),
                    "bri": max(1, int(baselines[lid] * bri_factor)),
                    "transitiontime": 5,  # 0.5s ease back
                })
        except Exception:
            logger.warning("rust flinch failed (recovers on next frame)", exc_info=True)
        finally:
            self._flinching = False

    async def release_loop(self) -> None:
        """Clear ``under_fire`` once damage has been quiet for ``release_s``.

        Ticks at 0.5s — fine-grained enough that the glow releases promptly
        after a firefight without a dedicated per-event timer. The actual
        hand-back to ember happens on the next screen-color frame (the route
        stops tinting once under_fire is False)."""
        while not self._stop.is_set():
            try:
                self._release_tick()
            except Exception:
                logger.debug("rust release_loop tick error", exc_info=True)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    def _release_tick(self) -> None:
        """One release check (extracted for testability): clear under_fire once
        damage has been quiet for ``release_s`` (and no flinch is mid-flight)."""
        if self._under_fire and not self._flinching:
            quiet = time.monotonic() - self._last_damage_at
            if quiet >= float(self._cfg["release_s"]):
                self._under_fire = False
                logger.debug("rust under-fire released (quiet %.1fs)", quiet)

    async def close(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Runtime config (no-redeploy knob)
    # ------------------------------------------------------------------

    def get_config(self) -> dict:
        """Return the live config dict (JSON-safe)."""
        return dict(self._cfg)

    def apply_config(self, cfg: dict) -> dict:
        """Merge a partial config, validating/clamping each key. Returns the
        full resolved config. Unknown keys ignored."""
        if not isinstance(cfg, dict):
            return self.get_config()
        if "enabled" in cfg:
            self._cfg["enabled"] = bool(cfg["enabled"])
        # Non-negative seconds (bounded so a typo can't wedge the loop).
        for key, lo, hi in (
            ("flinch_cooldown_s", 0.0, 30.0),
            ("release_s", 0.0, 30.0),
            ("flinch_hold_s", 0.0, 3.0),
        ):
            if cfg.get(key) is not None:
                self._cfg[key] = max(lo, min(hi, float(cfg[key])))
        # 0-1 factors.
        for key in ("flinch_dip_factor", "tint_bri_factor"):
            if cfg.get(key) is not None:
                self._cfg[key] = max(0.0, min(1.0, float(cfg[key])))
        # Hues 0-65535, sats 0-254, threshold 0-255.
        for key in ("flinch_hue", "tint_hue"):
            if cfg.get(key) is not None:
                self._cfg[key] = max(0, min(65535, int(cfg[key])))
        for key in ("flinch_sat", "tint_sat"):
            if cfg.get(key) is not None:
                self._cfg[key] = max(0, min(254, int(cfg[key])))
        if cfg.get("damage_threshold") is not None:
            self._cfg["damage_threshold"] = max(0, min(255, int(cfg["damage_threshold"])))
        return self.get_config()
