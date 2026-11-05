"""Offline #370 candidate; no app imports, sensors, or transport."""
import pytest

from backend.services.desk_visual_comfort import desk_diffuse_fill_candidate
from backend.services.light_state_calculator import apply_zone_overlay
from backend.services.screen_sync import ScreenSyncService


def candidate(**changes):
    context = dict(activity="watching", period="late_night", house="home",
                   source="desktop", zone="desk", face_present=True,
                   sample_age=0, conflicting_physical=False, owners=frozenset(),
                   enabled=True, dnd=False)
    context.update(changes)
    return desk_diffuse_fill_candidate({"on": True, "bri": 25, "ct": 400}, **context)


@pytest.mark.parametrize("activity", ["general", "idle", "working", "watching", "gaming", "relax", "social", "cooking"])
@pytest.mark.parametrize("period,floor", [("evening", 110), ("night", 90), ("late_night", 70)])
def test_low_l2_candidate(activity, period, floor):
    assert candidate(activity=activity, period=period)["bri"] == floor


@pytest.mark.parametrize("changes", [
    dict(house="away"), dict(house="sleeping"), dict(house="winding_down"),
    dict(activity="sleeping"), dict(activity="gameday"), dict(activity="pregameday"),
    dict(activity="unknown"), dict(source="latitude"), dict(source=None),
    dict(zone="couch"), dict(zone="bed"), dict(zone=None), dict(face_present=False),
    dict(sample_age=None), dict(sample_age=-1), dict(sample_age=31),
    dict(sample_age=float("nan")), dict(sample_age=float("inf")),
    dict(conflicting_physical=True), dict(enabled=False), dict(dnd=True), dict(period="day"),
])
def test_fail_closed(changes):
    assert candidate(**changes) == {"on": True, "bri": 25, "ct": 400}


@pytest.mark.parametrize("owner", ["manual_light", "scene", "transit", "protected", "external_off", "screen_sync", "effect", "host_return", "unknown"])
def test_any_stronger_or_unknown_owner_abstains(owner):
    assert candidate(owners=frozenset({owner}))["bri"] == 25


def test_manual_activity_is_only_semantic_preference():
    assert candidate(owners=frozenset({"manual_activity"}))["bri"] == 70
    assert candidate(owners=frozenset({"manual_activity", "manual_light"}))["bri"] == 25


@pytest.mark.parametrize("light", [
    {"on": False, "bri": 1, "ct": 400}, {"bri": 1, "ct": 400},
    {"on": True, "ct": 400}, {"on": True, "bri": 120, "ct": 400},
    {"on": True, "bri": 20, "hue": 1000, "sat": 120},
    {"on": True, "bri": 20, "ct": 250},
])
def test_no_power_color_or_brighter_target_changes(light):
    original = light.copy()
    assert desk_diffuse_fill_candidate(light, activity="watching", period="late_night",
        house="home", source="desktop", zone="desk", face_present=True,
        sample_age=0, conflicting_physical=False, owners=frozenset(), enabled=True,
        dnd=False) == original
    assert light == original


def test_candidate_does_not_mutate_input():
    first = candidate()
    first["bri"] = 1
    assert candidate()["bri"] == 70


def test_static_watching_preserves_explicit_off_and_other_fixtures():
    state = {"2": {"on": False, "bri": 1, "ct": 400},
             "5": {"on": True, "bri": 14, "ct": 400},
             "3": {"on": True, "bri": 10, "ct": 400},
             "4": {"on": True, "bri": 10, "ct": 400}}
    assert apply_zone_overlay(state, "watching", "late_night", "desk", None) == state


def test_static_floor_is_wired_but_default_sync_floor_is_unchanged():
    state = {"2": {"on": True, "bri": 1, "ct": 400},
             "5": {"on": True, "bri": 14, "ct": 400}}
    static = apply_zone_overlay(state, "watching", "late_night", "desk", None)
    sync = ScreenSyncService(hue_service=None, target_light_ids=["2", "5"])
    assert static["2"]["bri"] == 70
    assert sync.get_floor("watching", "2", zone="desk", period="late_night") == 25
    assert candidate()["bri"] == 70
    assert static["5"] == state["5"]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,expected", [
    ({}, 90), ({"desk_diffuse_fill": 1}, 30), ({"desk_diffuse_fill": "true"}, 30),
    ({"desk_diffuse_fill": {}}, 30), ({"source": "laptop"}, 30),
    ({"zone": "couch"}, None), ({"zone": "bed"}, None),
    ({"light_id": "5"}, None), ({"period": "day"}, None),
    ({"period": None}, None),
])
async def test_service_fill_flag_is_narrow(changes, expected):
    class Hue:
        calls = []
        async def set_light(self, lid, state):
            self.calls.append((lid, state))
            return True
    hue = Hue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2", "5"])
    args = dict(light_id="2", r=0, g=0, b=0, mode="watching", source="desktop",
                zone="desk", period="night", desk_diffuse_fill=True)
    args.update(changes)
    assert await sync.apply_color(**args)
    if expected is None:
        expected = sync.get_floor("watching", args["light_id"], zone=args["zone"], period=args["period"])
    assert hue.calls[-1][1]["bri"] == int(expected * sync._smoothing_alpha_for("watching", args["period"]))
    assert "ct" not in hue.calls[-1][1]


@pytest.mark.asyncio
async def test_qualified_floor_clamps_to_existing_cap():
    class Hue:
        state = None
        async def set_light(self, lid, state):
            self.state = state
            return True
    hue = Hue()
    sync = ScreenSyncService(hue_service=hue, target_light_ids=["2"])
    sync.get_cap = lambda *a, **kw: 60
    assert await sync.apply_color("2", 0, 0, 0, "watching", zone="desk",
                                  period="night", desk_diffuse_fill=True)
    assert hue.state["bri"] == int(60 * sync._smoothing_alpha_for("watching", "night"))
