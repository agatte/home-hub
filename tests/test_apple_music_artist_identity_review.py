"""Invented fixtures only; no application/runtime integration."""

from dataclasses import FrozenInstanceError, replace
import dis
import importlib
from itertools import permutations

from backend.services import apple_music_artist_identity_review as contract


def reference(**changes):
    return replace(contract.CatalogArtistReference(
        "invented_catalog", "CaseSensitive-X", "Imaginary Ensemble",
        contract.ClaimProvenance.SYNTHETIC_FIXTURE, True,
    ), **changes)


def observation(**changes):
    return replace(contract.LabelReview(
        contract.SourceLabelExposure("Imaginary Ensemble", contract.DaysBucket.TWO_TO_THREE_DAYS),
        (reference(),),
    ), **changes)


def counts(*rows):
    return dict(contract.evaluate_artist_identity_review(rows).counts)


def test_candidate_is_never_authority_or_preference():
    result = contract.evaluate_artist_identity_review((observation(),))
    assert dict(result.counts)["identity_candidate_for_human_review"] == 1
    assert result.preference_effect == result.rank_effect == result.live_identity_proofs == 0
    assert result.mapping_status == "hypothetical_candidate_only"
    assert "Imaginary" not in repr(result)
    assert "CaseSensitive" not in repr(result)


def test_redacted_immutable_inputs():
    row = observation()
    for value in (row, row.exposure, reference()):
        assert "redacted" in repr(value)
        assert "Imaginary" not in repr(value)
    try:
        row.exposure.label = "Changed"
    except FrozenInstanceError:
        pass
    else:
        assert False, "input must be frozen"


def test_dedup_reordering_and_conflict_revocation():
    row = observation()
    assert counts(row, row) == counts(row)
    assert counts(replace(row, references=(reference(), reference()))) == counts(row)
    changed = replace(row, exposure=replace(row.exposure, days_bucket=contract.DaysBucket.FOUR_TO_NINE_DAYS))
    for ordered in permutations((row, changed, row)):
        result = counts(*ordered)
        assert result["source_conflict_abstain"] == 1
        assert sum(result.values()) == 1
    folded = replace(row, exposure=replace(row.exposure, label="IMAGINARY ENSEMBLE"))
    assert counts(row, folded)["source_conflict_abstain"] == 1


def test_exact_case_provider_ids_multiple_matches_and_alias_collisions():
    for other in (reference(artist_id="casesensitive-x"), reference(provider="other")):
        assert counts(observation(references=(reference(), other)))["ambiguous_catalog_candidate"] == 1
    other = reference(artist_id="other", display_name="Invented Solo", aliases=("Imaginary Ensemble",))
    row = observation(exposure=contract.SourceLabelExposure("Invented Solo", contract.DaysBucket.ONE_DAY), references=(other,))
    assert counts(observation(), row)["ambiguous_catalog_candidate"] == 2
    reused = replace(other, artist_id=reference().artist_id, aliases=())
    assert counts(observation(), replace(row, references=(reused,)))["ambiguous_catalog_candidate"] == 2


def test_normalization_alias_and_composite_are_not_identity():
    for label in ("IMAGINARY ENSEMBLE", "Imaginary Ensemble feat. Invented Solo", "Imaginary Ensemble & Invented Solo"):
        row = observation(exposure=contract.SourceLabelExposure(label, contract.DaysBucket.ONE_DAY))
        assert counts(row)["ambiguous_catalog_candidate"] == 1
    # Ampersands may be genuine whole artist names; never split them.
    name = "Invented & Imaginary"
    row = observation(exposure=contract.SourceLabelExposure(name, contract.DaysBucket.ONE_DAY), references=(reference(display_name=name),))
    assert counts(row)["identity_candidate_for_human_review"] == 1
    fullwidth = replace(observation().exposure, label="Ｉmaginary Ensemble")
    assert counts(observation(exposure=fullwidth))["ambiguous_catalog_candidate"] == 1


def test_review_states_are_independent_and_reset_is_unreviewed():
    for state, status in (
        (contract.ReviewState.UNREVIEWED, "identity_candidate_for_human_review"),
        (contract.ReviewState.RESET, "identity_candidate_for_human_review"),
        (contract.ReviewState.REJECT_LABEL, "rejected_label_not_dislike"),
        (contract.ReviewState.NEEDS_VERIFICATION, "needs_verification_not_confirmed"),
    ):
        assert counts(observation(review_state=state))[status] == 1
    assert counts(observation(references=()))["source_unverified"] == 1
    assert counts(observation(references=(reference(independently_verified_claim=False),)))["source_unverified"] == 1


def test_hostile_inputs_fail_closed_without_echo():
    row = observation()
    hostile = [None, "", "\x00Invented", "\u200bInvented", "x" * 257, "\ud800"]
    cases = [observation(exposure=replace(row.exposure, label=value)) for value in hostile]
    cases += [
        observation(review_state="confirm_identity"),
        observation(review_state="unreviewed"),
        observation(references=(reference(provenance="trusted_provider"),)),
        observation(references=(reference(provenance="synthetic_fixture_only"),)),
        observation(references=(reference(independently_verified_claim=1),)),
        observation(references=(reference(aliases=["Invented"]),)),
        observation(references=(reference(artist_id=""),)),
        observation(references=(reference(),) * 6),
        observation(exposure=replace(row.exposure, source="other")),
        observation(exposure=replace(row.exposure, source_kind="verified_artist")),
        observation(exposure=replace(row.exposure, days_bucket="few")),
        "private-placeholder", None,
    ]
    for value in cases:
        result = counts(row, value)
        assert result["invalid_input_abstain"] == 1
        assert sum(result.values()) == 1


def test_exact_four_review_bands_and_whitespace_is_not_identity_proof():
    assert {band.value for band in contract.DaysBucket} == {
        "1_day", "2_to_3_days", "4_to_9_days", "10_plus_days",
    }
    row = observation()
    highest = replace(
        row, exposure=replace(row.exposure, days_bucket=contract.DaysBucket.TEN_PLUS_DAYS),
    )
    assert counts(highest)["identity_candidate_for_human_review"] == 1
    padded = replace(row, exposure=replace(row.exposure, label="  Imaginary   Ensemble  "))
    assert counts(row, padded)["source_conflict_abstain"] == 1
    assert counts(padded)["ambiguous_catalog_candidate"] == 1


def test_hostile_source_object_equality_never_escapes_or_impersonates():
    class RaisesOnCompare:
        def __ne__(self, other):
            raise RuntimeError("private-value-must-not-leak")

        def __eq__(self, other):
            raise RuntimeError("private-value-must-not-leak")

    class SpoofsComparison:
        def __ne__(self, other):
            return False

        def __eq__(self, other):
            return True

    original = observation()
    for hostile in (RaisesOnCompare(), SpoofsComparison(), 123, None):
        for attr in ("source", "source_kind"):
            bad = replace(
                original, exposure=replace(original.exposure, **{attr: hostile}),
            )
            result = contract.evaluate_artist_identity_review((original, bad))
            assert dict(result.counts)["invalid_input_abstain"] == 1
            assert sum(dict(result.counts).values()) == 1
            assert "private-value" not in repr(result)


def test_bounds_and_empty_batch():
    row = observation()
    assert sum(counts().values()) == 0
    assert counts(*((row,) * 5000))["identity_candidate_for_human_review"] == 1
    assert counts(*((row,) * 5001))["invalid_input_abstain"] == 1
    assert dict(contract.evaluate_artist_identity_review([row]).counts)["invalid_input_abstain"] == 1


def test_evaluation_does_not_call_io(monkeypatch):
    import builtins
    import io
    import os
    import socket
    import subprocess

    def blocked(*args, **kwargs):
        raise AssertionError("IO forbidden during evaluation")

    row = observation()
    with monkeypatch.context() as patches:
        for owner, name in (
            (builtins, "open"), (io, "open"), (os, "open"),
            (socket, "socket"), (socket, "create_connection"),
            (subprocess, "Popen"), (os, "system"), (builtins, "__import__"),
        ):
            patches.setattr(owner, name, blocked)
        assert counts(row)["identity_candidate_for_human_review"] == 1
        assert counts(row, observation(review_state="confirm_identity"))["invalid_input_abstain"] == 1


def test_import_graph_and_executable_names_are_pure():
    # Inspect loaded code objects, without opening source files or invoking IO.
    allowed = {"dataclasses", "enum", "unicodedata"}
    code = contract.__loader__.get_code(contract.__name__)
    imports = {i.argval for i in dis.get_instructions(code) if i.opname == "IMPORT_NAME"}
    assert imports == allowed
    for name in imports:
        module = importlib.import_module(name)
        assert module.__name__ in allowed
    forbidden = {"open", "exec", "eval", "socket", "subprocess", "sqlalchemy", "music_taste", "sonos", "music_discovery", "MusicBandit"}

    def inspect_code(current):
        assert not (set(current.co_names) & forbidden)
        for constant in current.co_consts:
            if hasattr(constant, "co_code"):
                inspect_code(constant)

    inspect_code(code)
