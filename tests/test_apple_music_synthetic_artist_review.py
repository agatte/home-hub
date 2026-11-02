"""#431 portable, synthetic-only review fixture tests. No personal Apple data."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts import apple_music_synthetic_artist_review as ui
from scripts import apple_music_synthetic_fixture_preview as fixture


def test_merged_aggregate_preview_accepts_only_fictional_observations():
    summary = fixture.build_synthetic_preview()
    assert summary.preview_format == "apple_artist_label_day_shadow_v1"
    assert summary.artist_label_days == 20
    assert summary.provisional_labels == 5
    assert summary.excluded_ambiguous_rows == 2
    assert dict(summary.histogram) == {
        "1_day": 2, "2_to_3_days": 1, "4_to_9_days": 1, "10_plus_days": 1,
    }
    assert summary.fictional_labels == tuple(
        (label, fixture._band(days)) for label, days in fixture.FIXTURES
    )
    assert "Imaginary Aurora" not in repr(summary)
    assert all(label in dict(fixture.FIXTURES) for label, _ in summary.fictional_labels)


def test_no_implicit_demo_session_or_arbitrary_candidates():
    with pytest.raises(ValueError, match="Explicit synthetic demo"):
        ui.LocalArtistReviewDemo()
    with pytest.raises(ValueError):
        ui.LocalArtistReviewDemo(demo=1)
    with pytest.raises(TypeError):
        ui.LocalArtistReviewDemo(demo=True, candidates=["private"])


@pytest.mark.parametrize("decision", ui.DECISIONS)
def test_ephemeral_review_action_only(decision):
    session = ui.LocalArtistReviewDemo(demo=True)
    session.decide(0, decision)
    assert session.rows()[0][-1] == decision
    assert ui.LocalArtistReviewDemo(demo=True).rows()[0][-1] == "Unreviewed"
    session.discard()
    assert session.rows() == ()
    assert session.summary is None


@pytest.mark.parametrize("index", [-1, 9, True, 1.0, None, "0"])
def test_unsupported_selection_abstains(index):
    session = ui.LocalArtistReviewDemo(demo=True)
    with pytest.raises(ValueError, match="Invalid demo selection"):
        session.decide(index, "Reject label")


@pytest.mark.parametrize("bad", ["Verified", "Favorite", "Like", "Playback", "", None])
def test_review_cannot_promote_identity_preference_or_proof(bad):
    session = ui.LocalArtistReviewDemo(demo=True)
    with pytest.raises(ValueError, match="Invalid demo review action"):
        session.decide(0, bad)
    assert session.rows()[0][-1] == "Unreviewed"


def test_reset_and_discard_prevents_reuse():
    session = ui.LocalArtistReviewDemo(demo=True)
    session.decide(1, "Reject label")
    session.decide(1, "Unreviewed")
    assert session.rows()[1][-1] == "Unreviewed"
    session.discard()
    session.discard()
    assert session.discarded
    with pytest.raises(ValueError, match="already discarded"):
        session.decide(1, "Unreviewed")


def test_provisional_labels_only_are_not_canonical_identity():
    rows = ui.LocalArtistReviewDemo(demo=True).rows()
    assert len(rows) == 5
    assert {row[3] for row in rows} == {ui.SOURCE}
    assert {row[4] for row in rows} == {"Unreviewed"}
    assert all(row[2] in ui.BANDS for row in rows)
    assert len({row[1] for row in rows}) == 5
    assert "Apple" not in repr(ui.DEMO_CANDIDATES[0])


@pytest.mark.parametrize("changed", [
    {"counts": {"candidate_artist_label_days": 999}},
    {"format": "not_approved"},
    {"artist_label_day_histogram": {"1_day": 999}},
])
def test_unexpected_engine_result_fails_closed(monkeypatch, changed):
    canonical = fixture.preview_artist_label_days
    def changed_engine(observations):
        report = canonical(observations)
        report.update(changed)
        if "counts" in changed:
            report["counts"].update(changed["counts"])
        return report
    monkeypatch.setattr(fixture, "preview_artist_label_days", changed_engine)
    with pytest.raises(fixture.SyntheticPreviewRejected,
                       match="Synthetic preview invariants failed"):
        fixture.build_synthetic_preview()


def test_invented_extra_private_fields_are_not_returned(monkeypatch):
    original = fixture.preview_artist_label_days
    private = "SYNTHETIC_ONLY_NEVER_ECHO"
    def augmented(observations):
        report = original(observations)
        report["private_artists"] = [private]
        report["counts"]["private_label"] = private
        report["warnings"].append(private)
        return report
    monkeypatch.setattr(fixture, "preview_artist_label_days", augmented)
    summary = fixture.build_synthetic_preview()
    assert private not in repr(summary)
    assert private not in str(summary)
    assert private not in str(summary.fictional_labels)


def test_only_standard_repo_module_import_no_source_paths_or_io():
    scripts = Path(ui.__file__).parent
    source = (scripts / "apple_music_synthetic_fixture_preview.py").read_text(
        encoding="utf-8"
    )
    ui_source = Path(ui.__file__).read_text(encoding="utf-8")
    syntax = ast.parse(source)
    imports = set()
    for node in ast.walk(syntax):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    assert imports <= {
        "__future__", "dataclasses", "datetime",
        "backend.services.apple_music_artist_familiarity_preview",
    }
    for banned in (
        "filedialog", "argparse", "tkinter", "tempfile", "Path(",
        "importlib", "exec(", "compile(", "socket", "sqlite",
        "subprocess", "open(", "read_bytes", "read_text",
        "requests", "Sonos", "MusicTasteSnapshot",
    ):
        assert banned not in source
    for banned in ("filedialog", "askopenfilename", "sqlite", "SonosService"):
        assert banned not in ui_source
    assert "from scripts.apple_music_synthetic_fixture_preview" in ui_source


def test_cli_with_no_demo_prints_help_without_launch(monkeypatch, capsys):
    monkeypatch.setattr(ui, "create_demo_window",
                        lambda: pytest.fail("UI launched without --demo"))
    assert ui.main([]) == 0
    assert "--demo" in capsys.readouterr().out


def test_cli_rejects_private_file_arguments_without_launch(monkeypatch):
    monkeypatch.setattr(ui, "create_demo_window",
                        lambda: pytest.fail("UI launched with unauthorized input"))
    with pytest.raises(SystemExit) as error:
        ui.main(["--demo", "--csv", "never-open.csv"])
    assert error.value.code == 2


def test_tk_discard_clears_display_and_in_memory_session():
    pytest.importorskip("tkinter")  # CI Python may not include optional Tk
    try:
        from tkinter import TclError
        root, session, table, close = ui.create_demo_window()
    except TclError:
        pytest.skip("Tk display unavailable")
    try:
        root.withdraw()
        assert len(table.get_children()) == 5
        footer = root.nametowidget(".safety_footer")
        assert "Selections vanish" in footer.cget("text")
        assert footer.pack_info()["side"] == "bottom"
        close()
        assert session.discarded
        assert session.rows() == ()
    finally:
        if not session.discarded:
            close()


def test_failed_aggregate_cannot_open_a_window(monkeypatch):
    tk = pytest.importorskip("tkinter")

    def fail_session(*args, **kwargs):
        raise fixture.SyntheticPreviewRejected("Synthetic preview invariants failed")

    monkeypatch.setattr(ui, "LocalArtistReviewDemo", fail_session)
    monkeypatch.setattr(
        tk, "Tk", lambda: pytest.fail("No window before aggregate validation")
    )
    with pytest.raises(fixture.SyntheticPreviewRejected,
                       match="Synthetic preview invariants failed"):
        ui.create_demo_window()


@pytest.mark.parametrize("arguments", [
    ["--csv", "C:\\Private\\MY_SECRET_APPLE_HISTORY.csv"],
    ["--demo", "--file", "/private/artist-history-export.csv"],
    ["--demo", "--unknown=PRIVATE_TRACK_NAME"],
])
def test_unrecognized_arguments_never_echo_source_values(
    arguments, monkeypatch, capsys,
):
    monkeypatch.setattr(
        ui, "create_demo_window",
        lambda: pytest.fail("GUI must never open when arguments are rejected"),
    )
    with pytest.raises(SystemExit) as exc:
        ui.main(arguments)
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Synthetic demo arguments rejected.\n"
