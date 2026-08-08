"""
SQLAlchemy models for persistent data.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class AppSetting(Base):
    """Key-value store for persistent app settings (survives restarts)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Scene(Base):
    """A saved light scene that can be activated with one tap."""

    __tablename__ = "scenes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    light_states: Mapped[dict] = mapped_column(JSON, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True, default="custom")
    effect: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class ModePlaylist(Base):
    """Maps an activity mode to a Sonos favorite/playlist for auto-play.

    Multiple entries per mode are supported — each can carry a vibe tag
    (energetic, mellow, focus, background, hype) so the mapper can pick
    the right one based on time of day or explicit request.
    """

    __tablename__ = "mode_playlists"
    __table_args__ = (
        UniqueConstraint("mode", "favorite_title", name="uq_mode_favorite"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    favorite_title: Mapped[str] = mapped_column(String(200), nullable=False)
    vibe: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    auto_play: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class MusicArtist(Base):
    """An artist from the user's Apple Music library or recommendations."""

    __tablename__ = "music_artists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    genres: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    track_count: Mapped[int] = mapped_column(Integer, default=0)
    rating_avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="import")
    similar_artists: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    similar_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class TasteProfile(Base):
    """Aggregated taste profile derived from library import (singleton row)."""

    __tablename__ = "taste_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    genre_distribution: Mapped[dict] = mapped_column(JSON, nullable=False)
    top_artists: Mapped[list] = mapped_column(JSON, nullable=False)
    mode_genre_map: Mapped[dict] = mapped_column(JSON, nullable=False)
    import_track_count: Mapped[int] = mapped_column(Integer, default=0)
    import_artist_count: Mapped[int] = mapped_column(Integer, default=0)
    last_import_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Recommendation(Base):
    """A music recommendation for a specific activity mode."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artist_name: Mapped[str] = mapped_column(String(200), nullable=False)
    track_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    album_name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    preview_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    artwork_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    itunes_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class RecommendationFeedback(Base):
    """User feedback on a recommendation (like, dismiss, etc.)."""

    __tablename__ = "recommendation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("recommendations.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Event logging — raw behavioral data for the future learning engine
# ---------------------------------------------------------------------------


class ActivityEvent(Base):
    """Records every mode transition for behavioral analysis."""

    __tablename__ = "activity_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # source: "automation", "manual", "pc_agent", "ambient"
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    # duration_seconds is filled in when the *next* event arrives
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Camera + audio context at the moment of the transition. Populated by
    # EventLogger from camera_service / latest audio_ml ml_decisions row.
    # All nullable — pre-enrichment rows + camera-disabled sessions store None.
    zone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    posture: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    audio_class: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    lux: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class LightAdjustment(Base):
    """Records every manual light change issued from the dashboard."""

    __tablename__ = "light_adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    light_id: Mapped[str] = mapped_column(String(20), nullable=False)
    light_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    bri_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bri_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hue_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hue_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sat_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sat_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ct_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ct_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    mode_at_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    zone_at_time: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    posture_at_time: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # trigger: "ws", "rest", "scene", "automation", "all_lights"
    trigger: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # weather_class: classify_for_bandit() output captured at adjustment time.
    # Values: "clear" | "clouds" | "rain" | "thunderstorm" | "snow" |
    # "golden_hour". NULL on pre-migration rows; LightingLearner retrain
    # folds NULL → "any" (same pattern as sonos_playback_events).
    weather_class: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


class SonosPlaybackEvent(Base):
    """Records every Sonos play/pause/skip/volume event."""

    __tablename__ = "sonos_playback_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    # event_type: "play", "pause", "skip", "volume", "auto_play", "suggestion"
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    favorite_title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    mode_at_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # triggered_by: "manual", "auto", "suggestion_accepted"
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    # Phase B (2026-05-12): weather class at event-log time so the bandit's
    # nightly retrain can rebuild weather-aware arms across 90d of history.
    # One of: "thunderstorm" / "rain" / "snow" / "clouds" / "golden_hour" /
    # "clear" / "any" (sentinel) / None (pre-migration legacy rows).
    weather_class: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)


class SceneActivation(Base):
    """Records every scene activation (preset, custom, or bridge)."""

    __tablename__ = "scene_activations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    scene_id: Mapped[str] = mapped_column(String(100), nullable=False)
    scene_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # source: "preset", "custom", "bridge"
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    mode_at_time: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)


# ---------------------------------------------------------------------------
# Mode → scene overrides (use Hue scenes instead of hardcoded light states)
# ---------------------------------------------------------------------------


class ModeSceneOverride(Base):
    """Maps a mode + time period to a Hue scene for automation."""

    __tablename__ = "mode_scene_overrides"
    __table_args__ = (
        UniqueConstraint("mode", "time_period", name="uq_mode_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    time_period: Mapped[str] = mapped_column(String(20), nullable=False)  # day, evening, night
    scene_id: Mapped[str] = mapped_column(String(200), nullable=False)  # preset name or bridge UUID
    scene_source: Mapped[str] = mapped_column(String(20), nullable=False)  # "preset" or "bridge"
    scene_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Learned rules (Phase 3b: rule engine)
# ---------------------------------------------------------------------------


class LearnedRule(Base):
    """A frequency-based rule learned from activity event patterns."""

    __tablename__ = "learned_rules"
    __table_args__ = (
        UniqueConstraint("day_of_week", "hour", name="uq_day_hour"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday, 6=Sunday
    hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23
    predicted_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0-1.0
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class RuleSuggestion(Base):
    """A single fire of a LearnedRule that was surfaced to the user.

    Persistent record of every suggestion. The frontend's Home banner reads
    the latest pending row at boot; expiry, accept, dismiss, and supersede
    transitions all UPDATE rows here. Replaces the previous in-memory
    `_last_suggestion` as the source of truth (kept as a cache pointer).

    Status vocabulary:
        pending     — broadcast to UI, awaiting user action
        accepted    — user clicked Switch; mode applied
        dismissed   — user clicked X
        expired     — auto-aged out by `expire_stale_pending` after 60min
        superseded  — a newer suggestion took its slot before resolution

    `resolved_source` vocabulary:
        user_accept:<remote-ip>
        user_dismiss:<remote-ip>
        auto_expire
        superseded_by:<new_id>

    Confidence is stored 0.0-1.0 (matches LearnedRule); API/WS serializers
    emit int(round(c*100)) for the percent UX payload.
    """

    __tablename__ = "rule_suggestions"
    __table_args__ = (
        Index("ix_rule_sugg_status_fired", "status", "fired_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # rule_id is the FK to LearnedRule for kind="mode" suggestions. For
    # kind="brightness" rows (weather-aware brightness suggestions, 2026-05-18)
    # the source is the LightingLearner scanner output, not a LearnedRule —
    # rule_id is NULL and the bucket key lives in `payload`.
    rule_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("learned_rules.id"), nullable=True,
    )
    fired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    predicted_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)  # 0.0-1.0
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_mode_at_fire: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolved_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # Discriminator: "mode" (original — LearnedRule mode flip) or "brightness"
    # (per-bucket lighting preference suggestion from LightingLearner scanner).
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="mode")
    # JSON-as-TEXT payload for kind-specific data. For "brightness":
    # {light_id, mode, period, weather_class, suggested_bri,
    #  suggested_multiplier, sample_count}. NULL on legacy "mode" rows.
    payload: Mapped[Optional[str]] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# ML decision and metrics logging
# ---------------------------------------------------------------------------


class MLDecision(Base):
    """Records every mode decision with reasoning chain for explainability."""

    __tablename__ = "ml_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    predicted_mode: Mapped[str] = mapped_column(String(50), nullable=False)
    actual_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # decision_source: "ml", "rule", "time", "manual"
    decision_source: Mapped[str] = mapped_column(String(30), nullable=False)
    factors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Set True when the originating source was untrusted (SourceTrust verdict)
    # at log time. Rows stay for forensics/analytics but are excluded from
    # every learner's training set — the gate that would have stopped the
    # 2026-05-27 lux pin from poisoning the predictor. See source_trust.py.
    quarantined: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MLMetric(Base):
    """Daily aggregate ML performance metrics."""

    __tablename__ = "ml_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    extra: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class RemediationLog(Base):
    """Audit trail for the bounded auto-remediation subsystem.

    One row per remediation decision — whether executed (autonomous), proposed
    (propose-only mode or a propose-tier policy), skipped (rate-limited /
    cooldown / disabled), or errored. The forensic record behind every change
    the remediator agent makes or recommends; nothing in the subsystem mutates
    state without a row here first. See backend/services/remediation_service.py.
    """

    __tablename__ = "remediation_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    # The troubled source the action targets (e.g. "camera"); nullable for
    # actions that aren't source-scoped.
    source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # "auto" (executed) | "propose" (recommended, awaiting human).
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    # "executed" | "proposed" | "skipped" | "error".
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    # Pointer back to the digest warn / investigator diagnosis that triggered
    # this (e.g. "2026-06-01#source-trust"); free-form, nullable.
    diagnosis_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    params: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Set True if a later manual/auto step reverted this action.
    reverted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class LivingRoomDecisionRecord(Base):
    """Bounded explainability record for the shadow living-room gate."""

    __tablename__ = "living_room_decision_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    behavior: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False)
    snapshot_version: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision: Mapped[dict] = mapped_column(JSON, nullable=False)
    semantic_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )


# ---------------------------------------------------------------------------
# AI Personality Layer (Phase A shadow-log).
#
# mood_samples: rolling 7-day record of EmotionService output. One row per
#   poll where the face was detected with sufficient confidence; suppressed
#   during sleeping / paused / emotion_enabled=false. Values are unitless
#   on [-1, 1] (valence, arousal) and [0, 1] (focus).
# mood_calibration: explicit self-report rows from the calibration UI. Used
#   to fit a per-user linear bias term added to live readings at output
#   time. Persistent (not retained on a window).
# vibe_requests: log of /api/personality/vibe calls — transcript, Claude
#   response, applied flag, cost ledger. Persistent for cost auditing.
# ---------------------------------------------------------------------------
class MoodSample(Base):
    """One emotion-detector reading; rolling 7-day retention."""

    __tablename__ = "mood_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    valence: Mapped[float] = mapped_column(Float, nullable=False)
    arousal: Mapped[float] = mapped_column(Float, nullable=False)
    focus: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # Factors that contributed: {face_conf, audio_arousal, top_blendshapes:{...}}
    factors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class MoodCalibration(Base):
    """User-supplied self-report against the detector's live reading."""

    __tablename__ = "mood_calibration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    # Self-report (ground truth)
    self_valence: Mapped[float] = mapped_column(Float, nullable=False)
    self_arousal: Mapped[float] = mapped_column(Float, nullable=False)
    self_focus: Mapped[float] = mapped_column(Float, nullable=False)
    # Detector's reading at the moment of self-report. Nullable: the user
    # can self-report even when the camera isn't returning a confident face.
    detected_valence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_arousal: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_focus: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class VibeRequest(Base):
    """One /api/personality/vibe VibeRouter request."""

    __tablename__ = "vibe_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    transcript: Mapped[str] = mapped_column(String(500), nullable=False)
    response: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="api")
