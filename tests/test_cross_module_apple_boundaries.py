"""Synthetic cross-module #431 acceptance; target files verified byte-identical to master.

No production data, network, HomeHub DB, CSV or device operations.
"""
from __future__ import annotations

import ast
import importlib.util
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.apple_music_artist_familiarity_preview import (
    DailyArtistObservation, preview_artist_label_days,
)
from backend.services.apple_music_taste_preview import (
    ApplePreviewEvent, preview_apple_taste,
)
from backend.services.apple_music_proof_reconciliation import (
    CatalogRecord, HistoricalTrack, Interval, CoverageReceipt,
    assess_catalog_identity, assess_sonos_action_log, assess_sonos_overlap,
)

UTC = timezone.utc
TIME = datetime(2026, 2, 4, 12, tzinfo=UTC)


def event(**changes):
    value = ApplePreviewEvent(
        event_id="SYNTHETIC-EVENT-A",
        session_key="SYNTHETIC-SESSION-A",
        recording_key="SYNTHETIC-RECORDING-A",
        ended_at=TIME,
        play_duration_ms=210_000,
        media_duration_ms=220_000,
        end_reason="NATURAL_END_OF_TRACK",
    )
    return replace(value, **changes)


def test_repeated_label_day_exposure_does_not_produce_taste_evidence():
    rows = [
        DailyArtistObservation(
            description="Imaginary Artist - Imaginary Track",
            day=date(2026, 1, n), play_count=75, duration_ms=200_000,
        )
        for n in range(1, 20)
    ]
    aggregate = preview_artist_label_days(rows)
    assert aggregate["artist_label_day_histogram"]["10_plus_days"] == 1
    assert aggregate["counts"]["candidate_artist_label_days"] == 19
    # The model requires separately justified recording, session and overlap.
    preview = preview_apple_taste([event(
        track_proof="title_and_date",
        session_proof="daily_title_join",
        cross_source_proof="unknown",
    )])
    assert preview["counts"]["abstain_unverified_recording"] == 1
    assert not any(name in repr(aggregate) + repr(preview) for name in (
        "Imaginary Artist", "Imaginary Track", "SYNTHETIC-RECORDING-A",
    ))
    assert "positive_weight" not in repr(preview)
    assert "preference_weight" not in repr(aggregate)


@pytest.mark.parametrize("source", [
    "provider_id", "title_and_date", "unverified",
])
def test_unverified_recording_proof_cannot_escape_gate(source):
    result = preview_apple_taste([event(
        track_proof=source, session_proof="independent_playback_session",
        cross_source_proof="no_overlap_verified",
    )])
    assert result["counts"]["abstain_unverified_recording"] == 1


def test_verified_catalog_candidate_not_listening_session_proof():
    history = HistoricalTrack(
        catalog_id="SYNTHETIC-RECORDING-A",
        title="Imaginary Track", artist="Imaginary Artist",
        album="Imaginary Album", duration_ms=220_000,
        id_origin="independent_catalog_lookup",
    )
    catalog = CatalogRecord(
        catalog_id="SYNTHETIC-RECORDING-A",
        title="Imaginary Track", artist="Imaginary Artist",
        album="Imaginary Album", duration_ms=220_000,
        source="apple_catalog_verified",
    )
    assert assess_catalog_identity(history, [catalog]) == (
        "corroborated_catalog_candidate_only"
    )
    preview = preview_apple_taste([event(
        track_proof="catalog_exact",
        session_proof="apple_event_id",
        cross_source_proof="no_overlap_verified",
    )])
    assert preview["counts"]["abstain_unverified_session"] == 1


def test_empty_sonos_action_log_cannot_establish_negative_overlap():
    apple_interval = Interval(TIME, TIME.replace(minute=4))
    overlap_status = assess_sonos_action_log(apple_interval, [])
    assert overlap_status == "unknown_action_log_cannot_prove_nonoverlap"
    result = preview_apple_taste([event(
        track_proof="catalog_exact",
        session_proof="independent_playback_session",
        cross_source_proof="unknown",
    )])
    assert result["counts"]["abstain_cross_source_overlap_unknown"] == 1


def test_continuous_coverage_claim_is_still_preview_not_weight():
    apple = Interval(TIME, TIME.replace(minute=4))
    coverage = CoverageReceipt(
        interval=Interval(TIME.replace(minute=0), TIME.replace(minute=9)),
        source="verified_continuous_sonos_capture",
        complete=True,
    )
    # The 2-minute clock skew means this coverage is still insufficient.
    assert assess_sonos_overlap(apple, [], [coverage]) == (
        "unknown_incomplete_sonos_coverage"
    )
    full = CoverageReceipt(
        interval=Interval(TIME.replace(minute=0).replace(hour=11),
                          TIME.replace(minute=9)),
        source="verified_continuous_sonos_capture",
        complete=True,
    )
    assert assess_sonos_overlap(apple, [], [full]) == (
        "no_overlap_with_complete_telemetry"
    )
    result = preview_apple_taste([event(
        track_proof="catalog_exact",
        session_proof="independent_playback_session",
        cross_source_proof="no_overlap_verified",
    )])
    assert result["counts"]["preview_completion_only"] == 1
    assert "positive_weight" not in repr(result)
    assert "trust_eligible" not in repr(result)


def test_two_event_ids_with_one_proven_session_only_preview_once():
    first = event(
        track_proof="catalog_exact",
        session_proof="independent_playback_session",
        cross_source_proof="no_overlap_verified",
    )
    other = replace(first, event_id="SYNTHETIC-EVENT-B")
    preview = preview_apple_taste([first, other])
    assert preview["counts"]["preview_completion_only"] == 1
    assert preview["counts"]["duplicate_session_rows"] == 1
    assert "SYNTHETIC-EVENT" not in repr(preview)


def test_no_apple_imports_in_canonical_taste_or_actuation():
    spec = importlib.util.find_spec("backend.services.music_taste")
    assert spec is not None and spec.origin is not None
    source = Path(spec.origin)
    tree = ast.parse(source.read_text(encoding="utf-8"))
    all_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            all_imports.update(name.name for name in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            all_imports.add(node.module)
    assert not any("apple_music" in name for name in all_imports)
    assert not any("apple_music" in name for name in ast.unparse(tree).split())


def test_event_representation_should_not_reveal_personal_identifiers():
    value = event(
        event_id="PRIVATE_EVENT_123",
        session_key="PRIVATE_SESSION_456",
        recording_key="PRIVATE_RECORDING_789",
        end_reason="PRIVATE_END_REASON",
    )
    for encoded in (repr(value), str(value)):
        assert "PRIVATE_" not in encoded
        assert "2026" not in encoded
        assert "redacted" in encoded.lower()


def test_daily_observation_repr_and_str_do_not_echo_artist_or_calendar_day():
    value = DailyArtistObservation(
        description="PRIVATE_ARTIST - PRIVATE_TRACK",
        day=date(2026, 1, 23),
        play_count=9,
        duration_ms=145_000,
        source="PRIVATE_EXPORT_SOURCE",
    )
    for encoded in (repr(value), str(value)):
        assert "PRIVATE_" not in encoded
        assert "2026" not in encoded
        assert "145000" not in encoded
        assert "redacted" in encoded.lower()
