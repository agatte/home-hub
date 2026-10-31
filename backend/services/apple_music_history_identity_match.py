"""Synthetic-first, in-memory Apple cross-export artist matching feasibility.

No database, persistence, network, HomeHub service, or song-level scoring.
Returns anonymous totals only; nothing derived here is a verified track ID.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
import unicodedata

MAX_LABEL = 2048
SEPARATOR = " - "


def _label(value: str) -> str:
    """Normalize conservatively; preserve punctuation and distinguishing text."""
    if not isinstance(value, str) or not 0 < len(value) <= MAX_LABEL:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def summarize_artist_join_coverage(
    play_song_names: Iterable[str],
    daily_track_descriptions: Iterable[str],
) -> dict[str, int]:
    """Estimate artist join coverage; never return track names or matched artists.

    Daily 'Track Description' is not a verified artist field. A candidate is
    *provisional* even if the suffix appears unique; this is never taste evidence.
    An ambiguous delimiter, inconsistent prefixes, or missing title abstains.
    Date/session identity and album recording identity are NOT established.
    """
    counts: Counter[str] = Counter()
    title_event_counts: Counter[str] = Counter()
    for name in play_song_names:
        counts["event_titles_examined"] += 1
        title = _label(name)
        if title:
            title_event_counts[title] += 1
        else:
            counts["blank_or_invalid_event_titles"] += 1

    # Normalize only in process memory; the returned report never contains keys.
    supported_artists: dict[str, set[str]] = defaultdict(set)
    ambiguous_titles: set[str] = set()
    for description in daily_track_descriptions:
        counts["daily_descriptions_examined"] += 1
        text = _label(description)
        if not text:
            counts["blank_or_invalid_daily_descriptions"] += 1
            continue

        possibilities: set[tuple[str, str]] = set()
        start = 0
        while True:
            offset = text.find(SEPARATOR, start)
            if offset < 0:
                break
            artist = text[:offset].strip()
            song = text[offset + len(SEPARATOR):].strip()
            if artist and song in title_event_counts:
                possibilities.add((song, artist))
            start = offset + len(SEPARATOR)

        # One daily string might split multiple ways into observed titles.
        # Abstain for all implicated titles; do not choose a delimiter casually.
        if len(possibilities) > 1:
            ambiguous_titles.update(song for song, _ in possibilities)
        elif possibilities:
            song, artist = next(iter(possibilities))
            supported_artists[song].add(artist)
        else:
            counts["daily_descriptions_without_exact_title_suffix"] += 1

    counts["distinct_event_titles"] = len(title_event_counts)
    for title, times in title_event_counts.items():
        artists = supported_artists.get(title, set())
        if title in ambiguous_titles or len(artists) > 1:
            counts["ambiguous_artist_event_rows"] += times
            counts["ambiguous_artist_title_labels"] += 1
        elif len(artists) == 1:
            counts["provisional_artist_event_rows"] += times
            counts["provisional_artist_title_labels"] += 1
        else:
            counts["unmatched_artist_event_rows"] += times
            counts["unmatched_artist_title_labels"] += 1

    return dict(sorted(counts.items()))
