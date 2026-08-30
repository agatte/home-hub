"""Explicit, bounded derived-result capture for camera shadow calibration.

This module is intentionally separate from ``camera_shadow`` so the core
handoff/authority firewall retains no disk-write capability.  It accepts only
``ShadowResult`` objects, which cannot contain raw frames, crops, tensors,
image hashes, or raw landmark arrays.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import uuid

from backend.services.camera_shadow import ShadowPerson, ShadowResult


_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class JsonlShadowResultSink:
    """Write a bounded, explicitly labeled stream of derived shadow results."""

    label: str
    output_dir: str
    max_records: int = 1000
    _path: Path = field(init=False, repr=False)
    _records_written: int = field(init=False, default=0, repr=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        clean_label = _LABEL_RE.sub("-", self.label.strip()).strip("-._")[:80]
        if not clean_label:
            raise ValueError("shadow capture label must contain a usable character")
        if self.max_records < 1:
            raise ValueError("shadow capture max_records must be positive")

        directory = Path(self.output_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{timestamp}-{clean_label}-{uuid.uuid4().hex[:8]}.jsonl"
        self._path = directory / filename
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def records_written(self) -> int:
        with self._lock:
            return self._records_written

    @property
    def full(self) -> bool:
        with self._lock:
            return self._records_written >= self.max_records

    def accept(self, result: ShadowResult) -> None:
        """Append one derived result unless the explicit record cap is full."""
        payload = self._serialize(result)
        line = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with self._lock:
            if self._records_written >= self.max_records:
                return
            with self._path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
                handle.write("\n")
            self._records_written += 1

    def _serialize(self, result: ShadowResult) -> dict[str, object]:
        return {
            "capture_label": self.label,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "run_id": result.metadata.run_id,
            "frame_seq": result.metadata.frame_seq,
            "captured_at": result.metadata.captured_at.isoformat(),
            "frame_width": result.metadata.width,
            "frame_height": result.metadata.height,
            "model_id": result.model_id,
            "artifact_id": result.artifact_id,
            "artifact_checksum": result.artifact_checksum,
            "status": result.status,
            "person_detected": result.person_detected,
            "person_count": result.person_count,
            "max_person_confidence": result.max_person_confidence,
            "persons": [self._serialize_person(person) for person in result.persons],
            "preprocess_ms": result.preprocess_ms,
            "inference_ms": result.inference_ms,
            "postprocess_ms": result.postprocess_ms,
            "total_ms": result.total_ms,
            "worker_init_ms": result.worker_init_ms,
            "queue_handoff_ms": result.queue_handoff_ms,
            "end_to_end_ms": result.end_to_end_ms,
            "tracking_summary": result.tracking_summary,
            "detail": result.detail,
        }

    @staticmethod
    def _serialize_person(person: ShadowPerson) -> dict[str, object]:
        bbox = person.bbox
        return {
            "confidence": person.confidence,
            "bbox": {
                "center_x": bbox.center_x,
                "center_y": bbox.center_y,
                "width": bbox.width,
                "height": bbox.height,
            },
            "keypoints": {
                "available_count": person.keypoints.available_count,
                "mean_confidence": person.keypoints.mean_confidence,
            },
            "torso_center": (
                list(person.torso_center) if person.torso_center is not None else None
            ),
            "association_type": person.association_type,
        }
