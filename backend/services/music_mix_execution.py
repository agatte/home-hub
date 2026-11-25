"""Internal guarded Sonos mix start; no route or session authority of its own."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from backend.services.music_continuation import MAX_CONTINUATION_TRACKS
from backend.services.music_queue_identity import apple_song_id
from backend.services.music_selected_plan import MAX_SELECTED_TRACKS, SelectedListeningPlan


@dataclass(frozen=True)
class MixStartResult:
    status: str
    reason: str
    confirmed_appends: int = 0
    continuation_tracks: int = 0
    sustained_listening: bool = False


def _item_matches(snapshot: tuple | None, identity: str, size: int) -> bool:
    if not snapshot or len(snapshot) != 3:
        return False
    update_id, total, xml = snapshot
    if not update_id or total != size or not isinstance(xml, str) or len(xml) > 65536:
        return False
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return False
    items = [item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == "item"]
    if len(items) != 1:
        return False
    resources = [
        (child.text or "").strip() for child in items[0]
        if child.tag.rsplit("}", 1)[-1] == "res"
    ]
    # Match an exact Apple song resource, not the displayed title or a
    # substring in arbitrary DIDL metadata. Other resource forms abstain.
    return bool(resources) and all(
        apple_song_id(uri) == identity for uri in resources
    )


async def start_selected_mix(
    sonos: Any, plan: SelectedListeningPlan, *,
    mutation_runner, preflight, still_current, continuation=(), on_started=None,
) -> MixStartResult:
    """Append a bounded exact mix to a proven empty queue and start item zero.

    Internal only. The caller MUST revalidate the plan and supply a shared Q/T
    ownership runner, fresh runtime admission (including volume and lifecycle),
    and synchronous intent/epoch guard. No title fallback, queue clearing,
    replay, volume writes or post-start automatic commands. An optional
    separately verified continuation tail is queued after the exact selection. Any possibly accepted
    append is retained on failure; never guess that the queue is unchanged.
    """
    selected = plan.candidates
    members = selected + tuple(continuation)
    if (
        plan.status != "verified_preview" or plan.kind != "artist_mix"
        or plan.actuation_allowed is not False
        or not 2 <= len(selected) <= MAX_SELECTED_TRACKS
        or len(continuation) > MAX_CONTINUATION_TRACKS
    ):
        return MixStartResult("suppressed", "invalid_mix")
    ids = [item.provider_id for item in members]
    if (
        len(set(ids)) != len(ids)
        or plan.choice_id != "artist_mix:" + ",".join(ids[:len(selected)])
    ):
        return MixStartResult("suppressed", "invalid_mix_identity")
    try:
        for member in members:
            if (
                member.provider != "itunes_search"
                or not member.provider_id.isascii() or not member.provider_id.isdigit()
                or member.media_type != "track" or member.verified is not True
                or member.catalog_verified is not True or not member.playback_capable
                or member.playback_adapter != "sonos_apple_music_share_link"
                or member.playback_reference != member.uri
                or member.metadata.get("playback_verification") != "live_verified"
                or sonos._canonical_apple_music_share_link(member.uri) != f"song:{member.provider_id}"
            ):
                return MixStartResult("suppressed", "invalid_member")
    except Exception:
        return MixStartResult("suppressed", "invalid_member")

    appended = 0
    mutation_attempted = False
    failure = "authority_unavailable"

    async def snapshots(size):
        rows = []
        for index in range(size):
            row = await sonos._safe_call(sonos._queue_item_snapshot_sync, index, 1.0)
            if not _item_matches(row, ids[index], size):
                return None
            rows.append(row)
        if len({row[0] for row in rows}) != 1:
            return None
        return rows

    async def setup():
        nonlocal appended, mutation_attempted, failure
        failure = "initial_admission_failed"
        initial = await preflight(expected_queue_size=0)
        if initial.get("reason") is not None or not still_current():
            return None
        evidence = await sonos.get_prepare_evidence()
        if not sonos.prepare_unloaded(evidence) or not still_current():
            return None
        volume = initial.get("volume_used")
        if type(volume) is not int or volume <= 0 or evidence.get("volume") != volume:
            return None
        uid = evidence.get("queue_uid")
        if not uid or str(await sonos._safe_call(lambda: sonos.device.uid)) != uid:
            return None
        device = sonos.device
        if device is None or str(device.uid) != uid:
            return None
        previous = []
        for index, member in enumerate(members):
            failure = "authority_or_queue_changed_before_append"
            fresh = await preflight(
                expected_queue_size=index,
                allowed_loaded_provider_id=ids[0] if index else None,
            )
            if fresh.get("reason") is not None or fresh.get("volume_used") != volume:
                return None
            if index:
                if await snapshots(index) != previous:
                    return None
            else:
                if await sonos.get_prepare_evidence() != evidence:
                    return None
            if not still_current() or sonos.device is not device:
                return None

            def guarded_append():
                if not still_current() or sonos.device is not device:
                    return None
                # Repeat the last proof in the settled worker, immediately
                # before append; a same-size external replacement must not
                # be mistaken for our previously confirmed queue.
                if index:
                    if sonos._queue_item_snapshot_sync(0, 1.0) != previous[0]:
                        return None
                elif sonos._prepare_evidence_sync() != evidence:
                    return None
                if not still_current() or sonos.device is not device:
                    return None
                return sonos._add_apple_music_share_link_sync(member.uri)

            mutation_attempted = True
            position = await sonos._safe_mutation_call(guarded_append)
            failure = "append_unverified"
            if type(position) is not int or position != index + 1:
                return None
            current = await snapshots(index + 1)
            if current is None:
                return None
            if [row[2] for row in current[:-1]] != [row[2] for row in previous]:
                return None
            previous = current
            appended = index + 1

        failure = "authority_or_queue_changed_before_play"
        final = await preflight(
            expected_queue_size=len(members), allowed_loaded_provider_id=ids[0],
        )
        if final.get("reason") is not None or final.get("volume_used") != volume:
            return None
        if str(await sonos._safe_call(lambda: sonos.device.uid)) != uid:
            return None
        if (await snapshots(len(members)) != previous or not still_current()
                or sonos.device is not device):
            return None
        # Same synchronous bounded final proof as assisted playback. No await
        # between the intent guard and the exact queue/source/transport check.
        failure = "play_command_unverified"
        if not sonos._play_queue_item_if_unchanged_sync(
            0, len(members), previous[0], queue_uid=uid, max_volume=volume,
        ):
            return None
        return previous[0], uid, volume, device, previous

    try:
        proof = await mutation_runner(setup)
        if proof is None:
            return MixStartResult(
                "indeterminate" if mutation_attempted else "suppressed", failure, appended,
            )
        snapshot, uid, volume, device, rows = proof
        verified = await sonos._verify_queue_playback_started(
            0, len(members), snapshot, queue_uid=uid, max_volume=volume,
        )
        if not still_current() or sonos.device is not device:
            return MixStartResult("indeterminate", "authority_changed_at_verification", appended)
        if not verified:
            return MixStartResult("indeterminate", "playback_start_unverified", appended)
        if on_started is not None:
            try:
                prefix = tuple(ET.tostring(ET.fromstring(row[2])[0], encoding="unicode") for row in rows)
                on_started(snapshot, uid, volume, device, prefix)
            except Exception:
                pass  # Optional renewal must not change a confirmed start receipt.
        return MixStartResult("started", "advancing_playback_verified", appended, len(continuation))
    except Exception:
        return MixStartResult(
            "indeterminate" if mutation_attempted else "suppressed", failure, appended,
        )
