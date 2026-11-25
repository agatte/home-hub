"""Exact saved Sonos container start for an explicit listening selection.

The existing title-based favorite route is deliberately not used. The device
is the authority for the container, while the shared session caller supplies
lifecycle, owner and manual-intent authority. Never clear a queue or change
play mode/volume, and never retry uncertain device writes.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from typing import Any

from backend.services.music_mix_execution import MixStartResult
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.playlist_catalog import VerifiedMusicCandidate


def _resolve_live_container(device, candidate: VerifiedMusicCandidate):
    """Use fresh raw provider objects, preserving the catalog's identity rule."""
    if candidate.source == "playlist":
        objects = device.get_sonos_playlists()
    elif candidate.source == "favorite":
        objects = device.music_library.get_sonos_favorites()
    else:
        return None
    matches = []
    for obj in objects:
        if candidate.source == "playlist":
            item = obj
            uri = obj.get_uri() if hasattr(obj, "get_uri") else getattr(obj, "uri", "")
        else:
            item = getattr(obj, "reference", obj)
            resources = getattr(item, "resources", None) or []
            if not resources:
                continue
            uri = getattr(resources[0], "uri", "")
        uri = str(uri or "").strip()
        identity = hashlib.sha256(f"{candidate.source}|{uri}".encode()).hexdigest()[:16]
        if uri and identity == candidate.provider_id:
            matches.append((obj, item, uri))
    # Detect ambiguity before title comparison: two objects sharing an identity
    # cannot be disambiguated just by their mutable display names.
    if len(matches) != 1:
        return None
    obj, item, uri = matches[0]
    if uri != candidate.uri or str(getattr(obj, "title", "") or "").strip() != candidate.title:
        return None
    return item


def _prepared_queue(evidence, snapshot, *, uid, volume):
    """Require a stable queue and no unrelated loaded source after the append."""
    if not isinstance(evidence, dict) or not snapshot or len(snapshot) != 3:
        return False
    revision, size, xml = snapshot
    if (
        not revision or type(size) is not int or size <= 0
        or not isinstance(xml, str) or len(xml) > 65536
        or evidence.get("queue_uid") != uid
        or evidence.get("queue_size") != size
        or evidence.get("queue_update_id") != revision
        or evidence.get("queue_first_item_hash") != hashlib.sha256(xml.encode()).hexdigest()
        or evidence.get("coordinator") is not True
        or evidence.get("play_mode") != "NORMAL"
        or evidence.get("transport_state") not in {"STOPPED", "NO_MEDIA_PRESENT"}
        or evidence.get("mute") is not False or evidence.get("volume") != volume
    ):
        return False
    try:
        root = ET.fromstring(xml)
        items = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "item"]
        if len(items) != 1:
            return False
        resources = {(node.text or "").strip() for node in items[0]
                     if node.tag.rsplit("}", 1)[-1] == "res" and (node.text or "").strip()}
    except ET.ParseError:
        return False
    if not resources:
        return False
    uri = evidence.get("current_uri")
    track_uri = evidence.get("queue_track_uri")
    if uri == "" and track_uri == "":
        return not any(evidence.get(key) for key in ("metadata", "media_metadata", "title"))
    # The player may automatically load the first queued track when a
    # container is added. Accept only its actual queue source and resource.
    return (uri == f"x-rincon-queue:{uid}#0" and evidence.get("queue_track") == 1
            and track_uri in resources)


async def start_selected_favorite(
    sonos: Any, plan: SelectedListeningPlan, *, mutation_runner, preflight, still_current,
) -> MixStartResult:
    if (
        plan.status != "verified_preview" or plan.kind != "favorite"
        or plan.actuation_allowed is not False or len(plan.candidates) != 1
    ):
        return MixStartResult("suppressed", "invalid_favorite")
    candidate = plan.candidates[0]
    if (
        candidate.provider != "sonos_favorite" or candidate.media_type != "favorite"
        or candidate.source not in {"playlist", "favorite"}
        or not candidate.uri or not candidate.title
        or candidate.verified is not True or candidate.catalog_verified is not True
        or not candidate.playback_capable or candidate.playback_adapter != "sonos_favorite_title"
        or candidate.playback_reference != candidate.title
        or plan.choice_id != "sonos_favorite:" + candidate.provider_id
        or candidate.provider_id != hashlib.sha256(
            f"{candidate.source}|{candidate.uri}".encode(),
        ).hexdigest()[:16]
    ):
        return MixStartResult("suppressed", "invalid_favorite_identity")

    attempted = False
    appended = 0
    reason = "initial_admission_failed"

    async def setup():
        nonlocal attempted, appended, reason
        initial = await preflight(expected_queue_size=0)
        if initial.get("reason") is not None or not still_current():
            return None
        evidence = await sonos.get_prepare_evidence()
        volume = initial.get("volume_used")
        if (not sonos.prepare_unloaded(evidence) or type(volume) is not int
                or volume <= 0 or evidence.get("volume") != volume or not still_current()):
            return None
        uid = evidence.get("queue_uid")
        device = sonos.device
        if device is None or not uid or str(device.uid) != uid:
            return None

        def append_exact():
            nonlocal attempted, reason
            reason = "favorite_identity_unavailable"
            if not still_current() or sonos.device is not device:
                return None
            item = _resolve_live_container(device, candidate)
            if item is None:
                return None
            reason = "authority_or_queue_changed_before_append"
            if (sonos.device is not device or sonos._prepare_evidence_sync() != evidence
                    or not still_current() or sonos.device is not device):
                return None
            attempted = True
            reason = "favorite_append_unverified"
            return device.add_to_queue(item)

        position = await sonos._safe_mutation_call(append_exact)
        if type(position) is not int or position != 1 or sonos.device is not device:
            return None
        snapshot = await sonos._safe_call(sonos._queue_item_snapshot_sync, 0, 1.0)
        current = await sonos.get_prepare_evidence()
        if (not _prepared_queue(current, snapshot, uid=uid, volume=volume)
                or current["queue_update_id"] == evidence.get("queue_update_id")):
            return None
        appended = 1  # One confirmed container append, not a track count.
        reason = "authority_or_queue_changed_before_play"
        if await sonos.get_prepare_evidence() != current:
            return None
        if not still_current() or sonos.device is not device:
            return None
        reason = "play_command_unverified"
        if not sonos._play_queue_item_if_unchanged_sync(
            0, snapshot[1], snapshot, queue_uid=uid, max_volume=volume,
        ):
            return None
        return snapshot, uid, volume, device

    try:
        proof = await mutation_runner(setup)
        if proof is None:
            return MixStartResult("indeterminate" if attempted else "suppressed", reason, appended)
        snapshot, uid, volume, device = proof
        verified = await sonos._verify_queue_playback_started(
            0, snapshot[1], snapshot, queue_uid=uid, max_volume=volume,
        )
        if not still_current() or sonos.device is not device:
            return MixStartResult("indeterminate", "authority_changed_at_verification", appended)
        if not verified:
            return MixStartResult("indeterminate", "playback_start_unverified", appended)
        return MixStartResult("started", "advancing_playback_verified", appended)
    except Exception:
        return MixStartResult("indeterminate" if attempted else "suppressed", reason, appended)
