from types import SimpleNamespace

import pytest

from backend.services.music_manual_policy import selected_play_volume
from backend.services.music_queue_identity import same_manual_source
from backend.services.sonos_service import SonosService


@pytest.mark.parametrize(('volume', 'target'), [(0, 18), (10, 10), (50, 18)])
def test_selected_volume_policy(volume, target):
    assert selected_play_volume(volume, 18) == target


@pytest.mark.asyncio
async def test_volume_write_checks_source_and_tolerates_position():
    device = SimpleNamespace(volume=0)
    evidence = {'volume': 0, 'position': '0:00:01', 'coordinator': True,
                'mute': False, 'play_mode': 'NORMAL', 'transport_state': 'PLAYING',
                'queue_update_id': '7', 'queue_track_uri':
                'x-sonosapi-hls-static:song:123?sid=204'}

    class Speaker:
        def __init__(self):
            self.device = device
            self.revision = '7'

        def _prepare_evidence_sync(self):
            return dict(evidence, position='0:00:02', volume=device.volume,
                        queue_update_id=self.revision)

        async def _safe_mutation_call(self, operation):
            return operation()

    speaker = Speaker()
    result = await SonosService.set_selected_play_volume(speaker, device, evidence, 18, lambda: True)
    assert result['status'] == 'ready'
    assert device.volume == 18
    device.volume = 0
    speaker.revision = '8'
    result = await SonosService.set_selected_play_volume(speaker, device, evidence, 18, lambda: True)
    assert result['status'] == 'refused'
    assert device.volume == 0
    assert not same_manual_source(evidence, dict(evidence, queue_track_uri='other'))
