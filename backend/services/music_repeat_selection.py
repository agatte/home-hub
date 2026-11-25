"""Repeat a deliberate mix selection without clearing an existing known queue.

Retained provenance is identity evidence, never permission. Only a fresh
owner-selected start under the shared writer lock may append and start.
"""
from __future__ import annotations

import hashlib
from urllib.parse import unquote

from backend.services.music_continuation import QueuedSong
from backend.services.music_mix_execution import MixStartResult, _item_matches
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
    return (
        isinstance(uri, str)
        and unquote(uri).split("?", 1)[0].casefold()
        == f"x-sonos-http:song:{proof.songs[track - 1].provider_id}"
    )


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
        for item in members:
            size = len(rows)

            def append_one():
                nonlocal attempted
                if not still_current() or sonos.device is not device:
                    return None
                if _read_prefix_sync(device, size, proof.revision) != rows:
                    return None
                if (
                    sonos._prepare_evidence_sync() != evidence
                    or sonos.device is not device or not still_current()
                ):
                    return None
                attempted = True
                return sonos._add_apple_music_share_link_sync(item.uri)

            reason = "repeat_append_unverified"
            position = await sonos._safe_mutation_call(append_one)
            if type(position) is not int or position != size + 1 or not still_current():
                return None
            first = await sonos._safe_call(sonos._queue_item_snapshot_sync, 0, 1.0)
            last = await sonos._safe_call(sonos._queue_item_snapshot_sync, size, 1.0)
            if (
                not first or len(first) != 3 or first[1] != size + 1
                or not first[0] or first[0] == proof.revision
                or hashlib.sha256(first[2].encode()).hexdigest() != proof.first_hash
                or not _item_matches(last, item.provider_id, size + 1)
                or last[0] != first[0]
            ):
                return None
            updated = await sonos._safe_call(_read_prefix_sync, device, size + 1, first[0])
            if updated is None or updated[:-1] != rows:
                return None
            next_proof = started_queue_proof(first, uid, volume, updated)
            song = QueuedSong(item.provider_id, item.title, item.metadata["artist_name"])
            if next_proof is None or next_proof.songs != proof.songs + (song,):
                return None
            fresh = await sonos.get_prepare_evidence()
            expected = {**evidence, "queue_update_id": first[0], "queue_size": size + 1}
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
