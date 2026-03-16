"""
Music discovery and mode-playlist mapping endpoints.
"""
from fastapi import APIRouter, HTTPException, Request

from backend.api.schemas.music import ModePlaylistEntry, ModePlaylistUpdate
from backend.services.music_mapper import SUPPORTED_MODES

router = APIRouter(prefix="/api/music", tags=["music"])


@router.get("/mode-playlists")
async def get_mode_playlists(request: Request) -> dict:
    """
    Get all mode-to-playlist mappings and available Sonos favorites.

    Returns the current mapping for each supported mode plus the list
    of Sonos favorites the user can choose from.
    """
    mapper = request.app.state.music_mapper
    sonos = request.app.state.sonos

    favorites = []
    if sonos.connected:
        try:
            favorites = await sonos.get_favorites()
        except Exception:
            pass

    mappings = {}
    raw = mapper.mapping
    for mode in SUPPORTED_MODES:
        entry = raw.get(mode, {})
        title = entry.get("favorite_title", "")
        if title:
            mappings[mode] = ModePlaylistEntry(
                mode=mode,
                favorite_title=title,
                auto_play=entry.get("auto_play", False),
            ).model_dump()
        else:
            mappings[mode] = None

    return {"mappings": mappings, "favorites": favorites}


@router.put("/mode-playlists/{mode}")
async def set_mode_playlist(
    mode: str, body: ModePlaylistUpdate, request: Request
) -> dict:
    """Set or update the playlist mapping for a mode."""
    if mode not in SUPPORTED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mode '{mode}'. Must be one of: {', '.join(SUPPORTED_MODES)}",
        )

    mapper = request.app.state.music_mapper
    await mapper.set_mapping(mode, body.favorite_title, body.auto_play)
    return {"status": "ok", "mode": mode, "favorite_title": body.favorite_title}


@router.delete("/mode-playlists/{mode}")
async def remove_mode_playlist(mode: str, request: Request) -> dict:
    """Remove the playlist mapping for a mode."""
    if mode not in SUPPORTED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mode '{mode}'. Must be one of: {', '.join(SUPPORTED_MODES)}",
        )

    mapper = request.app.state.music_mapper
    removed = await mapper.remove_mapping(mode)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No mapping for mode '{mode}'")
    return {"status": "ok", "mode": mode}
