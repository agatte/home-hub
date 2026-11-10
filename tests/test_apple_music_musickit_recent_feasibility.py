"""Invented MusicKit recent-track response fixtures only; no Apple account/data."""
from __future__ import annotations

import copy
import dataclasses
import subprocess
import sys
import unittest
from pathlib import Path

from backend.services.apple_music_musickit_recent_feasibility import (
    MAX_PAGES, MAX_PAGE_ITEMS, RecentTracksRefused, assess_recent_track_pages,
)


def song(identifier="1234567890", **attributes):
    return {"type": "songs", "id": identifier, "attributes": {
        "name": "Fictional Cloud Harp", "artistName": "Invented Lantern Trio",
        **attributes,
    }}


def page(*resources, next_value=None):
    result = {"data": list(resources)}
    if next_value is not None:
        result["next"] = next_value
    return result


class MusicKitRecentFeasibilityTests(unittest.TestCase):
    def refused(self, pages, needle="Fictional Cloud Harp"):
        with self.assertRaises(RecentTracksRefused) as caught:
            assess_recent_track_pages(pages)
        self.assertEqual(str(caught.exception),
                         "Offline recent-track feasibility refused")
        self.assertNotIn(needle, repr(caught.exception))

    def test_catalog_resource_is_not_a_play_event_or_taste(self):
        report = assess_recent_track_pages([page(song())])
        self.assertEqual((report.pages_examined, report.resource_observations), (1, 1))
        self.assertEqual(report.catalog_song_observations, 1)
        self.assertEqual(report.distinct_catalog_song_ids, 1)
        self.assertEqual(report.verified_play_sessions, 0)
        self.assertFalse(report.taste_updates_eligible)
        self.assertFalse(report.complete_history_proven)

    def test_repeated_resource_in_one_page_is_not_two_plays(self):
        report = assess_recent_track_pages([page(song(), song())])
        self.assertEqual(report.resource_observations, 2)
        self.assertEqual(report.repeated_catalog_id_observations, 1)
        self.assertEqual(report.verified_play_sessions, 0)

    def test_duplicates_across_page_boundaries_do_not_prove_play_count(self):
        report = assess_recent_track_pages([
            page(song(), next_value="/v1/me/recent/played/tracks?offset=1"),
            page(song(), song("789123")),
        ])
        self.assertEqual(report.catalog_song_observations, 3)
        self.assertEqual(report.distinct_catalog_song_ids, 2)
        self.assertEqual(report.repeated_catalog_id_observations, 1)
        self.assertFalse(report.last_page_advertised_next)

    def test_apparent_replay_timestamp_does_not_change_evidence_status(self):
        report = assess_recent_track_pages([page(
            song(playedAt="2026-11-09T08:00:00Z"),
            song(playedAt="2026-11-09T13:00:00Z"),
        )])
        self.assertEqual(report.distinct_catalog_song_ids, 1)
        self.assertEqual(report.verified_play_sessions, 0)

    def test_library_song_id_does_not_become_catalog_identity(self):
        report = assess_recent_track_pages([page(
            {"type": "library-songs", "id": "1234567890", "attributes": {
                "name": "Invented Archive Track",
            }}
        )])
        self.assertEqual(report.library_song_observations, 1)
        self.assertEqual(report.distinct_catalog_song_ids, 0)

    def test_music_videos_do_not_become_song_evidence(self):
        report = assess_recent_track_pages([page(
            {"type": "music-videos", "id": "1001"},
            {"type": "library-music-videos", "id": "1002"},
        )])
        self.assertEqual(report.video_observations, 2)
        self.assertEqual(report.catalog_song_observations, 0)

    def test_bad_catalog_ids_abstain_and_count_only(self):
        identifiers = (None, False, 12, "", "0000", "abc",
                       "\u0661\u0662\u0663", "4" * 33, "12 34")
        report = assess_recent_track_pages([page(*(song(x) for x in identifiers))])
        self.assertEqual(report.unusable_catalog_song_ids, len(identifiers))
        self.assertEqual(report.distinct_catalog_song_ids, 0)
        self.assertEqual(report.verified_play_sessions, 0)

    def test_only_ascii_decimal_nonzero_catalog_id_shape(self):
        report = assess_recent_track_pages([page(song("00000123"), song("123"))])
        self.assertEqual(report.distinct_catalog_song_ids, 2)
        self.assertEqual(report.verified_play_sessions, 0)

    def test_unexpected_resource_type_fails_closed(self):
        self.refused([page({"type": "albums", "id": "123"})])

    def test_unhashable_resource_type_fails_with_fixed_error(self):
        self.refused([page({"type": {"attacker": "text"}, "id": "123"})])

    def test_page_or_resource_shape_refused(self):
        for bad in ([{}], [{"data": {}}], [{"data": [None]}], [{"errors": [],
                   "data": []}]):
            with self.subTest(shape=str(type(bad))):
                self.refused(bad)

    def test_empty_and_excessive_pages_are_refused(self):
        self.refused([])
        self.refused([page()] * (MAX_PAGES + 1))

    def test_oversized_page_is_refused(self):
        self.refused([page(*(song(str(i + 1)) for i in range(MAX_PAGE_ITEMS + 1)))])

    def test_lazy_unbounded_iterable_not_accepted(self):
        self.refused(iter([page(song())]))

    def test_last_next_is_opaque_indicator_not_a_fetch(self):
        private_like_cursor = "/v1/me/recent/played/tracks?offset=secret"
        report = assess_recent_track_pages([page(song(), next_value=private_like_cursor)])
        self.assertTrue(report.last_page_advertised_next)
        self.assertFalse(report.complete_history_proven)
        self.assertNotIn("secret", repr(report))

    def test_invalid_next_refused_without_echo(self):
        self.refused([{"data": [song()], "next": {"hidden": "private"}}])
        self.refused([{"data": [song()], "next": "x" * 2049}])

    def test_response_titles_artwork_and_any_extra_attribute_never_returned(self):
        secret = "SECRET-FICTIONAL-LABEL-XYZ"
        report = assess_recent_track_pages([page(song(
            "123", name=secret, artistName=secret,
            artwork={"url": "https://invalid.example/" + secret},
            playDuration=1000, endReason="SKIPPED", location=secret,
        ))])
        self.assertNotIn(secret, repr(report))
        self.assertNotIn("123", repr(report))
        self.assertEqual(report.verified_play_sessions, 0)
        self.assertFalse(report.taste_updates_eligible)

    def test_input_never_mutated(self):
        pages = [page(song(), next_value="opaque-next")]
        before = copy.deepcopy(pages)
        assess_recent_track_pages(pages)
        self.assertEqual(pages, before)

    def test_immutable_anonymous_result(self):
        report = assess_recent_track_pages([page(song())])
        self.assertIn("aggregate-only", repr(report))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            report.pages_examined = 99

    def test_import_never_calls_network_sqlite_or_homehub_app(self):
        script = """
import socket, sqlite3
from unittest.mock import patch
def blocked(*a, **k):
    raise AssertionError('effect attempted')
with patch.object(socket, 'socket', blocked), patch.object(sqlite3, 'connect', blocked):
    import backend.services.apple_music_musickit_recent_feasibility as module
    assert module.assess_recent_track_pages([{'data': []}]).verified_play_sessions == 0
"""
        repo_root = Path(__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, "-B", "-c", script],
                              cwd=repo_root, capture_output=True, text=True,
                              timeout=20, check=False)
        self.assertEqual(proc.returncode, 0,
                         msg="Synthetic import-effect test failed")


if __name__ == "__main__":
    unittest.main()