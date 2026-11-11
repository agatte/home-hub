"""Opt-in, volatile observation counters. No downstream consumers or persistence."""
from __future__ import annotations

import asyncio
import secrets
import time
from collections import OrderedDict
from functools import partial

from backend.services.apple_music_lastfm_recent_source import (
    _USER, _KEY, read_lastfm_observed_page,
)

RETENTION_SECONDS = 7 * 86400
MAX_REMEMBERED = 4096


class LastFmShadowService:
    def __init__(self, *, enabled=False, username="", api_key=None,
                 poll_minutes=15, source=read_lastfm_observed_page,
                 clock=time.monotonic):
        self._configured = (
            type(username) is str and bool(_USER.fullmatch(username))
            and type(api_key) is str and bool(_KEY.fullmatch(api_key))
            and type(poll_minutes) is int and 5 <= poll_minutes <= 1440)
        self._enabled = enabled is True
        self._username = username
        self._api_key = api_key
        self._interval = poll_minutes * 60 if self._configured else 900
        self._source = source
        self._clock = clock
        self._key = secrets.token_bytes(32)
        self._seen = OrderedDict()
        self._success = None
        self._failed = False
        self._baseline = False
        self._new = 0
        self._recent = 0
        self._recent_24 = 0
        self._running = False

    @property
    def ready(self):
        return self._enabled and self._configured

    def start(self):
        """Caller owns returned task and must register it for cancellation."""
        if not self.ready or self._running:
            return None
        self._running = True
        return asyncio.create_task(self._run(), name="lastfm-shadow")

    def _expire(self, now):
        while self._seen and next(iter(self._seen.values())) <= now - RETENTION_SECONDS:
            self._seen.popitem(last=False)

    async def _poll_once(self):
        if not self.ready:
            return
        try:
            page = await asyncio.to_thread(partial(
                self._source, self._username, self._api_key,
                fingerprint_key=self._key))
            now = self._clock()
            self._expire(now)
            unseen = page.fingerprints.difference(self._seen)
            if self._baseline:
                self._new += len(unseen)
            for fingerprint in unseen:
                self._seen[fingerprint] = now
            while len(self._seen) > MAX_REMEMBERED:
                self._seen.popitem(last=False)
            self._baseline = True
            self._recent = len(page.fingerprints)
            self._recent_24 = page.summary.last_24_hours
            self._success = now
            self._failed = False
        except Exception:
            # Never log exception text, URLs, payloads or identifiers.
            self._failed = True

    async def _run(self):
        try:
            while self.ready:
                await self._poll_once()
                await asyncio.sleep(self._interval)
        finally:
            self._running = False

    def status(self):
        now = self._clock()
        self._expire(now)
        stale = self._success is None or now - self._success > 2 * self._interval
        state = ("disabled" if not self._enabled else
                 "unconfigured" if not self._configured else
                 "degraded" if self._failed else "stale" if stale else "fresh")
        return {
            "state": state, "enabled": self._enabled,
            "freshness": "stale" if stale else "fresh",
            "source": "lastfm_reported_scrobbles_unverified",
            "baseline_seeded": self._baseline,
            "recent_page_observations": self._recent,
            "recent_page_last_24_hours": self._recent_24,
            "unseen_observations_since_baseline": self._new,
            "remembered_observations": len(self._seen),
            "verified_independent_plays": 0, "taste_eligible": False,
        }
