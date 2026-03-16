"""
Evening wind-down routine service.

Triggered by the scheduler at a configurable time (default 9 PM).
Dims lights to relax mode, optionally activates candlelight effect,
lowers Sonos volume, and plays a brief TTS announcement.
"""
import logging

logger = logging.getLogger("home_hub.winddown")


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
    ) -> None:
        self._automation = automation_engine
        self._sonos = sonos_service
        self._tts = tts_service
        self._volume = volume
        self._activate_candlelight = activate_candlelight
        self._weekdays_only = weekdays_only

    async def execute(self) -> bool:
        """
        Run the evening wind-down routine.

        Returns:
            True if the routine completed successfully.
        """
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
            if self._sonos and self._sonos.speaker:
                self._sonos.speaker.volume = self._volume
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
