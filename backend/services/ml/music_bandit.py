"""Music Bandit — Thompson sampling playlist selection.

Learns which Sonos favorites you actually enjoy at different times by
tracking play/skip behavior. Each (mode, time_period, favorite_title) is
an "arm" with Beta(α, β) parameters. On mode change, samples from each
arm's distribution and picks the highest — naturally balancing exploration
vs exploitation.

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
        # arms: {"{mode}|{period}|{title}": [alpha, beta]}
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

    def _arm_key(self, mode: str, period: str, title: str) -> str:
        return f"{mode}|{period}|{title}"

    def _parse_key(self, key: str) -> tuple[str, str, str]:
        parts = key.split("|", 2)
        return parts[0], parts[1], parts[2]

    def _load(self) -> None:
        """Load arm parameters from disk."""
        if self._file.exists():
            try:
                data = json.loads(self._file.read_text())
                self._arms = data.get("arms", {})
                self._total_selections = data.get("total_selections", 0)
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

    def _ensure_arm(self, mode: str, period: str, title: str,
                    preferred: bool = False) -> str:
        """Create arm if it doesn't exist, return the key."""
        key = self._arm_key(mode, period, title)
        if key not in self._arms:
            prior = PRIOR_PREFERRED if preferred else PRIOR_DEFAULT
            self._arms[key] = [prior[0], prior[1]]
        return key

    def select(
        self,
        mode: str,
        period: str,
        candidates: list[dict],
        preferred_vibes: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """Pick the best playlist entry via Thompson sampling.

        Args:
            mode: Current activity mode.
            period: Time period (morning/day/evening/night).
            candidates: List of mapping dicts with favorite_title, vibe, etc.
            preferred_vibes: Vibes preferred for this period (for cold start priors).

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
                logger.debug("Bandit explore: '%s' (uniform)", choice["favorite_title"])
                self._track_predict(True)
                return choice

            # Thompson sampling: sample from each arm's Beta distribution
            best_sample = -1.0
            best_entry = None

            for entry in candidates:
                title = entry["favorite_title"]
                preferred = entry.get("vibe") in preferred_vibes
                key = self._ensure_arm(mode, period, title, preferred=preferred)
                alpha, beta = self._arms[key]
                sample = random.betavariate(alpha, beta)

                if sample > best_sample:
                    best_sample = sample
                    best_entry = entry

            self._total_selections += 1
            if best_entry:
                logger.debug(
                    "Bandit exploit: '%s' (sample=%.3f)",
                    best_entry["favorite_title"], best_sample,
                )
            self._track_predict(True)
            return best_entry
        except Exception as exc:
            self._track_predict(False, exc)
            logger.warning("Bandit select() failed: %s", exc)
            return None

    def record_reward(self, mode: str, period: str, title: str,
                      reward: float) -> None:
        """Update arm parameters with a reward (+α) or penalty (+β).

        Args:
            reward: Positive values increase α (good), negative increase β (bad).
        """
        key = self._ensure_arm(mode, period, title)
        if reward > 0:
            self._arms[key][0] += reward
        else:
            self._arms[key][1] += abs(reward)

        logger.info(
            "Bandit reward: '%s' %s%.1f → α=%.1f β=%.1f",
            title, "+" if reward > 0 else "", reward,
            self._arms[key][0], self._arms[key][1],
        )
        self._save()

    def get_status(self) -> dict[str, Any]:
        """Return bandit status for the API."""
        # Top arms per mode
        top_per_mode: dict[str, list[dict]] = {}
        for key, (alpha, beta) in self._arms.items():
            mode, period, title = self._parse_key(key)
            mean = alpha / (alpha + beta)
            entry = {
                "title": title,
                "period": period,
                "alpha": alpha,
                "beta": beta,
                "mean": round(mean, 3),
            }
            top_per_mode.setdefault(mode, []).append(entry)

        # Sort by mean descending within each mode
        for mode in top_per_mode:
            top_per_mode[mode].sort(key=lambda e: e["mean"], reverse=True)

        return {
            "arm_count": len(self._arms),
            "total_selections": self._total_selections,
            "arms_per_mode": {m: len(v) for m, v in top_per_mode.items()},
            "top_arms": {m: v[:5] for m, v in top_per_mode.items()},
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
            key = f"{mode}|{period}|{title}"

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
