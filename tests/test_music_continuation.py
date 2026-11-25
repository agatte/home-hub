from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from backend.services.music_continuation import ContinuationPlanner, QueuedSong
from backend.services.music_selected_plan import SelectedListeningPlan
from backend.services.recommendation_service import RecommendationService
from tests.test_music_selected_plan import Approvals, Catalog, Taste, song


def selected():
    return SelectedListeningPlan("artist_mix:11,12", "artist_mix", "execution_not_connected",
                                 (song("11"), song("12")))


def related(identity, artist="Related", **kwargs):
    return {"provider": "itunes_search", "provider_id": identity, "catalog_verified": True,
            "seed_artist": "Artist", "source_match": 0.8, "artist_name": artist,
            "track_name": f"Track {identity}", **kwargs}


def candidate(identity, artist="Related"):
    item = song(identity)
    return replace(item, metadata={**item.metadata, "artist_name": artist})


class Source:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def similar_tracks_for_artist(self, artist):
        self.calls.append(artist)
        return self.rows


@pytest.mark.asyncio
async def test_tail_exact_related_tracks_bounded_and_no_duplicates():
    source = Source([related("11"), related("21"), related("21"), related("22"),
                     related("23"), related("24"), related("25")])
    catalog = Catalog({i: candidate(i) for i in ("11", "21", "22", "23", "24", "25")})
    planner = ContinuationPlanner(source=source, catalog=catalog, taste_provider=Taste(),
                                  approval_service=Approvals())
    tail = await planner.preview(selected(), mode="general")
    assert [item.provider_id for item in tail] == ["21", "22", "23"]
    assert source.calls == ["Artist"]
    assert catalog.calls == [("itunes_search", i) for i in ("21", "22", "23", "24")]
    assert await planner.revalidate(tail, mode="general")


@pytest.mark.asyncio
async def test_veto_wrong_seed_and_unverified_identity_abstain():
    source = Source([related("21", seed_artist="Other"), related("22", source_match=0.1),
                     related("23"), related("24"), related("25"), related("26")])
    catalog = Catalog({"23": candidate("23"), "24": candidate("24"),
                       "25": candidate("99"), "26": candidate("26")})
    approvals = Approvals({("itunes_search", "23"): "revoke"})
    planner = ContinuationPlanner(source=source, catalog=catalog,
                                  taste_provider=Taste({"24": ("rejected", -1)}),
                                  approval_service=approvals)
    tail = await planner.preview(selected(), mode="general")
    assert [item.provider_id for item in tail] == ["26"]
    approvals.actions[("itunes_search", "26")] = "revoke"
    assert not await planner.revalidate(tail, mode="general")


@pytest.mark.asyncio
async def test_no_source_or_taste_evidence_does_not_invent_tail():
    planner = ContinuationPlanner(source=Source([related("21")]),
                                  catalog=Catalog({"21": candidate("21")}),
                                  taste_provider=Taste(fail=True), approval_service=Approvals())
    assert await planner.preview(selected(), mode="general") == ()
    assert await planner.preview(replace(selected(), kind="favorite"), mode="general") == ()

@pytest.mark.asyncio
async def test_source_queries_exact_seed_read_only_and_bounds_lookup():
    service = RecommendationService(lastfm_api_key="synthetic")
    service._get_similar_artists = AsyncMock(return_value=[
        {"name": "Artist", "match": 1}, {"name": "Low", "match": 0.1},
        {"name": "A", "match": 0.9}, {"name": "B", "match": 0.8},
        {"name": "C", "match": 0.7}, {"name": "D", "match": 0.6},
    ])
    service._search_itunes_tracks = AsyncMock(side_effect=lambda name, limit: [
        {"artist_name": name, "provider_id": str(i)} for i in range(5)
    ])
    try:
        rows = await service.similar_tracks_for_artist("Artist")
        assert len(rows) == 6
        assert [row["artist_name"] for row in rows] == ["A", "A", "B", "B", "C", "C"]
        assert all(row["seed_artist"] == "Artist" for row in rows)
        service._get_similar_artists.assert_awaited_once_with("Artist", persist_cache=False)
        assert service._search_itunes_tracks.await_count == 3
    finally:
        await service.close()

@pytest.mark.asyncio
async def test_actual_final_playlist_seed_and_duplicate_exclusion():
    source = Source([related("11"), related("21"), related("22")])
    catalog = Catalog({"12": song("12"), "11": candidate("11"),
                       "21": candidate("21"), "22": candidate("22")})
    planner = ContinuationPlanner(source=source, catalog=catalog, taste_provider=Taste(),
                                  approval_service=Approvals())
    prefix = (QueuedSong("11", "Track 11", "Artist"), QueuedSong("12", "Track 12", "Artist"))
    assert [item.provider_id for item in await planner.preview_container(prefix, mode="general")] == ["21", "22"]
    assert source.calls == ["Artist"]
    assert catalog.calls[0] == ("itunes_search", "12")
    source.calls.clear()
    assert await planner.preview_container(prefix[:-1] + (QueuedSong("12", "Wrong title", "Artist"),), mode="general") == ()
    assert source.calls == []
