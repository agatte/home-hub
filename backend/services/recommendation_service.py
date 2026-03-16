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

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()

    @property
    def enabled(self) -> bool:
        """Whether recommendations are available (requires Last.fm API key)."""
        return bool(self._lastfm_key)

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
        async with async_session() as session:
            result = await session.execute(select(TasteProfile).limit(1))
            profile = result.scalar_one_or_none()

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

        for seed_name in seeds[:5]:
            similar = await self._get_similar_artists(seed_name)
            for artist_info in similar:
                name = artist_info["name"]
                name_lower = name.lower()
                # Skip artists already in library
                if name_lower in owned_artists:
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
        """Get top artists whose genres match the target mode."""
        mode_genres = set()
        for keyword in GENRE_MODE_MAP.get(mode, []):
            mode_genres.add(keyword.lower())

        # Also include user's mode_genre_map
        for genre in profile.mode_genre_map.get(mode, []):
            mode_genres.add(genre.lower())

        if not mode_genres:
            # Fallback: use top artists regardless of genre
            return [a["name"] for a in profile.top_artists[:5]]

        seeds = []
        for artist in profile.top_artists:
            artist_genres = {g.lower() for g in artist.get("genres", [])}
            if artist_genres & mode_genres:
                seeds.append(artist["name"])
                if len(seeds) >= 5:
                    break

        # If no genre match, fall back to top artists
        if not seeds:
            seeds = [a["name"] for a in profile.top_artists[:3]]

        return seeds

    async def _get_similar_artists(self, artist_name: str) -> list[dict]:
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
            age = datetime.now(timezone.utc) - db_artist.similar_fetched_at
            if age < timedelta(days=SIMILAR_CACHE_DAYS):
                return db_artist.similar_artists

        # Query Last.fm
        similar = await self._query_lastfm_similar(artist_name)

        # Cache result
        if similar:
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
