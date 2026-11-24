from datetime import date

from scripts.check_project_admin_drift import check_development_journal


def entry(day="2026-11-24", title="Music", body=None):
    if body is None:
        body = (
            "**Owner intent:** Discovery. [Source](https://github.com/agatte/home-hub/issues/254)\n\n"
            "**Next:** Review the source.\n"
        )
    return f"### {day} — {title}\n\n{body}\n"


def journal(*entries):
    return "# Journal\n\n## Recent meaningful sessions\n\n" + "\n".join(entries)


def test_clean_recent_entry_and_historical_lesson_ignored():
    text = journal(entry()) + "\n## Earlier milestone / lesson\n\n### Old unstructured history\n"
    assert check_development_journal(text, {254: {}}, date(2026, 11, 24)) == ([], [])


def test_duplicate_paragraphs_and_heading_are_reported_without_text():
    drift, notices = check_development_journal(
        journal(entry(), entry()), {254: {}}, date(2026, 11, 24)
    )
    assert any("repeated dated session heading" in msg for msg in drift)
    assert any("exact repeated paragraph" in msg for msg in notices)
    assert not any("Discovery" in msg or "Review the source" in msg for msg in drift + notices)


def test_age_and_later_issue_update_are_advisory():
    drift, notices = check_development_journal(
        journal(entry(day="2026-10-01")),
        {254: {"updated_at": "2026-11-01T00:00:00Z"}},
        date(2026, 11, 24),
    )
    assert drift == []
    assert any("consider consolidation" in msg for msg in notices)
    assert any("updated after summary date" in msg for msg in notices)


def test_same_day_update_not_claimed_stale():
    assert check_development_journal(
        journal(entry()), {254: {"updated_at": "2026-11-24T23:00:00Z"}}, date(2026, 11, 24)
    ) == ([], [])


def test_missing_gate_and_source_and_future_date():
    drift, notices = check_development_journal(
        journal(entry(day="2026-11-25", body="Unlinked note.")), {}, date(2026, 11, 24)
    )
    assert any("future date" in msg for msg in drift)
    assert any("missing explicit next step" in msg for msg in drift)
    assert any("missing linked owning issue" in msg for msg in drift)
    assert notices == []


def test_missing_metadata_is_not_proof_of_staleness():
    drift, notices = check_development_journal(journal(entry()), {}, date(2026, 11, 24))
    assert drift == []
    assert notices == ["Journal entry 1: linked issue #254 absent from supplied metadata"]


def test_bad_date_and_missing_section():
    drift, _ = check_development_journal(
        journal(entry(day="2026-02-31")), {}, date(2026, 11, 24)
    )
    assert drift == ["Journal entry 1: invalid date"]
    assert check_development_journal("# No recent entries", {}, date(2026, 11, 24))[0]


def test_dated_checkpoint_label_is_supported():
    text = journal(entry()).replace("**Next:**", "**Next at this dated checkpoint:**")
    assert check_development_journal(text, {254: {}}, date(2026, 11, 24)) == ([], [])
