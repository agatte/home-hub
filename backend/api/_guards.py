"""Shared route guards — service-availability checks + client-clock clamp.

Originated in `lights.py` / `sonos.py` after the HOME-HUB-Y breaker
incident; lifted here so guest / music / scenes routes can use the
same shape without duplicating the helper across five files.
``clamp_client_timestamp`` joined 2026-06-07 after the desktop
mobo-swap clock incident (see its docstring).

Both checks distinguish two unavailability states with distinct detail
strings so post-mortem log readers can tell them apart:

- ``not connected``: initial bridge/speaker discovery or auth never
  succeeded. Long-lived failure mode; the service object exists but
  has no live transport.
- ``temporarily unavailable``: the circuit breaker is fast-failing
  because the bridge/speaker stopped responding mid-session and the
  cooldown hasn't elapsed yet. Transient; the next probe may recover.

Both surface as HTTP 503 (Service Unavailable) so clients know the
request is retry-worthy — distinct from the 500-class real failure
where retrying the same request makes no sense.

Half-open breaker state intentionally does NOT raise: the next call
through is a probe and may succeed, so denying it would deny clients
the natural recovery path.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger("home_hub.api.guards")

# Allowed forward skew before a client timestamp is clamped to server
# time. LAN round-trips are ~ms and agent cadences are >=2s, so anything
# beyond this is a wrong client clock, not network jitter.
CLIENT_CLOCK_TOLERANCE_S = 2.0

# Rate-limit the skew warning per source so a persistently-fast agent
# clock (2s POST cadence) doesn't flood the journal.
_SKEW_WARN_INTERVAL_S = 60.0
_last_skew_warn: dict[str, datetime] = {}


def clamp_client_timestamp(
    ts: Optional[datetime], *, source: str,
    tolerance_s: float = CLIENT_CLOCK_TOLERANCE_S,
) -> datetime:
    """Return ``ts`` clamped so it can never exceed server now.

    Routes that ingest off-host observations (presence, lux,
    blendshapes) accept a client-supplied capture timestamp. The
    services behind them keep monotonic high-water marks, so a single
    future-stamped report from a wrong client clock wedges the source
    until real time catches up — every subsequent honest report looks
    "out of order" and is dropped. Bit us 2026-06-07: a fresh-CMOS
    desktop clock ran ~4h40m fast after a motherboard swap, freezing
    the desktop presence lane (zone=desk, age_s=-16742) until NTP-time
    + 4h40m.

    The server clock is the only trusted clock at this boundary:
    ``None`` → server now; naive → assumed UTC; future beyond
    ``tolerance_s`` → clamped to server now (warning, rate-limited
    per source). Past timestamps pass through untouched — the
    services' out-of-order guards handle genuine staleness.
    """
    now = datetime.now(timezone.utc)
    if ts is None:
        return now
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    skew_s = (ts - now).total_seconds()
    if skew_s <= tolerance_s:
        return ts
    last_warn = _last_skew_warn.get(source)
    if last_warn is None or (now - last_warn).total_seconds() >= _SKEW_WARN_INTERVAL_S:
        _last_skew_warn[source] = now
        logger.warning(
            "clamped future timestamp from source=%s: client clock is "
            "+%.1fs ahead of server (check the client's NTP sync)",
            source, skew_s,
        )
    return now


def _check_hue_available(hue) -> None:
    """Raise 503 if the Hue service isn't currently reachable."""
    if not hue.connected:
        raise HTTPException(status_code=503, detail="Hue bridge not connected")
    if hue.breaker_open:
        raise HTTPException(status_code=503, detail="Hue bridge temporarily unavailable")


def _check_sonos_available(sonos) -> None:
    """Raise 503 if the Sonos service isn't currently reachable."""
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    if sonos.breaker_open:
        raise HTTPException(status_code=503, detail="Sonos temporarily unavailable")
