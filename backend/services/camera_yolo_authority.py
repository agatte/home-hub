"""Conservative YOLO person-authority gate for the Latitude camera.

This module has no camera/model dependencies. It converts the maximum person
confidence from the validated #198 YOLO26n-pose challenger into one of three
physical-evidence states: present, absent-candidate, or unknown/blinded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AuthorityDecision = Literal["present", "absent", "unknown"]


@dataclass
class YoloPresenceAuthority:
    """Require stable YOLO evidence before granting person authority."""

    person_confidence_threshold: float = 0.25
    blinded_confidence_ceiling: float = 0.01
    present_dwell_frames: int = 3
    _present_streak: int = 0

    def __post_init__(self) -> None:
        if not 0.0 < self.person_confidence_threshold <= 1.0:
            raise ValueError("person_confidence_threshold must be in (0, 1]")
        if not 0.0 <= self.blinded_confidence_ceiling < self.person_confidence_threshold:
            raise ValueError(
                "blinded_confidence_ceiling must be below person threshold"
            )
        if self.present_dwell_frames < 1:
            raise ValueError("present_dwell_frames must be positive")

    def reset(self) -> None:
        """Drop pending evidence after sleep, restart, or model invalidation."""
        self._present_streak = 0

    def evaluate(self, max_person_confidence: float | None) -> AuthorityDecision:
        """Classify one frame without turning camera blindness into absence.

        A very-low-confidence frame matches the near-closed-lid #198 signature
        and therefore abstains. Presence needs a short consecutive-frame dwell;
        sub-threshold but otherwise usable frames are absence candidates. The
        existing CameraService 15-frame absence dwell remains the final exit
        debounce.
        """
        if (
            max_person_confidence is None
            or max_person_confidence <= self.blinded_confidence_ceiling
        ):
            self._present_streak = 0
            return "unknown"

        if max_person_confidence < self.person_confidence_threshold:
            self._present_streak = 0
            return "absent"

        self._present_streak += 1
        if self._present_streak < self.present_dwell_frames:
            return "unknown"
        return "present"
