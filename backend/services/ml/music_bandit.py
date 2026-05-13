"""Music Bandit — Thompson sampling playlist selection.

Learns which Sonos favorites you actually enjoy at different times by
tracking play/skip behavior. Each (mode, time_period, weather_class,
favorite_title) is an "arm" with Beta(α, β) parameters. On mode change,
samples from each arm's distribution and picks the highest — naturally
balancing exploration vs exploitation.

Phase B (2026-05-12): added the ``weather_class`` dimension to the arm
key. Legacy 3-tuple arms (``mode|period|title``) auto-migrate to
``mode|period|any|title`` on load so accumulated priors are preserved.
New weather-specific arms warm-start from the corresponding ``any`` arm
when available so they don't begin life with a flat Beta(1,1) prior.

Cold start: Beta(3,1) for vibes matching the time-of-day heuristic,
Beta(1,1) for all others. 10% forced uniform exploration prevents
premature convergence.
"""
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from backend.database import async_session
from backend.models import SonosPlaybackEvent
from backend.services.ml.health_mixin import HealthTrackable

logger = logging.getLogger("home_hub.ml.bandit")

# Default priors
PRIOR_PREFERRED = (3.0, 1.0)  # Beta(3,1) — optimistic for preferred vibes
PRIOR_DEFAULT = (1.0, 1.0)    # Beta(1,1) — uninformative
EXPLORATION_RATE = 0.10        # 10% forced uniform exploration

# Weather-class sentinel for weather-agnostic arms (legacy 3-tuple
# migration, cold-start parent, no-weather fallback). Live observations
# resolve to one of the concrete classes via
# ``weather_class.classify_for_bandit``.
WEATHER_ANY = "any"

# Reward/penalty magnitudes
REWARD_KEEP_PLAYING = 1.0      # Listened 60s+ after auto-play
REWARD_MANUAL_PLAY = 2.0       # Manually played in same mode
REWARD_SUGGESTION_ACCEPTED = 1.0
PENALTY_SKIP = 1.0             # Skipped within 30s
PENALTY_DISMISS = 0.5          # Suggestion dismissed


class MusicBandit(HealthTrackable):
    """Thompson sampling bandit for playlist selection."""

    def __init__(self, model_manager, data_dir: Optional[Path] = None) -> None:
        self._model_manager = model_manager
        self._data_dir = data_dir or Path("data/models")
        self._file = self._data_dir / "music_bandit.json"
        # arms: {"{mode}|{period}|{weather}|{title}": [alpha, beta]}
        self._arms: dict[str, list[float]] = {}
        self._total_selections = 0
        # Track whether the on-disk arm state loaded cleanly. A failed
        # _load() resets _arms to {} and the bandit silently degrades to
        # uniform random — health() reports model_loaded=False so the
        # silent fallback is visible.
        self._load_failed = False
        self._init_health_tracking()
        self._load()

    @property
    def name(self) -> str:
        return "music_bandit"

    def _arm_key(self, mode: str, period: str, weather: str, title: str) -> str:
        return f"{mode}|{period}|{weather}|{title}"

    def _parse_key(self, key: str) -> tuple[str, str, str, str]:
        """Parse a key into ``(mode, period, weather, title)``.

        Tolerates legacy 3-pipe keys (``mode|period|title``) by inserting
        the ``WEATHER_ANY`` sentinel in the weather slot — used during
        the one-shot migration in ``_load``.
        """
        parts = key.split("|", 3)
        if len(parts) == 3:
            mode, period, title = parts
            return mode, period, WEATHER_ANY, title
        return parts[0], parts[1], parts[2], parts[3]

    def _load(self) -> None:
        """Load arm parameters from disk; migrate legacy 3-tuple keys."""
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                raw_arms = data.get("arms", {})
                self._total_selections = data.get("total_selections", 0)
                # Phase B migration: legacy 3-pipe keys (mode|period|title)
                # become 4-pipe (mode|period|any|title). Idempotent — a
                # second pass on already-migrated state is a no-op.
                migrated = 0
                self._arms = {}
                for key, params in raw_arms.items():
                    if key.count("|") == 2:
                        mode, period, title = key.split("|", 2)
                        new_key = self._arm_key(mode, period, WEATHER_ANY, title)
                        self._arms[new_key] = params
                        migrated += 1
                    else:
                        self._arms[key] = params
                if migrated:
                    logger.info(
                        "Music bandit Phase B migration: %d legacy 3-tuple "
                        "arms upgraded to 4-tuple with weather=%s",
                        migrated, WEATHER_ANY,
                    )
                    self._save()  # persist migration so next load is fast
                logger.info(
                    "Music bandit loaded: %d arms, %d selections",
                    len(self._arms), self._total_selections,
                )
            except Exception as e:
                logger.error("Failed to load music bandit: %s", e)
                self._arms = {}
                self._load_failed = True

    def _save(self) -> None:
        """Persist arm parameters to disk."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._file.write_text(json.dumps({
                "arms": self._arms,
                "total_selections": self._total_selections,
            }, indent=2))
        except Exception as e:
            logger.error("Failed to save music bandit: %s", e)

    def _ensure_arm(self, mode: str, period: str, weather: str, title: str,
                    preferred: bool = False) -> str:
        """Create arm if it doesn't exist, return the key.

        Warm-start: when a weather-specific arm is created and a weather-
        agnostic counterpart (``mode|period|any|title``) already has
        accumulated priors, the new arm inherits those priors as its
        starting state. This prevents weather-specific arms from beginning
        life at a flat Beta(1,1) when there's relevant history to seed
        from. The ``any`` arm continues to accumulate independently.
        """
        key = self._arm_key(mode, period, weather, title)
        if key in self._arms:
            return key
        if weather != WEATHER_ANY:
            any_key = self._arm_key(mode, period, WEATHER_ANY, title)
            if any_key in self._arms:
                # Copy (not reference) — subsequent updates don't bleed
                # back into the parent arm.
                self._arms[key] = list(self._arms[any_key])
                return key
        prior = PRIOR_PREFERRED if preferred else PRIOR_DEFAULT
        self._arms[key] = [prior[0], prior[1]]
        return key

    def select(
        self,
        mode: str,
        period: str,
        candidates: list[dict],
        preferred_vibes: Optional[list[str]] = None,
        weather: str = WEATHER_ANY,
    ) -> Optional[dict]:
        """Pick the best playlist entry via Thompson sampling.

        Args:
            mode: Current activity mode.
            period: Time period (morning/day/evening/night).
            candidates: List of mapping dicts with favorite_title, vibe, etc.
            preferred_vibes: Vibes preferred for this period (for cold start priors).
            weather: Weather class (thunderstorm/rain/snow/clouds/golden_hour/
                clear/any). Default ``WEATHER_ANY`` keeps back-compat for
                callers that haven't been weather-extended yet.

        Returns:
            The selected candidate dict, or None if no candidates.
        """
        if not candidates:
            return None

        preferred_vibes = preferred_vibes or []

        try:
            # 10% forced uniform exploration
            if random.random() < EXPLORATION_RATE:
                choice = random.choice(candidates)
                self._total_selections += 1
                logger.debug(
                    "Bandit explore: '%s' (uniform, weather=%s)",
                    choice["favorite_title"], weather,
                )
                self._track_predict(True)
                return choice

            # Thompson sampling: sample from each arm's Beta distribution
            best_sample = -1.0
            best_entry = None

            for entry in candidates:
                title = entry["favorite_title"]
                preferred = entry.get("vibe") in preferred_vibes
                key = self._ensure_arm(mode, period, weather, title, preferred=preferred)
                alpha, beta = self._arms[key]
                sample = random.betavariate(alpha, beta)

                if sample > best_sample:
                    best_sample = sample
                    best_entry = entry

            self._total_selections += 1
            if best_entry:
                logger.debug(
                    "Bandit exploit: '%s' (sample=%.3f, weather=%s)",
                    best_entry["favorite_title"], best_sample, weather,
                )
            self._track_predict(True)
            return best_entry
        except Exception as exc:
            self._track_predict(False, exc)
            logger.warning("Bandit select() failed: %s", exc)
            return None

    def record_reward(self, mode: str, period: str, title: str,
                      reward: float, weather: str = WEATHER_ANY) -> None:
        """Update arm parameters with a reward (+α) or penalty (+β).

        Args:
            reward: Positive values increase α (good), negative increase β (bad).
            weather: Weather class for the arm. Defaults to ``WEATHER_ANY`` for
                callers that haven't been extended; weather-aware retrain
                passes the real class from the event row.
        """
        key = self._ensure_arm(mode, period, weather, title)
        if reward > 0:
            self._arms[key][0] += reward
        else:
            self._arms[key][1] += abs(reward)

        logger.info(
            "Bandit reward: '%s' (weather=%s) %s%.1f → α=%.1f β=%.1f",
            title, weather, "+" if reward > 0 else "", reward,
            self._arms[key][0], self._arms[key][1],
        )
        self._save()

    def get_status(self) -> dict[str, Any]:
        """Return bandit status for the API.

        Output shape (Phase B): arms grouped by ``(mode, weather_class)``
        so the matrix structure surfaces. Legacy single-list-per-mode
        shape is dropped — clients should consume the nested dict.
        """
        # Top arms per (mode, weather_class)
        top_per_mode_weather: dict[str, dict[str, list[dict]]] = {}
        for key, (alpha, beta) in self._arms.items():
            mode, period, weather, title = self._parse_key(key)
            mean = alpha / (alpha + beta)
            entry = {
                "title": title,
                "period": period,
                "weather": weather,
                "alpha": alpha,
                "beta": beta,
                "mean": round(mean, 3),
            }
            top_per_mode_weather.setdefault(mode, {}).setdefault(weather, []).append(entry)

        # Sort by mean descending within each (mode, weather) bucket and trim.
        for mode, by_weather in top_per_mode_weather.items():
            for weather in by_weather:
                by_weather[weather].sort(key=lambda e: e["mean"], reverse=True)
                by_weather[weather] = by_weather[weather][:5]

        return {
            "arm_count": len(self._arms),
            "total_selections": self._total_selections,
            "arms_per_mode": {
                m: sum(len(v) for v in by_weather.values())
                for m, by_weather in top_per_mode_weather.items()
            },
            "top_arms": top_per_mode_weather,
        }

    def health(self) -> dict[str, Any]:
        """Health entry for the /health ml block.

        ``model_loaded`` is False when on-disk state existed but failed
        to parse; the bandit then runs with empty arms (silent uniform
        random fallback). Surfacing model_loaded=False makes that
        silent failure visible.
        """
        return HealthTrackable.health(
            self,
            is_shadow=False,
            model_loaded=not self._load_failed,
            extra={
                "arm_count": len(self._arms),
                "total_selections": self._total_selections,
            },
        )

    async def retrain(self) -> None:
        """Rebuild arm parameters from sonos_playback_events (nightly).

        Scans the last 90 days of events and reconstructs rewards from
        auto_play/skip/manual play sequences.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)

        try:
            async with async_session() as session:
                result = await session.execute(
                    select(SonosPlaybackEvent)
                    .where(SonosPlaybackEvent.timestamp >= cutoff)
                    .order_by(SonosPlaybackEvent.timestamp.asc())
                )
                events = result.scalars().all()
        except Exception as e:
            logger.error("Bandit retrain failed to query events: %s", e)
            return

        if not events:
            logger.info("Bandit retrain: no events to process")
            return

        # Rebuild arms from events
        new_arms: dict[str, list[float]] = {}

        for i, event in enumerate(events):
            if not event.favorite_title or not event.mode_at_time:
                continue

            title = event.favorite_title
            mode = event.mode_at_time
            # Derive period from event timestamp
            hour = event.timestamp.hour if event.timestamp else 12
            from backend.services.music_mapper import _time_period
            period = _time_period(hour)
            # Phase B: read weather_class captured at log time. Legacy
            # rows (pre-column) and rows where capture failed read as
            # None — bucket those into WEATHER_ANY.
            weather = getattr(event, "weather_class", None) or WEATHER_ANY
            key = self._arm_key(mode, period, weather, title)

            if key not in new_arms:
                new_arms[key] = [PRIOR_DEFAULT[0], PRIOR_DEFAULT[1]]

            if event.event_type == "auto_play":
                # Check if next event is a skip within 30s
                next_evt = events[i + 1] if i + 1 < len(events) else None
                if (next_evt
                        and next_evt.event_type == "skip"
                        and next_evt.timestamp
                        and event.timestamp
                        and (next_evt.timestamp - event.timestamp).total_seconds() < 30):
                    new_arms[key][1] += PENALTY_SKIP
                else:
                    new_arms[key][0] += REWARD_KEEP_PLAYING

            elif event.event_type == "play" and event.triggered_by == "manual":
                new_arms[key][0] += REWARD_MANUAL_PLAY

        self._arms = new_arms
        self._save()
        logger.info(
            "Bandit retrain complete: %d arms from %d events",
            len(new_arms), len(events),
        )
