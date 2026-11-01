"""#431 noninterference acceptance tests — invented labels/data only.

No private Apple CSV, Sonos telemetry, live data, network or DB access.
This is local acceptance evidence, not independent security sign-off.
"""
from __future__ import annotations

import ast
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services.apple_music_artist_familiarity_preview import (
    DailyArtistObservation,
    preview_artist_label_days,
)
from backend.services.apple_music_artist_local_audit import analyze_daily_csv
from backend.services.music_taste import build_music_taste_snapshot

ROOT = Path(__file__).resolve().parents[1]
APPLE_MODULES = (
    "apple_music_csv_record_budget.py",
    "apple_music_daily_join_audit.py",
    "apple_music_artist_local_audit.py",
    "apple_music_artist_familiarity_preview.py",
)


def _observation(**kwargs):
    sample = dict(
        description="Synthetic Artist - Sample Song",
        day=date(2026, 10, 1), play_count=42, duration_ms=120_000,
    )
    sample.update(kwargs)
    return DailyArtistObservation(**sample)


_ALLOWED_IMPORTS = frozenset({
    "__future__", "argparse", "collections", "collections.abc",
    "contextlib", "csv", "dataclasses", "datetime", "io", "json",
    "os", "pathlib", "re", "stat", "typing", "unicodedata",
})
_ALLOWED_APPLE_IMPORTS = frozenset({
    "apple_music_artist_familiarity_preview", "apple_music_daily_join_audit",
    "apple_music_csv_record_budget",
})


def _unsafe_imports(source: str) -> set[str]:
    """Find imports outside the intentionally tiny offline-reader graph.

    Both relative and absolute import forms are inspected; new imports
    require a conscious review instead of silently bypassing the check.
    """
    unsafe = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
            allowed = _ALLOWED_IMPORTS
        elif isinstance(node, ast.ImportFrom):
            names = [node.module] if node.module else [
                alias.name for alias in node.names
            ]
            allowed = (
                _ALLOWED_APPLE_IMPORTS if node.level else
                _ALLOWED_IMPORTS | _ALLOWED_APPLE_IMPORTS
            )
        else:
            continue
        for name in names:
            if name not in allowed:
                unsafe.add(str(name))
    return unsafe


def test_reader_has_no_backend_model_or_effectful_service_imports():
    for file_name in APPLE_MODULES:
        code = (ROOT / "backend" / "services" / file_name).read_text(
            encoding="utf-8",
        )
        assert _unsafe_imports(code) == set(), file_name


@pytest.mark.parametrize("source", [
    "from .music_taste import build_music_taste_snapshot",
    "from .. import database",
    "from backend.models import MusicArtist",
    "import socket",
    "import requests",
    "from . import music_taste",
])
def test_static_import_guard_flags_live_service_or_network_imports(source):
    assert _unsafe_imports(source)


def test_current_canonical_taste_has_no_apple_history_dependency():
    source = (ROOT / "backend" / "services" / "music_taste.py").read_text(
        encoding="utf-8",
    )
    assert "apple_music_artist_local_audit" not in source
    assert "apple_music_artist_familiarity_preview" not in source
    assert "apple_daily_tracks" not in source


def test_apple_aggregate_is_not_a_music_taste_snapshot_or_trust_upgrade():
    exposure = preview_artist_label_days([
        _observation(day=date(2026, 10, n)) for n in range(1, 13)
    ])
    assert exposure["artist_label_day_histogram"]["10_plus_days"] == 1

    # There is deliberately no adapter from Apple exposure to these inputs.
    snapshot = build_music_taste_snapshot(
        artists=[], recommendations=[], playback_events=[],
        explicit_feedback=[], generated_at=datetime(2026, 10, 31, tzinfo=timezone.utc),
    )
    assert snapshot.artists == {}
    assert snapshot.tracks == {}
    assert snapshot.favorites == {}
    unknown = snapshot.classify_candidate(
        SimpleNamespace(
            title="Imaginary Artist",
            media_type="artist",
            metadata={"artist_name": "Synthetic Artist"},
        )
    )
    assert unknown.classification == "exploratory"
    assert unknown.familiarity == 0
    assert unknown.preference == 0
    assert unknown.positive_weight == unknown.negative_weight == 0


def test_duplicate_and_conflicting_artist_days_have_stable_histogram():
    rows = [
        _observation(),
        _observation(description="Another Artist - Other Song"),
        _observation(day=date(2026, 10, 2)),
        _observation(day=date(2026, 10, 2),
                     description="Third Artist - Sample Song"),
    ]
    result = preview_artist_label_days(rows)
    shuffled = preview_artist_label_days(list(reversed(rows)) + rows)
    assert result["artist_label_day_histogram"] == shuffled[
        "artist_label_day_histogram"
    ]
    assert result["counts"]["candidate_artist_label_days"] == 2
    assert result["counts"]["abstain_ambiguous_or_conflicting_rows"] == 2


def test_local_audit_opens_only_explicit_input_and_leaves_no_output(
    tmp_path, monkeypatch,
):
    import csv
    import socket

    secret = "DONT_LOG_MY_PRIVATE_SOURCE_VALUE"
    source = tmp_path / "invented_daily.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow([
            "Track Description", "Date Played", "Play Count",
            "Play Duration Milliseconds", "Private Location",
        ])
        writer.writerow([
            "Synthetic Artist - Sample Song", "20261001", "42", "120000", secret,
        ])
    paths_before = {path.name for path in tmp_path.iterdir()}
    original_open = Path.open

    def guarded_open(self, mode="r", *args, **kwargs):
        assert self == source
        assert mode == "rb"
        return original_open(self, mode, *args, **kwargs)

    def network_denied(*_args, **_kwargs):
        raise AssertionError("offline Apple audit attempted a network call")

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(socket, "create_connection", network_denied)
    monkeypatch.setattr(socket.socket, "connect", network_denied)
    report = analyze_daily_csv(source)
    assert report["counts"]["candidate_artist_label_days"] == 1
    assert paths_before == {path.name for path in tmp_path.iterdir()}
    encoded = json.dumps(report)
    assert secret not in encoded
    assert "Synthetic Artist" not in encoded
    assert "Sample Song" not in encoded
    assert str(source) not in encoded


@pytest.mark.parametrize("play_count", [1, 10, 100, 1000])
def test_play_count_is_not_inferred_as_independent_sessions(play_count):
    report = preview_artist_label_days([
        _observation(play_count=play_count),
    ])
    assert report["counts"]["candidate_artist_label_days"] == 1
    assert report["artist_label_day_histogram"]["1_day"] == 1
