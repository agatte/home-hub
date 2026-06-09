"""
Tests for Phase 2 Rust event reactions — vignette detection + RustEventService
state machine (flinch cooldown, sustained under-fire, release, config knob).
"""
import numpy as np
import pytest

from backend.services.pc_agent.screen_sync_agent import compute_vignette_score
from backend.services.rust_event_service import RustEventService


class _FakeHue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def set_light(self, light_id: str, state: dict) -> None:
        self.calls.append((light_id, state))


class _FakeSync:
    """Minimal screen_sync stub — only last_applied_bri is used by the flinch."""

    def last_applied_bri(self, light_id: str) -> float:
        return 120.0


def _svc() -> RustEventService:
    return RustEventService(hue_service=_FakeHue(), screen_sync=_FakeSync())


# --- vignette detection -----------------------------------------------------

def test_vignette_discriminates_damage_from_fire():
    H, W = 400, 600
    gray = np.full((H, W, 3), 100, np.uint8)

    vig = np.full((H, W, 3), 100, np.uint8)
    b = int(H * 0.15)
    vig[:b, :] = vig[-b:, :] = [220, 20, 20]
    vig[:, :int(W * 0.10)] = vig[:, -int(W * 0.10):] = [220, 20, 20]

    fire = np.full((H, W, 3), 0, np.uint8)
    fire[:, :] = [200, 40, 10]

    assert compute_vignette_score(gray) < 5
    assert compute_vignette_score(vig) > 60          # clear damage signal
    assert compute_vignette_score(fire) < 10         # whole-screen red ≠ damage


# --- state machine ----------------------------------------------------------

@pytest.mark.asyncio
async def test_below_threshold_is_noop():
    svc = _svc()
    svc.apply_config({"damage_threshold": 40})
    out = await svc.report_damage(score=20)
    assert out["reaction"] == "below_threshold"
    assert svc.under_fire is False


@pytest.mark.asyncio
async def test_first_hit_flinches_and_sets_under_fire():
    svc = _svc()
    svc.apply_config({"damage_threshold": 40, "flinch_hold_s": 0.0})
    out = await svc.report_damage(score=120)
    assert out["reaction"] == "flinch"
    assert svc.under_fire is True
    import asyncio
    await asyncio.sleep(0)  # let the flinch task run
    # Flinch wrote both reacting lamps (dip + restore = ≥2 writes each).
    hue = svc._hue
    assert any(lid == "2" for lid, _ in hue.calls)
    assert any(lid == "5" for lid, _ in hue.calls)


@pytest.mark.asyncio
async def test_rapid_hits_fire_one_flinch_not_a_strobe():
    svc = _svc()
    svc.apply_config({"damage_threshold": 40, "flinch_cooldown_s": 5.0, "flinch_hold_s": 0.0})
    r1 = await svc.report_damage(score=120)
    r2 = await svc.report_damage(score=120)
    r3 = await svc.report_damage(score=120)
    assert r1["reaction"] == "flinch"           # first hit flinches
    assert r2["reaction"] == "under_fire"        # follow-ups hold, don't re-flash
    assert r3["reaction"] == "under_fire"
    assert svc.under_fire is True


@pytest.mark.asyncio
async def test_release_clears_under_fire_after_quiet():
    svc = _svc()
    svc.apply_config({"damage_threshold": 40, "release_s": 0.0, "flinch_hold_s": 0.0})
    await svc.report_damage(score=120)
    assert svc.under_fire is True
    import asyncio
    await asyncio.sleep(0)
    svc._flinching = False  # ensure not mid-flinch
    svc._release_tick()      # release_s=0 → quiet immediately
    assert svc.under_fire is False


# --- config knob ------------------------------------------------------------

def test_apply_config_partial_merge_and_clamp():
    svc = _svc()
    base = svc.get_config()
    out = svc.apply_config({"tint_hue": 4000, "flinch_dip_factor": 5.0})
    assert out["tint_hue"] == 4000                       # merged
    assert out["flinch_dip_factor"] == 1.0               # clamped to [0,1]
    assert out["flinch_cooldown_s"] == base["flinch_cooldown_s"]  # untouched
    # tint_for reflects the live config.
    assert svc.tint_for("2")[0] == 4000
