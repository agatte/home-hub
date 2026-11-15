"""Authenticated #293 runtime boundary, with no default broker or issuer.

Only this boundary may own sockets; no legacy manager or direct send is allowed.
Embedding code supplies exact endpoints, a trusted async verifier and
(optionally) a reviewed ownership-aware command dispatcher. No device
services are imported here. Browser admission defaults OFF: enabling the seam
requires a separately reviewed HttpOnly/Secure/SameSite=Strict, Path=/ cookie
issuer, recipient authentication and CSRF/session lifecycle. This module cannot
prove cookie attributes from a request. HTTP loopback kiosk origins are validated
but cannot admit a Secure cookie on ws://; kiosk TLS/issuance remains a gate.

No enrollment, provisioning, rollback protection or live activation is supplied.
OS-local enrollment/recovery (#287), browser/iPhone/kiosk issuance, native secret
delivery, #296 fixture identity and physical acceptance remain separate gates.
Run ``serve`` to own idle-session revalidation and final cleanup; all frame paths
revalidate without caching grants. The embedding must explicitly supply a trusted
async verifier: production requires the separately protected broker's fresh
decision (worker-owned IdentityStore is synthetic-test support only). Never
block the event loop, cache grants or
abandon running work on cancellation. Synchronous stores are refused. Admission
and active work have independent bounded in-flight slots; timeouts retain their
slot until the verifier actually finishes and discard every late result.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
import inspect
import ipaddress
import json
import math
import re
import time
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError

from backend.identity_core import Identity
from backend.identity_policy import PROFILES, WS, ws_command_operation
from backend.schemas.ws import WSCommand
from backend.services.ws_native_projection import project_native_ws_event

_COMMAND = TypeAdapter(WSCommand)
_LANES = {"owner_browser": "browser", "kiosk": "display",
          "windows_desktop": "display", "desktop_notifier": "notifier"}
_COOKIE = "__Host-homehub_ws"
_LIGHT_IDS = frozenset("123456")  # light_state_calculator.LIGHT_IDS; pinned release inventory
_TOKEN = re.compile(r"[0-9a-f]{32}\.[A-Za-z0-9_-]{43}\Z")
_PRIVATE_EVENTS = frozenset({"light_command_result", "light_command_reconciliation", "error"})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


@dataclass(frozen=True)
class Endpoint:
    """Server configuration, never constructed from request/forwarded headers."""

    origin: str
    profile: str

    def __post_init__(self):
        parsed = urlsplit(self.origin)
        if (self.profile not in _LANES or parsed.scheme not in {"http", "https"}
                or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment
                or parsed.netloc != parsed.netloc.lower() or "*" in self.origin
                or any(c.isspace() for c in self.origin)):
            raise ValueError("Invalid exact endpoint")
        # Force port validation, disallow ambiguous/noncanonical authorities.
        port = parsed.port
        host = parsed.hostname
        try:
            address = ipaddress.ip_address(host)
            canonical = f"[{address}]" if address.version == 6 else str(address)
        except ValueError:
            if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host):
                raise ValueError("Invalid host") from None
            canonical = host
        if parsed.netloc != canonical + (f":{port}" if port is not None else ""):
            raise ValueError("Noncanonical authority")
        if parsed.scheme == "http":
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
            if self.profile != "kiosk" or not loopback:
                raise ValueError("HTTP allowed only for explicit numeric loopback kiosk")


@dataclass(repr=False)
class _Session:
    socket: object
    endpoint: Endpoint
    token: str = field(repr=False)
    identity: object
    ready: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    inbound: deque = field(default_factory=deque)
    auth_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    work: set = field(default_factory=set)
    pending_sends: int = 0


class TrustedAsyncAuthorizer:
    """Explicit trust seam; no implicit offloading of thread-affine SQLite.

    The callback owns its connections, final fresh authorization and cleanup.
    It must not suppress cancellation or return a cached authorization. Its
    implementation/OS isolation remains an integration gate, not proven here.
    The server supplies stage="admission" or "active"; the callback must reserve
    independent active worker capacity so anonymous work cannot monopolize it.
    Boundary timeout does NOT cancel it: physical in-flight work stays bounded.
    """

    def __init__(self, authorize):
        if not inspect.iscoroutinefunction(authorize):
            raise TypeError("A trusted nonblocking async authorization callback is required")
        self.authorize = authorize


def _strict_command(message):
    if type(message) is not dict or type(message.get("data")) is not dict:
        raise ValueError("Invalid command")
    data = message["data"]
    if message.get("type") == "light_command":
        identifier = data.get("light_id")
        if type(identifier) is not str or identifier not in _LIGHT_IDS:
            raise ValueError("Invalid registered light")
        if "on" in data and type(data["on"]) is not bool:
            raise ValueError("Invalid power")
        bounds = {"bri": (0, 254), "ct": (153, 500), "hue": (0, 65535),
                  "sat": (0, 254), "transitiontime": (0, 600)}
        for key, (low, high) in bounds.items():
            if key in data and (type(data[key]) is not int or not low <= data[key] <= high):
                raise ValueError("Invalid light scalar")
        if "ct" in data and ("hue" in data or "sat" in data):
            raise ValueError("Mixed color fields")
    elif message.get("type") == "sonos_command" and "volume" in data:
        if type(data["volume"]) is not int or not 0 <= data["volume"] <= 100:
            raise ValueError("Invalid volume")
    # command_id is correlation only, validated by the exact schema below.
    return _COMMAND.validate_python(message, strict=True)


def _text(limit=160):
    return lambda v: type(v) is str and len(v) <= limit


def _number(low, high, *, integer=False):
    return lambda v: type(v) in ((int,) if integer else (int, float)) and math.isfinite(v) and low <= v <= high


def _enum(*values):
    return lambda v: type(v) is str and v in values


def _nullable(check):
    return lambda v: v is None or check(v)


def _BOOL(v):
    return type(v) is bool


_TEXT = _text()
# Correlation IDs are ephemeral, private receipts, never operation grants.
def _CORRELATION(value):
    return value is None or (
        type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value) is not None
    )
_COUNT = _number(0, 1_000_000, integer=True)
_PERCENT = _number(0, 100)
_LIGHT = {"light_id": _enum(*_LIGHT_IDS), "name": _TEXT, "on": _BOOL,
          "bri": _number(0, 254, integer=True), "hue": _number(0, 65535, integer=True),
          "sat": _number(0, 254, integer=True), "ct": _nullable(_number(153, 500, integer=True)),
          "colormode": _nullable(_enum("hs", "ct", "xy")), "reachable": _BOOL}
_PLAY = {"timestamp": _text(80), "play_type": _text(80), "description": _text(2000),
         "player": _nullable(_TEXT), "kicker": _nullable(_TEXT),
         "yards": _nullable(_number(-100, 100, integer=True)),
         "scoring_team": _nullable(_enum("colts", "opp")), "wpa": _nullable(_number(-1, 1))}
_DRIVE = {"team": _nullable(_enum("colts", "opp")), "plays": _nullable(_COUNT),
          "yards": _nullable(_number(-1000, 1000, integer=True)), "elapsed": _nullable(_text(40))}
_GAME = {"status": _enum("pregame", "in-progress", "final", "no-game"),
         "opponent": _nullable(_TEXT), "kickoff_utc": _nullable(_text(80)),
         "score_colts": _COUNT, "score_opp": _COUNT, "quarter": _COUNT, "clock": _text(40),
         "possession": _nullable(_enum("colts", "opp")), "last_play": _PLAY, "current_drive": _DRIVE}
_BRIGHTNESS = {"light_id": _enum(*_LIGHT_IDS), "mode": _TEXT, "period": _TEXT,
               "weather_class": _nullable(_TEXT), "suggested_bri": _number(0, 254, integer=True),
               "suggested_multiplier": _number(0, 10), "sample_count": _COUNT, "distinct_days": _COUNT}
# Exact event/field inventory from main.py, stores/init.js, stores/gameday.js
# and their emitters. Each nested dictionary has its own allowlist. URLs, raw
# fusion/process inputs and unreviewed ambient configuration are omitted.
_OWNER_EVENTS = {
    "mode_update": {"mode": _TEXT, "time_period": _text(40), "source": _TEXT,
                    "manual_override": _BOOL, "house_state": _nullable(_TEXT),
                    "activity": _nullable(_TEXT), "override_source": _nullable(_TEXT),
                    "override_user_owned": _BOOL},
    "connection_status": {"hue": _BOOL, "sonos": _BOOL, "build_id": _text(80),
                          "request_id": _text(12), "light_command_results": _BOOL},
    "light_update": _LIGHT,
    # These two frames are emitted privately by the guarded lighting branch
    # (#530). Reconciliation observations are intentionally stripped: a
    # client must perform its own version-fenced fresh read.
    "light_command_result": {"command_id": _CORRELATION,
                             "light_id": _enum(*_LIGHT_IDS),
                             "status": _enum("acknowledged", "denied", "unavailable",
                                             "invalid", "uncertain")},
    "light_command_reconciliation": {"command_id": _CORRELATION,
                                     "light_id": _enum(*_LIGHT_IDS)},
    "sonos_update": {"state": _TEXT, "track": _text(600), "artist": _text(600),
                     "album": _text(600), "volume": _PERCENT, "mute": _BOOL,
                     "duration": _text(16), "position": _text(16)},
    "dnd_update": {"enabled": _BOOL, "expiry_utc": _nullable(_text(80)),
                   "minutes_remaining": _number(0, 525600)},
    "music_suggestion": {"mode": _TEXT, "title": _text(600), "vibe": _nullable(_TEXT), "message": _text(1000)},
    "music_auto_played": {"mode": _TEXT, "title": _text(600), "vibe": _nullable(_TEXT), "source": _TEXT},
    "mode_suggestion": {"suggestion_id": _COUNT, "rule_id": _COUNT, "predicted_mode": _TEXT,
                        "confidence": _PERCENT, "sample_count": _COUNT, "message": _text(1000)},
    "mode_suggestion_dismissed": {},
    "brightness_suggestion": {"id": _COUNT, "kind": _enum("brightness"), "payload": _BRIGHTNESS,
                              "status": _TEXT, "fired_at": _text(80), "confidence": _PERCENT, "sample_count": _COUNT},
    "brightness_suggestion_dismissed": {"id": _COUNT},
    "ambient_update": {"playing": _BOOL, "sound": _nullable(_TEXT), "sound_label": _nullable(_TEXT),
                       "volume": _number(0, 1), "source": _nullable(_TEXT), "weather_override": _BOOL,
                       "weather_reactive": _BOOL, "sonos_enabled": _BOOL,
                       "sonos_ambient_active": _BOOL, "sonos_ambient_pending": _BOOL,
                       "sonos_present_volume": _PERCENT, "sonos_away_volume": _PERCENT},
    "camera_update": {"detection": _TEXT, "detection_source": _TEXT, "confidence": _number(0, 1),
                      "ambient_lux": _nullable(_number(0, 1_000_000)), "ema_lux": _nullable(_number(0, 1_000_000)),
                      "baseline_lux": _nullable(_number(0, 1_000_000)), "calibrated": _BOOL,
                      "current_multiplier": _number(0, 10), "consecutive_absent": _COUNT,
                      "pose_landmark_count": _COUNT, "zone": _nullable(_TEXT), "posture": _nullable(_TEXT),
                      "candidate_posture": _nullable(_TEXT), "authority_reason": _TEXT},
    "gameday_state": _GAME, "gameday_viewer_state": _GAME, "gameday_play": _PLAY,
    "gameday_celebration": {"sequence_key": _TEXT, "started_at": _number(0, 1e12)},
    "gameday_viewer_sync": {"enabled": _BOOL, "active": _BOOL, "authoritative": _BOOL,
                            "presentation_active": _BOOL, "reason": _TEXT, "service": _TEXT,
                            "player": _TEXT, "playback_status": _TEXT, "media_timestamp": _number(0, 1e12),
                            "observed_at": _text(80), "sample_age_seconds": _number(0, 1e9),
                            "lag_seconds": _number(-1e9, 1e9), "normal_streak": _COUNT,
                            "seek_generation": _COUNT, "last_seek_direction": _nullable(_TEXT),
                            "program_time_offset_seconds": _number(-86400, 86400)},
    "error": {"reason": _enum("validation", "denied", "unavailable")},
}
_REQUIRED = {"mode_update": {"mode"}, "connection_status": {"hue", "sonos", "build_id"},
             "light_update": {"light_id"},
             "light_command_result": {"command_id", "status"},
             "light_command_reconciliation": {"light_id"},
             "error": {"reason"},
             "gameday_state": {"status"}, "gameday_viewer_state": {"status"},
             "gameday_play": {"timestamp", "play_type", "description"},
             "gameday_celebration": {"sequence_key", "started_at"}}


def _fields(data, schema):
    if type(data) is not dict:
        raise ValueError("Invalid event")
    result = {}
    for key, check in schema.items():
        if key not in data:
            continue
        value = data[key]
        if type(check) is dict:
            if value is None and key in {"last_play", "current_drive"}:
                result[key] = None
            else:
                result[key] = _fields(value, check)
                if check is _PLAY and not {"timestamp", "play_type", "description"} <= result[key].keys():
                    raise ValueError("Incomplete nested play")
        elif check(value):
            result[key] = value
        else:
            raise ValueError("Invalid event field")
    return result


def project_event(profile, lane, kind, data):
    """Default deny; never use a projection miss to send the original event.

    Remaining release gates: pipeline_state (private arbitrary fusion/inputs),
    artwork/sound URLs and ambient configuration need owned safe contracts.
    Private lighting receipts use the #530 contract and never join broadcasts.
    """
    native = project_native_ws_event(profile=profile, lane=lane, message_type=kind, data=data)
    if native is not None:
        return native
    if (any(type(v) is not str for v in (profile, lane, kind))
            or (profile, lane) not in {("owner_browser", "browser"), ("kiosk", "display")}
            or type(data) is not dict or kind not in _OWNER_EVENTS):
        return None
    try:
        payload = _fields(data, _OWNER_EVENTS[kind])
        if not _REQUIRED.get(kind, set()) <= payload.keys():
            return None
        if not payload and _OWNER_EVENTS[kind]:
            return None
        return {"type": kind, "data": payload}
    except (ValueError, TypeError, OverflowError):
        return None


class AuthenticatedBoundary:
    """One event-loop/thread owner; no public caller-selected session identities.

    dispatcher(identity, validated_command) must preserve LightingAuthority/audio
    ownership and established apply chokepoints. Absent dispatcher denies commands.
    It must be cancellation-safe and recheck intent/ownership at its apply point;
    dispatch is time bounded and cancellation terminates the session. Authorization here
    is point-in-time intent permission, never actuator ownership or a write lease.
    """

    def __init__(self, store, endpoints, *, browser_issuer_ready=False, dispatcher=None,
                 clock=time.monotonic, io_timeout=2.0, recheck_seconds=5.0,
                 max_sessions=16, auth_per_second=8, auth_seconds=2.0,
                 inbound_per_second=4):
        self._endpoints = tuple(endpoints)
        if not self._endpoints or any(type(e) is not Endpoint for e in self._endpoints):
            raise ValueError("Explicit validated endpoints required")
        if (len(self._endpoints) > 4
                or len({e.profile for e in self._endpoints}) != len(self._endpoints)):
            raise ValueError("Ambiguous endpoint")
        for value in (io_timeout, recheck_seconds, auth_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 30:
                raise ValueError("Invalid time budget")
        for value in (max_sessions, auth_per_second, inbound_per_second):
            if type(value) is not int or not 0 < value <= 64:
                raise ValueError("Invalid resource budget")
        if type(store) is not TrustedAsyncAuthorizer:
            raise TypeError("Explicit TrustedAsyncAuthorizer required; synchronous stores are unsafe")
        self._store, self._clock = store, clock
        self._browser_ready = browser_issuer_ready is True
        self._dispatcher = dispatcher
        self._io_timeout, self._recheck = io_timeout, recheck_seconds
        self._max_sessions, self._auth_rate = max_sessions, auth_per_second
        self._auth_seconds, self._inbound_rate = auth_seconds, inbound_per_second
        self._sessions = {}
        self._auth_calls = deque()  # admission only; never charged to established sessions
        self._verifications = {"admission": set(), "active": set()}
        self.auth_count = 0
        self.auth_max_seconds = 0.0

    def _budget(self, bucket, maximum):
        now = self._clock()
        if not math.isfinite(now):
            return False
        while bucket and bucket[0] <= now - 1:
            bucket.popleft()
        if len(bucket) >= maximum:
            return False
        bucket.append(now)
        return True

    async def _authorize(self, token, endpoint, operation, *, admission=False):
        if admission and not self._budget(self._auth_calls, self._auth_rate):
            return None
        stage = "admission" if admission else "active"
        pending = self._verifications[stage]
        # No executor queue hidden behind a semaphore. Admission can never take
        # active capacity. Late/cancelled callers retain their physical-work slot.
        if len(pending) >= (1 if admission else self._max_sessions):
            return None
        start = time.perf_counter()
        task = asyncio.create_task(self._store.authorize(
            token, operation, lane=_LANES[endpoint.profile], stage=stage))
        pending.add(task)
        def settled(done):
            pending.discard(done)
            if not done.cancelled():
                done.exception()  # consume failures even after caller timeout/cancel
        task.add_done_callback(settled)
        self.auth_count += 1
        try:
            done, _ = await asyncio.wait({task}, timeout=self._auth_seconds)
            if not done:
                return None
            identity = task.result()
        except asyncio.CancelledError:
            raise
        except Exception:
            return None
        finally:
            elapsed = time.perf_counter() - start
            self.auth_max_seconds = max(self.auth_max_seconds, elapsed)
        if (elapsed > self._auth_seconds or type(identity) is not Identity
                or identity.profile != endpoint.profile or identity.lane != _LANES[endpoint.profile]
                or identity.source != PROFILES[endpoint.profile].source
                or (operation, identity.lane) not in PROFILES[endpoint.profile].grants):
            return None
        return identity

    async def close(self, socket):
        session = self._sessions.pop(socket, None)
        if session is not None:
            session.token = ""  # erase bearer reference before I/O
            # Registry removal alone cannot stop a suspended transport send.
            # Cancel owned I/O and dispatch; final actuator cleanup still belongs
            # to the established ownership handler, never fabricate a receipt.
            for task in tuple(session.work):
                task.cancel()
        try:
            await asyncio.wait_for(socket.close(code=1008), self._io_timeout)
        except Exception:
            pass

    def _handshake(self, socket):
        scope = socket.scope
        if scope.get("path") != "/ws" or scope.get("query_string", b""):
            return None
        raw_headers = scope.get("headers", [])
        if len(raw_headers) > 32 or sum(len(k) + len(v) for k, v in raw_headers) > 8192:
            return None
        headers = {}
        for key, value in raw_headers:
            key, value = key.decode("ascii").lower(), value.decode("ascii")
            if key in headers or key == "forwarded" or key.startswith("x-forwarded-"):
                return None
            headers[key] = value
        if "sec-websocket-protocol" in headers:  # no bearer subprotocol workaround
            return None
        host, origin = headers.get("host"), headers.get("origin")
        candidates = []
        for endpoint in self._endpoints:
            parsed = urlsplit(endpoint.origin)
            if host != parsed.netloc or scope.get("scheme") != (
                    "wss" if parsed.scheme == "https" else "ws"):
                continue
            browser = endpoint.profile in {"owner_browser", "kiosk"}
            if browser:
                if (not self._browser_ready or parsed.scheme != "https"
                        or origin != endpoint.origin or "authorization" in headers):
                    continue
                cookies = {}
                for part in headers.get("cookie", "").split(";"):
                    name, sep, value = part.strip().partition("=")
                    if not sep or name in cookies:
                        return None
                    cookies[name] = value
                token = cookies.get(_COOKIE)
            else:
                if origin is not None or "cookie" in headers:
                    continue
                auth = headers.get("authorization", "")
                token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else None
            if type(token) is str and _TOKEN.fullmatch(token):
                candidates.append((endpoint, token))
        return candidates

    async def admit(self, socket):
        """Validate before accept. No initial frames are automatically privileged."""
        if socket in self._sessions:
            await self.close(socket)
            return False
        try:
            candidate = self._handshake(socket)
            if not candidate or len(self._sessions) >= self._max_sessions:
                await self.close(socket)
                return False
            identity = None
            for endpoint, token in candidate:
                identity = await self._authorize(token, endpoint, WS, admission=True)
                if identity is not None:
                    break
            if (identity is None or socket in self._sessions
                    or len(self._sessions) >= self._max_sessions):
                await self.close(socket)
                return False
            session = _Session(socket, endpoint, token, identity)
            self._sessions[socket] = session  # reserve capacity across accept await
            await asyncio.wait_for(socket.accept(), self._io_timeout)
            if self._sessions.get(socket) is not session:
                return False
            session.ready = True
            return True
        except asyncio.CancelledError:
            await self.close(socket)
            raise
        except Exception:
            await self.close(socket)
            return False

    async def _valid(self, session, operation=WS):
        try:
            async with session.auth_lock:
                return await self._valid_serialized(session, operation)
        except asyncio.CancelledError:
            await self.close(session.socket)
            raise

    async def _valid_serialized(self, session, operation):
        if self._sessions.get(session.socket) is not session or not session.ready:
            return False
        try:
            identity = await self._authorize(session.token, session.endpoint, operation)
        except asyncio.CancelledError:
            await self.close(session.socket)
            raise
        if (self._sessions.get(session.socket) is not session
                or identity != session.identity):
            await self.close(session.socket)
            return False
        return True

    async def _work(self, session, awaitable):
        async def owned():
            # A close may win between authorization and task scheduling.
            if self._sessions.get(session.socket) is not session:
                awaitable.close()
                raise asyncio.CancelledError
            return await awaitable
        task = asyncio.create_task(owned())
        session.work.add(task)
        def settled(done):
            session.work.discard(done)
            if inspect.iscoroutine(awaitable):
                awaitable.close()
            if not done.cancelled():
                done.exception()
        task.add_done_callback(settled)
        try:
            return await asyncio.wait_for(task, self._io_timeout)
        finally:
            if not task.done():
                task.cancel()

    async def send(self, socket, kind, data):
        session = self._sessions.get(socket)
        if session is None or session.pending_sends >= 8:
            return False
        session.pending_sends += 1
        try:
            frame = project_event(session.identity.profile, session.identity.lane, kind, data)
            if frame is None:
                return False
            # Verification owns its separate timeout. Only lock/send use I/O budget.
            async with asyncio.timeout(self._io_timeout + self._auth_seconds):
                async with session.lock:
                    if not await self._valid(session):
                        return False
                    # _valid may have awaited; a parallel close must still win.
                    if self._sessions.get(socket) is not session:
                        return False
                    encoded = json.dumps(frame, allow_nan=False)
                    if len(encoded) > 16384:
                        return False
                    await self._work(session, socket.send_text(encoded))
                    return True
        except asyncio.CancelledError:
            if self._sessions.get(socket) is not session:
                return False
            await self.close(socket)
            raise
        except Exception:
            await self.close(socket)
            return False
        finally:
            session.pending_sends -= 1

    async def initial(self, socket, events):
        for kind, data in events:
            await self.send(socket, kind, data)

    async def broadcast(self, kind, data):
        if type(kind) is not str or kind in _PRIVATE_EVENTS:
            return
        # A transport raising cancellation must not cancel its producer/service.
        # Canceling the broadcast itself still cancels and drains its children.
        await asyncio.gather(*(self.send(ws, kind, data) for ws in tuple(self._sessions)),
                             return_exceptions=True)

    async def inbound(self, socket, raw):
        session = self._sessions.get(socket)
        if session is None:
            return False
        if not self._budget(session.inbound, self._inbound_rate):
            await self.close(socket)
            return False
        message = None
        try:
            if type(raw) is not str or len(raw) > 4096:
                raise ValueError("Invalid frame")
            message = json.loads(raw, object_pairs_hook=_unique_object)
            command = _strict_command(message)
            operation = ws_command_operation(command.type)
        except (ValidationError, ValueError, RecursionError):
            await self.send(socket, "error", {"reason": "validation"})
            # Reflect only a syntactically safe correlation, never invalid data.
            # This private response also reauthorizes the session before sending.
            data = message.get("data") if type(message) is dict else None
            identifier = data.get("command_id") if type(data) is dict else None
            if (type(message) is dict and message.get("type") == "light_command"
                    and type(identifier) is str and _CORRELATION(identifier)):
                await self.send(socket, "light_command_result", {
                    "command_id": identifier, "status": "invalid"})
            return False
        if (session.identity.profile not in {"owner_browser", "kiosk"}
                or operation is None):
            await self.close(socket)
            return False
        if not await self._valid(session, operation):
            return False
        if self._dispatcher is None:
            await self.send(socket, "error", {"reason": "unavailable"})
            return False
        try:
            events = await self._work(session, self._dispatcher(session.identity, command))
            # A dispatcher returns bounded private events, never raw socket access.
            if type(events) in (tuple, list) and len(events) <= 2:
                for kind, data in events:
                    if kind in _PRIVATE_EVENTS:
                        await self.send(socket, kind, data)
            return True
        except asyncio.CancelledError:
            if self._sessions.get(socket) is not session:
                return False
            await self.close(socket)
            raise
        except Exception:
            await self.close(socket)
            return False

    async def serve(self, socket, initial=()):
        """Own receive lifecycle; quiet sessions cannot retain indefinite grants."""
        if not await self.admit(socket):
            return
        session = self._sessions[socket]
        async def watch():
            while self._sessions.get(socket) is session:
                await asyncio.sleep(self._recheck)
                if not await self._valid(session):
                    return

        watcher = asyncio.create_task(watch())
        try:
            if callable(initial):
                if not await self._valid(session):
                    return
                initial = initial(session.identity)
            await self.initial(socket, initial)
            while self._sessions.get(socket) is session:
                try:
                    raw = await asyncio.wait_for(socket.receive_text(), self._recheck)
                except TimeoutError:
                    if not await self._valid(session):
                        break
                    continue
                await self.inbound(socket, raw)
        except Exception:
            pass
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            await self.close(socket)

    @property
    def connection_count(self):
        return sum(session.ready for session in self._sessions.values())
