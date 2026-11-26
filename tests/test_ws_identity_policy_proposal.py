"""Offline WebSocket command policy proposal for #287/#293; NOT ENFORCED.

These synthetic tests do not open sockets, mint production principals, wire
runtime auth, or move any deployed client from legacy WebSocket behavior.
"""
from types import MappingProxyType

import pytest

from backend.identity_core import IdentityStore
from backend.identity_policy import (
    PROFILES,
    WS,
    WS_COMMAND_OPERATIONS,
    WS_LIGHT_COMMAND,
    WS_SONOS_COMMAND,
    ws_command_operation,
)


@pytest.mark.parametrize("kind,operation", [
    ("light_command", WS_LIGHT_COMMAND),
    ("sonos_command", WS_SONOS_COMMAND),
])
def test_command_types_resolve_to_exact_non_wildcard_server_operations(kind, operation):
    assert ws_command_operation(kind) == operation
    assert operation.startswith("WS /ws:")
    assert operation != WS
    assert isinstance(WS_COMMAND_OPERATIONS, MappingProxyType)
    with pytest.raises(TypeError):
        WS_COMMAND_OPERATIONS[kind] = "WS /ws:owner"


@pytest.mark.parametrize("untrusted_type", [
    None, False, 0, {}, [], {"type": "light_command", "source": "owner"},
    "Light_Command", "light_command:all", "light_command/",
    "light_command ", "../light_command", "mode_update", "unknown",
])
def test_unknown_or_malformed_command_types_never_select_authority(untrusted_type):
    assert ws_command_operation(untrusted_type) is None


def test_published_profile_matrix_is_default_deny_for_non_owners():
    expected = {
        ("owner_browser", "browser"),
        ("kiosk", "display"),
    }
    for profile_name, profile in PROFILES.items():
        granted = {
            lane
            for operation, lane in profile.grants
            if operation in (WS_LIGHT_COMMAND, WS_SONOS_COMMAND)
        }
        if profile_name == "owner_browser":
            assert granted == {"browser"}
        elif profile_name == "kiosk":
            assert granted == {"display"}
        else:
            assert granted == set(), profile_name
    assert set(PROFILES) >= {key for key, _ in expected}


@pytest.fixture
def registry(tmp_path):
    capability = object()
    now = [1000.0]
    store = IdentityStore(
        tmp_path / "synthetic-ws-policy.sqlite",
        local_capability=capability, clock=lambda: now[0],
    )
    yield store, capability, now
    store.close()


@pytest.mark.parametrize("profile,lane", [
    ("owner_browser", "browser"), ("kiosk", "display"),
])
def test_exact_owner_or_kiosk_credential_grants_only_its_bound_lane(registry, profile, lane):
    store, cap, _ = registry
    enrollment = store.enroll(profile, capability=cap)
    for kind in WS_COMMAND_OPERATIONS:
        operation = ws_command_operation(kind)
        identity = store.authorize(enrollment.token, operation, lane=lane)
        assert identity is not None
        assert identity.profile == profile
        assert identity.source == PROFILES[profile].source
        assert identity.lane == lane
        for wrong_lane in ("browser", "display", "activity", "screen", "notifier", "tools"):
            if wrong_lane != lane:
                assert store.authorize(enrollment.token, operation, lane=wrong_lane) is None
    assert store.authorize(enrollment.token, WS, lane=lane) is not None
    assert store.authorize(enrollment.token, "WS /ws:unknown", lane=lane) is None
    assert enrollment.token not in repr(enrollment)


@pytest.mark.parametrize("profile", [
    "windows_desktop", "desktop_notifier", "mcp", "latitude",
    "guest_gateway", "alexa", "shortcuts", "local_operator",
])
def test_non_owner_profiles_cannot_send_manual_light_or_sonos_commands(registry, profile):
    store, cap, _ = registry
    enrollment = store.enroll(profile, capability=cap)
    for operation in (WS_LIGHT_COMMAND, WS_SONOS_COMMAND):
        for lane in ("browser", "display", "activity", "screen", "notifier", "tools"):
            assert store.authorize(enrollment.token, operation, lane=lane) is None
        # A header/source claim must never turn a native token into an owner.
        assert store.authorize(
            enrollment.token, operation, lane="browser", claimed_source="owner",
        ) is None


def test_revocation_and_wrong_source_deny_even_previously_authorized_ws_command(registry):
    store, cap, _ = registry
    enrollment = store.enroll("owner_browser", capability=cap)
    assert store.authorize(enrollment.token, WS_LIGHT_COMMAND, lane="browser")
    assert store.authorize(
        enrollment.token, WS_LIGHT_COMMAND, lane="browser",
        claimed_source="desktop",
    ) is None
    store.revoke(enrollment.principal_id, capability=cap)
    assert store.authorize(enrollment.token, WS_LIGHT_COMMAND, lane="browser") is None


def test_expired_owner_command_token_fails_closed(registry):
    store, cap, now = registry
    enrollment = store.enroll("owner_browser", capability=cap, lifetime=1)
    assert store.authorize(enrollment.token, WS_LIGHT_COMMAND, lane="browser")
    now[0] += 1
    assert store.authorize(enrollment.token, WS_LIGHT_COMMAND, lane="browser") is None
