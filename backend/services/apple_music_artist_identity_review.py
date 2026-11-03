"""Synthetic aggregate review contract. No authority, persistence, or preference effects."""

from dataclasses import dataclass
from enum import Enum
import unicodedata


class DaysBucket(Enum):
    ONE_DAY = "1_day"
    TWO_TO_THREE_DAYS = "2_to_3_days"
    FOUR_TO_NINE_DAYS = "4_to_9_days"
    TEN_PLUS_DAYS = "10_plus_days"


class ReviewState(Enum):
    UNREVIEWED = "unreviewed"
    NEEDS_VERIFICATION = "needs_verification"
    REJECT_LABEL = "reject_label"
    RESET = "reset"


class ClaimProvenance(Enum):
    SYNTHETIC_FIXTURE = "synthetic_fixture_only"


@dataclass(frozen=True, repr=False)
class SourceLabelExposure:
    label: str
    days_bucket: DaysBucket
    source: str = "apple_daily_tracks"
    source_kind: str = "artist_label_day_exposure"

    def __repr__(self):
        return "SourceLabelExposure(<redacted>)"


@dataclass(frozen=True, repr=False)
class CatalogArtistReference:
    provider: str
    artist_id: str
    display_name: str
    provenance: ClaimProvenance
    independently_verified_claim: bool = False
    aliases: tuple[str, ...] = ()

    def __repr__(self):
        return "CatalogArtistReference(<redacted>)"


@dataclass(frozen=True, repr=False)
class LabelReview:
    exposure: SourceLabelExposure
    references: tuple[CatalogArtistReference, ...] = ()
    review_state: ReviewState = ReviewState.UNREVIEWED

    def __repr__(self):
        return "LabelReview(<redacted>)"


STATUSES = (
    "source_unverified",
    "identity_candidate_for_human_review",
    "ambiguous_catalog_candidate",
    "rejected_label_not_dislike",
    "needs_verification_not_confirmed",
    "source_conflict_abstain",
    "invalid_input_abstain",
)
WARNINGS = (
    "synthetic_only_no_live_identity_proofs",
    "label_exposure_is_not_preference",
    "provider_claims_are_not_authority",
    "apple_sonos_overlap_unknown_no_double_counting",
)


@dataclass(frozen=True)
class AggregateReview:
    counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...] = WARNINGS
    mapping_status: str = "hypothetical_candidate_only"
    preference_effect: int = 0
    rank_effect: int = 0
    live_identity_proofs: int = 0


def _text(value):
    if type(value) is not str or not value or len(value) > 256:
        raise ValueError("invalid synthetic review input")
    normalized = unicodedata.normalize("NFKC", value)
    if (
        not normalized.strip()
        or len(normalized) > 256
        or any(unicodedata.category(c).startswith("C") for c in value + normalized)
    ):
        raise ValueError("invalid synthetic review input")
    return " ".join(normalized.casefold().split())


def _validate(row):
    if type(row) is not LabelReview or type(row.exposure) is not SourceLabelExposure:
        raise ValueError("invalid synthetic review input")
    exposure = row.exposure
    key = _text(exposure.label)
    if (
        type(exposure.days_bucket) is not DaysBucket
        or type(exposure.source) is not str
        or type(exposure.source_kind) is not str
        or exposure.source != "apple_daily_tracks"
        or exposure.source_kind != "artist_label_day_exposure"
        or type(row.review_state) is not ReviewState
        or type(row.references) is not tuple
        or len(row.references) > 5
    ):
        raise ValueError("invalid synthetic review input")
    for ref in row.references:
        if type(ref) is not CatalogArtistReference:
            raise ValueError("invalid synthetic review input")
        for value in (ref.provider, ref.artist_id, ref.display_name):
            _text(value)
        if (
            type(ref.provenance) is not ClaimProvenance
            or type(ref.independently_verified_claim) is not bool
            or type(ref.aliases) is not tuple
            or len(ref.aliases) > 16
        ):
            raise ValueError("invalid synthetic review input")
        for alias in ref.aliases:
            _text(alias)
    return key


def _signature(row):
    # Preserve exact provider/ID and spelling: normalized equality is not proof.
    refs = frozenset(row.references)
    return (row.exposure, refs, row.review_state)


def _status(row):
    refs = frozenset(row.references)
    if len(refs) > 1:
        return "ambiguous_catalog_candidate"
    if row.review_state is ReviewState.REJECT_LABEL:
        return "rejected_label_not_dislike"
    if row.review_state is ReviewState.NEEDS_VERIFICATION:
        return "needs_verification_not_confirmed"
    if not refs:
        return "source_unverified"
    ref = next(iter(refs))
    # Aliases and normalized-only matches cannot establish even this candidate.
    # Composite names are never split; only a whole-name exact match can qualify.
    if row.exposure.label != ref.display_name:
        return "ambiguous_catalog_candidate"
    if not ref.independently_verified_claim:
        return "source_unverified"
    return "identity_candidate_for_human_review"


def evaluate_artist_identity_review(rows: tuple[LabelReview, ...]) -> AggregateReview:
    """Evaluate at most 5000 observations; malformed batches fail closed as a unit.

    Empty references mean no catalog claim; supplied claims are bounded to 1–5.
    Exact duplicate claims/observations do not increase counts. Inconsistent
    observations revoke the entire normalized-label group. No per-label output.
    """
    counts = dict.fromkeys(STATUSES, 0)
    try:
        if type(rows) is not tuple or len(rows) > 5000:
            raise ValueError("invalid synthetic review input")
        groups = {}
        for row in rows:
            key = _validate(row)
            groups.setdefault(key, []).append(row)
        names = {}
        identities = {}
        for row in rows:
            for ref in row.references:
                identity = (ref.provider, ref.artist_id)
                identities.setdefault(identity, set()).add(ref)
                for name in (ref.display_name, *ref.aliases):
                    names.setdefault(_text(name), set()).add(identity)
        for group in groups.values():
            if len({_signature(row) for row in group}) != 1:
                status = "source_conflict_abstain"
            elif any(
                len(identities[(ref.provider, ref.artist_id)]) > 1
                or any(
                    len(names[_text(name)]) > 1
                    for name in (ref.display_name, *ref.aliases)
                )
                for ref in group[0].references
            ):
                status = "ambiguous_catalog_candidate"
            else:
                status = _status(group[0])
            counts[status] += 1
    except (ValueError, TypeError, AttributeError):
        counts = dict.fromkeys(STATUSES, 0)
        counts["invalid_input_abstain"] = 1
    return AggregateReview(tuple(counts.items()))
