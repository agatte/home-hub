"""Strict, data-only schema for the navigation-v1 incident bundle."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_ID = "homehub.incident.navigation.v1"
PROFILE_ID = "navigation-v1"
SCHEMA_VERSION = 1
PROFILE_VERSION = 1


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class KnownValue(StrictModel):
    status: Literal["known"]
    value: Any


class UnknownValue(StrictModel):
    status: Literal["unknown"]
    reason: Annotated[str, Field(min_length=1)]


class NotConsumedValue(StrictModel):
    status: Literal["not_consumed"]
    reason: Annotated[str, Field(min_length=1)]


EvidenceValue = Annotated[
    KnownValue | UnknownValue | NotConsumedValue,
    Field(discriminator="status"),
]


Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ImplementationIdentityV1(StrictModel):
    backend_commit: Annotated[str, Field(min_length=1)]
    backend_build: Annotated[str, Field(min_length=1)]
    backend_dirty: bool | Literal["unknown"]
    python_version: Annotated[str, Field(min_length=1)]
    dependency_identity: Annotated[str, Field(min_length=1)]
    tzdata_identity: Annotated[str, Field(min_length=1)]
    source_agent_build: EvidenceValue


class ConfigurationIdentityV1(StrictModel):
    consumed_values: dict[str, Any]
    value_sources: dict[str, str]
    policy_digest: Sha256


class WindowV1(StrictModel):
    start_utc: Annotated[str, Field(min_length=1)]
    end_utc: Annotated[str, Field(min_length=1)]
    checkpoint_utc: Annotated[str, Field(min_length=1)]
    timezone: Literal["America/Indiana/Indianapolis"]
    boundary: Literal["[start,end)"]


class SessionsV1(StrictModel):
    backend_boot_id: Annotated[str, Field(min_length=1)]
    backend_session_id: Annotated[str, Field(min_length=1)]
    source_sessions: dict[str, str]
    device_ids: dict[str, str]


class TimeIdentityV1(StrictModel):
    backend_monotonic_origin_ns: Annotated[int, Field(ge=0)]
    wall_time_anchor_utc: Annotated[str, Field(min_length=1)]
    clock_domain: Annotated[str, Field(min_length=1)]
    adjustments: list[dict[str, Any]]


class GapV1(StrictModel):
    field_or_event_id: Annotated[str, Field(min_length=1)]
    missing_interval: EvidenceValue
    reason: Annotated[str, Field(min_length=1)]
    affected_decisions: list[str]
    completeness_consequence: Literal["none", "uncertain", "incomplete"]


class ManifestV1(StrictModel):
    schema_id: Literal[SCHEMA_ID]
    schema_version: Literal[SCHEMA_VERSION]
    profile_id: Literal[PROFILE_ID]
    profile_version: Literal[PROFILE_VERSION]
    bundle_id: Annotated[str, Field(min_length=1)]
    capture_provenance: dict[str, Any]
    completeness_status: Literal["complete", "incomplete"]
    member_sha256: dict[str, Sha256]
    manifest_sha256: Sha256
    implementation: ImplementationIdentityV1
    configuration: ConfigurationIdentityV1
    window: WindowV1
    sessions: SessionsV1
    time: TimeIdentityV1
    gaps: list[GapV1]


class InitialStateV1(StrictModel):
    schema_id: Literal["homehub.incident.navigation.initial.v1"]
    schema_version: Literal[1]
    profile_id: Literal[PROFILE_ID]
    profile_version: Literal[PROFILE_VERSION]
    backend_boot_id: Annotated[str, Field(min_length=1)]
    backend_session_id: Annotated[str, Field(min_length=1)]
    checkpoint_utc: Annotated[str, Field(min_length=1)]
    quiescent: bool
    fusion: EvidenceValue
    engine: EvidenceValue
    transit: EvidenceValue
    camera: EvidenceValue
    engine_state: EvidenceValue
    working_context: EvidenceValue
    ownership: EvidenceValue
    adapter: EvidenceValue
    transition_boundary: EvidenceValue
    pending_evaluations: EvidenceValue


class InputEnvelopeV1(StrictModel):
    schema_id: Literal["homehub.incident.navigation.input.v1"]
    schema_version: Literal[1]
    event_id: Annotated[str, Field(min_length=1)]
    kind: Literal[
        "fusion_ingest",
        "fusion_invalidation",
        "camera_status_change",
        "camera_lux_change",
        "engine_tick",
        "transit_tick",
        "deadline_tick",
        "restoration_tick",
        "adapter_completion",
        "cache_change",
        "source_health",
        "boot_transition",
        "activity_transition",
        "lifecycle_transition",
        "period_transition",
        "owner_transition",
    ]
    source_id: Annotated[str, Field(min_length=1)]
    source_session_id: Annotated[str, Field(min_length=1)]
    source_sequence: EvidenceValue
    captured_at_original: EvidenceValue
    captured_at_normalized: Annotated[str, Field(min_length=1)]
    received_at_utc: Annotated[str, Field(min_length=1)]
    received_mono_ns: Annotated[int, Field(ge=0)]
    backend_dispatch_sequence: Annotated[int, Field(ge=1)]
    backend_boot_id: Annotated[str, Field(min_length=1)]
    backend_session_id: Annotated[str, Field(min_length=1)]
    clock_domain: Annotated[str, Field(min_length=1)]
    normalization_provenance: EvidenceValue
    payload: EvidenceValue
    evidence_refs: list[str]


class ExpectedAssertionV1(StrictModel):
    assertion_id: Annotated[str, Field(min_length=1)]
    category: Literal["historical", "product", "simulated"]
    claim: Annotated[str, Field(min_length=1)]
    value: EvidenceValue
    evidence_refs: list[str]


class ExpectedV1(StrictModel):
    schema_id: Literal["homehub.incident.navigation.expected.v1"]
    schema_version: Literal[1]
    profile_id: Literal[PROFILE_ID]
    profile_version: Literal[PROFILE_VERSION]
    assertions: list[ExpectedAssertionV1]
