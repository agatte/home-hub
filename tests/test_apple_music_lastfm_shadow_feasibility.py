"""Invented Last.fm recent-tracks pages only; no real account or playback."""
from __future__ import annotations

import copy
import dataclasses
import subprocess
import sys
import unittest
from pathlib import Path

from backend.services.apple_music_lastfm_shadow_feasibility import (
    LastFmShadowRefused, MAX_ITEMS_PER_PAGE, MAX_PAGES,
    assess_lastfm_recent_pages,
)


PRIVATE = "INVENTED_PRIVATE_TRACK_AND_USER_MARKER"


def song(uts="1794355200", *, live=False):
    item = {
        "name": PRIVATE,
        "artist": {"#text": PRIVATE},
        "album": {"#text": PRIVATE},
        "url": "https://invalid.example/" + PRIVATE,
        "date": {"uts": uts},
    }
    if live:
        item["@attr"] = {"nowplaying": "true"}
        item.pop("date")
    return item


def page(*items):
    return {"recenttracks": {"track": list(items), "@attr": {
        "user": PRIVATE, "total": "123", "page": "1",
    }}}


class LastFmShadowTests(unittest.TestCase):
    def refuses(self, pages):
        with self.assertRaises(LastFmShadowRefused) as caught:
            assess_lastfm_recent_pages(pages)
        self.assertEqual(str(caught.exception), "Offline Last.fm feasibility refused")
        self.assertNotIn(PRIVATE, repr(caught.exception))

    def test_one_reported_scrobble_has_zero_verified_sessions(self):
        a = assess_lastfm_recent_pages([page(song())])
        self.assertEqual((a.pages_examined, a.resource_observations), (1, 1))
        self.assertEqual(a.timestamped_scrobble_observations, 1)
        self.assertEqual(a.verified_play_sessions, 0)
        self.assertFalse(a.recording_identity_verified)
        self.assertFalse(a.taste_updates_eligible)
        self.assertFalse(a.complete_history_proven)

    def test_now_playing_is_not_a_completed_scrobble(self):
        a = assess_lastfm_recent_pages([page(song(live=True), song())])
        self.assertEqual(a.resource_observations, 2)
        self.assertEqual(a.now_playing_observations, 1)
        self.assertEqual(a.timestamped_scrobble_observations, 1)

    def test_timestamp_collision_is_not_a_play_or_duplicate_proof(self):
        a = assess_lastfm_recent_pages([page(song(), song())])
        self.assertEqual(a.timestamped_scrobble_observations, 2)
        self.assertEqual(a.repeated_timestamp_observations, 1)
        self.assertEqual(a.verified_play_sessions, 0)

    def test_cross_page_timestamp_collision(self):
        a = assess_lastfm_recent_pages([page(song()), page(song())])
        self.assertEqual(a.pages_examined, 2)
        self.assertEqual(a.repeated_timestamp_observations, 1)

    def test_missing_and_bad_dates_do_not_create_claims(self):
        no_date = song()
        no_date.pop("date")
        non_object = song()
        non_object["date"] = PRIVATE
        invalid = song(uts="abc")
        a = assess_lastfm_recent_pages([page(no_date, non_object, invalid)])
        self.assertEqual((a.missing_date_observations,
                          a.invalid_timestamp_observations), (1, 2))
        self.assertEqual(a.timestamped_scrobble_observations, 0)

    def test_timestamp_validation_is_ascii_utc_in_bounded_window(self):
        invalid = ("", "123", "-1794355200", "1794355200x",
                   "１７９４３５５２００", "0000000000", "4102444800",
                   "9999999999", 1794355200, True, None)
        for value in invalid:
            with self.subTest(value_type=type(value).__name__):
                a = assess_lastfm_recent_pages([page(song(uts=value))])
                self.assertEqual(a.invalid_timestamp_observations, 1)
                self.assertEqual(a.timestamped_scrobble_observations, 0)

    def test_zero_tracks_is_valid_but_not_complete_history(self):
        a = assess_lastfm_recent_pages([page()])
        self.assertEqual(a.resource_observations, 0)
        self.assertFalse(a.complete_history_proven)

    def test_malformed_envelopes_and_provider_errors_refuse(self):
        bad = [
            [{}], [{"error": 29, "message": PRIVATE}],
            [{"recenttracks": {}}], [{"recenttracks": {"track": None}}],
            [{"recenttracks": {"track": PRIVATE}}],
            [page(None)], [page({"@attr": {"nowplaying": PRIVATE}})],
            [page({"@attr": PRIVATE})], [None],
        ]
        for pages in bad:
            with self.subTest(kind=str(type(pages))):
                self.refuses(pages)

    def test_max_200_items_per_page_and_three_pages_fixture_budget(self):
        a = assess_lastfm_recent_pages([page(*([song()] * MAX_ITEMS_PER_PAGE))])
        self.assertEqual(a.resource_observations, MAX_ITEMS_PER_PAGE)
        self.refuses([page(*([song()] * (MAX_ITEMS_PER_PAGE + 1)))])
        self.refuses([page()] * (MAX_PAGES + 1))

    def test_lazy_iterables_and_empty_list_refuse(self):
        self.refuses([])
        self.refuses(iter([page()]))

    def test_sensitive_fields_never_surface_in_aggregates_or_repr(self):
        a = assess_lastfm_recent_pages([page(song())])
        self.assertNotIn(PRIVATE, repr(a))
        self.assertNotIn(PRIVATE, str(a))
        self.assertNotIn("1794355200", repr(a))
        self.assertEqual(set(dataclasses.asdict(a)), {
            "pages_examined", "resource_observations", "now_playing_observations",
            "timestamped_scrobble_observations", "missing_date_observations",
            "invalid_timestamp_observations", "repeated_timestamp_observations",
        })

    def test_input_not_mutated_and_aggregate_is_frozen(self):
        pages = [page(song(), song(live=True))]
        before = copy.deepcopy(pages)
        a = assess_lastfm_recent_pages(pages)
        self.assertEqual(pages, before)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.pages_examined = 500

    def test_import_and_assessment_do_not_access_network_or_db(self):
        script = """
import socket, sqlite3
from unittest.mock import patch
def blocked(*args, **kwargs):
    raise AssertionError('Unexpected side effect')
with patch.object(socket, 'socket', blocked), patch.object(sqlite3, 'connect', blocked):
    from backend.services.apple_music_lastfm_shadow_feasibility import assess_lastfm_recent_pages
    report = assess_lastfm_recent_pages([{'recenttracks': {'track': []}}])
    assert report.verified_play_sessions == 0
"""
        root = Path(__file__).resolve().parents[1]
        done = subprocess.run(
            [sys.executable, "-B", "-c", script], cwd=root,
            capture_output=True, text=True, timeout=20, check=False,
        )
        self.assertEqual(done.returncode, 0, "No-I/O import fixture failed")


if __name__ == "__main__":
    unittest.main()
