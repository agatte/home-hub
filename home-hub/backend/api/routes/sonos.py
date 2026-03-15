"""
Sonos speaker control endpoints.
"""
from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas.sonos import SonosStatus, TTSRequest, VolumeRequest

router = APIRouter(prefix="/api/sonos", tags=["sonos"])


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
    return {"status": "ok" if success else "error"}


@router.post("/pause")
async def sonos_pause(request: Request) -> dict:
    """Pause Sonos playback."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.pause()
    return {"status": "ok" if success else "error"}


@router.post("/next")
async def sonos_next(request: Request) -> dict:
    """Skip to next track."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.next_track()
    return {"status": "ok" if success else "error"}


@router.post("/previous")
async def sonos_previous(request: Request) -> dict:
    """Go to previous track."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.previous_track()
    return {"status": "ok" if success else "error"}


@router.post("/volume")
async def set_sonos_volume(body: VolumeRequest, request: Request) -> dict:
    """Set Sonos volume (0-100)."""
    sonos = request.app.state.sonos
    if not sonos.connected:
        raise HTTPException(status_code=503, detail="Sonos not connected")
    success = await sonos.set_volume(body.volume)
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
