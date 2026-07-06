"""AI Personality Layer — emotion inference, mood-ring light, vibe router.

Phase A (shadow-log only): EmotionService consumes face blendshapes from
camera_service and emits a mood_vector to mood_samples for offline
validation. No actuation.

Phases B/C/D layer on the mood-ring light, vibe intent, and hardening
once Phase A passes its Spearman ρ > 0.4 calibration gate.

Privacy contract: same as camera_service. Face landmark / blendshape
extraction runs in-memory only; raw frames and landmark coordinates
never persist. Only derived V/A/F floats and confidence land in DB.
Opt-in via emotion_enabled app setting (default false), gated
independently of camera_enabled.
"""
from backend.services.personality.emotion_service import EmotionService
from backend.services.personality.mood_palette import mood_to_hsv
from backend.services.personality.vibe_router import VibeRouter

__all__ = ["EmotionService", "VibeRouter", "mood_to_hsv"]
