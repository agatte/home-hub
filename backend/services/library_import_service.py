"""
Apple Music / iTunes library XML import service.

Parses the plist XML exported from iTunes (File > Library > Export Library),
extracts artist data, genre distribution, and playlist signals to build
a taste profile for mode-based music recommendations.
"""
import logging
import plistlib
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import delete, select

from backend.database import async_session
from backend.models import MusicArtist, TasteProfile

logger = logging.getLogger("home_hub.music.import")

# Genre-to-mode mapping for taste profile analysis
GENRE_MODE_MAP: dict[str, list[str]] = {
    "gaming": [
        "electronic", "edm", "dubstep", "drum & bass", "metal", "hard rock",
        "industrial", "synthwave", "cyberpunk", "power metal", "thrash metal",
        "alternative metal", "nu metal", "punk", "hardcore", "trap",
        "drum and bass", "dnb", "electro", "techno",
    ],
    "working": [
        "ambient", "classical", "lo-fi", "jazz", "instrumental", "new age",
        "study", "focus", "minimal", "post-rock", "downtempo", "chillhop",
        "soundtrack", "piano", "orchestral", "lofi", "lo fi",
    ],
    "relax": [
        "chill", "acoustic", "folk", "soft rock", "soul", "r&b", "bossa nova",
        "easy listening", "dream pop", "shoegaze", "indie folk", "singer-songwriter",
        "blues", "smooth jazz", "neo-soul", "soft pop",
    ],
    "social": [
        "pop", "hip-hop", "hip hop", "rap", "dance", "disco", "funk",
        "reggaeton", "latin", "party", "house", "top 40", "k-pop", "afrobeat",
        "dancehall", "r&b/soul", "urban", "club",
    ],
}

# Playlist name keywords that signal mode affinity
PLAYLIST_MODE_KEYWORDS: dict[str, list[str]] = {
    "gaming": ["game", "gaming", "hype", "energy", "pump", "battle", "boss"],
    "working": ["focus", "work", "study", "concentrate", "productive", "code", "deep"],
    "relax": ["chill", "relax", "calm", "sleep", "wind down", "mellow", "quiet"],
    "social": ["party", "dance", "pregame", "vibe", "turn up", "summer", "hits"],
}


class LibraryImportService:
    """
    Parses Apple Music/iTunes XML library exports and builds a taste profile.

    The XML is a plist with a 'Tracks' dict (keyed by track ID) and
    a 'Playlists' array. Each track has Name, Artist, Album, Genre,
    Play Count, Rating (0-100), Date Added, Total Time.
    """

    async def import_xml(self, file_path: Path) -> dict:
        """
        Parse an Apple Music library XML and persist artist data + taste profile.

        Args:
            file_path: Path to the exported XML file.

        Returns:
            Import statistics (track_count, artist_count, genre_count, etc.)
        """
        logger.info(f"Starting library import from {file_path}")

        # Parse the plist XML (synchronous but fast, stdlib)
        with open(file_path, "rb") as f:
            plist_data = plistlib.load(f)

        tracks_dict = plist_data.get("Tracks", {})
        playlists_list = plist_data.get("Playlists", [])

        if not tracks_dict:
            logger.warning("No tracks found in library XML")
            return {"track_count": 0, "artist_count": 0, "genre_count": 0}

        # Extract and aggregate artist data
        artists = self._aggregate_artists(tracks_dict)
        genre_dist = self._build_genre_distribution(artists)
        playlist_signals = self._extract_playlist_signals(
            playlists_list, tracks_dict
        )
        top_artists = self._rank_artists(artists)
        mode_genre_map = self._build_mode_genre_map(artists, playlist_signals)

        # Persist to database
        await self._save_artists(artists)
        await self._save_profile(
            genre_distribution=genre_dist,
            top_artists=top_artists,
            mode_genre_map=mode_genre_map,
            track_count=len(tracks_dict),
            artist_count=len(artists),
        )

        stats = {
            "track_count": len(tracks_dict),
            "artist_count": len(artists),
            "genre_count": len(genre_dist),
            "top_genres": sorted(
                genre_dist.items(), key=lambda x: x[1], reverse=True
            )[:10],
            "top_artists": top_artists[:10],
        }
        logger.info(
            f"Library import complete: {stats['track_count']} tracks, "
            f"{stats['artist_count']} artists, {stats['genre_count']} genres"
        )
        return stats

    def _aggregate_artists(self, tracks: dict) -> dict[str, dict]:
        """
        Aggregate track data by artist name.

        Returns:
            Dict of artist_name -> {play_count, track_count, genres, ratings}
        """
        artists: dict[str, dict] = {}

        for track in tracks.values():
            artist_name = track.get("Artist", "").strip()
            if not artist_name:
                continue

            if artist_name not in artists:
                artists[artist_name] = {
                    "play_count": 0,
                    "track_count": 0,
                    "genres": set(),
                    "ratings": [],
                }

            entry = artists[artist_name]
            entry["play_count"] += track.get("Play Count", 0)
            entry["track_count"] += 1

            genre = track.get("Genre", "").strip()
            if genre:
                entry["genres"].add(genre)

            # iTunes ratings: 0-100, step of 20 (20=1star, 100=5star)
            rating = track.get("Rating")
            if rating is not None and rating > 0:
                entry["ratings"].append(rating / 20.0)

        # Convert genre sets to sorted lists
        for entry in artists.values():
            entry["genres"] = sorted(entry["genres"])

        return artists

    def _build_genre_distribution(self, artists: dict[str, dict]) -> dict[str, float]:
        """
        Build normalized genre distribution weighted by play count.

        Returns:
            Dict of genre_name -> weight (0.0-1.0, sums to 1.0)
        """
        genre_weights: dict[str, float] = defaultdict(float)

        for entry in artists.values():
            weight = max(entry["play_count"], 1)  # at least 1 so unplayed tracks count
            for genre in entry["genres"]:
                genre_lower = genre.lower()
                genre_weights[genre_lower] += weight

        # Normalize
        total = sum(genre_weights.values())
        if total == 0:
            return {}

        return {
            genre: round(weight / total, 4)
            for genre, weight in sorted(
                genre_weights.items(), key=lambda x: x[1], reverse=True
            )
        }

    def _extract_playlist_signals(
        self, playlists: list[dict], tracks: dict
    ) -> dict[str, set[str]]:
        """
        Scan playlist names for mode-matching keywords and extract artists.

        Returns:
            Dict of mode -> set of artist names found in matching playlists.
        """
        signals: dict[str, set[str]] = defaultdict(set)

        for playlist in playlists:
            pl_name = playlist.get("Name", "").lower()
            # Skip system playlists
            if playlist.get("Master") or playlist.get("Distinguished Kind"):
                continue

            for mode, keywords in PLAYLIST_MODE_KEYWORDS.items():
                if any(kw in pl_name for kw in keywords):
                    # Extract artists from this playlist
                    for item in playlist.get("Playlist Items", []):
                        track_id = str(item.get("Track ID", ""))
                        track = tracks.get(track_id)
                        if track:
                            artist = track.get("Artist", "").strip()
                            if artist:
                                signals[mode].add(artist)

        return signals

    def _rank_artists(
        self, artists: dict[str, dict], limit: int = 50
    ) -> list[dict]:
        """
        Rank artists by weighted score (play count * rating boost).

        Returns:
            Top N artists as list of {name, score, play_count, genres}.
        """
        scored = []
        for name, entry in artists.items():
            avg_rating = (
                sum(entry["ratings"]) / len(entry["ratings"])
                if entry["ratings"]
                else 3.0  # neutral default
            )
            # Score: play_count weighted by rating (1-5 scale, centered at 3)
            score = entry["play_count"] * (1 + (avg_rating - 3) / 5)
            scored.append({
                "name": name,
                "score": round(score, 1),
                "play_count": entry["play_count"],
                "genres": entry["genres"],
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _build_mode_genre_map(
        self,
        artists: dict[str, dict],
        playlist_signals: dict[str, set[str]],
    ) -> dict[str, list[str]]:
        """
        Build a mapping of which genres the user listens to per mode.

        Combines the hardcoded GENRE_MODE_MAP with actual user data to
        find which of the user's genres match each mode.

        Returns:
            Dict of mode -> list of user genre names that match.
        """
        # Collect all user genres
        all_genres: set[str] = set()
        for entry in artists.values():
            all_genres.update(g.lower() for g in entry["genres"])

        mode_genres: dict[str, list[str]] = {}
        for mode, genre_keywords in GENRE_MODE_MAP.items():
            matched = []
            for user_genre in all_genres:
                for keyword in genre_keywords:
                    if keyword in user_genre or user_genre in keyword:
                        matched.append(user_genre)
                        break
            mode_genres[mode] = sorted(set(matched))

        return mode_genres

    async def _save_artists(self, artists: dict[str, dict]) -> None:
        """Persist aggregated artist data to database (replaces existing)."""
        async with async_session() as session:
            # Clear existing imported artists
            await session.execute(
                delete(MusicArtist).where(MusicArtist.source == "import")
            )

            for name, entry in artists.items():
                avg_rating = (
                    sum(entry["ratings"]) / len(entry["ratings"])
                    if entry["ratings"]
                    else None
                )
                session.add(MusicArtist(
                    name=name,
                    genres=entry["genres"],
                    play_count=entry["play_count"],
                    track_count=entry["track_count"],
                    rating_avg=round(avg_rating, 2) if avg_rating else None,
                    source="import",
                ))

            await session.commit()

        logger.info(f"Saved {len(artists)} artists to database")

    async def _save_profile(
        self,
        genre_distribution: dict,
        top_artists: list,
        mode_genre_map: dict,
        track_count: int,
        artist_count: int,
    ) -> None:
        """Persist taste profile (upsert singleton row)."""
        async with async_session() as session:
            result = await session.execute(select(TasteProfile).limit(1))
            profile = result.scalar_one_or_none()

            now = datetime.now(timezone.utc)

            if profile:
                profile.genre_distribution = genre_distribution
                profile.top_artists = top_artists
                profile.mode_genre_map = mode_genre_map
                profile.import_track_count = track_count
                profile.import_artist_count = artist_count
                profile.last_import_at = now
            else:
                session.add(TasteProfile(
                    genre_distribution=genre_distribution,
                    top_artists=top_artists,
                    mode_genre_map=mode_genre_map,
                    import_track_count=track_count,
                    import_artist_count=artist_count,
                    last_import_at=now,
                ))

            await session.commit()

        logger.info("Taste profile saved")

    async def get_profile(self) -> Optional[dict]:
        """
        Get the current taste profile summary.

        Returns:
            Profile dict or None if no import has been done.
        """
        async with async_session() as session:
            result = await session.execute(select(TasteProfile).limit(1))
            profile = result.scalar_one_or_none()

        if not profile:
            return None

        return {
            "genre_distribution": profile.genre_distribution,
            "top_artists": profile.top_artists,
            "mode_genre_map": profile.mode_genre_map,
            "import_track_count": profile.import_track_count,
            "import_artist_count": profile.import_artist_count,
            "last_import_at": (
                profile.last_import_at.isoformat() if profile.last_import_at else None
            ),
        }
