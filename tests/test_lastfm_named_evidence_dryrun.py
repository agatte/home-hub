"""Fabricated provider assertions only; no personal records or transport."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from itertools import permutations
import json
import pickle
from types import SimpleNamespace

import pytest

from backend.services import lastfm_named_evidence_dryrun as boundary
from backend.services.lastfm_taste_preview import CLOCK, rankings, synthetic_baseline

NOW = int(CLOCK.timestamp())  # Fixed fictional clock, never a real observation.


def consent():
    return boundary.FictionalConsent(synthetic_only=True, allow_named_rehearsal=True)


def qual(authority=boundary.AUTHORITY, sonos_proof=boundary.NON_OVERLAP):
    return boundary.FictionalQualification(authority, sonos_proof)


def row(artist="Copper Kites", title="Paper Comet", second=NOW, **changes):
    value = {"artist": {"#text": artist}, "name": title, "date": {"uts": str(second)}}
    value.update(changes)
    return value


def run(rows, *, qualifications=None):
    if qualifications is None:
        qualifications = [qual() for _ in rows]
    with boundary.NamedEvidenceRehearsal(
            synthetic_baseline(), rows, consent=consent(), qualifications=qualifications) as trial:
        return trial.preview(now_utc_second=NOW)


@pytest.mark.parametrize("grant", [None, True, "fictional", boundary.FictionalConsent(),
    boundary.FictionalConsent(synthetic_only=True),
    boundary.FictionalConsent(allow_named_rehearsal=True)])
def test_default_deny(grant):
    with pytest.raises(boundary.RehearsalDenied, match="^synthetic rehearsal denied$"):
        boundary.NamedEvidenceRehearsal(
            synthetic_baseline(), [row()], consent=grant, qualifications=[qual()])


def test_positive_is_explicit_and_aggregate_only():
    result = run([row()])
    assert result == {"synthetic_only": True, "source": "lastfm_unattributed",
        "apple_verified": False, "independent_plays_verified": False,
        "preference_inferred": False, "can_actuate": False,
        "eligible_assertions": 1, "changed_entities": 2, "counts": {}}
    assert run([row()], qualifications=[qual(sonos_proof=None)])["changed_entities"] == 0


@pytest.mark.parametrize("value,reason", [
    (None, "malformed"), (row(artist=""), "malformed"),
    (row(title=""), "malformed"), (row(artist="Copper|Kites"), "malformed"),
    (row(date={}), "malformed"), (row(date={"uts": NOW}), "malformed"),
    (row(date={"uts": str(NOW) + ".0"}), "malformed"),
    (row(date={"uts": "２０２６"}), "malformed"),
    (row(second=NOW + 1), "future"),
    (row(second=NOW - boundary.LOOKBACK_SECONDS - 1), "stale"),
    (row(**{"@attr": {"nowplaying": "true"}}), "now_playing_or_unknown_marker"),
    (row(**{"@attr": {"nowplaying": True}}), "now_playing_or_unknown_marker"),
    (row(**{"@attr": "invalid"}), "now_playing_or_unknown_marker"),
])
def test_abstention(value, reason):
    result = run([value])
    assert result["counts"] == {reason: 1}
    assert result["eligible_assertions"] == result["changed_entities"] == 0


@pytest.mark.parametrize("qualification,reason", [
    (qual(authority=None), "missing_authority"),
    (qual(sonos_proof=boundary.OVERLAP), "confirmed_overlap"),
    (qual(sonos_proof="no playback seen"), "unknown_coverage"),
])
def test_qualification_abstention(qualification, reason):
    result = run([row()], qualifications=[qualification])
    assert result["counts"] == {reason: 1}
    assert result["eligible_assertions"] == result["changed_entities"] == 0


def test_provider_cannot_self_attest_authority():
    for field, value in (("authority", boundary.AUTHORITY),
                         ("sonos_proof", boundary.NON_OVERLAP)):
        result = run([row(**{field: value})])
        assert result["counts"] == {"malformed": 1}
        assert result["eligible_assertions"] == result["changed_entities"] == 0


def test_bounds_and_freshness_rechecked():
    assert run([row(second=NOW - boundary.LOOKBACK_SECONDS)])["eligible_assertions"] == 1
    assert run([row()] * 50)["counts"] == {"duplicate": 49}
    for rows in ([row()] * 51, iter([row()]), {"track": [row()]}):
        grant = consent()
        with pytest.raises(boundary.RehearsalDenied):
            boundary.NamedEvidenceRehearsal(
                synthetic_baseline(), rows, consent=grant,
                qualifications=[qual() for _ in rows] if type(rows) is list else [])
        with pytest.raises(boundary.RehearsalDenied):
            boundary.NamedEvidenceRehearsal(
                synthetic_baseline(), [], consent=grant, qualifications=[])
    with boundary.NamedEvidenceRehearsal(
            synthetic_baseline(), [row()], consent=consent(),
            qualifications=[qual()]) as trial:
        for clock in (True, str(NOW), 0, NOW + 0.5):
            with pytest.raises(boundary.RehearsalDenied):
                trial.preview(now_utc_second=clock)
        assert trial.preview(now_utc_second=NOW + boundary.LOOKBACK_SECONDS + 1)[
            "counts"] == {"stale": 1}


def test_duplicates_conflicts_and_determinism():
    pairs = [(row(), qual()), (row(), qual(sonos_proof=None)),
             (row(), qual(sonos_proof=boundary.OVERLAP))]
    expected = run([p[0] for p in pairs], qualifications=[p[1] for p in pairs])
    assert expected["counts"] == {"confirmed_overlap": 1, "duplicate": 2}
    for order in permutations(pairs):
        assert run([p[0] for p in order], qualifications=[p[1] for p in order]) == expected
    assert run([p[0] for p in pairs[:2]], qualifications=[
        p[1] for p in pairs[:2]])["counts"] == {"duplicate": 1, "unknown_coverage": 1}
    assert run([row(), row()])["eligible_assertions"] == 1
    assert run([row(), row("Marble Otters")])["eligible_assertions"] == 2


def test_canonical_copy_and_exact_identity(monkeypatch):
    base = synthetic_baseline()
    base.genre_distribution["fictional_genre"] = 0.75
    base.mode_genre_map["fictional_context"] = ["fictional_genre"]
    base.tracks["velvet abacus|paper comet"] = replace(
        base.artists["velvet abacus"], kind="track",
        identity="velvet abacus|paper comet", sources=("sonos_playback",))
    before = deepcopy(base)
    rows = [row(), row("Tin Orchard"), row("Velvet Abacus"), row(artist="")]
    inputs = deepcopy(rows)
    captured = []
    original = boundary.overlay

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(boundary, "overlay", capture)
    with boundary.NamedEvidenceRehearsal(
            base, rows, consent=consent(), qualifications=[qual() for _ in rows]) as trial:
        first = trial.preview(now_utc_second=NOW)
        assert trial.preview(now_utc_second=NOW) == first
        snapshot = captured[0].snapshot  # Test-only spy, no public named export.
        assert snapshot == captured[1].snapshot
        assert base == before and rows == inputs
        for key in base.artists:
            assert snapshot.artists[key] == base.artists[key]
        assert snapshot.genre_distribution == base.genre_distribution
        assert snapshot.mode_genre_map == base.mode_genre_map
        assert snapshot.favorites == base.favorites
        assert snapshot.tracks["velvet abacus|paper comet"] == base.tracks[
            "velvet abacus|paper comet"]
        assert set(snapshot.tracks) == {"copper kites|paper comet", "velvet abacus|paper comet"}
        for entity in (snapshot.artists["copper kites"], snapshot.tracks["copper kites|paper comet"]):
            assert entity.preference == entity.positive_weight == entity.negative_weight == 0
            assert entity.contexts == {} and entity.last_observed_at is None
            assert entity.sources == (boundary.SOURCE,)
        assert "paper comet" not in snapshot.tracks  # Never a title-only bridge.
        for artist in ("", "Marble Otters", "Copper Кites"):  # Cyrillic confusable K.
            candidate = SimpleNamespace(media_type="track", title="Paper Comet",
                                        metadata={"artist_name": artist})
            assert snapshot.classify_candidate(candidate).familiarity == 0
        assert all(r["artist"] != "Tin Orchard" for r in asyncio.run(rankings(snapshot)))


def test_revocation_drop_and_redaction(capsys):
    grant = consent()
    trial = boundary.NamedEvidenceRehearsal(
        synthetic_baseline(), [row()], consent=grant, qualifications=[qual()])
    text = (repr(trial) + repr(grant) + repr(qual())
            + json.dumps(trial.preview(now_utc_second=NOW)))
    for value in (trial, grant):
        with pytest.raises(boundary.RehearsalDenied) as error:
            pickle.dumps(value)
        text += str(error.value) + repr(error.value)
    for sensitive in ("Copper", "Paper", str(NOW), CLOCK.isoformat()):
        assert sensitive not in text
    grant.revoke()
    assert trial._rows is trial._baseline is trial._consent is None
    for action in (lambda: trial.preview(now_utc_second=NOW),
                   lambda: boundary.NamedEvidenceRehearsal(synthetic_baseline(), [row()],
                                                           consent=grant, qualifications=[qual()])):
        with pytest.raises(boundary.RehearsalDenied):
            action()
    trial.drop()  # Idempotent.
    assert run([row()])["eligible_assertions"] == 1  # New explicit consent.
    assert capsys.readouterr() == ("", "")


def test_context_drop_on_error_and_owned_input_copy():
    rows = [row()]
    grant = consent()
    with pytest.raises(RuntimeError):
        with boundary.NamedEvidenceRehearsal(
                synthetic_baseline(), rows, consent=grant,
                qualifications=[qual()]) as trial:
            rows[0]["name"] = "Tampered Input"
            assert trial.preview(now_utc_second=NOW)["eligible_assertions"] == 1
            raise RuntimeError("fictional failure")
    with pytest.raises(boundary.RehearsalDenied):
        trial.preview(now_utc_second=NOW)


def test_no_external_access(monkeypatch):
    import socket
    from backend import database
    from backend.services import sonos_service

    def forbidden(*args, **kwargs):
        raise AssertionError("external access forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(database, "async_session", forbidden)
    monkeypatch.setattr(sonos_service.SonosService, "__init__", forbidden)
    assert run([row()])["changed_entities"] == 2
