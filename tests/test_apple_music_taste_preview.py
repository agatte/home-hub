"""Entirely invented Apple taste-preview inputs. No private export is used."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import apple_music_taste_preview as preview

AT = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def event(**changes):
    baseline = preview.ApplePreviewEvent(
        event_id="SYNTHETIC-EVENT-A",
        session_key="SYNTHETIC-SESSION-A",
        recording_key="SYNTHETIC-CATALOG-RECORDING-A",
        ended_at=AT,
        play_duration_ms=210_000,
        media_duration_ms=220_000,
        end_reason="NATURAL_END_OF_TRACK",
        track_proof="catalog_exact",
        session_proof="independent_playback_session",
        cross_source_proof="no_overlap_verified",
    )
    return replace(baseline, **changes)


def counts(*events):
    return preview.preview_apple_taste(events)["counts"]


def test_verified_synthetic_completion_is_only_a_candidate():
    result = preview.preview_apple_taste([event()])
    assert result["counts"]["preview_completion_only"] == 1
    assert "preference" not in result["counts"]
    assert "SYNTHETIC" not in repr(result)
    assert all(isinstance(v, int) for v in result["counts"].values())


@pytest.mark.parametrize(("field", "value", "bucket"), [
    ("track_proof", "unverified", "abstain_unverified_recording"),
    ("track_proof", "provider_id", "abstain_unverified_recording"),
    ("track_proof", "title_and_date", "abstain_unverified_recording"),
    ("recording_key", "", "abstain_unverified_recording"),
    ("session_proof", "apple_event_id", "abstain_unverified_session"),
    ("session_proof", "daily_title_join", "abstain_unverified_session"),
    ("cross_source_proof", "unknown", "abstain_cross_source_overlap_unknown"),
    ("cross_source_proof", "possible_overlap", "abstain_cross_source_overlap_unknown"),
    ("source", "sonos", "abstain_unsupported_source_or_event"),
    ("event_type", "PLAY_START", "abstain_unsupported_source_or_event"),
    ("ended_at", None, "abstain_invalid_timestamp"),
    ("play_duration_ms", -1, "abstain_invalid_durations"),
    ("play_duration_ms", float("nan"), "abstain_invalid_durations"),
    ("media_duration_ms", 0, "abstain_invalid_durations"),
])
def test_strict_provenance_and_payload_gates(field, value, bucket):
    assert counts(event(**{field: value}))[bucket] == 1


def test_typical_cross_export_provisional_join_abstains():
    assert counts(event(
        track_proof="title_and_date",
        session_proof="apple_event_id",
        cross_source_proof="unknown",
    ))["abstain_unverified_recording"] == 1


def test_repeated_event_id_is_idempotent():
    result = counts(event(), event())
    assert result["input_rows"] == 2
    assert result["distinct_session_keys_seen"] == 1
    assert result["duplicate_event_id_rows"] == 1
    assert result["preview_completion_only"] == 1


def test_different_ids_same_proven_session_not_two_plays():
    result = counts(event(), event(event_id="SYNTHETIC-EVENT-B"))
    assert result["distinct_session_keys_seen"] == 1
    assert result["duplicate_session_rows"] == 1
    assert result["preview_completion_only"] == 1


def test_conflicting_reasons_same_session_revoke_evidence():
    original = event()
    conflict = event(event_id="SYNTHETIC-EVENT-B", end_reason="TRACK_SKIPPED_FORWARDS")
    for pair in [(original, conflict), (conflict, original)]:
        result = counts(*pair)
        assert result["abstain_conflicting_identity_or_session"] == 1
        assert result.get("preview_completion_only", 0) == 0
        assert result.get("preview_early_skip_only", 0) == 0


def test_conflicting_id_across_sessions_revokes_both():
    original = event()
    second = event(session_key="SYNTHETIC-SESSION-B")
    result = counts(original, second)
    assert result["abstain_conflicting_identity_or_session"] == 2
    assert result["conflicting_event_id_rows"] == 1
    assert result.get("preview_completion_only", 0) == 0



def test_conflicting_recording_id_same_session_revoked():
    first = event()
    other = event(event_id="OTHER-EVENT", recording_key="OTHER-RECORDING")
    result = counts(first, other)
    assert result["abstain_conflicting_identity_or_session"] == 1
    assert result.get("preview_completion_only", 0) == 0


def test_independent_verified_sessions_can_be_repeat_listening():
    first = event()
    second = event(
        event_id="SYNTHETIC-EVENT-B", session_key="SYNTHETIC-SESSION-B",
        ended_at=AT + timedelta(hours=3),
    )
    result = counts(first, second)
    assert result["preview_completion_only"] == 2
    assert result["distinct_session_keys_seen"] == 2


def test_early_skip_is_weak_candidate_only_not_negative_weight():
    result = counts(event(
        end_reason="TRACK_SKIPPED_FORWARDS",
        play_duration_ms=12_000,
    ))
    assert result["preview_early_skip_only"] == 1
    assert "negative_weight" not in repr(result)


def test_late_skip_is_not_early_skip_or_negative_rating():
    result = counts(event(
        end_reason="TRACK_SKIPPED_BACKWARDS", play_duration_ms=190_000,
    ))
    assert result["preview_familiarity_only"] == 1
    assert result.get("preview_early_skip_only", 0) == 0


def test_unexplained_very_short_play_is_neutral():
    result = counts(event(end_reason="OTHER", play_duration_ms=5_000))
    assert result["preview_neutral_no_preference"] == 1


def test_naive_and_out_of_range_timestamps_fail_closed():
    result = counts(event(ended_at=datetime(2026, 1, 1)))
    assert result["abstain_invalid_timestamp"] == 1
    result = counts(event(ended_at=datetime(1999, 1, 1, tzinfo=timezone.utc)))
    assert result["abstain_invalid_timestamp"] == 1


def test_played_exceeds_plausible_duration_fails_closed():
    result = counts(event(play_duration_ms=400_000))
    assert result["abstain_invalid_durations"] == 1


def test_invalid_session_and_event_keys_not_interpreted_as_proof():
    for candidate in (event(event_id=""), event(session_key="")):
        result = counts(candidate)
        assert result["abstain_invalid_input"] == 1
        assert result["distinct_session_keys_seen"] == 0


def test_non_event_input_rejected_without_leak():
    result = preview.preview_apple_taste(["PRIVATE_WRONG_TYPE"])
    assert result["counts"]["abstain_invalid_input"] == 1
    assert "PRIVATE_WRONG_TYPE" not in repr(result)


def test_fixed_input_limit(monkeypatch):
    monkeypatch.setattr(preview, "MAX_INPUT_EVENTS", 2)
    with pytest.raises(preview.PreviewRejected, match="event limit") as error:
        preview.preview_apple_taste([event(), event(), event()])
    assert "SYNTHETIC" not in str(error.value)


def test_no_db_runtime_or_filesystem_imports():
    from pathlib import Path

    path = Path(preview.__file__)
    source = path.read_text(encoding="utf-8")
    for forbidden in (
        "backend.database", "backend.models", "open(", "Path(",
        "requests.", "urllib.", "music_bandit",
    ):
        assert forbidden not in source


def test_real_aggregate_cannot_be_used_as_track_evidence():
    # 36,214 provisional title/date matches are NOT 36,214 verified recordings.
    candidate = event(track_proof="title_and_date", session_proof="daily_title_join")
    result = counts(candidate)
    assert result["abstain_unverified_recording"] == 1
    assert result.get("preview_completion_only", 0) == 0


@pytest.mark.parametrize("reason", [
    "FAILED_TO_LOAD", "SCRUB_BEGIN", "SCRUB_END", "UNRECOGNIZED_END_REASON",
])
def test_unsupported_reason_cannot_manufacture_familiarity(reason):
    result = counts(event(end_reason=reason, play_duration_ms=210_000))
    assert result["abstain_unknown_or_nonplay_end_reason"] == 1
    assert result.get("preview_familiarity_only", 0) == 0


def test_neutral_pause_can_signal_familiarity_but_not_liking():
    result = counts(event(end_reason="PLAYBACK_MANUALLY_PAUSED"))
    assert result["preview_familiarity_only"] == 1
    assert result.get("preview_completion_only", 0) == 0


@pytest.mark.parametrize("field", [
    "recording_key", "track_proof", "session_proof", "cross_source_proof",
    "source", "event_type", "end_reason",
])
def test_oversized_identity_and_provenance_fields_are_not_retained(field):
    result = counts(event(**{field: "PRIVATE_" * 100}))
    assert result["abstain_invalid_input"] == 1
    assert result["distinct_session_keys_seen"] == 0
    assert "PRIVATE_" not in repr(result)
