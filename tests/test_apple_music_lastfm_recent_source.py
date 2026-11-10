"""Offline-only tests of the read-only Last.fm source adapter (#431)."""
from __future__ import annotations

import json
import unittest
from urllib.parse import parse_qs, urlparse

from backend.services.apple_music_lastfm_recent_source import (
    LastFmRecentUnavailable, read_lastfm_recent_summary,
)

USER = "synthetic_user"
KEY = "0123456789abcdef0123456789abcdef"
SECRET = "INVENTED_PRIVATE_TRACK_MARKER"
NOW = 1_795_000_000


def song(uts: int | str, *, live: bool = False):
    track = {
        "name": SECRET, "artist": {"#text": SECRET},
        "url": "https://invalid.example/" + SECRET,
    }
    if live:
        track["@attr"] = {"nowplaying": "true"}
    else:
        track["date"] = {"uts": str(uts)}
    return track


def document(*tracks, user=USER, total="13"):
    return {
        "recenttracks": {
            "@attr": {"user": user, "page": "1", "total": total},
            "track": list(tracks),
        },
    }


def offline(data):
    """Fake HTTP transport; returns fictional JSON bytes only."""
    content = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return lambda request: content


class LastFmRecentSourceTests(unittest.TestCase):
    def test_realistic_recent_page_aggregates_without_names(self):
        rows = [
            song(NOW - 100), song(NOW - 100),
            song(NOW - 100000), song(NOW - 600000),
            song(NOW - 100, live=True),
        ]
        r = read_lastfm_recent_summary(
            USER, KEY, now_seconds=NOW, fetch_bytes=offline(document(*rows)))
        self.assertEqual(r.observations, 5)
        self.assertEqual(r.timestamped_scrobbles, 4)
        self.assertEqual(r.now_playing, 1)
        self.assertEqual(r.last_24_hours, 2)
        self.assertEqual(r.last_7_days, 4)
        self.assertEqual(r.repeated_utc_seconds, 1)
        self.assertEqual(r.newest_age_hours, 0)
        self.assertEqual(r.reported_scrobbles_total, 13)
        self.assertFalse(r.taste_eligible)
        self.assertEqual(r.verified_independent_plays, 0)
        self.assertNotIn(SECRET, repr(r))
        self.assertNotIn(USER, repr(r))
        self.assertNotIn(KEY, repr(r))
        self.assertNotIn(str(NOW - 100), repr(r))

    def test_endpoint_and_credentials_only_in_request_not_result(self):
        seen = []
        def record(request):
            seen.append(request)
            return json.dumps(document(song(NOW - 60))).encode("utf-8")
        r = read_lastfm_recent_summary(USER, KEY, fetch_bytes=record, now_seconds=NOW)
        self.assertEqual(len(seen), 1)
        req = seen[0]
        u = urlparse(req.full_url)
        self.assertEqual((u.scheme, u.netloc, u.path),
                         ("https", "ws.audioscrobbler.com", "/2.0/"))
        p = parse_qs(u.query)
        self.assertEqual(p["method"], ["user.getrecenttracks"])
        self.assertEqual(p["user"], [USER])
        self.assertEqual(p["api_key"], [KEY])
        self.assertEqual(p["limit"], ["50"])
        self.assertEqual(p["page"], ["1"])
        self.assertEqual(req.get_method(), "GET")
        self.assertNotIn(KEY, repr(r))
        self.assertNotIn(USER, repr(r))

    def test_empty_history_not_a_verified_play(self):
        r = read_lastfm_recent_summary(USER, KEY, now_seconds=NOW,
                                      fetch_bytes=offline(document()))
        self.assertEqual(r.observations, 0)
        self.assertEqual(r.last_24_hours, 0)
        self.assertIsNone(r.newest_age_hours)
        self.assertEqual(r.verified_independent_plays, 0)

    def test_missing_and_invalid_dates_aggregate_conservatively(self):
        missing = song(NOW)
        del missing["date"]
        invalid = song("unexpected-private-value")
        r = read_lastfm_recent_summary(USER, KEY, now_seconds=NOW,
                                      fetch_bytes=offline(document(missing, invalid)))
        self.assertEqual(r.missing_date, 1)
        self.assertEqual(r.invalid_date, 1)
        self.assertEqual(r.last_7_days, 0)

    def test_future_timestamp_not_eligible_as_recent(self):
        r = read_lastfm_recent_summary(USER, KEY, now_seconds=NOW,
                                      fetch_bytes=offline(document(song(NOW + 18000))))
        self.assertEqual(r.last_24_hours, 0)
        self.assertEqual(r.last_7_days, 0)
        self.assertIsNone(r.newest_age_hours)

    def test_provider_error_and_mismatched_account_redacted(self):
        for data in ({"error": 6, "message": SECRET},
                     document(song(NOW), user=SECRET),
                     {"recenttracks": {"track": [song(NOW)]}},
                     {"recenttracks": {"@attr": {"user": USER}, "track": None}}):
            with self.subTest(data_shape=type(data).__name__):
                self.refused(data)

    def test_rejected_payloads_are_never_echoed(self):
        for content in (b"", b"not-json", b"x" * 512001,
                        SECRET.encode() + b" BAD",
                        json.dumps(document(*[song(NOW)] * 52)).encode("utf-8")):
            with self.subTest(length=len(content)):
                with self.assertRaises(LastFmRecentUnavailable) as caught:
                    read_lastfm_recent_summary(USER, KEY, now_seconds=NOW,
                                               fetch_bytes=lambda _r, c=content: c)
                self.assertEqual(str(caught.exception),
                                 "Last.fm recent summary unavailable")
                self.assertNotIn(SECRET, repr(caught.exception))

    def test_invalid_user_key_and_limits_never_fetch(self):
        calls = []
        def record(_request):
            calls.append(1)
            return b"{}"
        for user, key, limit in [
            ("bad/user", KEY, 50), (USER, "bad-key", 50),
            (USER, KEY, 0), (USER, KEY, 51),
            (USER, KEY, True), ("", KEY, 50),
        ]:
            with self.subTest(user_shape=type(user).__name__, limit=limit):
                with self.assertRaises(LastFmRecentUnavailable):
                    read_lastfm_recent_summary(user, key, limit=limit,
                                               now_seconds=NOW, fetch_bytes=record)
        self.assertEqual(calls, [])

    def test_network_exceptions_do_not_leak_urls_or_credentials(self):
        def bad(_request):
            raise OSError("sensitive " + KEY + " " + USER + " " + SECRET)
        with self.assertRaises(LastFmRecentUnavailable) as caught:
            read_lastfm_recent_summary(USER, KEY, now_seconds=NOW, fetch_bytes=bad)
        self.assertEqual(str(caught.exception), "Last.fm recent summary unavailable")
        self.assertNotIn(KEY, repr(caught.exception))
        self.assertNotIn(USER, repr(caught.exception))
        self.assertNotIn(SECRET, repr(caught.exception))

    def test_bounded_limit_explicit(self):
        def record(request):
            q = parse_qs(urlparse(request.full_url).query)
            self.assertEqual(q["limit"], ["1"])
            return json.dumps(document(song(NOW - 1))).encode()
        r = read_lastfm_recent_summary(USER, KEY, limit=1,
                                      now_seconds=NOW, fetch_bytes=record)
        self.assertEqual(r.observations, 1)

    def refused(self, data):
        with self.assertRaises(LastFmRecentUnavailable) as caught:
            read_lastfm_recent_summary(USER, KEY, now_seconds=NOW,
                                       fetch_bytes=offline(data))
        self.assertNotIn(SECRET, repr(caught.exception))


if __name__ == "__main__":
    unittest.main()
