"""Synthetic PowerShell-only checks of bounded #431 Last.fm API probe.

Never supplies credentials, personal profiles, actual track names or live URLs.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] /
          "scripts" / "Read-LastFmRecent-431.ps1")
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
MARKER = "PRIVATE_SYNTHETIC_TITLE_DO_NOT_DISCLOSE"
USERNAME = "inventeduser431"


def song(uts="1470000000", live=False):
    item = {
        "name": MARKER,
        "artist": {"#text": MARKER},
    }
    if live:
        item["@attr"] = {"nowplaying": "true"}
    else:
        item["date"] = {"uts": uts}
    return item


def payload(*items, user=USERNAME):
    return {"recenttracks": {"@attr": {
        "user": user, "total": "25", "page": "1", "perPage": "50",
    }, "track": list(items)}}


@unittest.skipUnless(sys.platform == "win32" and POWERSHELL,
                     "Windows PowerShell fixture test")
class LastFmProbeTests(unittest.TestCase):

    def run_fixture(self, doc, *, username=USERNAME):
        response = subprocess.run([
            POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(SCRIPT), "-Username", username,
            "-OfflineFixtureStdin",
        ], input=json.dumps(doc, separators=(",", ":")),
           capture_output=True, text=True, timeout=20, check=False)
        self.assertNotIn(MARKER, response.stdout + response.stderr)
        self.assertNotIn(USERNAME, response.stdout + response.stderr)
        self.assertTrue(response.stdout.strip(), "No aggregate JSON produced")
        return response.returncode, json.loads(response.stdout.strip())

    def test_timestamped_and_repeat_detection_is_aggregate_only(self):
        status, result = self.run_fixture(
            payload(song(), song(), song(live=True)))
        self.assertEqual(status, 0)
        self.assertEqual(result["status"], "synthetic_only")
        self.assertEqual(result["items_returned"], 3)
        self.assertEqual(result["timestamped_scrobbles"], 2)
        self.assertEqual(result["currently_playing"], 1)
        self.assertEqual(result["timestamps_with_collisions"], 1)
        self.assertEqual(result["total_scrobbles_reported"], 25)
        self.assertEqual(result["newest_year"], 2016)
        self.assertEqual(result["verified_distinct_play_sessions"], 0)
        self.assertFalse(result["taste_eligible"])
        self.assertEqual(result["has_artist_and_track"], 2)

    def test_empty_is_not_missing_account(self):
        status, result = self.run_fixture(payload())
        self.assertEqual(status, 0)
        self.assertEqual(result["timestamped_scrobbles"], 0)
        self.assertIsNone(result["newest_age_hours"])

    def test_missing_and_invalid_dates_abstain(self):
        no_date = song()
        no_date.pop("date")
        bad_date = song("PRIVATE_MARKER")
        status, result = self.run_fixture(payload(no_date, bad_date))
        self.assertEqual(status, 0)
        self.assertEqual(result["missing_timestamp"], 1)
        self.assertEqual(result["invalid_timestamp"], 1)

    def test_mismatched_account_refused(self):
        status, result = self.run_fixture(payload(song(), user="otheruser"))
        self.assertEqual(status, 2)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["phase"], "parse")

    def test_provider_error_number_only_no_message(self):
        status, result = self.run_fixture({
            "error": 10,
            "message": MARKER,
        })
        self.assertEqual(status, 3)
        self.assertEqual(result, {"status": "api_error", "error_code": 10})

    def test_bad_envelope_fails_closed(self):
        status, result = self.run_fixture({"recenttracks": {"track": []}})
        self.assertEqual(status, 2)
        self.assertEqual(result["status"], "blocked")

    def test_oversized_response_refused_without_echoing(self):
        status, result = self.run_fixture({
            "recenttracks": {"@attr": {"user": USERNAME},
                             "track": []},
            "ignored_secret": MARKER + "x" * 513000,
        })
        self.assertEqual(status, 2)
        self.assertEqual(result["phase"], "response_budget")

    def test_max_page_limit_50(self):
        status, result = self.run_fixture(payload(*([song()] * 52)))
        self.assertEqual(status, 2)
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
