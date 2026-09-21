"""
Music mapper — maps activity modes to Sonos favorites/playlists.

Supports multiple favorites per mode, each optionally tagged with a vibe
(energetic, mellow, focus, background, hype). On mode change, the mapper
picks the best-matching vibe based on time of day, then auto-plays or
broadcasts a suggestion via WebSocket. Mappings persist to SQLite.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select

from backend.database import async_session
from backend.models import ModePlaylist
from backend.services.audio_ownership import QUEUE_SOURCE, TRANSPORT, VOLUME
from backend.services.mode_volume_policy import compute_mode_volume
from backend.services.mode_volume_service import MODE_VOLUME_CURVES_KEY

logger = logging.getLogger("home_hub.music")

# Real 2026 preseason evidence showed the global TTS default (10) was too quiet
# for the T-30 room announcement. Keep this local to Game Day.
PREGAME_TTS_VOLUME = 24
PREGAME_TTS_LATE_NIGHT_CAP = 18
PREGAME_HYPE_SETTLE_ATTEMPTS = 20
PREGAME_HYPE_SETTLE_INTERVAL_SECONDS = 0.15
# Bounded Game Day fallback only. Any explicit pregameday mapping wins.
DEFAULT_PREGAME_HYPE_FAVORITE = "It's Lit!"

MODE_AUTOPLAY_OWNER = "music_mapper"
MODE_AUTOPLAY_PURPOSE = "mode_auto_play"

_PREGAME_SOURCE_TRANSPORT_KEYS = (
    "queue_uid",
    "queue_update_id",
    "queue_size",
    "queue_first_item_hash",
    "play_mode",
    "transport_state",
    "current_uri",
    "queue_track",
    "queue_track_uri",
)

TZ = ZoneInfo("America/Indiana/Indianapolis")

SUPPORTED_MODES = (
    "gaming", "working", "watching", "social", "relax", "cooking",
    # Pregameday is supported so users can add a hype playlist via
    # POST /api/music/mode-playlists, but on_mode_change() short-circuits
    # to enforce the silent T-60 build window — the row is read by the
    # dispatch_pregame_audio() handler when pregameday→gameday transitions.
    "pregameday",
)
VALID_VIBES = ("energetic", "mellow", "focus", "background", "hype")

# Time-of-day → preferred vibe order (first match wins)
_TIME_VIBE_PREFERENCE: dict[str, list[str]] = {
    "morning": ["focus", "mellow", "background", "energetic", "hype"],   # 5-10
    "day": ["energetic", "focus", "background", "mellow", "hype"],        # 10-18
    "evening": ["mellow", "background", "focus", "energetic", "hype"],    # 18-22
    "night": ["mellow", "background", "focus", "energetic", "hype"],      # 22-5
}

# Weather condition → preferred vibe order. Only precipitation/storms
# warrant a music suggestion; clouds and golden hour don't.
_WEATHER_VIBE_OVERRIDE: dict[str, list[str]] = {
    "thunderstorm": ["background", "mellow", "focus", "energetic", "hype"],
    "rain": ["mellow", "background", "focus", "energetic", "hype"],
    "snow": ["mellow", "focus", "background", "energetic", "hype"],
}

# Modes that skip weather music suggestions (party/sleep have their own thing)
_WEATHER_MUSIC_SKIP_MODES = frozenset(("social", "sleeping"))


def _time_period(hour: int) -> str:
    if 5 <= hour < 10:
        return "morning"
    if 10 <= hour < 18:
        return "day"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def _pregame_tts_volume(now: Optional[datetime] = None) -> int:
    """Game Day T-30 speech volume with the spec's 22:00-06:00 cap."""
    local_now = now.astimezone(TZ) if now is not None else datetime.now(tz=TZ)
    if local_now.hour >= 22 or local_now.hour < 6:
        return min(PREGAME_TTS_VOLUME, PREGAME_TTS_LATE_NIGHT_CAP)
    return PREGAME_TTS_VOLUME


class MusicMapper:
    """
    Maps activity modes to Sonos favorites for automatic playlist playback.

    Supports multiple favorites per mode via vibe tags. On mode change,
    picks the best vibe for the current time of day. Mappings persist
    to the mode_playlists SQLite table.
    """

    def __init__(
        self,
        sonos_service,
        ws_manager,
        event_logger=None,
        music_bandit=None,
        weather_service=None,
        tts_service=None,
        audio_ownership=None,
        setting_loader=None,
    ) -> None:
        self._sonos = sonos_service
        self._ws_manager = ws_manager
        self._event_logger = event_logger
        self._music_bandit = music_bandit
        self._audio_ownership = audio_ownership
        self._setting_loader = setting_loader
        # Phase B (2026-05-12): weather context for the bandit's 4-tuple
        # arm key. Optional — when None the bandit falls back to its
        # WEATHER_ANY sentinel and behaves like Phase A's 3-tuple shape.
        self._weather_service = weather_service
        # GAMEDAY_SPEC §10.3 audio dispatch — TTS for the pregameday→gameday
        # transition. Optional injection; when unset, dispatch_pregame_audio
        # skips the TTS step and still fires Sonos hype if the decision asks.
        self._tts_service = tts_service
        # Cache: mode -> list[{id, favorite_title, vibe, auto_play, priority}]
        self._cache: dict[str, list[dict]] = {m: [] for m in SUPPORTED_MODES}
        # Tracks the most recent mode requested — used to skip stale auto-plays
        self._last_requested_mode: Optional[str] = None
        # Set post-construction by bootstrap once AutomationEngine exists
        # (chicken-and-egg — engine needs music_mapper, music_mapper needs
        # engine for is_dnd_active() in on_mode_change / on_weather_change).
        self._automation = None

    def set_automation(self, automation) -> None:
        """Inject the automation engine reference (called from bootstrap)."""
        self._automation = automation

    def _pregame_audio_lifecycle_reason(
        self,
        *,
        synthetic: bool = False,
    ) -> Optional[str]:
        """Return why a pending T-30 audio action is no longer allowed."""
        if self._automation is None:
            return None
        mode = str(getattr(self._automation, "current_mode", "") or "").strip()
        allowed_modes = {"gameday", "pregameday"} if synthetic else {"gameday"}
        if mode not in allowed_modes:
            return f"mode_changed:{mode or 'unknown'}"
        house_state = str(
            getattr(self._automation, "house_state", "") or ""
        ).strip().casefold()
        if house_state in {"away", "sleeping"}:
            return f"house_state:{house_state}"
        try:
            if self._automation.is_dnd_active():
                return "dnd_active"
        except Exception:
            return "dnd_authority_unavailable"
        return None

    @staticmethod
    def _pregame_source_transport_matches(
        first: dict | None,
        second: dict | None,
    ) -> bool:
        if not first or not second:
            return False
        return all(
            first.get(key) == second.get(key)
            for key in _PREGAME_SOURCE_TRANSPORT_KEYS
        )

    @staticmethod
    def _pregame_hype_baseline_replaceable(
        evidence: dict | None,
    ) -> bool:
        """Whether an idle Sonos source may be conditionally replaced at T-30.

        Pregame may replace an unchanged stopped queue from earlier listening,
        but active/paused playback and mute are authoritative user intent.
        """
        if not evidence:
            return False
        if str(evidence.get("transport_state") or "").upper() not in {
            "STOPPED",
            "NO_MEDIA_PRESENT",
        }:
            return False
        return not bool(evidence.get("mute"))

    async def _pregame_hype_volume_target(
        self,
        *,
        current_volume: int,
    ) -> tuple[Optional[int], Optional[str]]:
        """Resolve the existing Game Day mode-volume policy for startup."""
        config = {}
        if self._setting_loader is not None:
            try:
                config = await self._setting_loader(MODE_VOLUME_CURVES_KEY) or {}
            except Exception:
                logger.exception("pregame hype mode-volume config read failed")
                return None, "volume_policy_unavailable"

        if self._automation is not None:
            period_getter = getattr(self._automation, "_get_time_period", None)
            try:
                period = (
                    str(period_getter())
                    if callable(period_getter)
                    else _time_period(datetime.now(tz=TZ).hour)
                )
            except Exception:
                return None, "volume_policy_unavailable"
        else:
            period = _time_period(datetime.now(tz=TZ).hour)

        decision = compute_mode_volume(
            "gameday",
            time_period=period,
            dnd=False,
            current_volume=int(current_volume),
            config=config,
        )
        target = int(decision.target)
        if decision.reason == "no_curve":
            return None, "volume_policy_unavailable"
        if target <= 0:
            return None, "gameday_volume_zero"
        return target, None

    async def _reserve_pregame_hype_lease(
        self,
        baseline_playback: dict | None,
    ) -> tuple[dict | None, str | None]:
        """Hold Game Day authority across TTS + the post-speech settle gap."""
        if self._audio_ownership is None:
            return None, "ownership_unavailable"
        if baseline_playback is None:
            return None, "ownership_preflight_unavailable"
        if not self._pregame_hype_baseline_replaceable(baseline_playback):
            if bool(baseline_playback.get("mute")):
                return None, "sonos_muted_before_tts"
            state = str(
                baseline_playback.get("transport_state") or "unknown"
            ).lower()
            return None, f"sonos_busy_before_tts:{state}"

        # Do not mark this as phase=reserved: TTS interruption leases are
        # allowed to overlay established owners, while manual ingress still
        # invalidates the exact queue/transport/volume dimensions underneath.
        lease = await self._audio_ownership.acquire(
            owner=MODE_AUTOPLAY_OWNER,
            purpose=MODE_AUTOPLAY_PURPOSE,
            dimensions=(QUEUE_SOURCE, TRANSPORT, VOLUME),
            evidence={"phase": "pending_hype", "sonos": baseline_playback},
            metadata={
                "mode": "gameday",
                "favorite_title": "pregame_hype_pending",
                "source": "pregame_audio",
            },
        )
        if lease is None:
            return None, "audio_ownership_busy"
        return lease, None

    async def _release_pregame_lease(
        self,
        lease: dict | None,
        *,
        reason: str,
    ) -> None:
        if self._audio_ownership is None or lease is None:
            return
        if await self._audio_ownership.is_valid(lease["lease_id"]):
            await self._audio_ownership.release(
                lease["lease_id"],
                reason=reason,
            )

    async def _play_pregame_hype_owned(
        self,
        *,
        title: str,
        baseline_playback: dict | None,
        lease: dict | None,
        synthetic: bool = False,
    ) -> tuple[bool, str]:
        """Start hype only while the pre-TTS authority/evidence still holds."""
        lifecycle_reason = self._pregame_audio_lifecycle_reason(
            synthetic=synthetic,
        )
        if lifecycle_reason:
            await self._release_pregame_lease(
                lease, reason=f"pregame_hype_lifecycle:{lifecycle_reason}",
            )
            return False, f"lifecycle:{lifecycle_reason}"
        if not self._sonos.connected:
            await self._release_pregame_lease(
                lease, reason="pregame_hype_sonos_disconnected",
            )
            return False, "sonos_disconnected"
        if baseline_playback is None or lease is None:
            return False, "ownership_preflight_unavailable"
        if not await self._audio_ownership.is_valid(
            lease["lease_id"], (QUEUE_SOURCE, TRANSPORT),
        ):
            await self._release_pregame_lease(
                lease, reason="pregame_hype_manual_source_takeover",
            )
            return False, "manual_source_takeover_during_tts_gap"

        final_playback = await self._sonos.get_playback_ownership_evidence()
        if not self._pregame_source_transport_matches(
            baseline_playback,
            final_playback,
        ):
            await self._release_pregame_lease(
                lease, reason="pregame_hype_source_changed",
            )
            return False, "sonos_source_changed_during_tts_gap"
        if not self._pregame_hype_baseline_replaceable(final_playback):
            await self._release_pregame_lease(
                lease, reason="pregame_hype_sonos_busy_after_tts",
            )
            if bool((final_playback or {}).get("mute")):
                return False, "sonos_muted_after_tts"
            return False, "sonos_busy_after_tts"

        baseline_volume = int(baseline_playback.get("volume") or 0)
        final_volume = int((final_playback or {}).get("volume") or 0)
        volume_lease_valid = await self._audio_ownership.is_valid(
            lease["lease_id"], (VOLUME,),
        )
        # Central manual volume invalidates VOLUME. Off-dashboard volume
        # changes cannot touch the lease, so the value comparison provides the
        # equivalent protection without blocking queue/transport hype.
        volume_still_owned = (
            volume_lease_valid and final_volume == baseline_volume
        )
        if not volume_still_owned and volume_lease_valid:
            # Off-dashboard volume changes do not invalidate central leases.
            # Relinquish our stale volume claim before continuing at the
            # externally selected level.
            await self._audio_ownership.release(
                lease["lease_id"],
                dimensions=(VOLUME,),
                reason="pregame_hype_external_volume_change",
            )

        startup_volume: Optional[int] = None
        if volume_still_owned:
            startup_volume, volume_reason = await self._pregame_hype_volume_target(
                current_volume=final_volume,
            )
            if startup_volume is None:
                await self._release_pregame_lease(
                    lease,
                    reason=f"pregame_hype_{volume_reason or 'volume_policy_unavailable'}",
                )
                return False, str(volume_reason or "volume_policy_unavailable")

        play_reason = "play_failed"
        ownership_established = False
        try:
            async def _owned_play() -> tuple[bool, str]:
                reason = self._pregame_audio_lifecycle_reason(
                    synthetic=synthetic,
                )
                if reason:
                    return False, f"lifecycle:{reason}"

                latest = await self._sonos.get_playback_ownership_evidence()
                if not self._pregame_source_transport_matches(
                    final_playback,
                    latest,
                ):
                    return False, "sonos_changed_before_play"
                if not self._pregame_hype_baseline_replaceable(latest):
                    if bool((latest or {}).get("mute")):
                        return False, "sonos_muted_before_play"
                    return False, "sonos_busy_before_play"

                success = await self._sonos.play_favorite(
                    title,
                    expected_queue_evidence=latest,
                )
                return bool(success), "played" if success else "play_failed"

            executed, outcome = await asyncio.wait_for(
                self._audio_ownership.run_if_valid(
                    lease["lease_id"],
                    (QUEUE_SOURCE, TRANSPORT),
                    _owned_play,
                ),
                timeout=12.0,
            )
            if not executed:
                play_reason = "audio_ownership_invalidated"
                return False, play_reason
            success, play_reason = outcome
            if not success:
                return False, play_reason

            # Sonos queue replacement returns before the player necessarily
            # leaves TRANSITIONING. Keep the lease and wait boundedly for the
            # exact new queue to become PLAYING before applying startup volume
            # or claiming durable ownership. Every sample re-proves central
            # queue/transport authority; volume-only takeover is yielded
            # independently and never blocks the hype source.
            settled_playback = None
            for _ in range(PREGAME_HYPE_SETTLE_ATTEMPTS):
                if not await self._audio_ownership.is_valid(
                    lease["lease_id"], (QUEUE_SOURCE, TRANSPORT),
                ):
                    break
                candidate = await self._sonos.get_playback_ownership_evidence()
                if candidate is None:
                    await asyncio.sleep(PREGAME_HYPE_SETTLE_INTERVAL_SECONDS)
                    continue

                if (
                    startup_volume is not None
                    and await self._audio_ownership.is_valid(
                        lease["lease_id"], (VOLUME,),
                    )
                    and int(candidate.get("volume") or 0) != final_volume
                ):
                    await self._audio_ownership.release(
                        lease["lease_id"],
                        dimensions=(VOLUME,),
                        reason="pregame_hype_volume_changed_during_settle",
                    )
                    startup_volume = None

                if (
                    str(candidate.get("transport_state") or "").upper() == "PLAYING"
                    and str(candidate.get("play_mode") or "").upper() == "SHUFFLE"
                    and int(candidate.get("queue_size") or 0) > 0
                    and str(candidate.get("current_uri") or "").startswith(
                        "x-rincon-queue:"
                    )
                ):
                    settled_playback = candidate
                    break
                await asyncio.sleep(PREGAME_HYPE_SETTLE_INTERVAL_SECONDS)

            # Apply the Game Day target only after playback is settled. The
            # conditional writer re-reads the full queue/transport/volume
            # fingerprint synchronously, so a racing manual/source change wins.
            if (
                startup_volume is not None
                and settled_playback is not None
                and await self._audio_ownership.is_valid(
                    lease["lease_id"], (VOLUME,),
                )
            ):
                async def _owned_volume() -> bool:
                    return await self._sonos.set_volume_if_playback_unchanged(
                        settled_playback,
                        startup_volume,
                    )

                volume_executed, volume_applied = await self._audio_ownership.run_if_valid(
                    lease["lease_id"],
                    (QUEUE_SOURCE, TRANSPORT, VOLUME),
                    _owned_volume,
                )
                if not volume_executed or not volume_applied:
                    logger.info(
                        "pregame hype kept current Sonos volume: "
                        "manual/ownership/playback evidence changed"
                    )

            if await self._audio_ownership.is_valid(lease["lease_id"], (VOLUME,)):
                await self._audio_ownership.release(
                    lease["lease_id"],
                    dimensions=(VOLUME,),
                    reason="pregame_hype_startup_volume_complete",
                )

            sonos_evidence = None
            if (
                settled_playback is not None
                and await self._audio_ownership.is_valid(
                    lease["lease_id"], (QUEUE_SOURCE, TRANSPORT),
                )
            ):
                candidate = await self._sonos.get_queue_ownership_evidence()
                if self._pregame_source_transport_matches(
                    settled_playback,
                    candidate,
                ):
                    sonos_evidence = candidate

            if (
                sonos_evidence is not None
                and await self._audio_ownership.is_valid(
                    lease["lease_id"], (QUEUE_SOURCE, TRANSPORT),
                )
            ):
                await self._audio_ownership.update_evidence(
                    lease["lease_id"],
                    {
                        "phase": "owned",
                        "sonos": sonos_evidence,
                        "favorite_title": title,
                    },
                )
                ownership_established = True
            else:
                await self._release_pregame_lease(
                    lease,
                    reason="pregame_hype_evidence_unavailable",
                )
                logger.warning(
                    "Pregame hype started without durable queue ownership evidence; "
                    "later mode exit will leave Sonos untouched"
                )
            return True, "played"
        except asyncio.TimeoutError:
            play_reason = "timeout"
            return False, play_reason
        finally:
            if play_reason != "played" or not ownership_established:
                # Never leave an unproven durable claim behind. Playback may
                # already have started, but retirement is authority-only and
                # deliberately does not mutate Sonos.
                await self._release_pregame_lease(
                    lease,
                    reason=f"pregame_hype_{play_reason}_unproven",
                )

    async def _release_mode_audio_lease(self, new_mode: str) -> None:
        """Retire a mode lease without destructive off-dashboard cleanup.

        Sonos exposes no conditional/CAS Stop or Clear. Even an exact queue
        fingerprint can become stale in the gap between proof and mutation if
        a physical/app Next wins. Until #273 has a stronger device/provider
        primitive, mode exit must surrender HomeHub ownership and leave Sonos
        untouched.
        """
        if self._audio_ownership is None:
            return
        lease = await self._audio_ownership.find_lease(
            owner=MODE_AUTOPLAY_OWNER,
            purpose=MODE_AUTOPLAY_PURPOSE,
        )
        if lease is None:
            return
        metadata = lease.get("metadata") or {}
        if str(metadata.get("mode") or "") == new_mode:
            return

        await self._audio_ownership.release(
            lease["lease_id"],
            reason=f"mode_exit_no_cas_cleanup:{metadata.get('mode')}->{new_mode}",
        )
        logger.info(
            "Retired mode audio lease without Sonos mutation mode=%s "
            "favorite=%s next_mode=%s reason=no_conditional_sonos_cleanup",
            metadata.get("mode"),
            metadata.get("favorite_title"),
            new_mode,
        )

    async def _reserve_mode_audio_lease(
        self, *, mode: str, title: str,
    ) -> dict | None:
        if self._audio_ownership is None:
            return None
        return await self._audio_ownership.acquire(
            owner=MODE_AUTOPLAY_OWNER,
            purpose=MODE_AUTOPLAY_PURPOSE,
            dimensions=(QUEUE_SOURCE, TRANSPORT),
            evidence={"phase": "reserved"},
            metadata={"mode": mode, "favorite_title": title},
        )

    @staticmethod
    def _queue_is_neutral_for_autoplay(evidence: dict | None) -> bool:
        if not evidence:
            return False
        if evidence.get("transport_state") not in {"STOPPED", "NO_MEDIA_PRESENT"}:
            return False
        if evidence.get("play_mode") != "NORMAL":
            return False
        if int(evidence.get("queue_size") or 0) != 0:
            return False
        uri = str(evidence.get("current_uri") or "")
        if not uri:
            return True
        queue_uid = str(evidence.get("queue_uid") or "")
        return bool(queue_uid) and uri == f"x-rincon-queue:{queue_uid}#0"

    def _current_weather_class(self) -> str:
        """Return the bandit-shape weather class for the current observation.

        Falls back to ``WEATHER_ANY`` when no weather_service is wired or
        no observation has been cached yet. Sync (no awaitable) so it can
        be called from ``pick_playlist``.
        """
        from backend.services.weather_class import WEATHER_ANY, classify_for_bandit
        if not self._weather_service:
            return WEATHER_ANY
        try:
            weather = self._weather_service.get_cached()
        except Exception as e:
            logger.debug("weather_service.get_cached() failed: %s", e)
            return WEATHER_ANY
        return classify_for_bandit(weather)

    async def load_from_db(self) -> None:
        """Load all mode-playlist mappings from the database into cache."""
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist).order_by(ModePlaylist.priority.desc())
            )
            rows = result.scalars().all()

        self._cache = {m: [] for m in SUPPORTED_MODES}
        for row in rows:
            if row.mode in self._cache:
                self._cache[row.mode].append({
                    "id": row.id,
                    "favorite_title": row.favorite_title,
                    "vibe": row.vibe,
                    "auto_play": row.auto_play,
                    "priority": row.priority,
                })

        total = sum(len(v) for v in self._cache.values())
        logger.info(f"Loaded {total} mode-playlist mappings from DB")

    @property
    def mapping(self) -> dict[str, list[dict]]:
        """Current mode-to-playlist mappings, all modes included."""
        return {mode: list(entries) for mode, entries in self._cache.items()}

    def pick_playlist(self, mode: str, vibe: Optional[str] = None) -> Optional[dict]:
        """
        Select the best playlist entry for a mode.

        If vibe is specified, filters to that vibe (falls back to any entry
        if none match). If vibe is None, uses the Thompson sampling bandit
        (if available) or falls back to the time-of-day heuristic.

        Returns:
            Entry dict {id, favorite_title, vibe, auto_play, priority}, or None.
        """
        entries = self._cache.get(mode, [])
        if not entries:
            return None

        if vibe:
            match = next((e for e in entries if e["vibe"] == vibe), None)
            return match or entries[0]

        hour = datetime.now(tz=TZ).hour
        period = _time_period(hour)
        preference = _TIME_VIBE_PREFERENCE[period]

        # Try Thompson sampling bandit first
        if self._music_bandit and len(entries) > 1:
            pick = self._music_bandit.select(
                mode=mode,
                period=period,
                candidates=entries,
                preferred_vibes=preference,
                weather=self._current_weather_class(),
            )
            if pick:
                return pick

        # Fallback: time-of-day vibe heuristic
        for preferred_vibe in preference:
            match = next((e for e in entries if e["vibe"] == preferred_vibe), None)
            if match:
                return match

        # Fallback: highest priority entry
        return entries[0]

    async def add_mapping(
        self,
        mode: str,
        favorite_title: str,
        vibe: Optional[str] = None,
        auto_play: bool = False,
        priority: int = 0,
    ) -> int:
        """
        Add or update a mode-to-playlist mapping. Persists to database.

        If the same (mode, favorite_title) already exists, updates its vibe,
        auto_play, and priority in place.

        Args:
            mode: Activity mode.
            favorite_title: Sonos favorite name.
            vibe: Optional vibe tag (energetic/mellow/focus/background/hype).
            auto_play: Whether to auto-play on mode change.
            priority: Higher priority entries are preferred (default 0).

        Returns:
            Database ID of the created or updated row.
        """
        existing_row = None
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist).where(
                    ModePlaylist.mode == mode,
                    ModePlaylist.favorite_title == favorite_title,
                )
            )
            existing_row = result.scalar_one_or_none()

            if existing_row:
                existing_row.vibe = vibe
                existing_row.auto_play = auto_play
                existing_row.priority = priority
                row_id = existing_row.id
            else:
                row = ModePlaylist(
                    mode=mode,
                    favorite_title=favorite_title,
                    vibe=vibe,
                    auto_play=auto_play,
                    priority=priority,
                )
                session.add(row)
                await session.flush()
                row_id = row.id

            await session.commit()

        await self._reload_mode(mode)
        action = "updated" if existing_row else "added"
        logger.info(
            f"Music mapping {action}: {mode} -> '{favorite_title}' "
            f"vibe={vibe} auto_play={auto_play}"
        )
        return row_id

    async def remove_mapping_by_id(self, mapping_id: int) -> bool:
        """
        Remove a specific mapping by database ID.

        Returns:
            True if removed, False if not found.
        """
        mode = None
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist).where(ModePlaylist.id == mapping_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return False
            mode = row.mode
            await session.delete(row)
            await session.commit()

        await self._reload_mode(mode)
        logger.info(f"Music mapping {mapping_id} removed")
        return True

    async def remove_all_for_mode(self, mode: str) -> int:
        """Remove all mappings for a mode. Returns count removed."""
        async with async_session() as session:
            result = await session.execute(
                delete(ModePlaylist).where(ModePlaylist.mode == mode)
            )
            await session.commit()
            count = result.rowcount

        self._cache[mode] = []
        if count:
            logger.info(f"Removed {count} mappings for mode '{mode}'")
        return count

    async def _reload_mode(self, mode: str) -> None:
        """Refresh the cache for a single mode from the database."""
        async with async_session() as session:
            result = await session.execute(
                select(ModePlaylist)
                .where(ModePlaylist.mode == mode)
                .order_by(ModePlaylist.priority.desc())
            )
            rows = result.scalars().all()

        self._cache[mode] = [
            {
                "id": row.id,
                "favorite_title": row.favorite_title,
                "vibe": row.vibe,
                "auto_play": row.auto_play,
                "priority": row.priority,
            }
            for row in rows
        ]

    async def on_mode_change(self, mode: str) -> Optional[dict]:
        """
        Handle a mode change — smart auto-play based on Sonos state.

        Picks the playlist via pick_playlist() — Thompson sampling bandit
        if available, else the time-of-day vibe heuristic.
        If Sonos is idle and auto_play is set, starts the playlist.
        If Sonos is busy, broadcasts a suggestion via WebSocket.

        Args:
            mode: The new activity mode.

        Returns:
            Dict describing the action taken, or None.
        """
        await self._release_mode_audio_lease(mode)

        if self._automation is not None and self._automation.is_dnd_active():
            logger.debug("DND active — skipping music mode-change handling for %s", mode)
            return None

        # Pregameday is the T-60 silent visual build — audio dispatch fires
        # via the dedicated pregameday→gameday transition handler at T-30,
        # NOT on entry to pregameday. Skip auto-play here even if a row
        # exists (GAMEDAY_SPEC §10.3).
        if mode == "pregameday":
            logger.debug("pregameday entry — silent build, no auto-play")
            return None

        # Away: nobody home — pause Sonos if it's playing. Skip the rest of
        # the auto-play flow regardless. Returning home clears the away
        # override; the user's pre-departure mode resumes via the priority
        # guard, which fires its own auto-play callback. Music doesn't
        # auto-resume — that's a deliberate choice (the speaker shouldn't
        # blast the second you walk in the door).
        if mode == "away":
            if self._sonos.connected:
                try:
                    status = await asyncio.wait_for(
                        self._sonos.get_status(), timeout=5.0,
                    )
                    if status.get("state") == "PLAYING":
                        await asyncio.wait_for(self._sonos.pause(), timeout=5.0)
                        logger.info("Away mode: paused Sonos playback")
                except asyncio.TimeoutError:
                    logger.warning("Away mode: Sonos pause timed out")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Away mode: Sonos pause failed: %s", exc)
            return None

        self._last_requested_mode = mode

        entry = self.pick_playlist(mode)
        if not entry or not entry.get("auto_play"):
            return None

        title = entry["favorite_title"]
        vibe = entry.get("vibe")

        if not self._sonos.connected:
            logger.warning("Sonos not connected — skipping music auto-play")
            return None

        try:
            try:
                status = await asyncio.wait_for(
                    self._sonos.get_status(), timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("Sonos get_status timed out (5s) — skipping auto-play")
                return None
            sonos_state = status.get("state", "STOPPED")

            if sonos_state in ("STOPPED", "NO_MEDIA_PRESENT"):
                if self._last_requested_mode != mode:
                    logger.info(
                        "Mode changed during auto-play setup ('%s' → '%s'), skipping.",
                        mode, self._last_requested_mode,
                    )
                    return None
                preflight_evidence = None
                if self._audio_ownership is not None:
                    preflight_evidence = (
                        await self._sonos.get_queue_ownership_evidence()
                    )
                    if not self._queue_is_neutral_for_autoplay(preflight_evidence):
                        logger.info(
                            "Sonos carries existing queue/source ownership — "
                            "suggesting '%s' instead of auto-play",
                            title,
                        )
                        await self._ws_manager.broadcast("music_suggestion", {
                            "mode": mode,
                            "title": title,
                            "vibe": vibe,
                            "message": f"Play '{title}' for {mode} mode?",
                        })
                        return {
                            "action": "suggested",
                            "title": title,
                            "vibe": vibe,
                        }

                lease = await self._reserve_mode_audio_lease(mode=mode, title=title)
                if self._audio_ownership is not None and lease is None:
                    logger.info(
                        "Audio ownership busy — suggesting '%s' instead of auto-play",
                        title,
                    )
                    await self._ws_manager.broadcast("music_suggestion", {
                        "mode": mode,
                        "title": title,
                        "vibe": vibe,
                        "message": f"Play '{title}' for {mode} mode?",
                    })
                    return {"action": "suggested", "title": title, "vibe": vibe}
                try:
                    if lease is not None:
                        async def _owned_play():
                            return await self._sonos.play_favorite(
                                title,
                                expected_queue_evidence=preflight_evidence,
                            )

                        executed, success = await asyncio.wait_for(
                            self._audio_ownership.run_if_valid(
                                lease["lease_id"],
                                (QUEUE_SOURCE, TRANSPORT),
                                _owned_play,
                            ),
                            timeout=6.0,
                        )
                        if not executed:
                            return None
                    else:
                        success = await asyncio.wait_for(
                            self._sonos.play_favorite(title), timeout=6.0
                        )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Sonos play_favorite timed out (6s) for '%s'", title
                    )
                    if lease is not None:
                        await self._audio_ownership.release(
                            lease["lease_id"], reason="auto_play_timeout",
                        )
                    return None
                if success:
                    if lease is not None:
                        sonos_evidence = None
                        for _ in range(4):
                            if not await self._audio_ownership.is_valid(
                                lease["lease_id"], (QUEUE_SOURCE, TRANSPORT),
                            ):
                                break
                            candidate = await self._sonos.get_queue_ownership_evidence()
                            if (
                                candidate
                                and candidate.get("transport_state") == "PLAYING"
                                and candidate.get("play_mode") == "SHUFFLE"
                                and int(candidate.get("queue_size") or 0) > 0
                                and str(candidate.get("current_uri") or "").startswith(
                                    "x-rincon-queue:"
                                )
                            ):
                                sonos_evidence = candidate
                                break
                            await asyncio.sleep(0.15)

                        if (
                            sonos_evidence is not None
                            and await self._audio_ownership.is_valid(
                                lease["lease_id"], (QUEUE_SOURCE, TRANSPORT),
                            )
                        ):
                            await self._audio_ownership.update_evidence(
                                lease["lease_id"],
                                {"phase": "owned", "sonos": sonos_evidence},
                            )
                        elif await self._audio_ownership.is_valid(lease["lease_id"]):
                            await self._audio_ownership.release(
                                lease["lease_id"],
                                reason="auto_play_evidence_unavailable",
                            )
                            logger.warning(
                                "Auto-play succeeded without durable queue ownership "
                                "evidence; leaving Sonos untouched on later mode exit"
                            )
                    logger.info(
                        f"Auto-playing '{title}' (vibe={vibe}) for mode '{mode}'"
                    )
                    await self._ws_manager.broadcast("music_auto_played", {
                        "mode": mode,
                        "title": title,
                        "vibe": vibe,
                    })
                    if self._event_logger:
                        await self._event_logger.log_sonos_event(
                            event_type="auto_play",
                            favorite_title=title,
                            mode_at_time=mode,
                            triggered_by="auto",
                            weather_class=self._current_weather_class(),
                        )
                    return {"action": "auto_played", "title": title, "vibe": vibe}
                if lease is not None:
                    await self._audio_ownership.release(
                        lease["lease_id"], reason="auto_play_failed",
                    )
                logger.warning(f"Failed to auto-play '{title}' for mode '{mode}'")
                await self._ws_manager.broadcast("music_auto_play_failed", {
                    "mode": mode,
                    "title": title,
                    "error": "Favorite not found or playback failed",
                })
                return None
            else:
                logger.info(
                    f"Sonos playing — suggesting '{title}' for mode '{mode}'"
                )
                await self._ws_manager.broadcast("music_suggestion", {
                    "mode": mode,
                    "title": title,
                    "vibe": vibe,
                    "message": f"Play '{title}' for {mode} mode?",
                })
                if self._event_logger:
                    await self._event_logger.log_sonos_event(
                        event_type="suggestion",
                        favorite_title=title,
                        mode_at_time=mode,
                        triggered_by="auto",
                        weather_class=self._current_weather_class(),
                    )
                return {"action": "suggested", "title": title, "vibe": vibe}

        except Exception as e:
            logger.error(f"Error during music auto-play: {e}", exc_info=True)
            return None

    async def on_mode_change_wrapper(self, mode: str) -> None:
        """Thin callback wrapper for AutomationEngine.register_on_mode_change."""
        await self.on_mode_change(mode)

    async def play_verified_candidate(
        self, candidate, *, expected_queue_size: int | None = None, before_play=None,
    ) -> bool:
        """Execute one already-authorized exact Music Intelligence candidate.

        This is an execution dispatch only; lifecycle, DND, ownership, trust,
        idempotency, and volume policy remain the caller's responsibility. The
        first #272 slice intentionally supports only exact Apple Music tracks.
        Sonos favorite containers retain their existing queue-clearing/shuffle
        semantics and therefore are not admitted to this narrow path.
        """
        if not getattr(candidate, "playback_capable", False):
            return False
        adapter = str(getattr(candidate, "playback_adapter", "") or "")
        if adapter != "sonos_apple_music_share_link":
            return False
        provider_id = str(getattr(candidate, "provider_id", "") or "")
        reference = str(getattr(candidate, "playback_reference", "") or "")
        if not provider_id or not reference:
            return False
        return await self._sonos.play_apple_music_share_link(
            provider_id, reference, expected_queue_size=expected_queue_size,
            before_play=before_play,
        )

    async def dispatch_pregame_audio(
        self,
        decision,
        *,
        synthetic: bool = False,
    ) -> dict:
        """Fire the pregameday→gameday audio (GAMEDAY_SPEC §10.3).

        Called at the T-30 pregameday→gameday transition by bootstrap's
        transition handler, AND by the synthetic test endpoint at
        POST /api/gameday/test/pregame with a tier-name-derived decision.

        Args:
            decision: a PregameAudioDecision (from compute_pregame_audio or
                decision_for_tier). Carries tts_line, sonos_hype_play,
                optional sonos_vibe.

        Returns:
            Dict summarizing what fired, including whether hype was requested and why
            Sonos did or did not start.
        """
        result = {
            "tts_fired": False,
            "sonos_fired": False,
            "picked_title": None,
            "sonos_hype_requested": bool(decision.sonos_hype_play),
            "sonos_reason": "not_requested" if not decision.sonos_hype_play else None,
        }

        lifecycle_reason = self._pregame_audio_lifecycle_reason(
            synthetic=synthetic,
        )
        if lifecycle_reason:
            if decision.sonos_hype_play:
                result["sonos_reason"] = f"lifecycle:{lifecycle_reason}"
            logger.info(
                "pregame audio suppressed before TTS: reason=%s",
                lifecycle_reason,
            )
            return result

        baseline_playback = None
        pregame_lease = None
        pregame_preflight_reason = None
        if decision.sonos_hype_play and self._audio_ownership is not None:
            try:
                baseline_playback = (
                    await self._sonos.get_playback_ownership_evidence()
                )
                (
                    pregame_lease,
                    pregame_preflight_reason,
                ) = await self._reserve_pregame_hype_lease(baseline_playback)
            except Exception:
                pregame_preflight_reason = "ownership_preflight_error"
                logger.exception("pregame hype ownership preflight failed")

        if decision.tts_line and self._tts_service:
            try:
                # Preseason room evidence showed the global TTS default was
                # inaudible. Game Day owns a bounded T-30 speech level while
                # preserving the spec's 22:00-06:00 apartment cap.
                await self._tts_service.speak(
                    decision.tts_line, volume=_pregame_tts_volume(),
                )
                result["tts_fired"] = True
            except asyncio.CancelledError:
                await self._release_pregame_lease(
                    pregame_lease,
                    reason="pregame_dispatch_cancelled_during_tts",
                )
                raise
            except Exception:
                logger.exception("pregame TTS dispatch failed")

        if decision.sonos_hype_play:
            # Brief gap so TTS doesn't get clipped by Sonos transport state
            # change. ~2s matches the §10.3 spec ("Sonos starts after TTS
            # finishes"). The final lifecycle + ownership gate below runs after
            # this gap, immediately before destructive favorite playback.
            try:
                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                await self._release_pregame_lease(
                    pregame_lease,
                    reason="pregame_dispatch_cancelled_during_gap",
                )
                raise
            picked = self._pick_pregame_hype(decision.sonos_vibe)
            pick_source = "mapping"
            # If no explicit mapping exists, normal/big/clutch Game Day may
            # fall back to the already-existing queueable Sonos favorite. A
            # user-configured pregameday mapping always remains authoritative.
            if picked is None and decision.sonos_vibe is None:
                if not self._sonos.connected:
                    result["sonos_reason"] = "sonos_disconnected"
                else:
                    try:
                        picked = await self._default_pregame_hype_fallback()
                    except asyncio.CancelledError:
                        await self._release_pregame_lease(
                            pregame_lease,
                            reason="pregame_dispatch_cancelled_during_fallback",
                        )
                        raise
                    pick_source = "fallback"
            if picked:
                try:
                    if self._audio_ownership is not None:
                        if pregame_lease is None:
                            success = False
                            reason = (
                                pregame_preflight_reason
                                or "ownership_preflight_unavailable"
                            )
                        else:
                            success, reason = await self._play_pregame_hype_owned(
                                title=picked["favorite_title"],
                                baseline_playback=baseline_playback,
                                lease=pregame_lease,
                                synthetic=synthetic,
                            )
                    else:
                        # Compatibility for isolated callers/tests that have not
                        # adopted #274. Production always injects ownership.
                        success = await asyncio.wait_for(
                            self._sonos.play_favorite(picked["favorite_title"]),
                            timeout=6.0,
                        )
                        reason = "played" if success else "play_failed"
                    result["sonos_reason"] = reason
                    if success:
                        result["sonos_fired"] = True
                        result["picked_title"] = picked["favorite_title"]
                        logger.info(
                            "pregame hype playing: title=%s vibe=%s tier=%s source=%s",
                            picked["favorite_title"],
                            picked.get("vibe"),
                            decision.tier,
                            pick_source,
                        )
                        await self._ws_manager.broadcast("music_auto_played", {
                            "mode": "gameday",
                            "title": picked["favorite_title"],
                            "vibe": picked.get("vibe"),
                            "source": "pregame_audio",
                        })
                    else:
                        logger.info(
                            "pregame hype suppressed: title=%s source=%s reason=%s",
                            picked["favorite_title"], pick_source, reason,
                        )
                except asyncio.TimeoutError:
                    result["sonos_reason"] = "timeout"
                    logger.warning("pregame Sonos play_favorite timed out")
                except Exception:
                    result["sonos_reason"] = "error"
                    logger.exception("pregame Sonos dispatch failed")
            else:
                await self._release_pregame_lease(
                    pregame_lease,
                    reason="pregame_hype_no_mapping_or_fallback",
                )
                if result["sonos_reason"] is None:
                    result["sonos_reason"] = "no_mapping_or_fallback"
                logger.warning(
                    "pregame hype requested but unavailable: reason=%s fallback=%r tier=%s",
                    result["sonos_reason"], DEFAULT_PREGAME_HYPE_FAVORITE, decision.tier,
                )

        return result

    async def _default_pregame_hype_fallback(self) -> Optional[dict]:
        """Resolve the bounded default favorite when no pregameday mapping exists.

        The fallback is intentionally discovery-based rather than a DB seed: it
        only applies when Sonos currently exposes the exact queueable favorite,
        and any explicit pregameday mapping takes precedence.
        """
        if not self._sonos.connected:
            return None
        try:
            favorites = await asyncio.wait_for(self._sonos.get_favorites(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("pregame fallback favorite lookup timed out")
            return None
        except Exception:
            logger.exception("pregame fallback favorite lookup failed")
            return None

        for favorite in favorites:
            title = str(favorite.get("title") or "")
            uri = str(favorite.get("uri") or "")
            if title.casefold() == DEFAULT_PREGAME_HYPE_FAVORITE.casefold() and uri:
                return {
                    "favorite_title": title,
                    "vibe": "hype",
                    "auto_play": True,
                    "priority": -1,
                }
        return None

    def _pick_pregame_hype(self, sonos_vibe: Optional[str]) -> Optional[dict]:
        """Pick the hype playlist entry for pregameday→gameday audio.

        Reads from the pregameday mode_playlists rows. Vibe filtering:
            - sonos_vibe="mellow" → prefer mellow/background vibes (victory-lap)
            - sonos_vibe=None     → any entry (default hype)

        Returns the entry dict {favorite_title, vibe, ...} or None.
        """
        entries = self._cache.get("pregameday", [])
        if not entries:
            return None
        if sonos_vibe == "mellow":
            mellow_picks = [
                e for e in entries
                if e.get("vibe") in ("mellow", "background")
            ]
            if mellow_picks:
                return mellow_picks[0]
        # Default: first entry (priority-ordered by _reload_mode).
        return entries[0]

    async def on_weather_change(
        self, condition: str, mode: str,
    ) -> Optional[dict]:
        """Suggest a weather-appropriate playlist when weather changes.

        Called by the automation engine when weather condition shifts (e.g.
        clear → rain). Never auto-plays — only broadcasts a WebSocket
        suggestion so the user can choose to switch.

        Args:
            condition: Classified weather (thunderstorm, rain, snow).
            mode: Current activity mode.

        Returns:
            Dict describing the suggestion, or None.
        """
        if self._automation is not None and self._automation.is_dnd_active():
            return None

        if mode in _WEATHER_MUSIC_SKIP_MODES:
            return None

        preference = _WEATHER_VIBE_OVERRIDE.get(condition)
        if not preference:
            return None

        entries = self._cache.get(mode, [])
        if not entries:
            return None

        # Pick best playlist using weather vibe preference
        pick = None
        for preferred_vibe in preference:
            match = next((e for e in entries if e["vibe"] == preferred_vibe), None)
            if match:
                pick = match
                break
        if not pick:
            pick = entries[0]

        title = pick["favorite_title"]
        vibe = pick.get("vibe")

        # Check if Sonos is already playing this
        if self._sonos.connected:
            try:
                status = await asyncio.wait_for(
                    self._sonos.get_status(), timeout=5.0,
                )
                current_track = status.get("title") or status.get("track") or ""
                if title.lower() in current_track.lower():
                    logger.debug(
                        "Weather suggestion '%s' already playing, skipping", title,
                    )
                    return None
            except (asyncio.TimeoutError, Exception):
                pass  # Suggest anyway if we can't check

        _WEATHER_LABELS = {
            "thunderstorm": "Stormy",
            "rain": "Rainy",
            "snow": "Snowy",
        }
        weather_label = _WEATHER_LABELS.get(condition, condition.title())

        logger.info(
            "Weather music suggestion: '%s' (vibe=%s) for %s weather in %s mode",
            title, vibe, condition, mode,
        )
        await self._ws_manager.broadcast("music_weather_suggestion", {
            "mode": mode,
            "title": title,
            "vibe": vibe,
            "weather": condition,
            "message": f"{weather_label} outside — try '{title}'?",
        })
        if self._event_logger:
            await self._event_logger.log_sonos_event(
                event_type="weather_suggestion",
                favorite_title=title,
                mode_at_time=mode,
                triggered_by="weather",
                weather_class=self._current_weather_class(),
            )
        return {"action": "weather_suggested", "title": title, "vibe": vibe}

    # ------------------------------------------------------------------
    # Legacy helpers — used by older code paths
    # ------------------------------------------------------------------

    def get_playlist_for_mode(self, mode: str) -> Optional[str]:
        """Return the best-match favorite title for a mode (legacy helper)."""
        entry = self.pick_playlist(mode)
        return entry["favorite_title"] if entry else None

    def should_auto_play(self, mode: str) -> bool:
        """Return True if any mapping for this mode has auto_play enabled."""
        return any(e["auto_play"] for e in self._cache.get(mode, []))
