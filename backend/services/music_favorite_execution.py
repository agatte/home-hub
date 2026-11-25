"""Exact saved Sonos container start for an explicit listening selection.

The existing title-based favorite route is deliberately not used. The device
is the authority for the container, while the shared session caller supplies
lifecycle, owner and manual-intent authority. Never clear a queue or change
play mode/volume, and never retry uncertain device writes.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import unquote

from soco.data_structures import to_didl_string

from backend.services.music_continuation import MAX_CONTINUATION_TRACKS, QueuedSong
from backend.services.music_mix_execution import MixStartResult, _item_matches
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


MAX_CONTAINER_TRACKS = 32


def _append_container_sync(device, item, uri):
    """Preserve the complete SOAP receipt, not just the first queue position."""
    resources = getattr(item, "resources", None) or []
    if not resources or resources[0].uri != uri:
        return None
    metadata = to_didl_string(item)
    response = device.avTransport.AddURIToQueue([
        ("InstanceID", 0), ("EnqueuedURI", uri), ("EnqueuedURIMetaData", metadata),
        ("DesiredFirstTrackNumberEnqueued", 0), ("EnqueueAsNext", 0),
    ], timeout=5.0)
    if int(response["FirstTrackNumberEnqueued"]) != 1:
        return None
    count = int(response["NumTracksAdded"])
    length = int(response["NewQueueLength"])
    return count if count > 0 and count == length else None


def _queue_prefix_sync(device, size, revision):
    """One bounded browse; every item must belong to the same exact revision."""
    if not 1 <= size <= MAX_CONTAINER_TRACKS + MAX_CONTINUATION_TRACKS:
        return None
    response = device.contentDirectory.Browse([
        ("ObjectID", "Q:0"), ("BrowseFlag", "BrowseDirectChildren"),
        ("Filter", "*"), ("StartingIndex", 0), ("RequestedCount", size),
        ("SortCriteria", ""),
    ], timeout=3.0)
    xml = response.get("Result")
    if (
        str(response.get("UpdateID") or "") != revision
        or int(response.get("TotalMatches") or 0) != size
        or int(response.get("NumberReturned") or 0) != size
        or not isinstance(xml, str) or len(xml) > 512000
    ):
        return None
    root = ET.fromstring(xml)
    if root.tag.rsplit("}", 1)[-1] != "DIDL-Lite":
        return None
    rows = tuple(ET.tostring(item, encoding="unicode") for item in root
                 if item.tag.rsplit("}", 1)[-1] == "item")
    return rows if len(rows) == size else None


def _exact_queued_songs(rows):
    songs = []
    for xml in rows:
        item = ET.fromstring(xml)
        resources = [(node.text or "").strip() for node in item
                     if node.tag.rsplit("}", 1)[-1] == "res"]
        ids = set()
        for uri in resources:
            match = re.fullmatch(r"x-sonos-http:song:([0-9]+)", unquote(uri).split("?", 1)[0],
                                 flags=re.IGNORECASE)
            if not match:
                return ()
            ids.add(match.group(1))
        titles = {(node.text or "").strip() for node in item
                  if node.tag.rsplit("}", 1)[-1] == "title"}
        artists = {(node.text or "").strip() for node in item
                   if node.tag.rsplit("}", 1)[-1] == "artist"}
        if not artists:
            artists = {(node.text or "").strip() for node in item
                       if node.tag.rsplit("}", 1)[-1] == "creator"}
        if len(ids) != 1 or len(titles) != 1 or len(artists) != 1 or "" in titles or "" in artists:
            return ()
        songs.append(QueuedSong(next(iter(ids)), next(iter(titles)), next(iter(artists))))
    return tuple(songs)


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
    continuation_planner=None, mode: str = "general", on_started=None,
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
    continuation_count = 0

    async def setup():
        nonlocal attempted, appended, reason, continuation_count
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
            return _append_container_sync(device, item, candidate.uri)

        size = await sonos._safe_mutation_call(append_exact)
        if type(size) is not int or size <= 0 or sonos.device is not device:
            return None
        snapshot = await sonos._safe_call(sonos._queue_item_snapshot_sync, 0, 1.0)
        current = await sonos.get_prepare_evidence()
        if (not _prepared_queue(current, snapshot, uid=uid, volume=volume)
                or snapshot[1] != size
                or current["queue_update_id"] == evidence.get("queue_update_id")):
            return None
        appended = 1  # One confirmed container append, not a track count.
        prefix = None
        if continuation_planner is not None and size <= MAX_CONTAINER_TRACKS:
            reason = "container_prefix_unverified"
            prefix = await sonos._safe_call(
                _queue_prefix_sync, device, size, snapshot[0],
            )
            if prefix is None:
                return None
            songs = _exact_queued_songs(prefix)
            tail = await continuation_planner.preview_container(songs, mode=mode) if songs else ()
            if tail and not await continuation_planner.revalidate(tail, mode=mode):
                tail = ()
            if not still_current() or sonos.device is not device:
                return None
            if len(tail) > MAX_CONTINUATION_TRACKS:
                return None
            ids = {song.provider_id for song in songs}
            names = {(song.artist.casefold(), song.title.casefold()) for song in songs}
            for item in tail:
                artist = str(item.metadata.get("artist_name") or "")
                identity = item.provider_id
                if (
                    not songs or item.provider != "itunes_search" or item.media_type != "track"
                    or not item.verified or not item.catalog_verified or not item.playback_capable
                    or item.playback_adapter != "sonos_apple_music_share_link"
                    or item.playback_reference != item.uri
                    or item.metadata.get("playback_verification") != "live_verified"
                    or not identity.isascii() or not identity.isdigit()
                    or identity in ids or not artist
                    or (artist.casefold(), item.title.casefold()) in names
                    or sonos._canonical_apple_music_share_link(item.uri) != f"song:{identity}"
                ):
                    return None
                ids.add(identity)
                names.add((artist.casefold(), item.title.casefold()))

            for item in tail:
                reason = "container_or_authority_changed_before_tail"
                if not still_current() or sonos.device is not device:
                    return None

                def append_track():
                    if (
                        not still_current() or sonos.device is not device
                        or sonos._prepare_evidence_sync() != current
                        or _queue_prefix_sync(device, size, snapshot[0]) != prefix
                        or not still_current() or sonos.device is not device
                    ):
                        return None
                    return sonos._add_apple_music_share_link_sync(item.uri)

                position = await sonos._safe_mutation_call(append_track)
                reason = "continuation_append_unverified"
                if type(position) is not int or position != size + 1:
                    return None
                first = await sonos._safe_call(sonos._queue_item_snapshot_sync, 0, 1.0)
                last = await sonos._safe_call(sonos._queue_item_snapshot_sync, size, 1.0)
                fresh = await sonos.get_prepare_evidence()
                if (
                    not _prepared_queue(fresh, first, uid=uid, volume=volume)
                    or first[0] == snapshot[0] or first[1] != size + 1
                    or first[2] != snapshot[2]
                    or not _item_matches(last, item.provider_id, size + 1)
                    or last[0] != first[0]
                ):
                    return None
                updated = await sonos._safe_call(_queue_prefix_sync, device, size + 1, first[0])
                if updated is None or updated[:-1] != prefix:
                    return None
                size += 1
                prefix, snapshot, current = updated, first, fresh
                continuation_count += 1
                appended += 1
            if await sonos._safe_call(_queue_prefix_sync, device, size, snapshot[0]) != prefix:
                return None
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
        return snapshot, uid, volume, device, prefix

    try:
        proof = await mutation_runner(setup)
        if proof is None:
            return MixStartResult("indeterminate" if attempted else "suppressed", reason, appended)
        snapshot, uid, volume, device, prefix = proof
        verified = await sonos._verify_queue_playback_started(
            0, snapshot[1], snapshot, queue_uid=uid, max_volume=volume,
        )
        if not still_current() or sonos.device is not device:
            return MixStartResult("indeterminate", "authority_changed_at_verification", appended)
        if not verified:
            return MixStartResult("indeterminate", "playback_start_unverified", appended)
        if on_started is not None and prefix:
            try:
                on_started(snapshot, uid, volume, device, prefix)
            except Exception:
                pass
        return MixStartResult("started", "advancing_playback_verified", appended, continuation_count)
    except Exception:
        return MixStartResult("indeterminate" if attempted else "suppressed", reason, appended)
