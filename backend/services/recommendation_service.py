"""
Music recommendation service.

Uses Last.fm for similar-artist discovery and the iTunes Search API
for track metadata and 30-second preview URLs. Generates per-mode
recommendations based on the user's taste profile.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote_plus

import httpx
from sqlalchemy import delete, select, update

from backend.database import async_session
from backend.models import (
    MusicArtist,
    Recommendation,
    RecommendationFeedback,
    TasteProfile,
)
from backend.services.library_import_service import GENRE_MODE_MAP

logger = logging.getLogger("home_hub.music.recs")

LASTFM_BASE = "https://ws.audioscrobbler.com/2.0/"
ITUNES_SEARCH = "https://itunes.apple.com/search"

# Cache TTL for Last.fm similar-artist data
SIMILAR_CACHE_DAYS = 30
SEMANTIC_TAG_CACHE_TTL = timedelta(days=7)
SEMANTIC_TAG_EMPTY_CACHE_TTL = timedelta(hours=1)


class RecommendationService:
    """
    Generates per-mode music recommendations using Last.fm + iTunes APIs.

    Flow:
    1. Pull seed artists from TasteProfile matching the target mode's genres
    2. Query Last.fm for similar artists (cached in MusicArtist.similar_artists)
    3. Score candidates by genre overlap, feedback history, novelty
    4. Fetch iTunes metadata (preview URL, artwork) for top candidates
    5. Persist as Recommendation rows
    """

    def __init__(self, lastfm_api_key: Optional[str] = None) -> None:
        self._lastfm_key = lastfm_api_key
        self._http = httpx.AsyncClient(timeout=15.0)
        # Semaphore for rate limiting external API calls
        self._api_sem = asyncio.Semaphore(1)
        self._semantic_tag_cache: dict[tuple[str, str], tuple[datetime, list[dict], timedelta]] = {}

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    @property
    def enabled(self) -> bool:
        """Whether recommendations are available (requires Last.fm API key)."""
        return bool(self._lastfm_key)

    async def _load_profile(self) -> Optional[TasteProfile]:
        """Load the current imported taste profile without mutating it."""
        async with async_session() as session:
            result = await session.execute(select(TasteProfile).limit(1))
            return result.scalar_one_or_none()

    async def discover_artist_candidates(
        self,
        mode: str,
        *,
        count: int = 8,
        tracks_per_artist: int = 3,
    ) -> list[dict]:
        """Return non-persisting, provider-verified discovery candidates.

        Last.fm supplies artist adjacency; iTunes verifies concrete track
        identities and metadata.  This method deliberately does not create or
        update Recommendation rows: the shared Music Intelligence layer owns
        ranking/explanations, while durable feedback remains explicit.
        """
        if not self._lastfm_key:
            return []
        profile = await self._load_profile()
        if not profile:
            return []
        seeds = self._get_seed_artists(profile, mode)
        if not seeds:
            return []

        owned_artists = {
            str(a.get("name") or "").strip().casefold()
            for a in profile.top_artists
            if isinstance(a, dict) and a.get("name")
        }
        candidates: dict[str, dict] = {}
        for seed_name in seeds[:5]:
            similar = await self._get_similar_artists(
                seed_name, persist_cache=False,
            )
            for artist_info in similar:
                name = str(artist_info.get("name") or "").strip()
                if not name:
                    continue
                key = name.casefold()
                if key in owned_artists:
                    continue
                try:
                    match = max(0.0, min(1.0, float(artist_info.get("match", 0.0))))
                except (TypeError, ValueError):
                    match = 0.0
                current = candidates.get(key)
                if current is None or match > current["source_match"]:
                    candidates[key] = {
                        "artist_name": name,
                        "seed_artist": seed_name,
                        "source_match": match,
                    }

        ranked = sorted(
            candidates.values(),
            key=lambda item: (-item["source_match"], item["artist_name"].casefold()),
        )
        results: list[dict] = []
        for candidate in ranked:
            tracks = await self._search_itunes_tracks(
                candidate["artist_name"], limit=tracks_per_artist,
            )
            if not tracks:
                continue
            results.append({
                **candidate,
                "source": "lastfm_similar+itunes_search",
                "tracks": tracks,
            })
            if len(results) >= max(1, count):
                break
        return results

    async def generate_recommendations(
        self, mode: str, count: int = 10
    ) -> list[dict]:
        """
        Generate recommendations for a mode based on the taste profile.

        Args:
            mode: Activity mode to generate recommendations for.
            count: Number of recommendations to generate.

        Returns:
            List of recommendation dicts with artist, track, preview info.
        """
        if not self._lastfm_key:
            logger.warning("Last.fm API key not configured — skipping recommendations")
            return []

        # Load taste profile
        profile = await self._load_profile()

        if not profile:
            logger.warning("No taste profile found — import library first")
            return []

        # Get seed artists for this mode
        seeds = self._get_seed_artists(profile, mode)
        if not seeds:
            logger.info(f"No seed artists found for mode '{mode}'")
            return []

        logger.info(
            f"Generating {count} recommendations for '{mode}' from "
            f"{len(seeds)} seed artists"
        )

        # Get similar artists from Last.fm (with caching)
        candidates: dict[str, dict] = {}
        owned_artists = {a["name"].lower() for a in profile.top_artists}

        # Exclude artists already recommended in other modes
        async with async_session() as session:
            result = await session.execute(
                select(Recommendation.artist_name).where(
                    Recommendation.source_mode != mode,
                    Recommendation.status == "pending",
                )
            )
            other_mode_artists = {r[0].lower() for r in result.all()}

        for seed_name in seeds[:5]:
            similar = await self._get_similar_artists(seed_name)
            for artist_info in similar:
                name = artist_info["name"]
                name_lower = name.lower()
                # Skip artists already in library or recommended in other modes
                if name_lower in owned_artists or name_lower in other_mode_artists:
                    continue
                if name_lower not in candidates:
                    candidates[name_lower] = {
                        "name": name,
                        "match": artist_info.get("match", 0.5),
                        "seed": seed_name,
                    }

        if not candidates:
            logger.info(f"No new candidates found for mode '{mode}'")
            return []

        # Score candidates
        scored = await self._score_candidates(candidates, mode, profile)
        top = sorted(scored, key=lambda x: x["score"], reverse=True)[:count]

        # Fetch iTunes metadata for top candidates
        recommendations = []
        for candidate in top:
            itunes_data = await self._search_itunes(candidate["name"])
            rec = {
                "artist_name": candidate["name"],
                "track_name": itunes_data.get("track_name"),
                "album_name": itunes_data.get("album_name"),
                "preview_url": itunes_data.get("preview_url"),
                "artwork_url": itunes_data.get("artwork_url"),
                "itunes_url": itunes_data.get("itunes_url"),
                "source_mode": mode,
                "reason": f"Similar to {candidate['seed']} in your library",
                "score": candidate["score"],
                "status": "pending",
            }
            recommendations.append(rec)

        # Persist to database
        await self._save_recommendations(mode, recommendations)

        logger.info(
            f"Generated {len(recommendations)} recommendations for '{mode}'"
        )
        return recommendations

    async def get_recommendations(
        self, mode: str, status: str = "pending"
    ) -> list[dict]:
        """
        Get existing recommendations for a mode.

        Args:
            mode: Activity mode.
            status: Filter by status (pending, liked, dismissed).

        Returns:
            List of recommendation dicts.
        """
        async with async_session() as session:
            query = (
                select(Recommendation)
                .where(
                    Recommendation.source_mode == mode,
                    Recommendation.status == status,
                )
                .order_by(Recommendation.score.desc())
                .limit(20)
            )
            result = await session.execute(query)
            rows = result.scalars().all()

        return [
            {
                "id": r.id,
                "artist_name": r.artist_name,
                "track_name": r.track_name,
                "album_name": r.album_name,
                "preview_url": r.preview_url,
                "artwork_url": r.artwork_url,
                "itunes_url": r.itunes_url,
                "source_mode": r.source_mode,
                "reason": r.reason,
                "score": r.score,
                "status": r.status,
            }
            for r in rows
        ]

    async def update_feedback(self, rec_id: int, action: str) -> bool:
        """
        Record user feedback on a recommendation.

        Args:
            rec_id: Recommendation ID.
            action: Feedback action (liked, dismissed).

        Returns:
            True if the recommendation was found and updated.
        """
        async with async_session() as session:
            result = await session.execute(
                update(Recommendation)
                .where(Recommendation.id == rec_id)
                .values(status=action)
            )
            if result.rowcount == 0:
                return False

            session.add(RecommendationFeedback(
                recommendation_id=rec_id,
                action=action,
            ))
            await session.commit()

        logger.info(f"Recommendation {rec_id} marked as '{action}'")
        return True

    def _get_seed_artists(
        self, profile: TasteProfile, mode: str
    ) -> list[str]:
        """
        Get top artists whose genres match the target mode.

        Uses genre-based matching first, then falls back to a mode-specific
        offset into the artist list so different modes get different seeds.
        """
        mode_genres = set()
        for keyword in GENRE_MODE_MAP.get(mode, []):
            mode_genres.add(keyword.lower())

        # Also include user's mode_genre_map
        for genre in profile.mode_genre_map.get(mode, []):
            mode_genres.add(genre.lower())

        if not mode_genres:
            # Fallback: offset into artist list by mode to avoid duplicates
            mode_offset = list(GENRE_MODE_MAP.keys()).index(mode) if mode in GENRE_MODE_MAP else 0
            start = mode_offset * 5
            return [a["name"] for a in profile.top_artists[start:start + 5]]

        seeds = []
        for artist in profile.top_artists:
            artist_genres = {g.lower() for g in artist.get("genres", [])}
            if artist_genres & mode_genres:
                seeds.append(artist["name"])
                if len(seeds) >= 5:
                    break

        # If no genre match, offset by mode so each mode gets different artists
        if not seeds:
            mode_offset = list(GENRE_MODE_MAP.keys()).index(mode) if mode in GENRE_MODE_MAP else 0
            start = mode_offset * 3
            artists = profile.top_artists[start:start + 5]
            if not artists:
                artists = profile.top_artists[:5]
            seeds = [a["name"] for a in artists]

        return seeds

    async def _get_similar_artists(
        self, artist_name: str, *, persist_cache: bool = True,
    ) -> list[dict]:
        """
        Get similar artists from Last.fm (with DB cache).

        Returns:
            List of {name, match} dicts.
        """
        # Check cache
        async with async_session() as session:
            result = await session.execute(
                select(MusicArtist).where(MusicArtist.name == artist_name)
            )
            db_artist = result.scalar_one_or_none()

        if db_artist and db_artist.similar_artists and db_artist.similar_fetched_at:
            fetched_at = db_artist.similar_fetched_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - fetched_at
            if age < timedelta(days=SIMILAR_CACHE_DAYS):
                return db_artist.similar_artists

        # Query Last.fm
        similar = await self._query_lastfm_similar(artist_name)

        # Cache result for the legacy durable recommendation path only.
        # Shadow discovery may read this cache but never writes it.
        if similar and persist_cache:
            async with async_session() as session:
                if db_artist:
                    await session.execute(
                        update(MusicArtist)
                        .where(MusicArtist.name == artist_name)
                        .values(
                            similar_artists=similar,
                            similar_fetched_at=datetime.now(timezone.utc),
                        )
                    )
                await session.commit()

        return similar

    async def _query_lastfm_similar(
        self, artist_name: str, limit: int = 15
    ) -> list[dict]:
        """Query Last.fm API for similar artists."""
        async with self._api_sem:
            try:
                resp = await self._http.get(
                    LASTFM_BASE,
                    params={
                        "method": "artist.getsimilar",
                        "artist": artist_name,
                        "api_key": self._lastfm_key,
                        "format": "json",
                        "limit": limit,
                    },
                )
                await asyncio.sleep(0.2)  # Rate limit: 5 req/sec

                if resp.status_code != 200:
                    logger.warning(
                        f"Last.fm API error for '{artist_name}': {resp.status_code}"
                    )
                    return []

                data = resp.json()
                artists = data.get("similarartists", {}).get("artist", [])
                return [
                    {
                        "name": a["name"],
                        "match": float(a.get("match", 0.5)),
                    }
                    for a in artists
                    if isinstance(a, dict)
                ]

            except Exception as e:
                logger.error(f"Last.fm query failed for '{artist_name}': {e}")
                return []

    async def get_semantic_tags(
        self,
        artist_name: str,
        *,
        track_name: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Return bounded Last.fm top tags with an in-memory freshness cache."""
        if not self._lastfm_key:
            return []
        artist = str(artist_name or "").strip()
        track = str(track_name or "").strip()
        if not artist:
            return []
        cache_key = (artist.casefold(), track.casefold())
        now = datetime.now(timezone.utc)
        cached = self._semantic_tag_cache.get(cache_key)
        if cached is not None:
            fetched_at, rows, ttl = cached
            if now - fetched_at <= ttl:
                return list(rows[: max(1, limit)])
        rows = await self._query_lastfm_top_tags(
            artist, track_name=track or None, limit=max(1, min(30, limit))
        )
        ttl = SEMANTIC_TAG_CACHE_TTL if rows else SEMANTIC_TAG_EMPTY_CACHE_TTL
        self._semantic_tag_cache[cache_key] = (now, list(rows), ttl)
        return list(rows)

    async def _query_lastfm_top_tags(
        self,
        artist_name: str,
        *,
        track_name: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Query Last.fm artist.getTopTags or track.getTopTags."""
        params = {
            "method": "track.gettoptags" if track_name else "artist.gettoptags",
            "artist": artist_name,
            "api_key": self._lastfm_key,
            "format": "json",
        }
        if track_name:
            params["track"] = track_name
        async with self._api_sem:
            try:
                resp = await self._http.get(LASTFM_BASE, params=params)
                await asyncio.sleep(0.2)
                if resp.status_code != 200:
                    logger.warning(
                        "Last.fm top-tags error for '%s'%s: %s",
                        artist_name,
                        f" / '{track_name}'" if track_name else "",
                        resp.status_code,
                    )
                    return []
                tags = resp.json().get("toptags", {}).get("tag", [])
                result: list[dict] = []
                for row in tags:
                    if not isinstance(row, dict):
                        continue
                    name = str(row.get("name") or "").strip()
                    if not name:
                        continue
                    try:
                        count = int(row.get("count") or 0)
                    except (TypeError, ValueError):
                        count = 0
                    result.append({"name": name, "count": max(0, count)})
                    if len(result) >= max(1, limit):
                        break
                return result
            except Exception as exc:
                logger.warning(
                    "Last.fm top-tags query failed for '%s'%s: %s",
                    artist_name,
                    f" / '{track_name}'" if track_name else "",
                    exc,
                )
                return []
    async def _search_itunes_tracks(
        self, artist_name: str, *, limit: int = 3,
    ) -> list[dict]:
        """Return verified iTunes tracks for exactly the requested artist."""
        async with self._api_sem:
            try:
                resp = await self._http.get(
                    ITUNES_SEARCH,
                    params={
                        "term": artist_name,
                        "media": "music",
                        "entity": "song",
                        "limit": max(5, min(25, limit * 3)),
                    },
                )
                await asyncio.sleep(0.5)
                if resp.status_code != 200:
                    return []
                data = resp.json()
                results = data.get("results", [])
                verified: list[dict] = []
                seen: set[str] = set()
                wanted = artist_name.strip().casefold()
                for result in results:
                    if not isinstance(result, dict):
                        continue
                    result_artist = str(result.get("artistName") or "").strip()
                    track_name = str(result.get("trackName") or "").strip()
                    provider_id = str(result.get("trackId") or "").strip()
                    if result_artist.casefold() != wanted or not track_name or not provider_id:
                        continue
                    if provider_id in seen:
                        continue
                    seen.add(provider_id)
                    verified.append({
                        "provider": "itunes_search",
                        "provider_id": provider_id,
                        "catalog_verified": True,
                        "playback_capability": "metadata_only",
                        "playback_adapter": None,
                        "playback_reference": None,
                        "artist_name": result_artist,
                        "track_name": track_name,
                        "album_name": result.get("collectionName"),
                        "preview_url": result.get("previewUrl"),
                        "artwork_url": result.get("artworkUrl100"),
                        "external_url": result.get("trackViewUrl"),
                    })
                    if len(verified) >= max(1, limit):
                        break
                return verified
            except Exception as exc:
                logger.error("iTunes discovery search failed for '%s': %s", artist_name, exc)
                return []

    async def _search_itunes(self, artist_name: str) -> dict:
        """
        Search iTunes for an artist's top track with preview URL.

        Returns:
            Dict with track_name, album_name, preview_url, artwork_url, itunes_url.
        """
        async with self._api_sem:
            try:
                resp = await self._http.get(
                    ITUNES_SEARCH,
                    params={
                        "term": artist_name,
                        "media": "music",
                        "limit": 3,
                    },
                )
                await asyncio.sleep(0.5)  # iTunes undocumented rate limit

                if resp.status_code != 200:
                    return {}

                data = resp.json()
                results = data.get("results", [])
                if not results:
                    return {}

                # Pick the first result with a preview URL
                for result in results:
                    if result.get("previewUrl"):
                        return {
                            "track_name": result.get("trackName"),
                            "album_name": result.get("collectionName"),
                            "preview_url": result.get("previewUrl"),
                            "artwork_url": result.get("artworkUrl100"),
                            "itunes_url": result.get("trackViewUrl"),
                        }

                # Fallback: first result without preview
                r = results[0]
                return {
                    "track_name": r.get("trackName"),
                    "album_name": r.get("collectionName"),
                    "preview_url": None,
                    "artwork_url": r.get("artworkUrl100"),
                    "itunes_url": r.get("trackViewUrl"),
                }

            except Exception as e:
                logger.error(f"iTunes search failed for '{artist_name}': {e}")
                return {}

    async def _score_candidates(
        self,
        candidates: dict[str, dict],
        mode: str,
        profile: TasteProfile,
    ) -> list[dict]:
        """Score recommendation candidates."""
        # Load feedback history
        async with async_session() as session:
            result = await session.execute(
                select(Recommendation).where(
                    Recommendation.source_mode == mode,
                    Recommendation.status.in_(["liked", "dismissed"]),
                )
            )
            feedback = result.scalars().all()

        liked_artists = {r.artist_name.lower() for r in feedback if r.status == "liked"}
        dismissed_artists = {r.artist_name.lower() for r in feedback if r.status == "dismissed"}

        # Mode genres for scoring
        mode_genres = set()
        for keyword in GENRE_MODE_MAP.get(mode, []):
            mode_genres.add(keyword.lower())

        scored = []
        for name_lower, info in candidates.items():
            score = info["match"]  # Base: Last.fm similarity (0-1)

            # Boost if previously liked similar artist
            if name_lower in liked_artists:
                score += 0.3
            # Penalty if previously dismissed
            if name_lower in dismissed_artists:
                score -= 0.5

            scored.append({
                "name": info["name"],
                "score": round(score, 3),
                "seed": info["seed"],
            })

        return scored

    async def _save_recommendations(
        self, mode: str, recommendations: list[dict]
    ) -> None:
        """Persist recommendations to database (clears old pending for mode)."""
        async with async_session() as session:
            # Remove old pending recommendations for this mode
            await session.execute(
                delete(Recommendation).where(
                    Recommendation.source_mode == mode,
                    Recommendation.status == "pending",
                )
            )

            for rec in recommendations:
                session.add(Recommendation(**rec))

            await session.commit()
