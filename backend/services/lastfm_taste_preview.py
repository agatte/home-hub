"""Offline synthetic experiment only; never registered as a runtime taste provider."""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Iterable

from backend.services.music_discovery import MusicDiscoveryService
from backend.services.music_taste import (
    MusicTasteSnapshot, TasteEntityEvidence, _key, _track_key,
)

CLOCK = datetime(2026, 1, 8, tzinfo=timezone.utc)
LOOKBACK = timedelta(days=7)
SOURCE = "synthetic:lastfm_scrobble/unattributed"
CAP = 0.8
MAX_RECORDS = 512


@dataclass(frozen=True)
class Observation:
    """Invented provider assertion. Overlap is explicit fixture proof, never guessed."""

    artist: str = ""
    title: str = ""
    timestamp: datetime | None = None
    now_playing: bool = False
    sonos_overlap_confirmed: bool = False


@dataclass(frozen=True)
class OverlayResult:
    snapshot: MusicTasteSnapshot
    diagnostics: dict


def familiarity(count: int) -> float:
    """Diminishing absolute target; reapplying the same batch cannot compound it."""
    return round(min(CAP, 0.45 + 0.1 * min(max(count - 1, 0), 4)), 4) if count else 0.0


def overlay(
    baseline: MusicTasteSnapshot, observations: Iterable[Observation], *, now: datetime = CLOCK,
) -> OverlayResult:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("an explicit timezone-aware clock is required")
    counts = Counter()
    assertions = {}
    for index, row in enumerate(observations):
        if index >= MAX_RECORDS:
            raise ValueError("synthetic observation budget exceeded")
        if not isinstance(row, Observation):
            counts["malformed"] += 1
            continue
        if row.now_playing is not False:
            counts["now_playing"] += 1
            continue
        if not all(isinstance(v, str) and v.strip() for v in (row.artist, row.title)):
            counts["missing_exact_identity"] += 1
            continue
        stamp = row.timestamp
        if not isinstance(stamp, datetime) or stamp.utcoffset() is None:
            counts["missing_or_malformed_date"] += 1
            continue
        if stamp > now:
            counts["future"] += 1
            continue
        if stamp < now - LOOKBACK:
            counts["stale"] += 1
            continue
        identity = (_key(row.artist), _key(row.title), stamp)
        overlap = row.sonos_overlap_confirmed is True
        if identity in assertions:
            counts["duplicate"] += 1
        # Conflicting duplicate qualification conservatively suppresses the assertion.
        assertions[identity] = assertions.get(identity, False) or overlap

    tracks = Counter()
    suppressed = Counter()
    for (artist, title, _), overlap in sorted(assertions.items()):
        if overlap:
            suppressed[(artist, title)] += 1
            counts["sonos_overlap_confirmed"] += 1
        else:
            tracks[(artist, title)] += 1
    snapshot = deepcopy(baseline)
    artists = defaultdict(set)
    track_diagnostics = []

    def updated(old, kind, identity, target, depth):
        if old is not None:
            # Passive assertions must not upgrade positive evidence to proven.
            if old.positive_weight > 0 or old.negative_weight > 0:
                # Do not let passive exposure rewrite explicit/canonical
                # judgment or accidentally change its ranking authority.
                return old
            promoted_familiarity = max(old.familiarity, target)
            promoted_depth = max(old.depth, depth)
            if promoted_familiarity == old.familiarity and promoted_depth == old.depth:
                return old
            return replace(
                old,
                familiarity=promoted_familiarity,
                depth=promoted_depth,
                # Preserve every prior source; identify the new passive
                # exposure responsible for this offline-only enrichment.
                sources=tuple(sorted(set(old.sources) | {SOURCE})),
            )
        return TasteEntityEvidence(
            kind, identity, target, 0.0, 0.0, 0.0, depth, (SOURCE,), None,
        )

    for artist, title in sorted(tracks.keys() | suppressed.keys()):
        count = tracks[(artist, title)]
        key = _track_key(title, artist)
        canonical_positive = (
            key in baseline.tracks and baseline.tracks[key].positive_weight > 0
        )
        canonical_artist = baseline.artists.get(artist)
        canonical_guard = canonical_artist is not None and (
            canonical_artist.positive_weight > 0 or canonical_artist.negative_weight > 0
        )
        if count:
            artists[artist].add(title)
            # New neutral tracks can lower a known artist's inherited
            # preference in MusicTasteSnapshot.classify_candidate. Keep
            # feedback-owned artists diagnostic-only in this dry run.
            if not canonical_guard:
                snapshot.tracks[key] = updated(
                    snapshot.tracks.get(key), "track", key, familiarity(count), min(count, 5),
                )
        track_diagnostics.append({
            "artist": artist, "track": title, "observed_count": count + suppressed[(artist, title)],
            "eligible_count": count, "repeat_depth": max(0, count - 1),
            "suppressed_count": suppressed[(artist, title)],
            "inferred_familiarity_target": familiarity(count),
            "reason_codes": ["exact_artist_title", "passive_not_preference"]
            + (["confirmed_sonos_overlap_suppressed"] if suppressed[(artist, title)] else [])
            + (["canonical_positive_unchanged"] if canonical_positive else [])
            + (["canonical_artist_feedback_guard"] if canonical_guard else []),
        })
    artist_diagnostics = []
    for artist, titles in sorted(artists.items()):
        count = sum(tracks[(artist, title)] for title in titles)
        depth = min(4, len(titles))
        snapshot.artists[artist] = updated(
            snapshot.artists.get(artist), "artist", artist, familiarity(count), depth,
        )
        artist_diagnostics.append({
            "artist": artist, "observed_count": count, "unique_named_tracks": len(titles),
            "inferred_depth_target": depth,
            "reason_codes": ["unique_tracks_not_replays", "passive_not_preference"]
            + (["canonical_artist_feedback_guard"] if (
                artist in baseline.artists and (
                    baseline.artists[artist].positive_weight > 0
                    or baseline.artists[artist].negative_weight > 0
                )
            ) else []),
        })
    return OverlayResult(snapshot, {
        "source_qualification": SOURCE, "apple_identity_verified": False,
        "independent_plays_verified": False, "preference_inferred": False,
        "counts": dict(sorted(counts.items())), "artists": artist_diagnostics,
        "tracks": track_diagnostics,
    })


class SnapshotProvider:
    def __init__(self, value):
        self.value = value

    async def snapshot(self):
        return self.value


class SyntheticSource:
    enabled = True

    async def discover_artist_candidates(self, mode, *, count=8, tracks_per_artist=3):
        return [{
            "artist_name": artist, "seed_artist": "Fable Lanterns", "source_match": match,
            "source": "synthetic_catalog_fixture",
            "tracks": [{"track_name": "Paper Comet", "provider": "synthetic_catalog",
                        "provider_id": f"fiction-{index}", "catalog_verified": True,
                        "playback_capability": "metadata_only"}],
        } for index, (artist, match) in enumerate([
            ("Velvet Abacus", 0.79), ("Copper Kites", 0.79), ("Marble Otters", 0.77),
            ("Tin Orchard", 0.99),
        ])][:count]


def synthetic_baseline():
    def entity(name, preference, positive, negative, sources):
        return TasteEntityEvidence(
            "artist", _key(name), 0.8, preference, positive, negative, 1, sources, None,
        )
    return MusicTasteSnapshot(CLOCK, None, {}, {}, {
        "velvet abacus": entity("Velvet Abacus", 0.4, 3, 0, ("explicit_feedback:fits_me",)),
        "tin orchard": entity("Tin Orchard", -0.75, 0, 3, ("explicit_feedback:not_for_me",)),
    }, {}, {})


def synthetic_observations():
    return [Observation(artist, title, CLOCK - timedelta(hours=index + 1))
            for index, (artist, title) in enumerate(
                [("Copper Kites", "Paper Comet")] * 6
                + [("Copper Kites", "Glass Meadow"), ("Marble Otters", "Paper Comet"),
                   ("Tin Orchard", "Paper Comet"), ("Velvet Abacus", "Paper Comet")])]


async def rankings(snapshot):
    result = await MusicDiscoveryService(
        source=SyntheticSource(), taste_provider=SnapshotProvider(snapshot),
    ).preview("gaming", count=4)
    return [{"rank": index, "artist": c.artist_name, "score": round(c.score, 4),
             "classification": c.artist_classification, "preference": c.artist_preference,
             "depth": c.artist_depth, "novelty": c.novelty_ratio, "reasons": list(c.reasons),
             "tracks": [{"title": t.track_name, "classification": t.taste_classification,
                         "capability": t.playback_capability} for t in c.tracks]}
            for index, c in enumerate(result.clusters, 1)]


async def demo():
    baseline = synthetic_baseline()
    result = overlay(baseline, synthetic_observations())
    return {"synthetic_only": True, "source_qualification": SOURCE,
            "catalog_verification": "fictional fixture assertion; no catalog lookup",
            "before": await rankings(baseline), "after": await rankings(result.snapshot),
            "excluded": [{"artist": "Tin Orchard", "reason": "canonical_not_for_me_rejected"}],
            "evidence": result.diagnostics}
