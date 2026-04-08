"""
Evening wind-down routine service.

Triggered by the scheduler at a configurable time (default 9 PM).
Dims lights to relax mode, optionally activates candlelight effect,
lowers Sonos volume, and plays a brief TTS announcement.
"""
import asyncio
import logging

logger = logging.getLogger("home_hub.winddown")

_ACTIVE_MODES = frozenset({"gaming", "watching", "social", "working"})


class WinddownRoutineService:
    """
    Executes the evening wind-down routine.

    Reuses the existing 'relax' mode via set_manual_override — this
    automatically dims lights and activates the candlelight Hue effect.
    Additionally lowers Sonos volume for a calmer atmosphere.
    """

    def __init__(
        self,
        automation_engine,
        sonos_service,
        tts_service,
        volume: int = 20,
        activate_candlelight: bool = True,
        weekdays_only: bool = False,
        skip_if_active: bool = True,
    ) -> None:
        self._automation = automation_engine
        self._sonos = sonos_service
        self._tts = tts_service
        self._volume = volume
        self._activate_candlelight = activate_candlelight
        self._weekdays_only = weekdays_only
        self._skip_if_active = skip_if_active

    async def execute(self, force: bool = False) -> bool:
        """
        Run the evening wind-down routine.

        If skip_if_active is True (default), checks whether the user is in an
        active mode (gaming, watching, social, working). If so, waits 30 minutes
        and checks again, up to 4 retries (2 hours total). If still active after
        all retries, skips for the night and returns False.

        Args:
            force: If True, bypass the activity check and execute immediately.
                   Used by the test endpoint.

        Returns:
            True if the routine completed successfully, False if skipped or errored.
        """
        _MAX_RETRIES = 4
        _RETRY_DELAY_SECONDS = 1800  # 30 minutes

        if not force and self._skip_if_active and self._automation:
            for attempt in range(_MAX_RETRIES + 1):
                mode = self._automation.current_mode
                if mode not in _ACTIVE_MODES:
                    break
                if attempt < _MAX_RETRIES:
                    logger.info(
                        "Wind-down delayed: active mode '%s' detected "
                        "(attempt %d/%d). Retrying in 30 minutes.",
                        mode, attempt + 1, _MAX_RETRIES,
                    )
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)
                else:
                    logger.warning(
                        "Wind-down skipped for tonight: still in active mode "
                        "'%s' after %d retries.", mode, _MAX_RETRIES,
                    )
                    return False

        logger.info("Executing evening wind-down routine")

        try:
            # Switch to relax mode — dims lights + activates candlelight effect
            if self._automation:
                await self._automation.set_manual_override("relax")
                logger.info("Switched to relax mode for wind-down")
        except Exception as e:
            logger.error(f"Wind-down mode switch failed: {e}")
            return False

        # Lower Sonos volume
        try:
            if self._sonos and self._sonos.connected:
                await self._sonos.set_volume(self._volume)
                logger.info(f"Sonos volume set to {self._volume}")
        except Exception as e:
            logger.error(f"Wind-down volume adjustment failed: {e}")

        # Brief TTS announcement
        try:
            if self._tts:
                await self._tts.speak(
                    "Wind-down time. Lights dimmed, volume lowered.",
                    volume=self._volume,
                )
        except Exception as e:
            logger.error(f"Wind-down TTS failed: {e}")

        logger.info("Wind-down routine complete")
        return True
