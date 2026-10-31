"""#431: synthetic-only independent catalog and Sonos overlap policy tests."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import pytest

from backend.services.apple_music_proof_reconciliation import (
    CatalogRecord, CoverageReceipt, HistoricalTrack, Interval,
    ReconciliationRejected, assess_catalog_identity,
    assess_sonos_action_log, assess_sonos_overlap, summarize_proof_decisions,
)

NOW = datetime(2026, 10, 1, 20, tzinfo=timezone.utc)


def history(**changes):
    return replace(HistoricalTrack(
        catalog_id="SYNTHETIC-TRACK-42", title="Fake Song",
        artist="Imaginary Artist", album="Invented Album",
        duration_ms=200_000, id_origin="independent_catalog_lookup",
    ), **changes)


def catalog(**changes):
    return replace(CatalogRecord(
        catalog_id="SYNTHETIC-TRACK-42", title="Fake Song",
        artist="Imaginary Artist", album="Invented Album",
        duration_ms=200_000, source="apple_catalog_verified",
    ), **changes)


def interval(start_min=0, end_min=3):
    return Interval(NOW + timedelta(minutes=start_min), NOW + timedelta(minutes=end_min))


def receipt(start=-3, end=7, *, complete=True, source="verified_continuous_sonos_capture"):
    return CoverageReceipt(interval(start, end), source=source, complete=complete)


def test_exact_independent_id_and_full_metadata_is_only_candidate():
    result = assess_catalog_identity(history(), [catalog()])
    assert result == "corroborated_catalog_candidate_only"
    assert "Fake Song" not in result
    assert "SYNTHETIC-TRACK" not in result


@pytest.mark.parametrize(("change", "status"), [
    ({"catalog_id": ""}, "missing_independent_catalog_id"),
    ({"catalog_id": "other"}, "catalog_id_not_found"),
    ({"title": "Another Fake Song"}, "catalog_metadata_mismatch"),
    ({"artist": "Different Artist"}, "catalog_metadata_mismatch"),
    ({"album": "Different Album"}, "catalog_metadata_mismatch"),
    ({"duration_ms": 200_002}, "corroborated_catalog_candidate_only"),
    ({"duration_ms": 203_000}, "catalog_metadata_mismatch"),
    ({"duration_ms": None}, "catalog_metadata_mismatch"),
    ({"catalog_id": "synthetic-track-42"}, "catalog_id_not_found"),
])
def test_identity_fail_closed_and_case_sensitive_ids(change, status):
    assert assess_catalog_identity(history(**change), [catalog()]) == status


def test_missing_verified_catalog_source_never_passes():
    assert assess_catalog_identity(history(), [catalog(source="untrusted")]) == (
        "catalog_source_unverified"
    )


def test_conflicting_duplicate_catalog_id_abstains():
    refs = [catalog(), catalog(artist="Another Imaginary Artist")]
    assert assess_catalog_identity(history(), refs) == "conflicting_catalog_metadata"


def test_exact_duplicate_catalog_reference_is_not_a_conflict():
    assert assess_catalog_identity(history(), [catalog(), catalog()]) == (
        "corroborated_catalog_candidate_only"
    )


def test_metadata_only_title_artist_without_independent_catalog_id_abstains():
    assert assess_catalog_identity(history(catalog_id=""), [catalog()]) == (
        "missing_independent_catalog_id"
    )


def test_no_sonos_action_does_not_prove_nonoverlap():
    assert assess_sonos_action_log(interval(), []) == (
        "unknown_action_log_cannot_prove_nonoverlap"
    )


@dataclass(frozen=True)
class Action:
    timestamp: datetime
    event_type: str


def test_point_action_near_apple_window_is_possible_not_confirmed_overlap():
    assert assess_sonos_action_log(
        interval(), [Action(NOW + timedelta(minutes=4), "auto_play")]
    ) == "possible_overlap_from_sonos_action"


def test_volume_only_is_not_a_proven_play_and_not_a_negative():
    assert assess_sonos_action_log(
        interval(), [Action(NOW + timedelta(minutes=1), "volume")]
    ) == "unknown_action_log_cannot_prove_nonoverlap"


def test_sonos_verified_window_blocks_apple_session():
    result = assess_sonos_overlap(
        interval(), [interval(2, 8)], [receipt()]
    )
    assert result == "possible_cross_source_overlap"


def test_clock_skew_expands_possible_overlap():
    assert assess_sonos_overlap(
        interval(), [interval(5, 6)], [receipt()]
    ) == "possible_cross_source_overlap"


def test_empty_sonos_windows_without_complete_capture_never_prove_absence():
    assert assess_sonos_overlap(interval(), [], []) == (
        "unknown_incomplete_sonos_coverage"
    )



def test_only_complete_continuous_sonos_coverage_can_assert_no_overlap():
    assert assess_sonos_overlap(
        interval(), [], [receipt()]
    ) == "no_overlap_with_complete_telemetry"


@pytest.mark.parametrize(("complete", "source"), [
    (False, "verified_continuous_sonos_capture"),
    (True, "sonos_playback_events"),
    (True, "unverified"),
])
def test_action_log_or_incomplete_receipt_cannot_assert_negative(complete, source):
    assert assess_sonos_overlap(
        interval(), [], [receipt(complete=complete, source=source)]
    ) == "unknown_incomplete_sonos_coverage"


def test_coverage_gap_and_boundary_both_fail_closed():
    assert assess_sonos_overlap(
        interval(), [], [receipt(-3, 1), receipt(2, 7)]
    ) == "unknown_incomplete_sonos_coverage"
    assert assess_sonos_overlap(
        interval(), [], [receipt(0, 7)]
    ) == "unknown_incomplete_sonos_coverage"


def test_contiguous_coverage_intervals_can_join_without_gaps():
    assert assess_sonos_overlap(
        interval(), [], [receipt(-3, 1), receipt(1, 7)]
    ) == "no_overlap_with_complete_telemetry"


def test_naive_or_invalid_apple_time_fails_closed():
    apple = Interval(datetime(2026, 10, 1, 20), datetime(2026, 10, 1, 21))
    assert assess_sonos_overlap(apple, [], [receipt()]) == (
        "unknown_invalid_apple_session"
    )
    assert assess_sonos_action_log(apple, []) == "unknown_invalid_apple_session"


def test_invalid_sonos_interval_does_not_silently_disappear():
    invalid = Interval(NOW + timedelta(hours=3), NOW)
    assert assess_sonos_overlap(interval(), [invalid], [receipt()]) == (
        "unknown_invalid_sonos_interval"
    )


def test_missing_action_timestamp_does_not_prove_negative():
    assert assess_sonos_action_log(
        interval(), [Action(datetime(2026, 10, 1), "play")]
    ) == "unknown_invalid_action_timestamp"


def test_source_value_never_leaks_through_report():
    statuses = [
        assess_catalog_identity(history(), [catalog()]),
        assess_catalog_identity(history(artist="PRIVATE_PERSON"), [catalog()]),
    ]
    overlap = [
        assess_sonos_action_log(interval(), []),
        assess_sonos_overlap(interval(), [interval(2, 3)], [receipt()]),
    ]
    report = summarize_proof_decisions(statuses, overlap)
    assert report["counts"]["catalog_corroborated_catalog_candidate_only"] == 1
    assert report["counts"]["catalog_catalog_metadata_mismatch"] == 1
    assert report["counts"]["overlap_possible_cross_source_overlap"] == 1
    assert "PRIVATE" not in repr(report)
    assert "SYNTHETIC-TRACK" not in repr(report)


def test_unsupported_report_status_rejected():
    with pytest.raises(ReconciliationRejected, match="Unsupported catalog decision"):
        summarize_proof_decisions(["PRIVATE_SOURCE_TEXT"], [])


def test_aggregate_has_no_preference_weights_or_homehub_side_effects():
    report = summarize_proof_decisions(
        ["corroborated_catalog_candidate_only"], ["unknown_incomplete_sonos_coverage"]
    )
    assert "preference" not in report["counts"]
    assert "catalog_corroborated_catalog_candidate_only" in report["counts"]


def test_resource_caps_are_enforced_without_leaks(monkeypatch):
    import backend.services.apple_music_proof_reconciliation as reconciliation

    monkeypatch.setattr(reconciliation, "MAX_RECORDS", 1)
    with pytest.raises(ReconciliationRejected, match="reference limit"):
        assess_catalog_identity(history(), [catalog(), catalog()])
    with pytest.raises(ReconciliationRejected, match="interval limit"):
        assess_sonos_overlap(interval(), [interval(6, 7), interval(7, 8)], [])


@pytest.mark.parametrize("origin", [
    "apple_play_activity_provider_id", "title_and_date", "unverified",
])
def test_opaque_provider_ids_cannot_masquerade_as_catalog_proof(origin):
    assert assess_catalog_identity(
        history(id_origin=origin), [catalog()]
    ) == "catalog_id_origin_unverified"


def test_without_independent_source_assertion_defaults_to_unknown():
    raw = HistoricalTrack(
        catalog_id="SYNTHETIC-TRACK-42", title="Fake Song",
        artist="Imaginary Artist", album="Invented Album",
        duration_ms=200_000,
    )
    assert assess_catalog_identity(raw, [catalog()]) == "catalog_id_origin_unverified"
