"""Shared route guards for service-availability checks.

Originated in `lights.py` / `sonos.py` after the HOME-HUB-Y breaker
incident; lifted here so guest / music / scenes routes can use the
same shape without duplicating the helper across five files.

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
from fastapi import HTTPException


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
