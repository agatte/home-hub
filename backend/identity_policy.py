"""Inactive, bounded policy inventory. No route imports or enforcement.

Operation identifiers describe exact actions, never URL prefixes. Lane selection
must be performed by a future server adapter, not a payload/header source field.
"""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Profile:
    source: str
    grants: frozenset[tuple[str, str]]


STATUS = "GET /api/automation/status"
WS = "WS /ws:mode_update"
WS_LIGHT_COMMAND = "WS /ws:light_command"
WS_SONOS_COMMAND = "WS /ws:sonos_command"

# Offline-only proposal for the two current inbound WebSocket command kinds.
# The future #293 server adapter, NOT a caller-supplied source or lane, must
# select this exact operation and pass a principal-bound lane to IdentityStore.
# Nothing in the current /ws endpoint imports this mapping or enforces it.
WS_COMMAND_OPERATIONS = MappingProxyType({
    "light_command": WS_LIGHT_COMMAND,
    "sonos_command": WS_SONOS_COMMAND,
})


def ws_command_operation(message_type: object) -> str | None:
    """Map an exact server-validated inbound type; unknown types deny."""
    return WS_COMMAND_OPERATIONS.get(message_type) if type(message_type) is str else None

OVERRIDE = "POST /api/automation/override"
GEOFENCE = "POST /api/presence/geofence"
HEALTH = "POST /api/automation/agent-health"
ACTIVITY = "POST /api/automation/activity"
SCREEN = "POST /api/automation/screen-color"
AUDIO = "POST /api/learning/audio-decision"
FACE = "POST /api/personality/blendshape"
LUX = "POST /api/camera/desktop/lux"
CAMERA = "GET /api/camera/status"
TRAVEL = "POST /api/host/travel"


def _profile(source, *grants):
    return Profile(source, frozenset(grants))


# Deliberately partial inventory: omitted actions (including guest actions) deny.
# Six desktop lanes share ONE principal/credential, not six credentials.
PROFILES = MappingProxyType({
    "owner_browser": _profile("owner", (STATUS, "browser"), (OVERRIDE, "browser"),
        (WS, "browser"), (WS_LIGHT_COMMAND, "browser"), (WS_SONOS_COMMAND, "browser")),
    "kiosk": _profile("kiosk", (STATUS, "display"), (WS, "display"),
        (WS_LIGHT_COMMAND, "display"), (WS_SONOS_COMMAND, "display")),
    "windows_desktop": _profile("desktop", (ACTIVITY, "activity"), (AUDIO, "audio"),
        (SCREEN, "screen"), (FACE, "camera"), (LUX, "camera"),
        (CAMERA, "display"), (WS, "display"), (WS, "sleep"),
        *((HEALTH, lane) for lane in ("activity", "audio", "screen", "camera", "display", "sleep"))),
    "desktop_notifier": _profile("desktop_notifier", (STATUS, "notifier"), (WS, "notifier")),
    "mcp": _profile("mcp", (STATUS, "tools")),
    "latitude": _profile("latitude", (ACTIVITY, "streaming"), (HEALTH, "streaming")),
    "guest_gateway": _profile("guest_gateway"),
    "alexa": _profile("alexa", (OVERRIDE, "skill")),
    "shortcuts": _profile("ios_shortcut", (GEOFENCE, "geofence")),
    "local_operator": _profile("local_operator", (TRAVEL, "lifecycle")),
})
