"""
Sonos speaker control endpoints — playback, volume, TTS, favorites, music mapping.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.schemas.sonos import SonosStatus, TTSRequest, VolumeRequest

router = APIRouter(prefix="/api/sonos", tags=["sonos"])


async def _log_manual_sonos(
    request: Request,
    event_type: str,
    favorite_title: Optional[str] = None,
    volume: Optional[int] = None,
) -> None:
    """Fire-and-forget manual Sonos event logger."""
    event_logger = getattr(request.app.state, "event_logger", None)
    automation = getattr(request.app.state, "automation", None)
    if event_logger:
        mode = automation.current_mode if automation else None
        await event_logger.log_sonos_event(
            event_type=event_type,
            favorite_title=favorite_title,
            mode_at_time=mode,
            volume=volume,
            triggered_by="manual",
        )


@router.get("/status", response_model=SonosStatus)
async def get_sonos_status(request: Request) -> dict:
    """Get current Sonos playback status (track, artist, volume, etc.)."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    return await sonos.get_status()


@router.post("/play")
async def sonos_play(request: Request) -> dict:
    """Resume Sonos playback."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.play()
    if success:
        await _log_manual_sonos(request, "play")
    return {"status": "ok" if success else "error"}


@router.post("/pause")
async def sonos_pause(request: Request) -> dict:
    """Pause Sonos playback."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.pause()
    if success:
        await _log_manual_sonos(request, "pause")
    return {"status": "ok" if success else "error"}


@router.post("/next")
async def sonos_next(request: Request) -> dict:
    """Skip to next track."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.next_track()
    if success:
        await _log_manual_sonos(request, "skip")
    return {"status": "ok" if success else "error"}


@router.post("/previous")
async def sonos_previous(request: Request) -> dict:
    """Go to previous track."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.previous_track()
    if success:
        await _log_manual_sonos(request, "skip")
    return {"status": "ok" if success else "error"}


@router.post("/volume")
async def set_sonos_volume(body: VolumeRequest, request: Request) -> dict:
    """Set Sonos volume (0-100)."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.set_volume(body.volume)
    if success:
        await _log_manual_sonos(request, "volume", volume=body.volume)
    return {"status": "ok" if success else "error", "volume": body.volume}


@router.post("/tts")
async def speak_text(body: TTSRequest, request: Request) -> dict:
    """
    Generate TTS audio and play it on the Sonos speaker.

    Implements duck-and-resume: if music is playing, it will pause,
    speak, then resume where it left off.
    """
    tts = request.app.state.tts
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")

    success = await tts.speak(text=body.text, volume=body.volume)
    return {
        "status": "ok" if success else "error",
        "text": body.text,
    }


# ------------------------------------------------------------------
# Favorites & music mapping
# ------------------------------------------------------------------

class MusicMappingEntry(BaseModel):
    """A single mode-to-playlist mapping."""

    mode: str = Field(..., description="Activity mode name")
    favorite_title: str = Field(..., description="Sonos favorite name")
    auto_play: bool = Field(default=False, description="Auto-play on mode change")


@router.get("/favorites")
async def get_favorites(request: Request) -> dict:
    """List all Sonos favorites (playlists, stations, etc.)."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")

    favorites = await sonos.get_favorites()
    return {"favorites": favorites}


@router.post("/favorites/{title}/play")
async def play_favorite(title: str, request: Request) -> dict:
    """Play a Sonos favorite by title."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")

    success = await sonos.play_favorite(title)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"Favorite '{title}' not found or playback failed",
        )
    await _log_manual_sonos(request, "play", favorite_title=title)
    return {"status": "ok", "playing": title}


@router.get("/music-map")
async def get_music_map(request: Request) -> dict:
    """Get the current mode-to-playlist mapping."""
    mapper = getattr(request.app.state, "music_mapper", None)
    if not mapper:
        return {"mapping": {}}
    return {"mapping": mapper.mapping}


@router.put("/music-map")
async def update_music_map(entry: MusicMappingEntry, request: Request) -> dict:
    """Update a single mode-to-playlist mapping."""
    mapper = getattr(request.app.state, "music_mapper", None)
    if not mapper:
        raise HTTPException(status_code=503, detail="Music mapper not initialized")

    await mapper.add_mapping(entry.mode, entry.favorite_title, auto_play=entry.auto_play)
    return {"status": "ok", "mapping": mapper.mapping}
