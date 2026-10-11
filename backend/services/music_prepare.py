"""Explicit, ephemeral preparation authority. Never stages or starts playback."""
import secrets
import time

from backend.services.audio_ownership import QUEUE_SOURCE, TRANSPORT, INTERRUPTION


class MusicPrepareService:
    TTL = 45

    def __init__(self, state):
        self.state = state
        self.previews = {}

    def mode(self):
        return str(getattr(getattr(self.state, 'automation', None),
                           'current_mode', '') or '').strip().casefold()

    def block_revision(self):
        return getattr(getattr(self.state, "music_mapper", None), "_manual_music_block_revision", None)

    def allowed(self, mode):
        try:
            return self.policy_reason() is None
        except Exception:
            return False

    def policy_reason(self):
        try:
            return self.state.music_assisted_playback._policy_reason()
        except Exception:
            return 'authority_unavailable'

    async def preview(self):
        now = time.monotonic()
        self.previews = {k: v for k, v in self.previews.items() if v['expires'] > now}
        mode = self.mode()
        reason = self.policy_reason()
        if reason:
            return {'status': 'refused', 'reason': reason}
        authority = getattr(self.state, 'audio_ownership', None)
        if authority is None:
            return {'status': 'refused', 'reason': 'audio_ownership_unavailable'}
        epoch = await authority.capture_opportunistic((QUEUE_SOURCE, TRANSPORT, INTERRUPTION))
        if epoch is None:
            return {'status': 'refused', 'reason': 'audio_ownership_busy'}
        manual = authority.capture_manual_intent()
        block_revision = self.block_revision()
        evidence = await self.state.sonos.get_prepare_evidence()
        reason = self.policy_reason()
        if reason:
            return {'status': 'refused', 'reason': reason}
        if (not authority.opportunistic_is_current(epoch)
                or self.block_revision() != block_revision
                or authority.capture_manual_intent() != manual):
            return {'status': 'refused', 'reason': 'authority_changed'}
        if self.state.sonos.prepare_unloaded(evidence):
            return {'status': 'ready', 'reason': 'already_unloaded_play_requires_separate_action'}
        if not self.state.sonos.prepare_eligible(evidence):
            return {'status': 'refused', 'reason': 'source_not_eligible'}
        token = secrets.token_urlsafe(32)
        # Bound memory as well as lifetime; old previews lose authority.
        if len(self.previews) >= 64:
            self.previews.pop(next(iter(self.previews)))
        self.previews[token] = dict(evidence=evidence, mode=mode, epoch=epoch,
                                    manual=manual, authority=authority, block_revision=block_revision,
                                    expires=time.monotonic() + self.TTL)
        return {'status': 'preview', 'token': token, 'expires_in': self.TTL,
                'track': evidence['title'], 'warning': 'The current track will be discarded.'}

    async def confirm(self, token):
        # Consume before the first await, including failures and cancellation.
        preview = self.previews.pop(token, None) if isinstance(token, str) else None
        if not preview or preview['expires'] <= time.monotonic():
            return {'status': 'refused', 'reason': 'preview_expired_or_used'}
        reason = self.policy_reason()
        if reason:
            return {'status': 'refused', 'reason': reason}
        authority = getattr(self.state, 'audio_ownership', None)
        if authority is not preview['authority']:
            return {'status': 'refused', 'reason': 'authority_changed'}

        def current():
            return (time.monotonic() < preview['expires']
                    and self.allowed(preview['mode'])
                    and self.state.audio_ownership is authority
                    and self.block_revision() == preview['block_revision']
                    and authority.capture_manual_intent() == preview['manual']
                    and authority.opportunistic_is_current(preview['epoch']))

        async def operation():
            if not current():
                return {'status': 'refused', 'reason': 'authority_changed'}
            return await self.state.sonos.prepare_if_unchanged(preview['evidence'], current)

        executed, result = await authority.run_if_opportunistic(preview['epoch'], operation)
        return result if executed else {'status': 'refused', 'reason': 'audio_ownership_busy_or_changed'}
