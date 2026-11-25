"""Repeat a deliberate mix selection without clearing an existing known queue.

Retained provenance is identity evidence, never permission. Only a fresh
owner-selected start under the shared writer lock may append and start.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET

from backend.services.music_continuation import QueuedSong
from backend.services.music_favorite_execution import (
    MAX_CONTAINER_TRACKS, _exact_queued_songs, _resolve_live_container, to_didl_string,
)
from backend.services.music_mix_execution import MixStartResult, _item_matches
from backend.services.music_queue_identity import apple_song_id
from backend.services.music_selected_plan import MAX_SELECTED_TRACKS, _exact_song
from backend.services.music_sustained_listening import (
    MAX_SESSION_TRACKS, QueueProof, RetainedQueue, _read_prefix_sync, started_queue_proof,
)


def stopped_queue_matches(proof: QueueProof, evidence, *, ceiling: int) -> bool:
    if not proof.valid() or not isinstance(evidence, dict):
        return False
    track = evidence.get("queue_track")
    volume = evidence.get("volume")
    if (
        evidence.get("queue_uid") != proof.uid
        or evidence.get("queue_update_id") != proof.revision
        or evidence.get("queue_size") != len(proof.songs)
        or evidence.get("queue_first_item_hash") != proof.first_hash
        or evidence.get("current_uri") != f"x-rincon-queue:{proof.uid}#0"
        or evidence.get("transport_state") != "STOPPED"
        or evidence.get("coordinator") is not True
        or evidence.get("play_mode") != "NORMAL"
        or evidence.get("mute") is not False
        or type(volume) is not int or not 0 < volume <= ceiling
        or type(track) is not int or not 1 <= track <= len(proof.songs)
    ):
        return False
    uri = evidence.get("queue_track_uri")
    return apple_song_id(uri) == proof.songs[track - 1].provider_id


async def probe_repeat_queue(sonos, origin: RetainedQueue, *, ceiling, still_current):
    """Read-only preflight. Unknown, foreign, changed or active queues abstain."""
    if not still_current() or sonos is not origin.sonos or sonos.device is not origin.device:
        return None
    if len(origin.rows) != len(origin.proof.songs) or len(origin.rows) >= MAX_SESSION_TRACKS:
        return None
    evidence = await sonos.get_prepare_evidence()
    if not stopped_queue_matches(origin.proof, evidence, ceiling=ceiling):
        return None
    if await sonos._safe_call(
        _read_prefix_sync, origin.device, len(origin.rows), origin.proof.revision,
    ) != origin.rows:
        return None
    if (
        not still_current() or sonos.device is not origin.device
        or await sonos.get_prepare_evidence() != evidence
        or sonos.device is not origin.device or not still_current()
    ):
        return None
    return evidence


async def start_repeat_mix(
    sonos, plan, origin: RetainedQueue, initial, *, mutation_runner,
    still_current, on_started,
):
    """Append only selected exact songs; seek to the first NEW track once."""
    members = plan.candidates
    ids = [item.provider_id for item in members]
    offset = len(origin.rows)
    if (
        plan.status != "verified_preview" or plan.kind != "artist_mix"
        or plan.actuation_allowed is not False or not 2 <= len(ids) <= MAX_SELECTED_TRACKS
        or len(set(ids)) != len(ids) or plan.choice_id != "artist_mix:" + ",".join(ids)
        or not offset or offset + len(ids) > MAX_SESSION_TRACKS
    ):
        return MixStartResult("suppressed", "repeat_selection_unavailable")
    try:
        for item in members:
            artist = item.metadata.get("artist_name")
            if (
                not isinstance(artist, str) or not artist.strip()
                or not _exact_song(item, item.provider_id, item.title, artist)
                or sonos._canonical_apple_music_share_link(item.uri) != f"song:{item.provider_id}"
            ):
                return MixStartResult("suppressed", "invalid_member")
    except Exception:
        return MixStartResult("suppressed", "invalid_member")

    batches = tuple(
        ((QueuedSong(item.provider_id, item.title, item.metadata["artist_name"]),),
         lambda item=item: sonos._add_apple_music_share_link_sync(item.uri))
        for item in members
    )
    return await _run_repeat(
        sonos, origin, initial, batches, mutation_runner=mutation_runner,
        still_current=still_current, on_started=on_started,
    )


def _song_resources(rows):
    """Require exact Apple service resources, not merely a numeric song id."""
    result = []
    for row in rows:
        root = ET.fromstring(row)
        resources = tuple((node.text or "").strip() for node in root
                          if node.tag.rsplit("}", 1)[-1] == "res")
        if not resources or any(
            apple_song_id(uri) is None
            for uri in resources
        ):
            return None
        result.append(resources)
    return tuple(result)


def _saved_expansion(device, candidate, capacity):
    """Bounded native saved playlist expansion; never guess cloud contents."""
    item = _resolve_live_container(device, candidate)
    if item is None:
        return None
    identity = getattr(item, "item_id", "")
    match = re.fullmatch(r"SQ:([0-9]+)", identity) if isinstance(identity, str) else None
    if (
        not match or getattr(item, "parent_id", None) != "SQ:"
        or candidate.uri != "file:///jffs/settings/savedqueues.rsq#" + match.group(1)
    ):
        return None
    limit = min(MAX_CONTAINER_TRACKS, capacity)
    if limit < 1:
        return None
    response = device.contentDirectory.Browse([
        ("ObjectID", identity), ("BrowseFlag", "BrowseDirectChildren"),
        ("Filter", "*"), ("StartingIndex", 0), ("RequestedCount", limit),
        ("SortCriteria", ""),
    ], timeout=3.0)
    revision = str(response.get("UpdateID") or "")
    count = int(response.get("TotalMatches") or 0)
    xml = response.get("Result")
    if (
        not revision or not 1 <= count <= limit
        or int(response.get("NumberReturned") or 0) != count
        or not isinstance(xml, str) or len(xml) > 512000
    ):
        return None
    root = ET.fromstring(xml)
    if root.tag.rsplit("}", 1)[-1] != "DIDL-Lite":
        return None
    rows = tuple(ET.tostring(node, encoding="unicode") for node in root
                 if node.tag.rsplit("}", 1)[-1] == "item")
    songs = _exact_queued_songs(rows)
    resources = _song_resources(rows)
    if len(rows) != count or len(songs) != count or resources is None:
        return None
    item_resources = getattr(item, "resources", None) or []
    if not item_resources or item_resources[0].uri != candidate.uri:
        return None
    return item, (identity, revision, songs, resources)


async def start_repeat_favorite(
    sonos, plan, origin, initial, *, mutation_runner, still_current, on_started,
):
    if (
        plan.status != "verified_preview" or plan.kind != "favorite"
        or plan.actuation_allowed is not False or len(plan.candidates) != 1
    ):
        return MixStartResult("suppressed", "invalid_favorite")
    candidate = plan.candidates[0]
    if (
        candidate.provider != "sonos_favorite" or candidate.media_type != "favorite"
        or candidate.source != "playlist" or not candidate.title or not candidate.uri
        or candidate.verified is not True or candidate.catalog_verified is not True
        or not candidate.playback_capable or candidate.playback_adapter != "sonos_favorite_title"
        or candidate.playback_reference != candidate.title
        or plan.choice_id != "sonos_favorite:" + candidate.provider_id
        or candidate.provider_id != hashlib.sha256(
            f"{candidate.source}|{candidate.uri}".encode(),
        ).hexdigest()[:16]
    ):
        return MixStartResult("suppressed", "repeat_playlist_unavailable")
    offset = len(origin.rows)
    capacity = MAX_SESSION_TRACKS - offset
    device = origin.device
    try:
        if not still_current() or sonos.device is not device:
            return MixStartResult("suppressed", "repeat_queue_changed")
        prepared = await sonos._safe_call(_saved_expansion, device, candidate, capacity)
        if prepared is None or not still_current() or sonos.device is not device:
            return MixStartResult("suppressed", "repeat_playlist_contents_unverified")
        _, expected = prepared
        songs, resources = expected[2:]

        def prepare_append():
            fresh = _saved_expansion(device, candidate, capacity)
            if fresh is None or fresh[1] != expected:
                return None
            item = fresh[0]
            metadata = to_didl_string(item)

            def append():
                result = device.avTransport.AddURIToQueue([
                    ("InstanceID", 0), ("EnqueuedURI", candidate.uri),
                    ("EnqueuedURIMetaData", metadata),
                    ("DesiredFirstTrackNumberEnqueued", 0), ("EnqueueAsNext", 0),
                ], timeout=5.0)
                if (
                    int(result["FirstTrackNumberEnqueued"]) != offset + 1
                    or int(result["NumTracksAdded"]) != len(songs)
                    or int(result["NewQueueLength"]) != offset + len(songs)
                ):
                    return None
                return offset + 1

            return append

        return await _run_repeat(
            sonos, origin, initial, ((songs, None),), mutation_runner=mutation_runner,
            still_current=still_current, on_started=on_started,
            prepare_append=prepare_append, expected_resources=resources,
        )
    except Exception:
        return MixStartResult("suppressed", "repeat_playlist_contents_unverified")


async def _run_repeat(
    sonos, origin, initial, batches, *, mutation_runner, still_current, on_started,
    prepare_append=None, expected_resources=None,
):
    offset = len(origin.rows)
    ids = [song.provider_id for songs, _ in batches for song in songs]
    attempted = False
    appended = 0
    reason = "repeat_queue_changed"
    device = origin.device
    volume = initial["volume"]
    uid = origin.proof.uid

    async def setup():
        nonlocal attempted, appended, reason
        proof, rows, evidence = origin.proof, origin.rows, initial
        if await probe_repeat_queue(sonos, origin, ceiling=volume, still_current=still_current) != evidence:
            return None
        first = None
        for songs, append in batches:
            size = len(rows)
            new_size = size + len(songs)

            def append_one():
                nonlocal attempted
                if not still_current() or sonos.device is not device:
                    return None
                operation = prepare_append() if prepare_append is not None else append
                if operation is None:
                    return None
                if _read_prefix_sync(device, size, proof.revision) != rows:
                    return None
                if (
                    sonos._prepare_evidence_sync() != evidence
                    or sonos.device is not device or not still_current()
                ):
                    return None
                attempted = True
                return operation()

            reason = "repeat_append_unverified"
            position = await sonos._safe_mutation_call(append_one)
            if type(position) is not int or position != size + 1 or not still_current():
                return None
            first = await sonos._safe_call(sonos._queue_item_snapshot_sync, 0, 1.0)
            last = await sonos._safe_call(sonos._queue_item_snapshot_sync, new_size - 1, 1.0)
            if (
                not first or len(first) != 3 or first[1] != new_size
                or not first[0] or first[0] == proof.revision
                or hashlib.sha256(first[2].encode()).hexdigest() != proof.first_hash
                or not _item_matches(last, songs[-1].provider_id, new_size)
                or last[0] != first[0]
            ):
                return None
            updated = await sonos._safe_call(_read_prefix_sync, device, new_size, first[0])
            if updated is None or updated[:size] != rows:
                return None
            if expected_resources is not None and _song_resources(updated[size:]) != expected_resources:
                return None
            next_proof = started_queue_proof(first, uid, volume, updated)
            if next_proof is None or next_proof.songs != proof.songs + songs:
                return None
            fresh = await sonos.get_prepare_evidence()
            expected = {**evidence, "queue_update_id": first[0], "queue_size": new_size}
            if fresh != expected or not stopped_queue_matches(next_proof, fresh, ceiling=volume):
                return None
            proof, rows, evidence = next_proof, updated, fresh
            appended += 1

        reason = "repeat_queue_changed_before_play"
        target = await sonos._safe_call(sonos._queue_item_snapshot_sync, offset, 1.0)
        if (
            not _item_matches(target, ids[0], len(rows)) or target[0] != proof.revision
            or await sonos._safe_call(_read_prefix_sync, device, len(rows), proof.revision) != rows
            or await sonos.get_prepare_evidence() != evidence
            or not still_current() or sonos.device is not device
        ):
            return None
        reason = "repeat_play_unverified"
        if not sonos._play_queue_item_if_unchanged_sync(
            offset, len(rows), target, queue_uid=uid, max_volume=volume,
        ):
            return None
        return first, target, rows

    try:
        result = await mutation_runner(setup)
        if result is None:
            return MixStartResult("indeterminate" if attempted else "suppressed", reason, appended)
        first, target, rows = result
        verified = await sonos._verify_queue_playback_started(
            offset, len(rows), target, queue_uid=uid, max_volume=volume,
        )
        if not verified or not still_current() or sonos.device is not device:
            return MixStartResult("indeterminate", "repeat_playback_start_unverified", appended)
        on_started(first, uid, volume, device, rows)
        return MixStartResult("started", "advancing_playback_verified", appended)
    except Exception:
        return MixStartResult("indeterminate" if attempted else "suppressed", reason, appended)
