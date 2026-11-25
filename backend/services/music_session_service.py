"""Process-local, single-use custody for explicit listening selection.

No route is registered here. Only an authenticated owner-facing adapter may
issue or redeem tickets, using a server-derived owner scope, never a client
supplied owner identity. A restart discards all tickets and never replays I/O.
"""
from __future__ import annotations

import secrets
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Callable

from backend.services.audio_ownership import INTERRUPTION, QUEUE_SOURCE, TRANSPORT
from backend.services.music_favorite_execution import start_selected_favorite
from backend.services.music_listening_choices import build_listening_choices
from backend.services.music_manual_policy import manual_volume_policy
from backend.services.music_mix_execution import MixStartResult, start_selected_mix
from backend.services.music_requests import MusicRequestResolver, MusicRequestResult
from backend.services.music_selected_plan import SelectedListeningPlanner
from backend.services.music_sustained_listening import SustainedListening, started_queue_proof

TICKET_TTL = 120
MAX_TICKETS = 32


@dataclass(frozen=True)
class _Ticket:
    owner_scope: str
    request: MusicRequestResult
    choices: frozenset[str]
    limit: int
    expires: float
    runtime_mode: str


def _refused(reason: str) -> MixStartResult:
    return MixStartResult("suppressed", reason)


class ListeningSessionService:
    """Explicit selected-session start, with no continuing playback lease."""

    def __init__(self, state: Any, planner: SelectedListeningPlanner, *, continuation_planner=None, clock=time.monotonic):
        self._state = state
        self._planner = planner
        self._continuation_planner = continuation_planner
        self._sustained = SustainedListening(continuation_planner, clock=clock) if continuation_planner is not None else None
        self._clock = clock
        self._tickets: dict[str, _Ticket] = {}

    async def run_loop(self):
        if self._sustained is not None:
            await self._sustained.run_loop()

    def issue(self, request: MusicRequestResult, *, owner_scope: str, limit: int = 6) -> dict:
        if not isinstance(owner_scope, str) or not owner_scope or len(owner_scope) > 128:
            raise ValueError("server-derived owner scope required")
        if not isinstance(request, MusicRequestResult):
            raise TypeError("server-generated preview required")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("invalid choice limit")
        if (
            request.status != "shadow_ready" or request.shadow is not True
            or request.actuation_allowed is not False
            or (request.discovery is not None and (
                request.discovery.shadow is not True
                or request.discovery.actuation_allowed is not False
            ))
        ):
            return {"status": "unavailable"}
        projected = build_listening_choices(request.to_dict(), limit=limit)["choices"]
        choices = frozenset(row["id"] for row in projected if row["kind"] in {"artist_mix", "favorite"})
        if not choices:
            return {"status": "unavailable"}
        runtime_mode = str(getattr(getattr(self._state, "automation", None),
                                   "current_mode", "") or "").strip().casefold()
        if not runtime_mode or MusicRequestResolver._mode(runtime_mode) != request.resolved_request.mode:
            return {"status": "unavailable"}
        now = self._clock()
        self._tickets = {key: value for key, value in self._tickets.items() if value.expires > now}
        if len(self._tickets) >= MAX_TICKETS:
            self._tickets.pop(next(iter(self._tickets)))
        token = secrets.token_urlsafe(32)
        self._tickets[token] = _Ticket(owner_scope, deepcopy(request), choices, limit, now + TICKET_TTL, runtime_mode)
        return {"status": "selection_available", "token": token, "expires_in": TICKET_TTL,
                "choice_ids": sorted(choices), "actuation_allowed": False}

    async def start(
        self, token: str, choice_id: str, *, owner_scope: str,
        authorized: Callable[[], bool],
    ) -> MixStartResult:
        if not isinstance(token, str) or not isinstance(choice_id, str):
            return _refused("invalid_selection")
        ticket = self._tickets.get(token)
        if ticket is None or ticket.owner_scope != owner_scope or not authorized():
            return _refused("selection_unavailable")
        # Consume synchronously before any await. A cancelled or uncertain start
        # never regains authority, even if no hardware change was observed.
        self._tickets.pop(token)
        if self._clock() >= ticket.expires:
            return _refused("selection_expired")
        if choice_id not in ticket.choices:
            return _refused("choice_not_visible")
        state = self._state
        authority = getattr(state, "audio_ownership", None)
        mapper = getattr(state, "music_mapper", None)
        assisted = getattr(state, "music_assisted_playback", None)
        sonos = getattr(state, "sonos", None)
        automation = getattr(state, "automation", None)
        if any(value is None for value in (authority, mapper, assisted, sonos, automation)):
            return _refused("authority_unavailable")

        def mode():
            return str(automation.current_mode or "").strip().casefold()

        try:
            initial_mode = mode()
            if initial_mode != ticket.runtime_mode:
                return _refused("selection_mode_changed")
            manual_revision = authority.capture_manual_intent()
            block_revision = mapper._manual_music_block_revision
            if assisted._policy_reason() is not None:
                return _refused("runtime_policy_refused")
            # Shared admission: claims cannot displace existing durable owners.
            epoch = await authority.capture_opportunistic(
                (QUEUE_SOURCE, TRANSPORT, INTERRUPTION), claim=True,
            )
        except Exception:
            return _refused("authority_unavailable")
        if epoch is None:
            return _refused("audio_ownership_busy")

        volume = None

        def session_allowed():
            try:
                policy = manual_volume_policy(automation)
                return (
                    authorized()
                    and state.audio_ownership is authority and state.music_mapper is mapper
                    and state.music_assisted_playback is assisted and state.sonos is sonos
                    and state.automation is automation and mode() == initial_mode
                    and mapper._manual_music_block_revision == block_revision
                    and authority.capture_manual_intent() == manual_revision
                    and assisted._policy_reason() is None
                    and policy["reason"] is None
                    and (volume is None or 0 < volume <= policy["volume_ceiling"])
                )
            except Exception:
                return False

        def current():
            return (
                self._clock() < ticket.expires
                and authority.opportunistic_is_current(epoch)
                and session_allowed()
            )

        async def preflight(**kwargs):
            if not current():
                return {"reason": "authority_changed"}
            evidence = await assisted._runtime_preflight(**kwargs)
            if not current():
                return {"reason": "authority_changed"}
            return evidence

        try:
            if not current():
                return _refused("authority_changed")
            selected = await self._planner.preview(ticket.request, choice_id, limit=ticket.limit)
            if selected.status != "verified_preview" or selected.kind not in {"artist_mix", "favorite"}:
                return _refused(selected.reason)
            initial = await preflight(expected_queue_size=0)
            if initial.get("reason") is not None:
                return _refused(initial["reason"])
            volume = initial.get("volume_used")
            if type(volume) is not int or not current():
                return _refused("volume_or_authority_unavailable")
        except Exception:
            return _refused("selection_revalidation_failed")

        tail = ()
        if selected.kind == "artist_mix" and self._continuation_planner is not None:
            tail = await self._continuation_planner.preview(
                selected, mode=ticket.request.resolved_request.mode,
            )
            if not current():
                return _refused("authority_changed")

        async def mutation_runner(operation):
            async def admitted():
                # Refresh provider and current veto evidence again while the
                # shared transaction is held, before the first possible write.
                if not current():
                    return None
                fresh = await self._planner.preview(ticket.request, choice_id, limit=ticket.limit)
                if fresh != selected or not current():
                    return None
                if tail and not await self._continuation_planner.revalidate(
                    tail, mode=ticket.request.resolved_request.mode,
                ):
                    return None
                if not current():
                    return None
                return await operation()

            executed, proof = await authority.run_if_opportunistic(epoch, admitted)
            return proof if executed else None

        started = []

        def on_started(snapshot, uid, volume, device, rows):
            proof = started_queue_proof(snapshot, uid, volume, rows)
            if proof is not None:
                started.append((proof, device, rows))

        # Never retry the executor. It distinguishes suppressed from possibly
        # accepted I/O. If an unexpected error escapes, report uncertainty.
        try:
            executor = start_selected_favorite if selected.kind == "favorite" else start_selected_mix
            extra = {"continuation": tail} if tail else {}
            if selected.kind == "favorite" and self._continuation_planner is not None:
                extra = {"continuation_planner": self._continuation_planner,
                         "mode": ticket.request.resolved_request.mode}
            if self._sustained is not None:
                extra["on_started"] = on_started
            result = await executor(
                sonos, selected, mutation_runner=mutation_runner,
                preflight=preflight, still_current=current, **extra,
            )
            if result.status == "started" and started and current():
                try:
                    append_token = await authority.capture_listening_append(
                        epoch, manual_revision=manual_revision,
                    )
                    if append_token is not None and current() and state.bootstrap_ready is True:
                        proof, device, rows = started[0]
                        installed = self._sustained.install(
                            authority=authority, token=append_token, sonos=sonos, device=device,
                            proof=proof, rows=rows, mode=ticket.request.resolved_request.mode,
                            allowed=lambda: state.bootstrap_ready is True and session_allowed(),
                        )
                        if installed:
                            result = replace(result, sustained_listening=True)
                except Exception:
                    pass  # Confirmed start stays truthful if renewal is unavailable.
            return result
        except Exception:
            return MixStartResult("indeterminate", "execution_outcome_unknown")
