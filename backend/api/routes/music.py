"""
Music discovery and mode-playlist mapping endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from backend.api._guards import _check_sonos_available
from backend.api.auth import require_api_key
from backend.api.schemas.music import ModePlaylistAdd, ModePlaylistEntry
from backend.config import DATA_DIR
from backend.rate_limit import limiter
from backend.services.didl_lite import build_track_didl_lite
from backend.services.music_curator import MusicCuratorError
from backend.services.music_mapper import SUPPORTED_MODES, VALID_VIBES
from backend.services.sonos_service import is_allowed_play_uri

router = APIRouter(prefix="/api/music", tags=["music"])

# Upload guards for /import. The parser is plistlib (expat under the hood),
# which doesn't resolve external entities but does honor internal <!ENTITY>
# declarations — so a "billion laughs" payload can still blow up RAM during
# parse. The size cap + entity scan close that together without a defusedxml
# dependency, since legitimate Apple/iTunes plists never declare entities.
MAX_IMPORT_BYTES = 50 * 1024 * 1024  # ~2x a heavy Apple Music library
_IMPORT_CHUNK_BYTES = 1024 * 1024
_ALLOWED_IMPORT_CONTENT_TYPES = (
    "application/xml",
    "text/xml",
    "text/plain",
    "application/octet-stream",
)


@router.get("/mode-playlists")
async def get_mode_playlists(request: Request) -> dict:
    """
    Get all mode-to-playlist mappings and available Sonos favorites.

    Returns all mappings per mode (multiple per mode, each with a vibe tag)
    plus the list of Sonos favorites to choose from.
    """
    mapper = request.app.state.music_mapper
    sonos = request.app.state.sonos

    favorites = []
    if sonos.connected:
        try:
            favorites = await sonos.get_favorites()
        except Exception:
            pass

    raw = mapper.mapping
    mappings = {}
    for mode in SUPPORTED_MODES:
        entries = raw.get(mode, [])
        mappings[mode] = [
            ModePlaylistEntry(
                id=e["id"],
                mode=mode,
                favorite_title=e["favorite_title"],
                vibe=e.get("vibe"),
                auto_play=e.get("auto_play", False),
                priority=e.get("priority", 0),
            ).model_dump()
            for e in entries
        ]

    return {"mappings": mappings, "favorites": favorites}


@router.post("/mode-playlists", dependencies=[Depends(require_api_key)])
async def add_mode_playlist(body: ModePlaylistAdd, request: Request) -> dict:
    """Add a new mode-to-playlist mapping with an optional vibe tag."""
    if body.mode not in SUPPORTED_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported mode '{body.mode}'. Must be one of: {', '.join(SUPPORTED_MODES)}",
        )
    if body.vibe and body.vibe not in VALID_VIBES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid vibe '{body.vibe}'. Must be one of: {', '.join(VALID_VIBES)}",
        )

    mapper = request.app.state.music_mapper
    mapping_id = await mapper.add_mapping(
        mode=body.mode,
        favorite_title=body.favorite_title,
        vibe=body.vibe,
        auto_play=body.auto_play,
        priority=body.priority,
    )
    return {
        "status": "ok",
        "id": mapping_id,
        "mode": body.mode,
        "favorite_title": body.favorite_title,
        "vibe": body.vibe,
    }


@router.delete("/mode-playlists/{mapping_id}", dependencies=[Depends(require_api_key)])
async def remove_mode_playlist(mapping_id: int, request: Request) -> dict:
    """Remove a specific playlist mapping by ID."""
    mapper = request.app.state.music_mapper
    removed = await mapper.remove_mapping_by_id(mapping_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No mapping with id {mapping_id}")
    return {"status": "ok", "id": mapping_id}


# ------------------------------------------------------------------
# Library import & taste profile
# ------------------------------------------------------------------

@router.post("/import", dependencies=[Depends(require_api_key)])
@limiter.limit("5/minute")
async def import_library(file: UploadFile, request: Request) -> dict:
    """
    Import an Apple Music / iTunes library XML file.

    Parses the plist XML, extracts artist data, genre distribution,
    and playlist signals, then builds and persists a taste profile.
    """
    if not file.filename or not file.filename.lower().endswith(".xml"):
        raise HTTPException(status_code=400, detail="File must be a .xml file")

    content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
    if content_type and not any(
        content_type == allowed for allowed in _ALLOWED_IMPORT_CONTENT_TYPES
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Unexpected content type: {content_type}",
        )

    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            if int(declared_length) > MAX_IMPORT_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large (max {MAX_IMPORT_BYTES // (1024 * 1024)}MB)",
                )
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_IMPORT_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_IMPORT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {MAX_IMPORT_BYTES // (1024 * 1024)}MB)",
            )
        chunks.append(chunk)
    content = b"".join(chunks)

    if b"<!ENTITY" in content:
        raise HTTPException(
            status_code=400,
            detail="Entity declarations are not allowed in import XML",
        )

    import_service = request.app.state.library_import

    imports_dir = DATA_DIR / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = imports_dir / "library_import.xml"

    try:
        tmp_path.write_bytes(content)
        stats = await import_service.import_xml(tmp_path)
        return stats
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
    finally:
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


# ------------------------------------------------------------------
# Shadow discovery (#257)
# ------------------------------------------------------------------

@router.get("/discovery/status")
async def get_discovery_status(request: Request) -> dict:
    """Return non-actuating discovery capability without external calls."""
    discovery = getattr(request.app.state, "music_discovery", None)
    if discovery is None:
        raise HTTPException(status_code=503, detail="Music discovery not initialized")
    return discovery.status()


@router.post("/discovery/preview", dependencies=[Depends(require_api_key)])
@limiter.limit("4/hour")
async def preview_discovery(
    request: Request,
    mode: str = "gaming",
    policy: str = "gentle",
    count: int = 6,
    tracks_per_artist: int = 3,
) -> dict:
    """Generate explainable suggestions only; never actuates or persists rows."""
    if count < 1 or count > 10:
        raise HTTPException(status_code=400, detail="count must be between 1 and 10")
    if tracks_per_artist < 1 or tracks_per_artist > 5:
        raise HTTPException(
            status_code=400, detail="tracks_per_artist must be between 1 and 5"
        )
    discovery = getattr(request.app.state, "music_discovery", None)
    if discovery is None:
        raise HTTPException(status_code=503, detail="Music discovery not initialized")
    try:
        result = await discovery.preview(
            mode,
            policy=policy,
            count=count,
            tracks_per_artist=tracks_per_artist,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()


# ------------------------------------------------------------------
# Recommendations
# ------------------------------------------------------------------

@router.get("/recommendations")
async def get_recommendations(mode: str, request: Request) -> dict:
    """Get pending recommendations for a mode."""
    rec_service = request.app.state.recommendation_service
    if not rec_service.enabled:
        return {"recommendations": [], "message": "Last.fm API key not configured"}

    recs = await rec_service.get_recommendations(mode)
    return {"recommendations": recs}


@router.post("/recommendations/generate", dependencies=[Depends(require_api_key)])
async def generate_recommendations(
    request: Request, mode: str = "gaming"
) -> dict:
    """Trigger recommendation generation for a mode."""
    rec_service = request.app.state.recommendation_service
    if not rec_service.enabled:
        raise HTTPException(
            status_code=503,
            detail="Last.fm API key not configured. Add LASTFM_API_KEY to .env",
        )

    recs = await rec_service.generate_recommendations(mode)
    return {"recommendations": recs, "count": len(recs)}


@router.post("/recommendations/{rec_id}/feedback", dependencies=[Depends(require_api_key)])
async def submit_feedback(rec_id: int, request: Request) -> dict:
    """Submit feedback on a recommendation (like or dismiss)."""
    body = await request.json()
    action = body.get("action")
    if action not in ("liked", "dismissed"):
        raise HTTPException(
            status_code=400, detail="Action must be 'liked' or 'dismissed'"
        )

    rec_service = request.app.state.recommendation_service
    found = await rec_service.update_feedback(rec_id, action)
    if not found:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return {"status": "ok", "action": action}


@router.post("/preview", dependencies=[Depends(require_api_key)])
async def play_preview(request: Request) -> dict:
    """Play a 30-second iTunes preview on Sonos.

    Optional metadata fields (``track``, ``artist``, ``album``, ``artwork_url``)
    populate Sonos's Now Playing card via a DIDL-Lite envelope — without them,
    plain HTTP streams show blank metadata.
    """
    body = await request.json()
    preview_url = body.get("preview_url")
    if not preview_url:
        raise HTTPException(status_code=400, detail="preview_url is required")

    # SSRF guard: anyone authorized to hit write endpoints could otherwise
    # aim the speaker at internal addresses. The allowlist matches iTunes
    # preview clips + our own LAN-served TTS/static URLs and rejects
    # everything else with a 400 (distinguishes "bad input" from a 503
    # "Sonos broken" so we get useful telemetry).
    if not is_allowed_play_uri(preview_url):
        raise HTTPException(
            status_code=400, detail="preview_url not on the allowlist"
        )

    sonos = request.app.state.sonos
    _check_sonos_available(sonos)

    # Build the DIDL-Lite envelope from any metadata the caller supplied.
    # Empty string when no track/title — sonos_service.play_uri falls back
    # to SoCo's default behavior in that case.
    meta = build_track_didl_lite(
        title=str(body.get("track") or "").strip(),
        artist=str(body.get("artist") or "").strip() or None,
        album=str(body.get("album") or "").strip() or None,
        album_art_uri=str(body.get("artwork_url") or "").strip() or None,
    )

    success = await sonos.play_uri(preview_url, meta=meta or None)
    return {"status": "ok" if success else "error"}


@router.get("/taste")
async def get_music_taste(request: Request, limit: int = 10) -> dict:
    """Return read-only taste/familiarity diagnostics for Music Intelligence."""
    if limit < 1 or limit > 25:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 25")
    taste = getattr(request.app.state, "music_taste", None)
    if taste is None:
        raise HTTPException(status_code=503, detail="Music taste service not initialized")
    try:
        snapshot = await taste.snapshot()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Music taste snapshot unavailable") from exc
    return snapshot.summary(limit=limit)


@router.get("/curator/status")
async def get_curator_status(request: Request) -> dict:
    """Return shadow-curator capability/status without running the model."""
    curator = getattr(request.app.state, "music_curator", None)
    if curator is None:
        raise HTTPException(status_code=503, detail="Music curator not initialized")
    return curator.status()


@router.post("/curator/preview", dependencies=[Depends(require_api_key)])
@limiter.limit("6/hour")
async def preview_curator(
    request: Request, mode: str = "gameday", limit: int = 6,
) -> dict:
    """Generate a non-actuating, provider-verified curator preview.

    This endpoint may incur one bounded intent-provider call, so it is authenticated.
    The result is suggestions only: it cannot play Sonos, mutate mappings, or
    update bandit rewards.
    """
    curator = getattr(request.app.state, "music_curator", None)
    if curator is None:
        raise HTTPException(status_code=503, detail="Music curator not initialized")
    if not curator.supports_mode(mode):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported curator mode '{mode}'. Must be one of: "
                f"{', '.join(curator.supported_modes)}"
            ),
        )
    if limit < 1 or limit > 12:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 12")
    try:
        result = await curator.preview(mode, limit=limit)
    except MusicCuratorError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.to_dict()


@router.get("/bandit-status")
async def get_bandit_status(request: Request) -> dict:
    """Return the music bandit's arm landscape (Phase B visibility).

    Phase B groups arms by ``(mode, weather_class)`` so the top picks per
    mode can be inspected across weather classes — useful for MCP debugging
    and verifying context-aware selection without a full matrix UI.
    """
    bandit = getattr(request.app.state, "music_bandit", None)
    if bandit is None:
        return {"arm_count": 0, "total_selections": 0, "top_arms": {}}
    return bandit.get_status()
