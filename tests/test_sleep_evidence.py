"""GH#236 Apple Health sleep-evidence shadow ingestion tests."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.api.auth import require_api_key, require_localhost
from backend.api.routes import sleep_evidence
from backend.models import Base


@pytest.fixture
async def client(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    monkeypatch.setattr(sleep_evidence, "async_session", session_factory)

    app = FastAPI()
    app.include_router(sleep_evidence.router)
    app.dependency_overrides[require_api_key] = lambda: None
    app.dependency_overrides[require_localhost] = lambda: None
    app.state.automation = SimpleNamespace(house_state="home", activity="general")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as http_client:
        yield http_client
    await engine.dispose()


def _payload(
    *,
    sample_uuid: str = "550e8400-e29b-41d4-a716-446655440000",
    stage: str = "asleep_core",
    observed_at: datetime | None = None,
    end_at: datetime | None = None,
    source_bundle_id: str | None = "com.apple.health",
) -> dict:
    now = datetime.now(timezone.utc)
    sample_end = end_at or (now - timedelta(minutes=2))
    sample_start = sample_end - timedelta(minutes=12)
    return {
        "client_kind": "healthkit_observer",
        "client_observed_at": (observed_at or now).isoformat(),
        "client_version": "shadow-test",
        "samples": [{
            "sample_uuid": sample_uuid,
            "stage": stage,
            "start_at": sample_start.isoformat(),
            "end_at": sample_end.isoformat(),
            "source_bundle_id": source_bundle_id,
            "source_product_type": "Watch7,5",
            "source_version": "26.0",
        }],
    }


@pytest.mark.asyncio
async def test_ingest_is_shadow_only_and_reviewable(client):
    response = await client.post(
        "/api/sleep/evidence",
        json=_payload(),
        headers={"X-Source": "ios_healthkit:test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["shadow_only"] is True
    assert body["authority_applied"] is False
    assert body["inserted"] == 1

    review = await client.get("/api/sleep/evidence/recent?hours=24")
    assert review.status_code == 200
    data = review.json()
    assert data["count"] == 1
    assert data["active_count"] == 1
    assert data["source_counts"] == {"com.apple.health": 1}
    row = data["rows"][0]
    assert row["stage"] == "asleep_core"
    assert row["source_bundle_id"] == "com.apple.health"
    assert row["ingest_source"] == "ios_healthkit:test"
    assert row["house_state_at_first_receive"] == "home"
    assert row["activity_at_first_receive"] == "general"
    assert row["freshness_status"] == "under_5m"
    assert row["observer_delay_s"] is not None
    assert row["network_delay_s"] is not None


@pytest.mark.asyncio
async def test_shortcut_backfill_does_not_poison_native_observer_latency(client):
    now = datetime.now(timezone.utc)
    sample_end = now - timedelta(minutes=10)
    payload = _payload(
        observed_at=now - timedelta(minutes=5),
        end_at=sample_end,
    )
    payload["client_kind"] = "shortcut_backfill"
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 200

    first = (await client.get("/api/sleep/evidence/recent")).json()["rows"][0]
    assert first["first_client_kind"] == "shortcut_backfill"
    assert first["freshness_basis"] == "shortcut_backfill"
    assert first["observer_delay_s"] is None

    native = {**payload, "client_kind": "healthkit_observer"}
    native["client_observed_at"] = now.isoformat()
    assert (await client.post("/api/sleep/evidence", json=native)).status_code == 200

    row = (await client.get("/api/sleep/evidence/recent")).json()["rows"][0]
    assert row["first_client_kind"] == "shortcut_backfill"
    assert row["freshness_basis"] == "healthkit_observer"
    assert row["native_observer_observed_at"] is not None
    assert row["observer_delay_s"] >= 599


@pytest.mark.asyncio
async def test_retry_is_idempotent_and_preserves_one_row(client):
    payload = _payload()
    first = await client.post("/api/sleep/evidence", json=payload)
    assert first.json()["inserted"] == 1
    first_row = (await client.get("/api/sleep/evidence/recent")).json()["rows"][0]

    await asyncio.sleep(0.01)
    second = await client.post("/api/sleep/evidence", json=payload)
    assert second.json()["inserted"] == 0
    assert second.json()["updated"] == 1

    review = await client.get("/api/sleep/evidence/recent")
    assert review.json()["count"] == 1
    second_row = review.json()["rows"][0]
    assert second_row["first_received_at"] == first_row["first_received_at"]
    assert second_row["last_received_at"] != first_row["last_received_at"]


@pytest.mark.asyncio
async def test_missing_provenance_can_be_enriched_without_uuid_conflict(client):
    payload = _payload(source_bundle_id=None)
    payload["samples"][0]["source_product_type"] = None
    payload["samples"][0]["source_version"] = None
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 200

    enriched = {**payload, "samples": [dict(payload["samples"][0])]}
    enriched["samples"][0]["source_bundle_id"] = "com.apple.health"
    enriched["samples"][0]["source_product_type"] = "Watch7,5"
    enriched["samples"][0]["source_version"] = "26.0"
    response = await client.post("/api/sleep/evidence", json=enriched)
    assert response.status_code == 200
    row = (await client.get("/api/sleep/evidence/recent")).json()["rows"][0]
    assert row["source_bundle_id"] == "com.apple.health"
    assert row["source_product_type"] == "Watch7,5"


@pytest.mark.asyncio
async def test_uuid_reuse_with_changed_sample_content_is_rejected(client):
    payload = _payload(stage="asleep_core")
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 200

    changed = _payload(stage="awake")
    response = await client.post("/api/sleep/evidence", json=changed)
    assert response.status_code == 409
    assert "sample_uuid collision" in response.json()["detail"]


@pytest.mark.asyncio
async def test_unknown_deletion_creates_tombstone(client):
    payload = {
        "client_kind": "healthkit_observer",
        "client_observed_at": datetime.now(timezone.utc).isoformat(),
        "deleted_sample_uuids": ["550e8400-e29b-41d4-a716-446655440099"],
    }
    response = await client.post("/api/sleep/evidence", json=payload)
    assert response.status_code == 200
    assert response.json()["deleted"] == 1

    data = (await client.get("/api/sleep/evidence/recent")).json()
    assert data["deleted_count"] == 1
    row = data["rows"][0]
    assert row["stage"] is None
    assert row["deleted_at"] is not None
    assert row["freshness_status"] == "unknown"


@pytest.mark.asyncio
async def test_empty_or_overlapping_batch_is_rejected(client):
    now = datetime.now(timezone.utc).isoformat()
    empty = await client.post(
        "/api/sleep/evidence",
        json={"client_kind": "manual_test", "client_observed_at": now},
    )
    assert empty.status_code == 422

    sample = _payload()
    sample["deleted_sample_uuids"] = [sample["samples"][0]["sample_uuid"]]
    overlap = await client.post("/api/sleep/evidence", json=sample)
    assert overlap.status_code == 422


@pytest.mark.asyncio
async def test_unknown_batch_or_sample_fields_are_rejected(client):
    payload = _payload()
    payload["unexpected_health_metadata"] = {"heart_rate": 72}
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 422

    payload = _payload()
    payload["samples"][0]["unexpected_metadata"] = "private"
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 422


@pytest.mark.asyncio
async def test_repeated_deletion_preserves_first_deletion_time(client):
    sample_uuid = "550e8400-e29b-41d4-a716-446655440077"
    payload = {
        "client_kind": "healthkit_observer",
        "client_observed_at": datetime.now(timezone.utc).isoformat(),
        "deleted_sample_uuids": [sample_uuid],
    }
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 200
    first = (await client.get("/api/sleep/evidence/recent")).json()["rows"][0]
    first_deleted_at = first["deleted_at"]

    await asyncio.sleep(0.01)
    payload["client_observed_at"] = datetime.now(timezone.utc).isoformat()
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 200
    second = (await client.get("/api/sleep/evidence/recent")).json()["rows"][0]
    assert second["deleted_at"] == first_deleted_at


@pytest.mark.asyncio
async def test_future_client_clock_is_flagged_and_excluded_from_latency_aggregate(client):
    now = datetime.now(timezone.utc)
    payload = _payload(
        observed_at=now + timedelta(hours=1),
        end_at=now - timedelta(minutes=10),
    )
    assert (await client.post("/api/sleep/evidence", json=payload)).status_code == 200

    review = (await client.get("/api/sleep/evidence/recent")).json()
    row = review["rows"][0]
    assert row["client_clock_status"] == "future_skew"
    assert row["network_delay_s"] < -3500
    assert row["observer_delay_s"] is not None
    assert review["client_clock_status_counts"] == {"future_skew": 1}
    assert review["observer_delay_s"] == {"min": None, "max": None, "avg": None}


@pytest.mark.asyncio
async def test_review_summarizes_delayed_delivery_without_granting_authority(client):
    now = datetime.now(timezone.utc)
    payload = _payload(
        observed_at=now - timedelta(minutes=40),
        end_at=now - timedelta(minutes=45),
    )
    response = await client.post("/api/sleep/evidence", json=payload)
    assert response.status_code == 200

    review = (await client.get("/api/sleep/evidence/recent")).json()
    assert review["authority_applied"] is False
    assert review["freshness_counts"] == {"over_30m": 1}
    assert review["stage_counts"] == {"asleep_core": 1}
    assert review["observer_delay_s"]["min"] >= 299

def test_raw_review_route_is_direct_localhost_only():
    route = next(
        route
        for route in sleep_evidence.router.routes
        if route.path == "/api/sleep/evidence/recent"
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert require_localhost in dependency_calls
    assert require_api_key not in dependency_calls
