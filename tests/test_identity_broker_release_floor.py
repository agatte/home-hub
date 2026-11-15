"""Offline rollback-floor fixtures; no host or runtime authority."""
from copy import deepcopy
from pathlib import Path

import pytest

from security.homehub_identity_broker import release_floor as floor


def record():
    return dict(schema=1, epoch=5, generation=9, commit_sha="a" * 40,
                artifact_sha256="b" * 64, provenance_sha256="c" * 64,
                package=floor.PACKAGE, path=floor.PATH, identity=floor.IDENTITY,
                surfaces=floor.SURFACES)


def evaluate(candidate=None, stored=None, expected=None, release=None, surface="boot"):
    return floor.evaluate(record() if candidate is None else candidate,
                          record() if stored is None else stored,
                          expected_floor=record() if expected is None else expected,
                          expected_release=record() if release is None else release,
                          surface=surface)


@pytest.mark.parametrize("surface", floor.SURFACES)
def test_every_surface_requires_external_guard(surface):
    report = evaluate(surface=surface)
    assert report.fixture_consistent
    assert report.issues == floor.GATES
    assert report.status == "BLOCKED"
    assert report.runtime_authorized is False
    assert any(row.surface == surface and row.missing for row in floor.coverage())


def test_coverage_independently_locks_every_required_case_and_evidence():
    expected = (
        "boot", "service-restart", "deploy-forward", "rollback", "failed-deploy-recovery",
        "return-home", "direct-user-restart", "linger-alternate-user-service",
        "restored-checkout", "manual-process",
    )
    assert floor.SURFACES == expected
    assert tuple(row.surface for row in floor.coverage()) == expected
    labels = {e.label for e in floor.audit_entrypoints(snapshots()).evidence}
    for row in floor.coverage():
        assert set(row.source_labels) <= labels
        assert row.missing
    rows = {row.surface: row for row in floor.coverage()}
    assert rows["manual-process"].source_labels == ()
    assert rows["linger-alternate-user-service"].source_labels == ()
    assert rows["failed-deploy-recovery"].source_labels == (
        "failure-recovery", "rollback-reset", "user-restart")


@pytest.mark.parametrize("key", ["epoch", "generation", "schema"])
@pytest.mark.parametrize("value", [True, False, -1, 2**64, "5", 5.0, None])
def test_strict_unsigned_integers(key, value):
    candidate = record()
    candidate[key] = value
    assert "record-schema" in evaluate(candidate).issues


@pytest.mark.parametrize("key,value", [
    ("commit_sha", "a" * 7), ("commit_sha", "A" * 40),
    ("artifact_sha256", "unsigned"), ("provenance_sha256", "reviewed"),
    ("package", "old-user-service"), ("path", "%h/home-hub/run.py"),
    ("identity", "anthony"), ("surfaces", ("boot",)),
    ("surfaces", floor.SURFACES + ("unknown",)),
    ("surfaces", list(floor.SURFACES)),
])
def test_schema_does_not_allow_legacy_exception(key, value):
    candidate = record()
    candidate[key] = value
    assert "record-schema" in evaluate(candidate).issues


@pytest.mark.parametrize("key", ["commit_sha", "artifact_sha256", "provenance_sha256"])
def test_exact_independent_release_binding(key):
    candidate = record()
    candidate[key] = "d" * len(candidate[key])
    assert "unapproved-release-or-provenance" in evaluate(candidate).issues


def test_downgrade_even_when_release_is_approved_and_sha_sorts_later():
    candidate = record()
    candidate.update(epoch=4, commit_sha="f" * 40)
    report = evaluate(candidate, release=deepcopy(candidate))
    assert "below-floor" in report.issues
    assert not report.runtime_authorized


def test_forward_requires_exact_release_and_current_generation():
    candidate = record()
    candidate.update(epoch=6, commit_sha="0" * 40)
    assert evaluate(candidate, release=deepcopy(candidate)).fixture_consistent
    candidate["generation"] = 8
    assert "stale-generation" in evaluate(candidate, release=deepcopy(candidate)).issues
    stored = record()
    stored["generation"] = 8
    assert "stale-or-mismatched-floor" in evaluate(stored=stored).issues


@pytest.mark.parametrize("bad", [{}, None, True, "reviewed", object(),
                               {"signed": True}, {"override": "approved"}])
def test_no_fallback_or_invented_approval(bad):
    for position in range(4):
        records = [record() for _ in range(4)]
        records[position] = bad
        report = floor.evaluate(records[0], records[1], expected_floor=records[2],
                                expected_release=records[3], surface="boot")
        assert "record-schema" in report.issues
        assert not report.runtime_authorized


@pytest.mark.parametrize("key", ["reviewed", "signed", "override", "runtime_authorized"])
def test_extra_fields_are_not_approval(key):
    candidate = record()
    candidate[key] = True
    assert "record-schema" in evaluate(candidate).issues


def snapshots():
    root = Path(__file__).resolve().parents[1]
    return {path: (root / path).read_text(encoding="utf-8") for path, _ in floor.SOURCE_HASHES}


def test_current_literal_repository_is_bypass_present():
    sources = snapshots()
    report = floor.audit_entrypoints(sources)
    assert not any(i.startswith(("unrecognized-source", "missing-shape")) for i in report.issues)
    assert {"bypass-present:" + label for _, label, _ in floor.MATCHES} <= set(report.issues)
    assert sum(e.label == "user-restart" for e in report.evidence) == 2
    for evidence in report.evidence:
        literal = next(text for _, label, text in floor.MATCHES if label == evidence.label)
        assert sources[evidence.path].replace("\r\n", "\n")[evidence.start:evidence.end] == literal
    assert report.status == "BLOCKED" and not report.runtime_authorized


@pytest.mark.parametrize("path,digest", floor.SOURCE_HASHES)
def test_source_rewrite_cannot_remove_gate(path, digest):
    sources = snapshots()
    sources[path] = "# independently approved; override=secure\n"
    report = floor.audit_entrypoints(sources)
    assert "unrecognized-source:" + path in report.issues
    assert not report.fixture_consistent and not report.runtime_authorized


@pytest.mark.parametrize("change", ["extra", "missing", "size", "type", "unicode"])
def test_unknown_inventory_and_unreadable_shape_fail_closed(change):
    sources = snapshots()
    path = floor.SOURCE_HASHES[0][0]
    if change == "extra":
        sources["/arbitrary/path"] = "safe"
    elif change == "missing":
        del sources[path]
    else:
        sources[path] = {"size": "x" * (128 * 1024 + 1), "type": True,
                         "unicode": "\ud800"}[change]
    report = floor.audit_entrypoints(sources)
    assert not report.fixture_consistent and not report.runtime_authorized


@pytest.mark.parametrize("surface", ["old-user-service-exception", "override", None, True])
def test_unknown_launch_surface(surface):
    assert "launch-surface" in evaluate(surface=surface).issues


def test_crlf_offsets_are_normalized_and_reports_have_no_grant_constructor():
    sources = {p: s.replace("\n", "\r\n") for p, s in snapshots().items()}
    assert floor.audit_entrypoints(sources) == floor.audit_entrypoints(snapshots())
    with pytest.raises(TypeError):
        floor.Report((), runtime_authorized=True)
