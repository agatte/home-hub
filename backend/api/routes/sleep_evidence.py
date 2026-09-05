"""Apple Health sleep evidence ingestion and calibration review.

Phase 1 of GH#236 is intentionally shadow-only. The authenticated ingest
surface stores HealthKit sleep samples plus timing/provenance needed to
measure real delivery behavior. It never changes HomeHub house state.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from backend.api.auth import require_api_key, require_localhost, source_from_request
from backend.database import async_session
from backend.models import AppleHealthSleepEvidence

router = APIRouter(prefix="/api/sleep", tags=["sleep-evidence"])

SleepStage = Literal[
    "in_bed",
    "awake",
    "asleep_core",
    "asleep_deep",
    "asleep_rem",
    "asleep_unspecified",
]
SampleUUID = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
]


class SleepEvidenceSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_uuid: SampleUUID
    stage: SleepStage
    start_at: datetime
    end_at: datetime
    source_bundle_id: str | None = Field(default=None, max_length=200)
    source_product_type: str | None = Field(default=None, max_length=100)
    source_version: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_interval(self) -> "SleepEvidenceSample":
        if _as_utc(self.end_at) < _as_utc(self.start_at):
            raise ValueError("end_at must be on or after start_at")
        return self


class SleepEvidenceBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_kind: Literal["healthkit_observer", "shortcut_backfill", "manual_test"]
    client_observed_at: datetime
    client_version: str | None = Field(default=None, max_length=50)
    samples: list[SleepEvidenceSample] = Field(default_factory=list, max_length=256)
    deleted_sample_uuids: list[SampleUUID] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def validate_payload(self) -> "SleepEvidenceBatch":
        ids = [sample.sample_uuid for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("samples contains duplicate sample_uuid values")
        if len(self.deleted_sample_uuids) != len(set(self.deleted_sample_uuids)):
            raise ValueError("deleted_sample_uuids contains duplicates")
        overlap = set(ids) & set(self.deleted_sample_uuids)
        if overlap:
            raise ValueError("a sample cannot be upserted and deleted in one batch")
        if not self.samples and not self.deleted_sample_uuids:
            raise ValueError("batch must contain samples or deletions")
        return self


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _dt_equal(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return _as_utc(left) == _as_utc(right)


def _client_clock_status(
    observed_at: datetime | None,
    received_at: datetime | None,
) -> str:
    """Classify only clear future client-clock skew; delayed delivery stays valid."""
    if observed_at is None or received_at is None:
        return "not_native_observer"
    offset_s = (_as_utc(observed_at) - _as_utc(received_at)).total_seconds()
    if offset_s > 120:
        return "future_skew"
    return "plausible_or_delayed"


def _freshness_status(received_at: datetime, sample_end_at: datetime | None) -> str:
    """Diagnostic delivery bucket only; it grants no lifecycle authority."""
    if sample_end_at is None:
        return "unknown"
    age_s = (_as_utc(received_at) - _as_utc(sample_end_at)).total_seconds()
    if age_s < -120:
        return "future_sample"
    if age_s <= 300:
        return "under_5m"
    if age_s <= 1800:
        return "under_30m"
    return "over_30m"


def _sleep_context(request: Request) -> tuple[str | None, str | None]:
    engine = getattr(request.app.state, "automation", None)
    if engine is None:
        return None, None
    return (
        getattr(engine, "house_state", None),
        getattr(engine, "activity", None),
    )


def _sample_conflicts(
    row: AppleHealthSleepEvidence,
    sample: SleepEvidenceSample,
) -> bool:
    """HealthKit objects are immutable; reject UUID reuse with changed content."""
    if row.stage is None:
        return False
    return any((
        row.stage != sample.stage,
        not _dt_equal(row.sample_start_at, sample.start_at),
        not _dt_equal(row.sample_end_at, sample.end_at),
        (
            row.source_bundle_id is not None
            and sample.source_bundle_id is not None
            and row.source_bundle_id != sample.source_bundle_id
        ),
        (
            row.source_product_type is not None
            and sample.source_product_type is not None
            and row.source_product_type != sample.source_product_type
        ),
        (
            row.source_version is not None
            and sample.source_version is not None
            and row.source_version != sample.source_version
        ),
    ))


def _serialize_row(row: AppleHealthSleepEvidence) -> dict:
    def iso(value: datetime | None) -> str | None:
        return _as_utc(value).isoformat() if value is not None else None

    observer_delay_s = None
    network_delay_s = None
    if row.sample_end_at is not None and row.native_observer_observed_at is not None:
        observer_delay_s = round(
            (
                _as_utc(row.native_observer_observed_at)
                - _as_utc(row.sample_end_at)
            ).total_seconds(),
            3,
        )
    if (
        row.native_observer_observed_at is not None
        and row.native_observer_received_at is not None
    ):
        network_delay_s = round(
            (
                _as_utc(row.native_observer_received_at)
                - _as_utc(row.native_observer_observed_at)
            ).total_seconds(),
            3,
        )
    client_clock_status = _client_clock_status(
        row.native_observer_observed_at,
        row.native_observer_received_at,
    )
    return {
        "sample_uuid": row.sample_uuid,
        "stage": row.stage,
        "start_at": iso(row.sample_start_at),
        "end_at": iso(row.sample_end_at),
        "source_bundle_id": row.source_bundle_id,
        "source_product_type": row.source_product_type,
        "source_version": row.source_version,
        "first_observed_at": iso(row.first_observed_at),
        "first_received_at": iso(row.first_received_at),
        "first_client_kind": row.first_client_kind,
        "native_observer_observed_at": iso(row.native_observer_observed_at),
        "native_observer_received_at": iso(row.native_observer_received_at),
        "last_received_at": iso(row.last_received_at),
        "deleted_at": iso(row.deleted_at),
        "client_kind": row.client_kind,
        "client_version": row.client_version,
        "ingest_source": row.ingest_source,
        "house_state_at_first_receive": row.house_state_at_first_receive,
        "activity_at_first_receive": row.activity_at_first_receive,
        "observer_delay_s": observer_delay_s,
        "network_delay_s": network_delay_s,
        "client_clock_status": client_clock_status,
        "freshness_status": _freshness_status(
            row.native_observer_received_at or row.first_received_at,
            row.sample_end_at,
        ) if row.first_received_at is not None else "unknown",
        "freshness_basis": (
            "healthkit_observer"
            if row.native_observer_received_at is not None
            else row.first_client_kind
        ),
    }


@router.post("/evidence", dependencies=[Depends(require_api_key)])
async def ingest_sleep_evidence(
    payload: SleepEvidenceBatch,
    request: Request,
) -> dict:
    """Store Apple Health sleep evidence without applying lifecycle authority."""
    received_at = datetime.now(timezone.utc)
    observed_at = _as_utc(payload.client_observed_at)
    ingest_source = source_from_request(request, fallback="ios_healthkit")[:100]
    house_state, activity = _sleep_context(request)
    all_ids = [sample.sample_uuid for sample in payload.samples]
    all_ids.extend(payload.deleted_sample_uuids)

    inserted = 0
    updated = 0
    deleted = 0
    async with async_session() as session:
        existing: dict[str, AppleHealthSleepEvidence] = {}
        if all_ids:
            result = await session.execute(
                select(AppleHealthSleepEvidence).where(
                    AppleHealthSleepEvidence.sample_uuid.in_(all_ids)
                )
            )
            existing = {row.sample_uuid: row for row in result.scalars().all()}

        for sample in payload.samples:
            row = existing.get(sample.sample_uuid)
            if row is not None and _sample_conflicts(row, sample):
                raise HTTPException(
                    status_code=409,
                    detail=f"sample_uuid collision with different content: {sample.sample_uuid}",
                )
            if row is None:
                row = AppleHealthSleepEvidence(
                    sample_uuid=sample.sample_uuid,
                    first_observed_at=observed_at,
                    first_received_at=received_at,
                    first_client_kind=payload.client_kind,
                    house_state_at_first_receive=house_state,
                    activity_at_first_receive=activity,
                )
                session.add(row)
                existing[sample.sample_uuid] = row
                inserted += 1
            else:
                updated += 1

            row.stage = sample.stage
            row.sample_start_at = _as_utc(sample.start_at)
            row.sample_end_at = _as_utc(sample.end_at)
            if sample.source_bundle_id is not None:
                row.source_bundle_id = sample.source_bundle_id
            if sample.source_product_type is not None:
                row.source_product_type = sample.source_product_type
            if sample.source_version is not None:
                row.source_version = sample.source_version
            if (
                payload.client_kind == "healthkit_observer"
                and row.native_observer_observed_at is None
            ):
                row.native_observer_observed_at = observed_at
                row.native_observer_received_at = received_at
            row.last_observed_at = observed_at
            row.last_received_at = received_at
            row.client_kind = payload.client_kind
            row.client_version = payload.client_version
            row.ingest_source = ingest_source

        for sample_uuid in payload.deleted_sample_uuids:
            row = existing.get(sample_uuid)
            if row is None:
                row = AppleHealthSleepEvidence(
                    sample_uuid=sample_uuid,
                    first_observed_at=observed_at,
                    first_received_at=received_at,
                    first_client_kind=payload.client_kind,
                    house_state_at_first_receive=house_state,
                    activity_at_first_receive=activity,
                )
                session.add(row)
                existing[sample_uuid] = row
                inserted += 1
            else:
                updated += 1
            if row.deleted_at is None:
                row.deleted_at = received_at
            row.last_observed_at = observed_at
            row.last_received_at = received_at
            row.client_kind = payload.client_kind
            row.client_version = payload.client_version
            row.ingest_source = ingest_source
            deleted += 1

        await session.commit()

    return {
        "status": "ok",
        "shadow_only": True,
        "authority_applied": False,
        "received_at": received_at.isoformat(),
        "inserted": inserted,
        "updated": updated,
        "deleted": deleted,
    }


@router.get("/evidence/recent", dependencies=[Depends(require_localhost)])
async def recent_sleep_evidence(
    hours: int = Query(default=72, ge=1, le=24 * 30),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict:
    """Return localhost-only raw calibration rows and delivery diagnostics."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    async with async_session() as session:
        result = await session.execute(
            select(AppleHealthSleepEvidence)
            .where(AppleHealthSleepEvidence.last_received_at >= since)
            .order_by(AppleHealthSleepEvidence.last_received_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()

    serialized = [_serialize_row(row) for row in rows]
    active = [row for row in serialized if row["deleted_at"] is None]
    stage_counts = Counter(
        row["stage"] for row in active if row["stage"] is not None
    )
    freshness_counts = Counter(row["freshness_status"] for row in active)
    source_counts = Counter(
        row["source_bundle_id"] or "unknown" for row in active
    )
    observer_delays = [
        row["observer_delay_s"]
        for row in active
        if (
            row["observer_delay_s"] is not None
            and row["client_clock_status"] != "future_skew"
        )
    ]
    clock_status_counts = Counter(row["client_clock_status"] for row in active)

    return {
        "shadow_only": True,
        "authority_applied": False,
        "window_hours": hours,
        "count": len(serialized),
        "active_count": len(active),
        "deleted_count": len(serialized) - len(active),
        "stage_counts": dict(stage_counts),
        "freshness_counts": dict(freshness_counts),
        "source_counts": dict(source_counts),
        "client_clock_status_counts": dict(clock_status_counts),
        "observer_delay_s": {
            "min": min(observer_delays) if observer_delays else None,
            "max": max(observer_delays) if observer_delays else None,
            "avg": (
                round(sum(observer_delays) / len(observer_delays), 3)
                if observer_delays else None
            ),
        },
        "rows": serialized,
    }
