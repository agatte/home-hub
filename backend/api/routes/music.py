"""
Music discovery and mode-playlist mapping endpoints.
"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

from backend.api.schemas.music import ModePlaylistEntry, ModePlaylistUpdate
from backend.config import DATA_DIR
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


# ------------------------------------------------------------------
# Library import & taste profile
# ------------------------------------------------------------------

@router.post("/import")
async def import_library(file: UploadFile, request: Request) -> dict:
    """
    Import an Apple Music / iTunes library XML file.

    Parses the plist XML, extracts artist data, genre distribution,
    and playlist signals, then builds and persists a taste profile.
    """
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="File must be a .xml file")

    import_service = request.app.state.library_import

    # Save uploaded file temporarily
    imports_dir = DATA_DIR / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = imports_dir / "library_import.xml"

    try:
        content = await file.read()
        tmp_path.write_bytes(content)
        stats = await import_service.import_xml(tmp_path)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
    finally:
        # Clean up temp file
        if tmp_path.exists():
            tmp_path.unlink()


@router.get("/profile")
async def get_taste_profile(request: Request) -> dict:
    """Get the current taste profile summary."""
    import_service = request.app.state.library_import
    profile = await import_service.get_profile()

    if not profile:
        return {"profile": None, "message": "No library imported yet"}

    return {"profile": profile}
