import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.audio_ownership import AudioOwnershipService, INTERRUPTION
from backend.services.music_assisted_playback import MusicAssistedPlaybackService
from backend.services.music_prepare import MusicPrepareService
from backend.services.sonos_service import SonosService


class Device:
    """Only reads, Stop, and empty SetAVTransportURI exist: other writes fail tests."""
    uid = 'speaker'
    is_coordinator = True

    def __init__(self):
        self.avTransport = self.contentDirectory = self
        self.state = 'PAUSED_PLAYBACK'
        self.uri = 'x-sonos-http:exact-source'
        self.media_uri = self.uri
        self.position = '0:00:00'
        self.metadata = '<root xmlns:dc="urn:dc"><dc:title>The Poplar Tree</dc:title></root>'
        self.size = 0
        self.update = '1'
        self.mode = 'NORMAL'
        self.mute = False
        self.volume = 22
        self.writes = []
        self.after_stop = lambda: None
        self.unsupported = False
        self.no_unload = False

    def GetTransportSettings(self, args):
        return {'PlayMode': self.mode}

    def GetTransportInfo(self, args):
        return {'CurrentTransportState': self.state}

    def GetMediaInfo(self, args):
        return {'CurrentURI': self.media_uri, 'CurrentURIMetaData': self.metadata}

    def GetPositionInfo(self, args):
        return {'Track': '1', 'TrackURI': self.uri, 'RelTime': self.position,
                'TrackDuration': '0:03:00', 'TrackMetaData': self.metadata}

    def Browse(self, args):
        return {'TotalMatches': self.size, 'UpdateID': self.update, 'Result': ''}

    def Stop(self, args):
        self.writes.append('Stop')
        self.state = 'STOPPED'
        self.position = '0:00:00'
        self.after_stop()

    def SetAVTransportURI(self, args):
        assert dict(args) == {'InstanceID': 0, 'CurrentURI': '', 'CurrentURIMetaData': ''}
        self.writes.append('Unload')
        if self.unsupported:
            raise RuntimeError('unsupported')
        if not self.no_unload:
            self.media_uri = self.uri = self.metadata = ''


@pytest.fixture
def setup():
    async def load(_):
        return {}

    async def save(*args):
        pytest.fail('Preparation must not persist ownership or settings')

    device = Device()
    sonos = SonosService()
    sonos._device, sonos._connected = device, True
    state = SimpleNamespace(
        sonos=sonos, audio_ownership=AudioOwnershipService(setting_loader=load, setting_saver=save),
        automation=SimpleNamespace(current_mode='gaming', house_state='home', is_dnd_active=lambda: False),
        away_manager=SimpleNamespace(away=False), tts=SimpleNamespace(is_speaking=False),
        ambient_sound=SimpleNamespace(get_state=lambda: {}))
    # Use the real common policy with a disposable lifecycle fixture.
    policy = object.__new__(MusicAssistedPlaybackService)
    policy._app_state = state
    policy._lifecycle_state = lambda: {}
    state.music_assisted_playback = policy
    return MusicPrepareService(state), state, device


@pytest.mark.asyncio
async def test_preview_read_only_confirm_single_use(setup):
    service, state, device = setup
    preview = await service.preview()
    assert preview['track'] == 'The Poplar Tree'
    assert device.writes == []
    assert 'uri' not in repr(preview).lower()
    result, duplicate = await asyncio.gather(service.confirm(preview['token']), service.confirm(preview['token']))
    assert result['status'] == 'ready'
    assert duplicate['status'] == 'refused'
    assert device.writes == ['Stop', 'Unload']


@pytest.mark.asyncio
async def test_real_observed_radio_style_source_and_stop_position_reset(setup):
    # Read-only October 10 physical evidence: CurrentURI is x-sonosapi-radio,
    # TrackURI is x-sonosprog-http, queue=0, coordinator, paused, NORMAL.
    service, state, device = setup
    device.media_uri = 'x-sonosapi-radio:station-source'
    device.uri = 'x-sonosprog-http:song:1510825901.mp4?sid=204'
    device.position = '0:00:02'
    preview = await service.preview()
    assert preview['status'] == 'preview'
    assert preview['track'] == 'The Poplar Tree'
    assert device.writes == []
    result = await service.confirm(preview['token'])
    assert result['status'] == 'ready'
    assert device.writes == ['Stop', 'Unload']
    assert device.media_uri == ''
    assert device.uri == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('state', 'PLAYING'), ('state', 'UNKNOWN'), ('size', 1), ('size', None),
    ('mode', 'SHUFFLE'), ('is_coordinator', False), ('mute', True), ('volume', 0), ('uri', 'x-rincon-queue:speaker#0'),
    ('uri', 'x-sonos-htastream:tv'), ('uri', 'x-rincon-stream:line'), ('update', None)])
async def test_preview_refuses_unsafe_source(setup, field, value):
    service, state, device = setup
    setattr(device, field, value)
    assert (await service.preview())['status'] == 'refused'
    assert device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['mode', 'dnd', 'away', 'tts', 'ambient', 'source', 'manual', 'expired', 'restart', 'owner'])
async def test_confirm_stale_or_blocked_has_no_writes(setup, change):
    service, state, device = setup
    token = (await service.preview())['token']
    if change == 'mode': state.automation.current_mode = 'sleeping'
    if change == 'dnd': state.automation.is_dnd_active = lambda: True
    if change == 'away': state.away_manager.away = True
    if change == 'tts': state.tts.is_speaking = True
    if change == 'ambient': state.ambient_sound.get_state = lambda: {'playing': True}
    if change == 'source': device.uri += '-changed'
    if change == 'manual': state.audio_ownership.record_manual_intent(('transport',))
    if change == 'expired': service.previews[token]['expires'] = 0
    if change == 'restart': service = MusicPrepareService(state)
    if change == 'owner': state.audio_ownership._leases['test'] = {'dimensions': [INTERRUPTION]}
    assert (await service.confirm(token))['status'] != 'ready'
    assert device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['source', 'queue', 'manual', 'policy', 'volume'])
async def test_race_between_stop_and_unload(setup, change):
    service, state, device = setup
    token = (await service.preview())['token']
    def race():
        if change == 'source': device.uri += '-external'
        if change == 'queue': device.size = 1
        if change == 'manual': state.audio_ownership.record_manual_intent(('transport',))
        if change == 'policy': state.automation.current_mode = 'away'
        if change == 'volume': device.volume = 30
    device.after_stop = race
    assert (await service.confirm(token))['status'] == 'not_ready'
    assert device.writes == ['Stop']


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['unsupported', 'no_unload'])
async def test_stop_alone_never_ready(setup, failure):
    service, state, device = setup
    token = (await service.preview())['token']
    setattr(device, failure, True)
    assert (await service.confirm(token))['status'] == 'not_ready'
    assert (await service.confirm(token))['status'] == 'refused'
    assert device.writes == ['Stop', 'Unload']


def test_route_strict_auth_and_body(setup):
    from backend.api.routes.music import router
    service, state, device = setup
    app = FastAPI()
    app.include_router(router)
    for key, value in vars(state).items(): setattr(app.state, key, value)
    app.state.music_prepare = service
    with TestClient(app, client=('192.168.1.99', 1234)) as client:
        assert client.get('/api/music/prepare/preview').status_code in {401, 503}
        assert client.post('/api/music/prepare/confirm', json={'token': 'x'}).status_code in {401, 503}
    with TestClient(app) as client:
        assert client.post('/api/music/prepare/confirm', json={'token': 'x', 'uri': 'unsafe'}).status_code == 422
        assert client.get('/api/music/prepare/preview').json()['status'] == 'preview'
    assert device.writes == []


@pytest.mark.asyncio
async def test_manual_recheck_unloaded_is_read_only(setup):
    service, state, device = setup
    device.state = 'STOPPED'
    device.uri = device.media_uri = device.metadata = ''
    result = await service.preview()
    assert result['status'] == 'ready'
    assert 'token' not in result
    assert device.writes == []


@pytest.mark.asyncio
async def test_stopped_nonqueue_empty_queue_requires_confirm_without_stop(setup):
    service, state, device = setup
    state.automation.current_mode = 'idle'
    device.state = 'STOPPED'
    device.uri = ''  # STOPPED can lose track details while retaining CurrentURI.
    device.metadata = ''
    original_volume = device.volume
    preview = await service.preview()
    assert preview['status'] == 'preview'
    assert preview['source_kind'] == 'stopped'
    assert 'track' not in preview and 'uri' not in repr(preview).lower()
    assert device.writes == []
    assert (await service.confirm(preview['token'])) == {
        'status': 'ready', 'reason': 'unloaded_verified_play_requires_separate_action'}
    assert device.writes == ['Unload']  # no Stop, Play, queue or volume write
    assert device.state == 'STOPPED'
    assert device.size == 0 and device.volume == original_volume
    assert device.media_uri == '' and device.uri == ''
    assert (await service.confirm(preview['token']))['reason'] == 'preview_expired_or_used'


@pytest.mark.asyncio
@pytest.mark.parametrize('music_source', [
    'x-sonos-http:track', 'x-sonosapi-stream:station',
    'x-sonosapi-hls:station', 'x-sonosapi-radio:station',
])
async def test_stopped_allowlisted_source_types_preview_without_writes(setup, music_source):
    service, state, device = setup
    device.state = 'STOPPED'
    device.media_uri = music_source
    device.uri = device.metadata = ''
    result = await service.preview()
    assert result['status'] == 'preview'
    assert result['source_kind'] == 'stopped'
    assert 'track' not in result
    assert device.writes == []


def _http_music_didl(uri, *, media_class='object.item.audioItem.musicTrack',
                     protocol='http-get:*:audio/mpeg:*'):
    from xml.sax.saxutils import escape

    return ('<DIDL-Lite xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/">'
            '<item><upnp:class>' + escape(media_class) + '</upnp:class>'
            '<res protocolInfo="' + escape(protocol) + '">' + escape(uri) +
            '</res></item></DIDL-Lite>')


@pytest.mark.asyncio
async def test_stopped_http_matching_music_track_requires_explicit_confirm(setup):
    service, state, device = setup
    state.automation.current_mode = 'idle'
    device.state = 'STOPPED'
    source = 'http://music.example.test/audio/song.mp3?opaque=one&item=two'
    device.media_uri = device.uri = source
    device.metadata = _http_music_didl(source)
    preview = await service.preview()
    assert preview['status'] == 'preview'
    assert preview['source_kind'] == 'stopped'
    assert 'track' not in preview
    assert source not in repr(preview)
    assert device.writes == []
    result = await service.confirm(preview['token'])
    assert result == {'status': 'ready',
                      'reason': 'unloaded_verified_play_requires_separate_action'}
    assert device.writes == ['Unload']  # no Stop, Play, queue clear or volume change
    assert device.size == 0 and device.volume == 22
    assert (await service.confirm(preview['token']))['status'] == 'refused'


@pytest.mark.asyncio
@pytest.mark.parametrize('difference', [
    'track_uri', 'metadata_resource', 'metadata_missing', 'metadata_malformed',
    'metadata_video_class', 'metadata_broadcast_class', 'metadata_video_protocol',
    'metadata_unsupported_protocol', 'http_host_only', 'http_missing_host',
    'https_scheme', 'oversized_metadata',
])
async def test_stopped_http_unverified_music_never_previews_or_writes(setup, difference):
    service, state, device = setup
    device.state = 'STOPPED'
    source = 'http://music.example.test/audio/song.mp3'
    device.media_uri = device.uri = source
    device.metadata = _http_music_didl(source)
    if difference == 'track_uri':
        device.uri = 'http://music.example.test/audio/other.mp3'
    elif difference == 'metadata_resource':
        device.metadata = _http_music_didl('http://music.example.test/audio/other.mp3')
    elif difference == 'metadata_missing':
        device.metadata = ''
    elif difference == 'metadata_malformed':
        device.metadata = '<item><unclosed>'
    elif difference == 'metadata_video_class':
        device.metadata = _http_music_didl(source, media_class='object.item.videoItem')
    elif difference == 'metadata_broadcast_class':
        device.metadata = _http_music_didl(
            source, media_class='object.item.audioItem.audioBroadcast')
    elif difference == 'metadata_video_protocol':
        device.metadata = _http_music_didl(source, protocol='http-get:*:video/mp4:*')
    elif difference == 'metadata_unsupported_protocol':
        device.metadata = _http_music_didl(source, protocol='unknown:*:audio/mpeg:*')
    elif difference == 'http_host_only':
        device.media_uri = device.uri = 'http://music.example.test/'
        device.metadata = _http_music_didl(device.media_uri)
    elif difference == 'http_missing_host':
        device.media_uri = device.uri = 'http:/audio/song.mp3'
        device.metadata = _http_music_didl(device.media_uri)
    elif difference == 'https_scheme':
        device.media_uri = device.uri = 'https://music.example.test/audio/song.mp3'
        device.metadata = _http_music_didl(device.media_uri)
    elif difference == 'oversized_metadata':
        device.metadata = _http_music_didl(source) + ' ' * 65536
    preview = await service.preview()
    assert preview['status'] == 'refused'
    # Malformed XML fails the existing evidence reader before classification.
    expected = ('source_evidence_unavailable' if difference == 'metadata_malformed'
                else 'source_stopped_but_loaded')
    assert preview['reason'] == expected
    assert 'token' not in preview
    assert not service.previews and device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['metadata', 'current_uri', 'track_uri', 'queue_revision'])
async def test_stopped_http_source_changes_before_confirm_never_unload(setup, change):
    service, state, device = setup
    device.state = 'STOPPED'
    source = 'http://music.example.test/audio/song.mp3'
    device.media_uri = device.uri = source
    device.metadata = _http_music_didl(source)
    preview = await service.preview()
    assert preview['status'] == 'preview'
    if change == 'metadata':
        device.metadata = _http_music_didl(source, protocol='http-get:*:audio/aac:*')
    elif change == 'current_uri':
        device.media_uri = 'http://music.example.test/audio/other.mp3'
    elif change == 'track_uri':
        device.uri = 'http://music.example.test/audio/other.mp3'
    elif change == 'queue_revision':
        device.update = 'new-revision'
    assert (await service.confirm(preview['token']))['status'] != 'ready'
    assert device.writes == []


@pytest.mark.asyncio
async def test_stopped_preview_never_exposes_retained_title_or_source(setup):
    service, state, device = setup
    device.state = 'STOPPED'
    preview = await service.preview()
    assert preview['status'] == 'preview'
    assert preview['source_kind'] == 'stopped'
    assert 'track' not in preview
    assert 'The Poplar Tree' not in repr(preview)
    assert 'exact-source' not in repr(preview)
    assert device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('media_uri', ''), ('media_uri', 'x-sonos-http:'),
    ('media_uri', 'x-sonos-http:/'),
    ('media_uri', 'x-rincon-queue:speaker#0'),
    ('media_uri', 'x-rincon-stream:line-in'),
    ('media_uri', 'x-sonos-htastream:tv'),
    ('uri', 'x-rincon-queue:speaker#0'),
    ('size', 1), ('update', ''), ('uid', ''), ('mode', 'SHUFFLE'),
    ('mute', True), ('volume', 0), ('is_coordinator', False),
    ('state', 'PLAYING'),
])
async def test_stopped_unsafe_source_never_previews_or_writes(setup, field, value):
    service, state, device = setup
    device.state = 'STOPPED'
    setattr(device, field, value)
    result = await service.preview()
    assert result['status'] == 'refused'
    assert 'token' not in result and not service.previews
    assert device.writes == []


@pytest.mark.asyncio
async def test_stopped_stale_metadata_only_cannot_be_discarded(setup):
    service, state, device = setup
    device.state = 'STOPPED'
    device.media_uri = device.uri = ''
    result = await service.preview()
    assert result['reason'] == 'source_stopped_but_loaded'
    assert 'token' not in result and device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('change', [
    'source', 'queue', 'queue_revision', 'volume', 'manual', 'owner',
    'away', 'expired', 'restart',
])
async def test_stopped_confirmation_rereads_source_and_authority(setup, change):
    service, state, device = setup
    device.state = 'STOPPED'
    preview = await service.preview()
    token = preview['token']
    if change == 'source': device.media_uri = 'x-sonos-http:other-source'
    if change == 'queue': device.size = 1
    if change == 'queue_revision': device.update = '2'
    if change == 'volume': device.volume = 25
    if change == 'manual': state.audio_ownership.record_manual_intent(('transport',))
    if change == 'owner':
        state.audio_ownership._leases['other'] = {'dimensions': [INTERRUPTION]}
    if change == 'away': state.away_manager.away = True
    if change == 'expired': service.previews[token]['expires'] = 0
    if change == 'restart': service = MusicPrepareService(state)
    assert (await service.confirm(token))['status'] != 'ready'
    assert device.writes == []


@pytest.mark.asyncio
async def test_stopped_source_changes_during_confirm_final_read_no_write(setup):
    service, state, device = setup
    device.state = 'STOPPED'
    token = (await service.preview())['token']
    original = device.GetMediaInfo
    reads = {'count': 0}

    def changing_media(args):
        reads['count'] += 1
        if reads['count'] == 3:
            device.media_uri = 'x-sonos-http:externally-changed'
        return original(args)

    device.GetMediaInfo = changing_media
    assert (await service.confirm(token))['status'] == 'refused'
    assert device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['unsupported', 'no_unload'])
async def test_stopped_unload_failure_is_not_ready_and_not_retried(setup, failure):
    service, state, device = setup
    device.state = 'STOPPED'
    token = (await service.preview())['token']
    setattr(device, failure, True)
    assert (await service.confirm(token))['status'] == 'not_ready'
    assert device.writes == ['Unload']
    assert (await service.confirm(token))['reason'] == 'preview_expired_or_used'
    assert device.writes == ['Unload']


@pytest.mark.asyncio
async def test_preview_busy_owner_no_writes(setup):
    service, state, device = setup
    state.audio_ownership._leases['test'] = {'dimensions': [INTERRUPTION]}
    assert (await service.preview())['reason'] == 'audio_ownership_busy'
    assert device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('changes,reason', [
    (None, 'source_evidence_unavailable'),
    ({'transport_state': 'STOPPED', 'current_uri': 'x-rincon-queue:speaker#0',
      'queue_track_uri': '', 'title': '', 'metadata': '', 'media_metadata': ''},
     'source_stopped_but_loaded'),
    ({'transport_state': 'STOPPED', 'current_uri': '', 'queue_track_uri': '',
      'title': '', 'metadata': 'stale-private-metadata', 'media_metadata': ''},
     'source_stopped_but_loaded'),
    ({'queue_size': None}, 'source_queue_evidence_unavailable'),
    ({'queue_size': '0'}, 'source_queue_evidence_unavailable'),
    ({'queue_size': -1}, 'source_queue_evidence_unavailable'),
    ({'queue_update_id': None}, 'source_queue_evidence_unavailable'),
    ({'queue_size': 1}, 'source_queue_not_empty'),
    ({'transport_state': 'PLAYING'}, 'source_playing'),
    ({'title': ''}, 'source_missing_track_details'),
    ({'queue_track_uri': ''}, 'source_missing_track_details'),
    ({'current_uri': 'x-rincon-mp3radio:private-radio'}, 'source_unsupported_transport'),
    ({'queue_track_uri': 'x-rincon-queue:private-queue'}, 'source_unsupported_transport'),
    ({'queue_track_uri': 'x-rincon-stream:private-line'}, 'source_unsupported_transport'),
    ({'queue_track_uri': 'x-sonos-htastream:private-tv'}, 'source_unsupported_transport'),
    ({'coordinator': False}, 'source_not_coordinator'),
    ({'play_mode': 'SHUFFLE'}, 'source_play_mode_not_normal'),
    ({'mute': True}, 'source_muted'),
    ({'volume': 0}, 'source_volume_zero'),
    ({'transport_state': 'UNKNOWN'}, 'source_not_eligible'),
])
async def test_source_diagnostics_are_opaque_read_only_refusals(setup, changes, reason):
    service, state, device = setup
    evidence = state.sonos._prepare_evidence_sync()
    evidence = None if changes is None else dict(evidence, **changes)

    async def read_evidence():
        return evidence

    state.sonos.get_prepare_evidence = read_evidence
    before = dict(evidence) if evidence else evidence
    assert SonosService.prepare_ineligible_reason(evidence) == reason
    assert await service.preview() == {'status': 'refused', 'reason': reason}
    assert evidence == before
    assert not service.previews
    assert device.writes == []


@pytest.mark.asyncio
async def test_failed_evidence_is_never_already_unloaded(setup):
    service, state, device = setup
    device.update = None  # Existing reader collapses failed queue reads to None.
    assert await service.preview() == {
        'status': 'refused', 'reason': 'source_evidence_unavailable'}
    assert not service.previews and device.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize('lifecycle,reason', [
    ({'travel': True}, 'travel_mode_active'),
    ({'returning_home': True}, 'returning_home_active'),
])
async def test_lifecycle_refusal_precedes_source_diagnostics(setup, lifecycle, reason):
    service, state, device = setup
    state.music_assisted_playback._lifecycle_state = lambda: lifecycle

    async def unexpected_read():
        pytest.fail('Lifecycle must refuse before reading source evidence')

    state.sonos.get_prepare_evidence = unexpected_read
    assert await service.preview() == {'status': 'refused', 'reason': reason}
    assert not service.previews and device.writes == []


@pytest.mark.asyncio
async def test_idle_home_preview_confirm_keeps_activity_and_volume(setup):
    service, state, device = setup
    state.automation.current_mode = 'idle'
    preview = await service.preview()
    assert preview['status'] == 'preview'
    assert device.writes == []
    assert (await service.confirm(preview['token']))['status'] == 'ready'
    assert state.automation.current_mode == 'idle'
    assert device.volume == 22 and device.mute is False
    assert device.writes == ['Stop', 'Unload']


@pytest.mark.asyncio
@pytest.mark.parametrize('change,reason', [
    ('away', 'apartment_away'), ('house_away', 'apartment_away'),
    ('sleeping', 'sleeping_active'), ('dnd', 'dnd_active'),
    ('tts', 'tts_active'), ('ambient', 'ambient_playback_owned'),
    ('disconnected', 'sonos_unavailable'), ('unknown_house', 'house_authority_unavailable'),
    ('missing_house', 'authority_unavailable'), ('travel', 'travel_mode_active'),
    ('returning', 'returning_home_active'),
])
async def test_idle_preview_precise_refusal_without_token_or_writes(setup, change, reason):
    service, state, device = setup
    state.automation.current_mode = 'idle'
    if change == 'away': state.away_manager.away = True
    if change == 'house_away': state.automation.house_state = 'away'
    if change == 'sleeping': state.automation.current_mode = 'sleeping'
    if change == 'dnd': state.automation.is_dnd_active = lambda: True
    if change == 'tts': state.tts.is_speaking = True
    if change == 'ambient': state.ambient_sound.get_state = lambda: {'playing': True}
    if change == 'disconnected': state.sonos._connected = False
    if change == 'unknown_house': state.automation.house_state = 'unknown'
    if change == 'missing_house': del state.automation.house_state
    if change == 'travel': state.music_assisted_playback._lifecycle_state = lambda: {'travel': True}
    if change == 'returning': state.music_assisted_playback._lifecycle_state = lambda: {'returning_home': True}
    result = await service.preview()
    assert result == {'status': 'refused', 'reason': reason}
    assert not service.previews and device.writes == []


@pytest.mark.asyncio
async def test_prepare_authority_replacement_refuses_consumed_token(setup):
    service, state, device = setup
    token = (await service.preview())['token']
    state.audio_ownership = None
    assert (await service.confirm(token))['reason'] == 'authority_changed'
    assert (await service.confirm(token))['reason'] == 'preview_expired_or_used'
    assert device.writes == []


@pytest.mark.asyncio
async def test_prepare_blocking_transition_revision_never_revives_preview(setup):
    service, state, device = setup
    state.music_mapper = SimpleNamespace(_manual_music_block_revision=0)
    token = (await service.preview())['token']
    state.music_mapper._manual_music_block_revision = 1
    state.automation.current_mode = 'idle'
    assert (await service.confirm(token))['status'] == 'refused'
    assert device.writes == []


@pytest.mark.asyncio
async def test_activity_revision_to_idle_preserves_explicit_preview(setup):
    service, state, device = setup
    state.music_mapper = SimpleNamespace(_mode_request_revision=1)
    token = (await service.preview())['token']
    state.music_mapper._mode_request_revision = 2
    state.automation.current_mode = 'idle'
    assert (await service.confirm(token))['status'] == 'ready'
    assert device.writes == ['Stop', 'Unload']


@pytest.mark.asyncio
async def test_cancelled_confirm_keeps_authority_until_worker_settles(setup):
    service, state, device = setup
    token = (await service.preview())['token']
    started, release = threading.Event(), threading.Event()
    def block():
        started.set()
        assert release.wait(3)
    device.after_stop = block
    task = asyncio.create_task(service.confirm(token))
    for _ in range(100):
        if started.is_set(): break
        await asyncio.sleep(.005)
    assert started.is_set()
    task.cancel()
    waiter = asyncio.create_task(state.audio_ownership.capture_opportunistic(('transport',)))
    try:
        await asyncio.sleep(.02)
        assert not task.done()
        assert not waiter.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError): await task
    await waiter
    assert (await service.confirm(token))['status'] == 'refused'
