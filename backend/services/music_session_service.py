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

from backend.services.audio_ownership import AUDIO_DIMENSIONS, INTERRUPTION, QUEUE_SOURCE, TRANSPORT
from backend.services.music_listening_choices import build_listening_choices
from backend.services.music_manual_policy import manual_volume_policy, selected_play_reason
from backend.services.music_mix_execution import MixStartResult
from backend.services.music_requests import MusicRequestResult
from backend.services.music_selected_plan import SelectedListeningPlanner
from backend.services.music_sustained_listening import SustainedListening, started_queue_proof
from backend.services.music_selected_manual_execution import execute_selected_manual

TICKET_TTL = 120
MAX_START_VALIDATION_AGE = 3.0
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
    """Explicit manual selected-session start and bounded append-only continuation."""

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
            return {"status": "unavailable", "reason": "preview_unavailable"}
        projected = build_listening_choices(request.to_dict(), limit=limit)["choices"]
        choices = frozenset(row["id"] for row in projected if row["kind"] in {"artist_mix", "favorite"})
        if not choices:
            return {"status": "unavailable", "reason": "no_eligible_playback"}
        runtime_mode = str(getattr(getattr(self._state, "automation", None),
                                   "current_mode", "") or "").strip().casefold()
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
        assisted = getattr(state, "music_assisted_playback", None)
        sonos = getattr(state, "sonos", None)
        automation = getattr(state, "automation", None)
        if any(value is None for value in (authority, assisted, sonos, automation)):
            return _refused("authority_unavailable")
        try:
            lifecycle = assisted._lifecycle_state
            reason = selected_play_reason(state, lifecycle)
            if reason is not None:
                return _refused(reason)
            manual_revision = authority.record_manual_intent(AUDIO_DIMENSIONS)
            selected_revision = authority.capture_selected_manual_intent()

            def session_allowed():
                try:
                    return (
                        authorized()
                        and state.audio_ownership is authority and state.sonos is sonos
                        and state.music_assisted_playback is assisted and state.automation is automation
                        and authority.capture_selected_manual_intent() == selected_revision
                        and selected_play_reason(state, lifecycle) is None
                    )
                except Exception:
                    return False

            def admitted_intent():
                return self._clock() < ticket.expires and session_allowed()

            def ceiling():
                return manual_volume_policy(automation)["volume_ceiling"]

            selected = await self._planner.preview(ticket.request, choice_id, limit=ticket.limit)
            if selected.status != "verified_preview" or selected.kind not in {"artist_mix", "favorite"}:
                return _refused(selected.reason)
            if not admitted_intent():
                return _refused("authority_changed")
            # Optional recommendations are prepared outside the audio writer lock.
            # Stale optional suggestions must not veto the selected music.
            tail = ()
            if selected.kind == "artist_mix" and self._continuation_planner is not None:
                try:
                    tail = await self._continuation_planner.preview(
                        selected, mode=ticket.request.resolved_request.mode,
                    )
                except Exception:
                    tail = ()
            fresh = await self._planner.preview(ticket.request, choice_id, limit=ticket.limit)
            if fresh != selected or not admitted_intent():
                return _refused("selection_revalidation_failed")
            if tail:
                try:
                    if not await self._continuation_planner.revalidate(
                        tail, mode=ticket.request.resolved_request.mode,
                    ):
                        tail = ()
                except Exception:
                    tail = ()
            if not admitted_intent():
                return _refused("authority_changed")
            validated_at = self._clock()

            async def admitted():
                if not admitted_intent() or not 0 <= self._clock() - validated_at <= MAX_START_VALIDATION_AGE:
                    return _refused("authority_changed")
                epoch = authority.selected_manual_epoch()

                def current():
                    return admitted_intent() and authority.opportunistic_is_current(epoch)

                if self._sustained is not None:
                    self._sustained.stop()
                    self._sustained.forget_retained()
                result, observed = await execute_selected_manual(
                    sonos, selected, still_current=current, ceiling=ceiling, continuation=tail,
                )
                if result.status == "started" and observed is not None and current() and self._sustained is not None:
                    try:
                        proof = started_queue_proof(
                            observed.first, observed.uid, observed.volume, observed.rows, offset=observed.offset,
                        )
                        token = authority.capture_admitted_listening_append(
                            {key: epoch[key] for key in (QUEUE_SOURCE, TRANSPORT, INTERRUPTION)},
                            manual_revision=manual_revision,
                        )
                        if token is not None and current() and getattr(state, "bootstrap_ready", False) is True:
                            installed = self._sustained.install(
                                authority=authority, token=token, sonos=sonos, device=observed.device,
                                proof=proof, rows=observed.rows, mode=ticket.request.resolved_request.mode,
                                allowed=lambda: state.bootstrap_ready is True and session_allowed(),
                                owner_scope=owner_scope, initial_track=observed.offset + 1,
                            )
                            if installed:
                                result = replace(result, sustained_listening=True)
                    except Exception:
                        pass  # Optional append authority cannot change verified start.
                return result

            return await authority.run_manual(
                AUDIO_DIMENSIONS, source="owner_listening", reason="manual_selected_play",
                operation=admitted, intent_revision=manual_revision,
                superseded_result=_refused("authority_changed"),
                admission_guard=admitted_intent, protect_interruptions=True,
            )
        except Exception:
            return MixStartResult("indeterminate", "execution_outcome_unknown")
