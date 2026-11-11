from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from itertools import permutations
from types import SimpleNamespace
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend.services.lastfm_taste_preview import (
    CAP, CLOCK, MAX_RECORDS, SOURCE, Observation, demo, overlay, rankings,
    synthetic_baseline, synthetic_observations,
)


def match(snapshot, artist="Copper Kites", title="Paper Comet", kind="track"):
    return snapshot.classify_candidate(SimpleNamespace(
        media_type=kind, title=title,
        metadata={"artist_name": artist, "track_name": title},
    ))


def test_empty_identical():
    base = synthetic_baseline()
    result = overlay(base, [])
    assert result.snapshot == base
    assert asyncio.run(rankings(base)) == asyncio.run(rankings(result.snapshot))


def test_repeat_diminishes_and_caps():
    base = synthetic_baseline()
    values = []
    for n in (1, 2, 5, 20):
        rows = [Observation("Copper Kites", "Paper Comet", CLOCK - timedelta(seconds=i))
                for i in range(n)]
        snap = overlay(base, rows).snapshot
        values.append(match(snap).familiarity)
        assert snap.artists["copper kites"].depth == 1
        assert match(snap).classification != "proven"
        assert match(snap).positive_weight == match(snap).negative_weight == 0
        assert match(snap).preference == 0
    assert values[0] < values[1] < values[2] == values[3] == CAP
    assert values[2] - values[1] < 4 * (values[1] - values[0])


def test_permutation_duplicates_and_reapplication():
    base = synthetic_baseline()
    rows = [Observation("Copper Kites", "Paper Comet", CLOCK),
            Observation("Copper Kites", "Glass Meadow", CLOCK)]
    expected = overlay(base, rows + rows)
    for order in permutations(rows + rows):
        result = overlay(base, order)
        assert result == expected
        assert overlay(result.snapshot, order).snapshot == result.snapshot
    assert expected.snapshot.artists["copper kites"].depth == 2
    assert len(expected.snapshot.tracks) == 2
    assert expected.diagnostics["counts"]["duplicate"] == 2


@pytest.mark.parametrize("row,reason", [
    (None, "malformed"),
    (Observation("", "Paper Comet", CLOCK), "missing_exact_identity"),
    (Observation("Copper Kites", "", CLOCK), "missing_exact_identity"),
    (Observation("Copper Kites", "Paper Comet"), "missing_or_malformed_date"),
    (Observation("Copper Kites", "Paper Comet", CLOCK.replace(tzinfo=None)),
     "missing_or_malformed_date"),
    (Observation("Copper Kites", "Paper Comet", CLOCK + timedelta(seconds=1)), "future"),
    (Observation("Copper Kites", "Paper Comet", CLOCK - timedelta(days=8)), "stale"),
    (Observation("Copper Kites", "Paper Comet", CLOCK, True), "now_playing"),
])
def test_invalid_abstains(row, reason):
    base = synthetic_baseline()
    result = overlay(base, [row])
    assert result.snapshot == base
    assert result.diagnostics["counts"] == {reason: 1}


def test_overlap_suppresses_even_conflicting_duplicate():
    base = synthetic_baseline()
    row = Observation("Copper Kites", "Paper Comet", CLOCK)
    overlap = replace(row, sonos_overlap_confirmed=True)
    for rows in ([row, overlap], [overlap, row]):
        result = overlay(base, rows)
        assert result.snapshot == base
        assert result.diagnostics["tracks"][0]["suppressed_count"] == 1
    assert overlay(base, [row]).snapshot != base  # no name/time overlap guessing


def test_exact_identity_unseen_track_and_title_only_abstain():
    snap = overlay(synthetic_baseline(), synthetic_observations()).snapshot
    assert match(snap).classification == "familiar"
    assert match(snap, title="Unwritten Cloud").familiarity == 0
    assert match(snap, artist="").familiarity == 0
    assert match(snap, artist="Marble Otters").familiarity == 0.45
    assert all("|" in key for key in snap.tracks)


def test_preserves_canonical_objects_preferences_context_and_sonos():
    base = synthetic_baseline()
    old = base.artists["velvet abacus"]
    base.tracks["velvet abacus|paper comet"] = replace(
        old, kind="track", identity="velvet abacus|paper comet",
        sources=("sonos_playback",), contexts={"gaming": "fixture_context"},
    )
    before = deepcopy(base)
    snap = overlay(base, synthetic_observations()).snapshot
    assert base == before
    assert snap.artists["velvet abacus"] == old
    assert snap.tracks["velvet abacus|paper comet"] == base.tracks["velvet abacus|paper comet"]
    for key, entity in base.artists.items():
        new = snap.artists[key]
        for field in ("preference", "positive_weight", "negative_weight", "sources",
                      "last_observed_at", "contexts"):
            assert getattr(new, field) == getattr(entity, field)
    snap.genre_distribution["fiction"] = 1
    assert base.genre_distribution == {}


def test_passive_track_overlay_cannot_dilute_existing_explicit_artist_judgment():
    baseline = synthetic_baseline()
    enriched = overlay(baseline, synthetic_observations())
    before = {item["artist"]: item for item in asyncio.run(rankings(baseline))}
    after = {item["artist"]: item for item in asyncio.run(rankings(enriched.snapshot))}
    for field in ("score", "preference", "depth", "novelty", "classification", "reasons"):
        assert before["Velvet Abacus"][field] == after["Velvet Abacus"][field]
    assert baseline.artists["tin orchard"] == enriched.snapshot.artists["tin orchard"]
    assert "tin orchard|paper comet" not in enriched.snapshot.tracks
    track = next(item for item in enriched.diagnostics["tracks"]
                 if item["artist"] == "velvet abacus")
    assert "canonical_artist_feedback_guard" in track["reason_codes"]


def test_enriched_neutral_evidence_retains_old_source_and_marks_synthetic_origin():
    baseline = synthetic_baseline()
    neutral = replace(
        baseline.artists["velvet abacus"], identity="marble otters",
        familiarity=0.2, preference=0.0, positive_weight=0.0,
        negative_weight=0.0, depth=0, sources=("existing_neutral",), contexts={},
    )
    baseline.artists["marble otters"] = neutral
    baseline.tracks["marble otters|paper comet"] = replace(
        neutral, kind="track", identity="Paper Comet",
    )
    enriched = overlay(baseline, [
        Observation("Marble Otters", "Paper Comet", CLOCK),
    ]).snapshot
    for item in (
        enriched.artists["marble otters"],
        enriched.tracks["marble otters|paper comet"],
    ):
        assert item.sources == ("existing_neutral", SOURCE)
        assert item.preference == item.positive_weight == item.negative_weight == 0
        assert item.familiarity > 0.2
    assert baseline.artists["marble otters"].sources == ("existing_neutral",)
    assert baseline.tracks["marble otters|paper comet"].sources == ("existing_neutral",)


def test_actual_rank_flip_rejection_and_transparency():
    result = asyncio.run(demo())
    assert [r["artist"] for r in result["before"]] == [
        "Velvet Abacus", "Copper Kites", "Marble Otters"]
    assert [r["artist"] for r in result["after"]] == [
        "Copper Kites", "Velvet Abacus", "Marble Otters"]
    before, after = result["before"][1], result["after"][0]
    assert before["preference"] == after["preference"] == 0
    assert before["novelty"] == 1 and after["novelty"] == 0
    assert before["depth"] == 0 and after["depth"] == 2
    assert after["score"] - before["score"] == pytest.approx(0.09)
    assert "artist depth 2" in after["reasons"]
    assert match(overlay(synthetic_baseline(), synthetic_observations()).snapshot,
                 "Tin Orchard", kind="artist").classification == "rejected"
    assert all(t["capability"] == "metadata_only" for r in result["after"] for t in r["tracks"])
    assert not result["evidence"]["apple_identity_verified"]
    assert not result["evidence"]["independent_plays_verified"]


def test_budget_and_clock():
    with pytest.raises(ValueError):
        overlay(synthetic_baseline(), [Observation()] * (MAX_RECORDS + 1))
    with pytest.raises(ValueError):
        overlay(synthetic_baseline(), [], now=CLOCK.replace(tzinfo=None))


async def test_offline_and_cli_deterministic(monkeypatch):
    import socket
    from backend import database

    def forbidden(*args, **kwargs):
        raise AssertionError("offline preview attempted external access")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(database, "async_session", forbidden)
    first = await demo()
    assert await demo() == first
    script = Path(__file__).resolve().parents[1] / "scripts" / "demo_lastfm_taste_preview.py"
    outputs = [subprocess.check_output([sys.executable, "-B", str(script)]) for _ in range(2)]
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0]) == first
    assert "https:" not in outputs[0].decode()
    assert CLOCK.isoformat() not in outputs[0].decode()
