import pytest

from backend.services.music_favorite_execution import _exact_queued_songs
from backend.services.music_mix_execution import _item_matches
from backend.services.music_queue_identity import apple_song_id
from backend.services.music_repeat_selection import stopped_queue_matches
from backend.services.music_sustained_listening import sample_cursor
from tests.test_music_repeat_selection import StoppedSonos, origin_for


@pytest.mark.parametrize("suffix", ["", "?sid=9", "?sid=204&amp;sid=9", "?sid=204&amp;sid=204", "?sid=204#other"])
def test_other_or_ambiguous_service_never_establishes_queue_identity(suffix):
    uri = "x-sonos-http:song%3a11" + suffix
    row = f"<item><title>Track 11</title><artist>Artist</artist><res>{uri}</res></item>"
    assert apple_song_id(uri.replace("&amp;", "&")) is None
    assert not _item_matches(("rev", 1, f"<DIDL-Lite>{row}</DIDL-Lite>"), "11", 1)
    assert not _exact_queued_songs((row,))
    sonos = StoppedSonos([0.0])
    origin = origin_for(sonos)
    evidence = {**sonos._prepare_evidence_sync(), "queue_track_uri": uri.replace("&amp;", "&")}
    assert not stopped_queue_matches(origin.proof, evidence, ceiling=18)
    assert sample_cursor(origin.proof, {**evidence, "transport_state": "PLAYING"}, now=0) is None


def test_exact_apple_service_and_song_is_accepted():
    uri = "x-sonos-http:song%3a11?sid=204&flags=8232&sn=2"
    assert apple_song_id(uri) == "11"
