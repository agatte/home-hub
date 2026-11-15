"""#293 default-deny native WebSocket projection contract; synthetic data only."""
import pytest

from backend.services.ws_native_projection import project_native_ws_event


def project(profile, lane, event, data):
    return project_native_ws_event(
        profile=profile, lane=lane, message_type=event, data=data,
    )


def test_desktop_brightness_receives_only_mode_and_time_period():
    result = project("windows_desktop", "display", "mode_update", {
        "mode": "Winding Down",
        "time_period": "late_night",
        "house_state": {"room": "Bedroom", "secret": "not-for-desktop"},
        "activity": {"person": "hidden"},
        "manual_override": True,
    })
    assert result == {
        "type": "mode_update",
        "data": {"mode": "Winding Down", "time_period": "late_night"},
    }


@pytest.mark.parametrize("profile,lane", [
    ("windows_desktop", "activity"),
    ("windows_desktop", "sleep"),
    ("desktop_notifier", "notifier"),
    ("kiosk", "display"),
    ("owner_browser", "browser"),
    ("guest_gateway", "guest"),
])
def test_mode_update_denied_for_all_other_native_lanes_and_profiles(profile, lane):
    assert project(profile, lane, "mode_update", {"mode": "Home"}) is None


def test_desktop_notifier_preserves_text_but_strips_executable_actions():
    original = {
        "title": "Lighting suggestion",
        "subtitle": "A useful adjustment",
        "kind": "suggestion",
        "factors": [{"label": "Evening", "value": "soft", "lane": "camera",
                     "impact": 0.8, "secret": "private"}],
        "actions": [{"label": "Accept", "url": "/api/learning/accept", "method": "POST",
                     "headers": {"Authorization": "Bearer private"}}],
        "output_delta": None,
        "user_id": "sensitive",
        "house_state": {"room": "Bedroom"},
    }
    result = project("desktop_notifier", "notifier", "notification", original)
    assert result == {"type": "notification", "data": {
        "title": "Lighting suggestion",
        "subtitle": "A useful adjustment",
        "kind": "suggestion",
        "factors": [{"label": "Evening", "value": "soft"}],
        "actions": [],
    }}
    assert "secret" not in repr(result)
    assert "Authorization" not in repr(result)


@pytest.mark.parametrize("profile,lane", [
    ("windows_desktop", "display"), ("windows_desktop", "sleep"),
    ("desktop_notifier", "display"), ("owner_browser", "browser"),
    ("kiosk", "display"), ("guest_gateway", "guest"),
])
def test_notification_denied_to_all_except_exact_notifier(profile, lane):
    assert project(profile, lane, "notification", {"title": "Hello"}) is None


@pytest.mark.parametrize("message", ["light_update", "presence_update",
    "connection_status", "sonos_update", "pipeline_state",
    "light_command_result", "secret_event", None, 1, ["notification"]])
def test_unknown_messages_default_deny(message):
    assert project("desktop_notifier", "notifier", message, {"title": "Hi"}) is None


@pytest.mark.parametrize("invalid", [None, {}, [], {"mode": 7},
    {"mode": ""}, {"mode": "x" * 81}, {"mode": "Home", "time_period": 1}])
def test_malformed_brightness_payload_denies(invalid):
    assert project("windows_desktop", "display", "mode_update", invalid) is None


@pytest.mark.parametrize("invalid", [
    None, {}, [], {"title": 12}, {"title": ""},
    {"title": "x" * 201},
    {"title": "Hi", "factors": [{"label": "Room", "value": None}]},
])
def test_invalid_or_unbounded_notification_denies(invalid):
    assert project("desktop_notifier", "notifier", "notification", invalid) is None


@pytest.mark.parametrize("url", [
    "https://external.example/collect?token=private",
    "http://127.0.0.1:8000/private",
    "http://169.254.169.254/latest/meta-data/",
    "/api/learning/accept",
    "//evil.example/action",
    "javascript:alert(1)",
])
@pytest.mark.parametrize("action_type,method", [
    ("http", "POST"), ("http", "GET"), ("view", "POST"),
])
def test_notification_actions_are_never_executable(url, action_type, method):
    import json

    result = project("desktop_notifier", "notifier", "notification", {
        "title": "A suggestion", "kind": "suggestion",
        "actions": [{"label": "Go", "url": url, "type": action_type,
                     "method": method, "headers": {"Authorization": "private"}}],
    })
    assert result == {"type": "notification", "data": {
        "title": "A suggestion", "kind": "suggestion", "factors": [], "actions": [],
    }}
    assert url not in json.dumps(result)
    assert "Authorization" not in json.dumps(result)


class EqualToEverything:
    def __eq__(self, other):
        return True


@pytest.mark.parametrize("parameter", ["profile", "lane", "message_type"])
def test_selectors_require_exact_strings(parameter):
    import json

    args = {
        "profile": "windows_desktop",
        "lane": "display",
        "message_type": "mode_update",
        "data": {"mode": "Home"},
    }
    args[parameter] = EqualToEverything()
    assert project_native_ws_event(**args) is None
    assert json.dumps(project("windows_desktop", "display", "mode_update",
                              {"mode": "Home"}))


def test_action_shape_is_not_forwarded_or_inspected():
    # Data originates inside the process, so it may not be JSON-compatible.
    # The projection must not inspect or serialize arbitrary action objects.
    import json

    event = project("desktop_notifier", "notifier", "notification", {
        "title": "Review this in HomeHub", "actions": [EqualToEverything()],
    })
    assert event["data"]["actions"] == []
    assert "actions" in json.dumps(event)


def test_no_shared_mutable_payload_alias():
    raw = {"title": "Check", "factors": [{"label": "Cause", "value": "First"}]}
    event = project("desktop_notifier", "notifier", "notification", raw)
    raw["factors"][0]["value"] = "Changed"
    assert event["data"]["factors"][0]["value"] == "First"
