"""One-shot, read-only Last.fm recent scrobble assessment for HomeHub #431.

Opt-in call only. NOT imported by live HomeHub routes/services; NO account
authorization, scheduler, persistence, preferences, presence or Sonos actions.
Server assertions do not prove Apple source, unique listens or preference.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, Request, build_opener,
)

from backend.services.apple_music_lastfm_shadow_feasibility import (
    LastFmShadowRefused, assess_lastfm_recent_pages, _unix_second,
)

ENDPOINT = "https://ws.audioscrobbler.com/2.0/"
MAX_RESPONSE_BYTES = 512_000
MAX_TRACKS = 50
REQUEST_TIMEOUT_SECONDS = 12
_USER = re.compile(r"[A-Za-z0-9_-]{2,32}\Z", re.ASCII)
_KEY = re.compile(r"[0-9a-fA-F]{32}\Z", re.ASCII)


class LastFmRecentUnavailable(ValueError):
    """Deliberately fixed diagnostics: never expose account, key, URL or music."""

    def __init__(self) -> None:
        super().__init__("Last.fm recent summary unavailable")


@dataclass(frozen=True, repr=False)
class LastFmRecentSummary:
    """Anonymous numbers only; no recording, listening-session or taste proof."""

    reported_scrobbles_total: int | None
    observations: int
    now_playing: int
    timestamped_scrobbles: int
    missing_date: int
    invalid_date: int
    repeated_utc_seconds: int
    last_24_hours: int
    last_7_days: int
    newest_age_hours: int | None
    source: str = "lastfm_reported_scrobbles_unverified"

    @property
    def verified_independent_plays(self) -> int:
        return 0

    @property
    def taste_eligible(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "LastFmRecentSummary(<aggregate-only>)"


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LastFmRecentUnavailable()


def _read_https(request: Request) -> bytes:
    """Only the official endpoint; system TLS verification; no redirects."""
    opener = build_opener(HTTPSHandler(), _NoRedirects())
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise LastFmRecentUnavailable()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if not raw or len(raw) > MAX_RESPONSE_BYTES:
            raise LastFmRecentUnavailable()
        return raw


def read_lastfm_recent_summary(
    username: str,
    api_key: str,
    *,
    limit: int = MAX_TRACKS,
    now_seconds: int | None = None,
    fetch_bytes: Callable[[Request], bytes] | None = None,
) -> LastFmRecentSummary:
    """Return aggregated last-page exposure without retaining any track details.

    `fetch_bytes` is a synthetic-test injection point; the production default
    does a single explicit HTTPS GET with the supplied key. This function has
    no callers in the live app and cannot launch automatically.
    """
    try:
        if (not isinstance(username, str) or not _USER.fullmatch(username)
                or not isinstance(api_key, str) or not _KEY.fullmatch(api_key)
                or type(limit) is not int or not 1 <= limit <= MAX_TRACKS):
            raise LastFmRecentUnavailable()
        if now_seconds is None:
            now_seconds = int(time.time())
        if type(now_seconds) is not int or not 946684800 <= now_seconds < 4102444800:
            raise LastFmRecentUnavailable()

        query = urlencode({
            "method": "user.getrecenttracks",
            "user": username,
            "api_key": api_key,
            "format": "json",
            "limit": limit,
            "page": 1,
        })
        request = Request(
            ENDPOINT + "?" + query,
            headers={"Accept": "application/json", "User-Agent": "HomeHub-readonly-431/1"},
            method="GET",
        )
        raw = (fetch_bytes or _read_https)(request)
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
            raise LastFmRecentUnavailable()
        data = json.loads(raw.decode("utf-8"))
        if type(data) is not dict or "error" in data:
            raise LastFmRecentUnavailable()
        envelope = data.get("recenttracks")
        if type(envelope) is not dict:
            raise LastFmRecentUnavailable()
        meta = envelope.get("@attr")
        if type(meta) is not dict or str(meta.get("user", "")).casefold() != username.casefold():
            raise LastFmRecentUnavailable()
        tracks = envelope.get("track")
        if type(tracks) is not list or len(tracks) > limit + 1:
            raise LastFmRecentUnavailable()

        assessed = assess_lastfm_recent_pages([data])
        total_text = meta.get("total")
        total = (int(total_text) if type(total_text) is str
                 and total_text.isascii() and total_text.isdecimal()
                 and len(total_text) <= 9 else None)
        newest = 0
        recent_24 = recent_7 = 0
        for item in tracks:
            marker = item.get("@attr")
            if type(marker) is dict and marker.get("nowplaying") == "true":
                continue
            date = item.get("date")
            second = _unix_second(date.get("uts")) if type(date) is dict else None
            if second is None or second > now_seconds + 600:
                continue
            newest = max(newest, second)
            age = now_seconds - second
            if 0 <= age <= 86400:
                recent_24 += 1
            if 0 <= age <= 604800:
                recent_7 += 1
        return LastFmRecentSummary(
            reported_scrobbles_total=total,
            observations=assessed.resource_observations,
            now_playing=assessed.now_playing_observations,
            timestamped_scrobbles=assessed.timestamped_scrobble_observations,
            missing_date=assessed.missing_date_observations,
            invalid_date=assessed.invalid_timestamp_observations,
            repeated_utc_seconds=assessed.repeated_timestamp_observations,
            last_24_hours=recent_24,
            last_7_days=recent_7,
            newest_age_hours=max(0, (now_seconds - newest) // 3600) if newest else None,
        )
    except Exception:
        # Third-party exception and request repr may contain sensitive query
        # parameters, account names, track text, exact dates, or raw JSON.
        raise LastFmRecentUnavailable() from None
