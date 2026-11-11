"""Synthetic-only, offline #431 rehearsal. Never register as a runtime provider.

Consent and coverage are fictional caller declarations, not authentication or
proof about real accounts. Only aggregate results leave the public interface.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from backend.services.lastfm_taste_preview import Observation, SOURCE as OVERLAY_SOURCE, overlay

SOURCE = "lastfm_unattributed"
AUTHORITY = "synthetic:lastfm_recent_assertion"
NON_OVERLAP = "synthetic:complete_sonos_coverage_non_overlap"
OVERLAP = "synthetic:confirmed_sonos_overlap"
MAX_RECORDS = 50
LOOKBACK_SECONDS = 7 * 86400


class RehearsalDenied(ValueError):
    def __init__(self):
        super().__init__("synthetic rehearsal denied")


@dataclass(frozen=True, repr=False)
class FictionalQualification:
    """Out-of-band fake source and Sonos proof; never trust provider-row fields."""

    authority: str | None = None
    sonos_proof: str | None = None

    def __repr__(self):
        return "<FictionalQualification synthetic-only>"


class FictionalConsent:
    """One batch only. Explicit opt-in is not real-world consent authority."""

    __slots__ = ("_available", "_session")

    def __init__(self, *, synthetic_only=False, allow_named_rehearsal=False):
        self._available = synthetic_only is True and allow_named_rehearsal is True
        self._session = None

    def revoke(self):
        self._available = False
        if self._session is not None:
            self._session.drop()
        self._session = None

    def __repr__(self):
        return "<FictionalConsent redacted>"

    def __reduce_ex__(self, protocol):
        raise RehearsalDenied()


def _second(value):
    # Exact ASCII UTC epoch seconds; never float, datetime guess, or date text.
    if (type(value) is str and len(value) <= 10 and value.isascii()
            and value.isdecimal()):
        second = int(value)
        if 946684800 <= second < 4102444800:
            return second
    return None


def _name(value):
    return (type(value) is str and 0 < len(value) <= 200
            and bool(value.strip()) and "|" not in value
            and all(character.isprintable() for character in value))


class NamedEvidenceRehearsal:
    """Temporary owned copies, no named export. Call drop/revoke or use with.

    No timer or background task: freshness is checked on every preview against
    an explicit fixture clock. Drop removes references, not secure memory erasure.
    Caller-owned inputs and Python debugger/traceback memory are outside this API.
    """

    __slots__ = ("_baseline", "_rows", "_consent", "_closed")

    def __init__(self, baseline, records, *, consent=None, qualifications=None):
        self._baseline = self._rows = self._consent = None
        self._closed = True
        if type(consent) is not FictionalConsent or not consent._available:
            raise RehearsalDenied()
        # A failed attempt also consumes the grant; retry needs a fresh grant.
        consent._available = False
        if (type(records) is not list or len(records) > MAX_RECORDS
                or type(qualifications) is not list
                or len(qualifications) != len(records)
                or any(type(q) is not FictionalQualification for q in qualifications)):
            raise RehearsalDenied()
        # Never let untrusted provider rows self-assert source or Sonos authority.
        # Synthetic out-of-band qualifications model the future trusted join.
        rows = []
        for row, qualification in zip(records, qualifications):
            if (type(row) is not dict or "authority" in row
                    or "sonos_proof" in row):
                rows.append(None)
                continue
            artist = row.get("artist")
            date = row.get("date")
            attr = row.get("@attr")
            values = (
                artist.get("#text") if type(artist) is dict else None,
                row.get("name"),
                date.get("uts") if type(date) is dict else None,
                (attr.get("nowplaying", "false") if type(attr) is dict
                 else "false" if attr is None else "invalid"),
                qualification.authority, qualification.sonos_proof,
            )
            clean = tuple(v if type(v) is str and len(v) <= 200 else None for v in values)
            # Invalid marker types must abstain rather than become absent.
            rows.append(clean[:3] + (clean[3] or "invalid",) + clean[4:])
        self._baseline = deepcopy(baseline)
        self._rows = rows
        self._consent = consent
        self._closed = False
        consent._session = self

    def __repr__(self):
        return "<NamedEvidenceRehearsal redacted>"

    def __reduce_ex__(self, protocol):
        raise RehearsalDenied()

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, *exc):
        self.drop()

    def _require_open(self):
        if self._closed:
            raise RehearsalDenied()

    def drop(self):
        self._closed = True
        self._rows = self._baseline = None
        if self._consent is not None:
            self._consent._session = None
        self._consent = None

    def preview(self, *, now_utc_second):
        """Return aggregate counters only; no snapshot, diagnostics, names or dates."""
        self._require_open()
        if type(now_utc_second) is not int or not 946684800 <= now_utc_second < 4102444800:
            raise RehearsalDenied()
        counts = Counter()
        assertions = {}
        for row in self._rows:
            if row is None:
                counts["malformed"] += 1
                continue
            artist, title, stamp, playing, authority, proof = row
            if authority != AUTHORITY:
                counts["missing_authority"] += 1
                continue
            if playing is not None and playing != "false":
                counts["now_playing_or_unknown_marker"] += 1
                continue
            second = _second(stamp)
            if not _name(artist) or not _name(title) or second is None:
                counts["malformed"] += 1
                continue
            if second > now_utc_second:
                counts["future"] += 1
                continue
            if second < now_utc_second - LOOKBACK_SECONDS:
                counts["stale"] += 1
                continue
            identity = (artist.strip().casefold(), title.strip().casefold(), second)
            # Most restrictive duplicate wins, independent of input order.
            status = 2 if proof == OVERLAP else 0 if proof == NON_OVERLAP else 1
            if identity in assertions:
                counts["duplicate"] += 1
            assertions[identity] = max(assertions.get(identity, 0), status)
        eligible = []
        for (artist, title, second), status in sorted(assertions.items()):
            if status:
                counts["confirmed_overlap" if status == 2 else "unknown_coverage"] += 1
            else:
                eligible.append(Observation(
                    artist, title, datetime.fromtimestamp(second, timezone.utc)))
        result = overlay(self._baseline, eligible,
                         now=datetime.fromtimestamp(now_utc_second, timezone.utc))
        # Requalify only the disposable copy. Never return identity-bearing
        # overlay diagnostics or a snapshot that could escape revocation.
        changed = 0
        for kind in ("artists", "tracks"):
            entities = getattr(result.snapshot, kind)
            original = getattr(self._baseline, kind)
            for key, entity in entities.items():
                if entity != original.get(key):
                    changed += 1
                    entities[key] = replace(entity, sources=tuple(sorted(
                        {SOURCE if s == OVERLAY_SOURCE else s for s in entity.sources})))
        return {
            "synthetic_only": True, "source": SOURCE,
            "apple_verified": False, "independent_plays_verified": False,
            "preference_inferred": False, "can_actuate": False,
            "eligible_assertions": len(eligible), "changed_entities": changed,
            "counts": dict(sorted(counts.items())),
        }
