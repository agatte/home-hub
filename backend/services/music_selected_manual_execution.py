"""Explicit selected playback under the caller's shared manual audio lock.

Existing queue entries are preserved as opaque identity evidence, not owned
music. Only the new suffix earns continuation authority. Never retry or clear.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from urllib.parse import urlsplit

from backend.services.music_continuation import MAX_CONTINUATION_TRACKS
from backend.services.music_manual_policy import selected_play_volume
from backend.services.music_mix_execution import MixStartResult, _item_matches
from backend.services.music_queue_identity import (
    apple_song_id, play_source_fingerprint, same_manual_source, selected_apple_source,
)
from backend.services.music_repeat_selection import _song_resources
from backend.services.music_favorite_execution import _resolve_live_container, to_didl_string
from backend.services.music_selected_plan import MAX_SELECTED_TRACKS, _exact_song
from backend.services.music_sustained_listening import MAX_QUEUE_TRACKS, _read_prefix_sync, _read_rows_sync

_NORMALIZABLE_MODES = {
    "NORMAL", "SHUFFLE", "SHUFFLE_NOREPEAT", "REPEAT_ALL",
    "REPEAT_ONE", "SHUFFLE_REPEAT_ONE",
}
_IDLE = {"STOPPED", "NO_MEDIA_PRESENT"}
_ORDINARY_SCHEMES = {
    "x-sonos-http", "x-sonosapi-hls-static", "x-sonosapi-hls",
    "x-sonosapi-stream", "x-sonosapi-radio",
}


@dataclass(frozen=True)
class ManualStartProof:
    first: tuple
    uid: str
    volume: int
    device: object
    rows: tuple[str, ...]
    offset: int


def ordinary_source(sonos, evidence):
    if not isinstance(evidence, dict):
        return False
    uid = evidence.get("queue_uid")
    size = evidence.get("queue_size")
    state = evidence.get("transport_state")
    volume = evidence.get("volume")
    if (
        not uid or not evidence.get("queue_update_id")
        or type(size) is not int or not 0 <= size <= MAX_QUEUE_TRACKS
        or evidence.get("coordinator") is not True
        or evidence.get("mute") is not False
        or type(volume) is not int or not 0 <= volume <= 100
        or evidence.get("play_mode") not in _NORMALIZABLE_MODES
        or state not in _IDLE | {"PLAYING", "PAUSED_PLAYBACK"}
    ):
        return False
    proof = play_source_fingerprint(evidence)
    if proof is None:
        return False
    uri, track, _, metadata = proof
    if not uri:
        return state in _IDLE and not any(proof)
    if uri == f"x-rincon-queue:{uid}#0":
        return size > 0
    try:
        source = urlsplit(uri)
        if source.scheme in _ORDINARY_SCHEMES:
            return bool(source.path.strip("/ "))
        if source.scheme in {"http", "https"}:
            return (
                bool(source.netloc and source.path.strip("/ "))
                and track == uri
                and sonos._stopped_http_music_metadata_matches(metadata, uri)
            )
    except ValueError:
        pass
    # TV/line-in/group follower/unknown source: no new takeover semantics.
    return False


def _rows(device, evidence):
    size = evidence["queue_size"]
    return _read_prefix_sync(device, size, evidence["queue_update_id"]) if size else ()


def _exact_mix(sonos, plan):
    members = plan.candidates
    ids = tuple(item.provider_id for item in members)
    if (
        plan.status != "verified_preview" or plan.kind != "artist_mix"
        or plan.actuation_allowed is not False
        or not 2 <= len(ids) <= MAX_SELECTED_TRACKS
        or len(set(ids)) != len(ids)
        or plan.choice_id != "artist_mix:" + ",".join(ids)
    ):
        return False
    return all(
        isinstance(item.metadata.get("artist_name"), str)
        and bool(item.metadata["artist_name"].strip())
        and _exact_song(item, item.provider_id, item.title, item.metadata["artist_name"])
        and sonos._canonical_apple_music_share_link(item.uri) == f"song:{item.provider_id}"
        for item in members
    )


def _exact_favorite(plan):
    if (
        plan.status != "verified_preview" or plan.kind != "favorite"
        or plan.actuation_allowed is not False or len(plan.candidates) != 1
    ):
        return False
    c = plan.candidates[0]
    return (
        c.provider == "sonos_favorite" and c.media_type == "favorite"
        and c.source in {"playlist", "favorite"} and bool(c.title and c.uri)
        and c.verified is True and c.catalog_verified is True
        and c.playback_capable and c.playback_adapter == "sonos_favorite_title"
        and c.playback_reference == c.title
        and plan.choice_id == "sonos_favorite:" + c.provider_id
        and c.provider_id == hashlib.sha256(f"{c.source}|{c.uri}".encode()).hexdigest()[:16]
    )


def _resources(row):
    try:
        node = ET.fromstring(row)
        values = tuple((child.text or "").strip() for child in node
                       if child.tag.rsplit("}", 1)[-1] == "res")
        return values if values and all(values) else None
    except (TypeError, ET.ParseError):
        return None


def _manual_saved_expansion(device, candidate, capacity):
    """Exact native saved playlist, independent of provider or Apple identity."""
    item = _resolve_live_container(device, candidate)
    identity = getattr(item, "item_id", "")
    match = re.fullmatch(r"SQ:([0-9]+)", identity) if isinstance(identity, str) else None
    if (
        item is None or not match or getattr(item, "parent_id", None) != "SQ:"
        or candidate.uri != "file:///jffs/settings/savedqueues.rsq#" + match.group(1)
        or capacity < 1
    ):
        return None
    refs = getattr(item, "resources", None) or ()
    if not refs or refs[0].uri != candidate.uri:
        return None
    response = device.contentDirectory.Browse([
        ("ObjectID", identity), ("BrowseFlag", "BrowseDirectChildren"),
        ("Filter", "*"), ("StartingIndex", 0), ("RequestedCount", 1),
        ("SortCriteria", ""),
    ], timeout=3.0)
    revision = str(response.get("UpdateID") or "")
    count = int(response.get("TotalMatches") or 0)
    if not revision or not 1 <= count <= capacity or int(response.get("NumberReturned") or 0) != 1:
        return None
    rows = _read_rows_sync(device, identity, count, revision)
    if rows is None:
        return None
    resources = tuple(_resources(row) for row in rows)
    if not all(resources):
        return None
    return item, (identity, revision, rows, resources)


async def execute_selected_manual(sonos, plan, *, still_current, ceiling, continuation=()):
    """Return (truthful receipt, optional exact start proof); caller owns audio lock."""
    attempted = False
    appended = 0
    reason = "manual_source_unavailable"
    device = sonos.device

    def current():
        return device is not None and sonos.device is device and still_current()

    def failure():
        return MixStartResult("indeterminate" if attempted else "suppressed", reason, appended), None

    try:
        if not current():
            return failure()
        if not (_exact_mix(sonos, plan) or _exact_favorite(plan)):
            reason = "manual_selection_unavailable"
            return failure()
        evidence = await sonos.get_prepare_evidence()
        if not ordinary_source(sonos, evidence):
            reason = "sonos_muted" if isinstance(evidence, dict) and evidence.get("mute") else reason
            return failure()
        if selected_play_volume(evidence["volume"], ceiling()) is None:
            reason = "manual_volume_unavailable"
            return failure()
        uid = evidence["queue_uid"]
        if str(device.uid) != uid or not current():
            return failure()
        offset = evidence["queue_size"]
        rows = await sonos._safe_call(_rows, device, evidence)
        if rows is None or not same_manual_source(evidence, await sonos.get_prepare_evidence()) or not current():
            reason = "manual_queue_changed"
            return failure()

        batches = []
        capacity = MAX_QUEUE_TRACKS - offset
        if plan.kind == "artist_mix":
            if len(plan.candidates) > capacity:
                reason = "manual_queue_capacity"
                return failure()
            members = list(plan.candidates)
            if isinstance(continuation, tuple) and len(continuation) <= MAX_CONTINUATION_TRACKS:
                try:
                    tail = []
                    seen = {item.provider_id for item in members}
                    names = {(item.metadata["artist_name"].casefold(), item.title.casefold()) for item in members}
                    for item in continuation:
                        artist = item.metadata.get("artist_name")
                        name = (artist.casefold(), item.title.casefold())
                        if (
                            not artist.strip() or item.provider_id in seen or name in names
                            or not _exact_song(item, item.provider_id, item.title, artist)
                            or sonos._canonical_apple_music_share_link(item.uri) != f"song:{item.provider_id}"
                        ):
                            raise ValueError("invalid optional continuation")
                        seen.add(item.provider_id)
                        names.add(name)
                        tail.append(item)
                    members.extend(tail[:capacity - len(members)])
                except (AttributeError, TypeError, ValueError, KeyError):
                    pass
            for item in members:
                batches.append(((item.provider_id,), None,
                                lambda item=item: sonos._add_apple_music_share_link_sync(item.uri)))
        elif plan.candidates[0].source == "playlist":
            candidate = plan.candidates[0]
            expansion = await sonos._safe_call(_manual_saved_expansion, device, candidate, capacity)
            if expansion is None or not current():
                reason = "manual_playlist_unverified"
                return failure()
            _, expected = expansion
            _, resources = expected[2:]
            ids = (None,) * len(resources)

            def append_saved():
                fresh = _manual_saved_expansion(device, candidate, capacity)
                if fresh is None or fresh[1] != expected:
                    return None
                # Refresh container before the final source/prefix proof.
                return fresh[0]

            batches.append((ids, resources, append_saved))

        else:
            # Cloud favorites do not provide an enumerable saved-playlist
            # expansion. Retain the established exact native object + receipt
            # contract, with complete prior-prefix and appended-row evidence.
            candidate = plan.candidates[0]
            if capacity < 1:
                reason = "manual_queue_capacity"
                return failure()
            batches.append((None, None, lambda: _resolve_live_container(device, candidate)))

        favorite = plan.kind == "favorite"
        cloud = favorite and plan.candidates[0].source == "favorite"
        selected_ids = tuple(identity for ids, _, _ in batches for identity in (ids or ()))
        for ids, resources, operation in batches:
            size = len(rows)
            new_size = size + len(ids) if ids is not None else None
            reason = "manual_append_unverified"

            def append_one():
                nonlocal attempted
                container = operation() if resources is not None or cloud else None
                if (resources is not None or cloud) and container is None:
                    return None
                if container is not None:
                    refs = getattr(container, "resources", None) or ()
                    if not refs or refs[0].uri != candidate.uri:
                        return None
                    metadata = to_didl_string(container)
                if (
                    not current() or _rows(device, evidence) != rows
                    or not same_manual_source(evidence, sonos._prepare_evidence_sync())
                    or not current()
                ):
                    return None
                attempted = True
                if resources is None and not cloud:
                    return operation()
                response = device.avTransport.AddURIToQueue([
                    ("InstanceID", 0), ("EnqueuedURI", candidate.uri),
                    ("EnqueuedURIMetaData", metadata),
                    ("DesiredFirstTrackNumberEnqueued", 0), ("EnqueueAsNext", 0),
                ], timeout=5.0)
                count = int(response["NumTracksAdded"])
                length = int(response["NewQueueLength"])
                position = int(response["FirstTrackNumberEnqueued"])
                if cloud:
                    if not 1 <= count <= capacity or length != size + count:
                        return None
                    return position, count
                if count != len(ids) or length != new_size:
                    return None
                return position

            position = await sonos._safe_mutation_call(append_one)
            if cloud:
                if not isinstance(position, tuple) or len(position) != 2:
                    return failure()
                position, count = position
                new_size = size + count
            if type(position) is not int or position != size + 1 or not current():
                return failure()
            first = await sonos._safe_call(sonos._queue_item_snapshot_sync, 0, 1.0)
            if (
                not first or first[1] != new_size or not first[0]
                or first[0] == evidence["queue_update_id"]
            ):
                return failure()
            first_hash = hashlib.sha256(first[2].encode()).hexdigest()
            if size and first_hash != evidence["queue_first_item_hash"]:
                return failure()
            updated = await sonos._safe_call(_read_prefix_sync, device, new_size, first[0])
            if updated is None or updated[:size] != rows:
                return failure()
            if favorite:
                actual_resources = tuple(_resources(row) for row in updated[size:])
                if (
                    not actual_resources or any(row is None for row in actual_resources)
                    or (resources is not None and actual_resources != resources)
                ):
                    return failure()
            else:
                actual_resources = _song_resources(updated[size:])
                if (
                    actual_resources is None or len(actual_resources) != len(ids)
                    or any(any(apple_song_id(uri) != identity for uri in row)
                           for identity, row in zip(ids, actual_resources))
                    or (resources is not None and actual_resources != resources)
                ):
                    return failure()
            fresh = await sonos.get_prepare_evidence()
            expected = dict(evidence, queue_update_id=first[0], queue_size=new_size,
                            queue_first_item_hash=first_hash)
            if not same_manual_source(expected, fresh):
                # Empty stopped source can expose its first newly enqueued
                # song automatically. Do not adopt an arbitrary loaded source.
                if not (
                    size == 0 and not any(play_source_fingerprint(evidence) or ())
                    and ordinary_source(sonos, fresh)
                    and ((
                        fresh["current_uri"] == f"x-rincon-queue:{uid}#0"
                        and fresh["queue_track"] == 1
                        and fresh["queue_track_uri"] in actual_resources[0]
                    ) if favorite else selected_apple_source(play_source_fingerprint(fresh), uid, ids[0]))
                    and all(fresh.get(k) == expected.get(k) for k in (
                        "queue_uid", "queue_update_id", "queue_size", "queue_first_item_hash",
                        "coordinator", "mute", "volume", "play_mode", "transport_state",
                    ))
                ):
                    return failure()
            if not current():
                return failure()
            rows, evidence = updated, fresh
            appended += 1 if cloud else len(ids)

        # Stop the old source before raising a zero volume. Never make an old
        # muted-at-zero track suddenly audible as a side effect of selecting new.
        reason = "manual_stop_unverified"
        if evidence["transport_state"] not in _IDLE:
            def stop_old():
                nonlocal attempted
                if (
                    not current() or _rows(device, evidence) != rows
                    or not same_manual_source(evidence, sonos._prepare_evidence_sync())
                    or not current()
                ):
                    return False
                attempted = True
                device.avTransport.Stop([("InstanceID", 0)], timeout=3.0)
                return True
            if not await sonos._safe_mutation_call(stop_old):
                return failure()
            fresh = await sonos.get_prepare_evidence()
            if not same_manual_source(dict(evidence, transport_state="STOPPED"), fresh) or not current():
                return failure()
            evidence = fresh

        # A manual new ordered selection needs NORMAL, even if the prior queue
        # was shuffled. Any observed reordering aborts instead of clearing.
        reason = "manual_play_mode_unverified"
        if evidence["play_mode"] != "NORMAL":
            def normal_mode():
                nonlocal attempted
                if (
                    not current() or _rows(device, evidence) != rows
                    or not same_manual_source(evidence, sonos._prepare_evidence_sync())
                    or not current()
                ):
                    return False
                attempted = True
                device.avTransport.SetPlayMode([("InstanceID", 0), ("NewPlayMode", "NORMAL")], timeout=3.0)
                return True
            if not await sonos._safe_mutation_call(normal_mode):
                return failure()
            fresh = await sonos.get_prepare_evidence()
            if (
                not same_manual_source(dict(evidence, play_mode="NORMAL"), fresh)
                or await sonos._safe_call(_rows, device, fresh) != rows or not current()
            ):
                return failure()
            evidence = fresh

        reason = "manual_volume_unavailable"
        volume = selected_play_volume(evidence["volume"], ceiling())
        if volume is None or not current():
            return failure()
        if volume != evidence["volume"]:
            receipt = await sonos.set_selected_play_volume(
                device, evidence, volume,
                lambda: current() and ceiling() is not None and volume <= ceiling(),
            )
            if receipt.get("status") != "ready":
                reason = receipt.get("reason", "manual_volume_unavailable")
                return failure()
            fresh = await sonos.get_prepare_evidence()
            if not same_manual_source(dict(evidence, volume=volume), fresh) or not current():
                reason = "volume_unverified"
                return failure()
            evidence = fresh

        def final_current():
            limit = ceiling()
            return current() and type(limit) is int and 0 < volume <= limit

        reason = "manual_queue_changed_before_play"
        target = await sonos._safe_call(sonos._queue_item_snapshot_sync, offset, 1.0)
        first = await sonos._safe_call(sonos._queue_item_snapshot_sync, 0, 1.0)
        target_resources = _resources(rows[offset])
        if (
            not target_resources
            or not target or len(target) != 3 or target[1] != len(rows)
            or (not favorite and not _item_matches(target, selected_ids[0], len(rows)))
            or target[0] != evidence["queue_update_id"]
            or not first or first[0] != target[0] or first[1] != target[1]
            or await sonos._safe_call(_rows, device, evidence) != rows
            or not same_manual_source(evidence, await sonos.get_prepare_evidence())
            or not final_current()
        ):
            return failure()
        reason = "manual_play_unverified"
        attempted = True
        if not sonos._play_queue_item_if_unchanged_sync(
            offset, len(rows), target, queue_uid=uid, max_volume=volume,
            expected_source=play_source_fingerprint(evidence), still_current=final_current,
            expected_resources=target_resources,
        ):
            return failure()
        if not await sonos._verify_queue_playback_started(
            offset, len(rows), target, queue_uid=uid, max_volume=volume,
            still_current=final_current, expected_resources=target_resources,
        ) or not final_current():
            reason = "playback_start_unverified"
            return failure()
        fresh = await sonos.get_prepare_evidence()
        if (
            not isinstance(fresh, dict) or fresh.get("queue_uid") != uid
            or fresh.get("queue_update_id") != target[0] or fresh.get("queue_size") != len(rows)
            or fresh.get("current_uri") != f"x-rincon-queue:{uid}#0"
            or fresh.get("queue_track") != offset + 1 or fresh.get("queue_track_uri") not in target_resources
            or fresh.get("transport_state") != "PLAYING" or fresh.get("coordinator") is not True
            or fresh.get("mute") is not False or fresh.get("volume") != volume
            or fresh.get("play_mode") != "NORMAL"
            or await sonos._safe_call(_rows, device, fresh) != rows or not final_current()
        ):
            reason = "playback_start_unverified"
            return failure()
        return (
            MixStartResult("started", "advancing_playback_verified", appended,
                           appended - len(plan.candidates) if plan.kind == "artist_mix" else 0),
            ManualStartProof(first, uid, volume, device, rows, offset),
        )
    except Exception:
        return failure()
