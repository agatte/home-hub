"""Tests for explicit derived-only camera shadow JSONL capture."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from backend.services.camera_shadow import (
    KeypointSummary,
    NormalizedBox,
    ShadowFrameMetadata,
    ShadowPerson,
    ShadowResult,
)
from backend.services.camera_shadow_capture import JsonlShadowResultSink


def _result(frame_seq: int = 1) -> ShadowResult:
    metadata = ShadowFrameMetadata(
        run_id="capture-test",
        frame_seq=frame_seq,
        captured_at=datetime.now(timezone.utc),
        width=640,
        height=480,
    )
    person = ShadowPerson(
        bbox=NormalizedBox(0.5, 0.6, 0.3, 0.5),
        keypoints=KeypointSummary(12, 0.88),
        confidence=0.91,
        torso_center=(0.51, 0.62),
        association_type="native_pose_instance",
    )
    return ShadowResult(
        metadata=metadata,
        model_id="yolo26n-pose-openvino-fp32-640",
        artifact_id="artifact:test",
        artifact_checksum="a" * 64,
        status="ok",
        person_detected=True,
        person_count=1,
        max_person_confidence=0.91,
        persons=(person,),
        preprocess_ms=5.0,
        inference_ms=20.0,
        postprocess_ms=1.0,
        total_ms=26.0,
        worker_init_ms=100.0,
        queue_handoff_ms=3.0,
        end_to_end_ms=130.0,
        tracking_summary=None,
    )


def test_capture_requires_usable_label_and_positive_cap(tmp_path):
    with pytest.raises(ValueError):
        JsonlShadowResultSink(" !!! ", str(tmp_path))
    with pytest.raises(ValueError):
        JsonlShadowResultSink("normal-couch", str(tmp_path), max_records=0)


def test_capture_writes_derived_json_and_enforces_cap(tmp_path):
    sink = JsonlShadowResultSink(
        "normal couch / bright-white", str(tmp_path), max_records=2,
    )
    sink.accept(_result(1))
    sink.accept(_result(2))
    sink.accept(_result(3))

    lines = sink.path.read_text(encoding="utf-8").splitlines()
    assert sink.records_written == 2
    assert sink.full
    assert len(lines) == 2
    payloads = [json.loads(line) for line in lines]
    assert [payload["frame_seq"] for payload in payloads] == [1, 2]
    assert all(payload["capture_label"] == "normal couch / bright-white" for payload in payloads)

    person = payloads[0]["persons"][0]
    assert person["confidence"] == pytest.approx(0.91)
    assert person["bbox"]["center_x"] == pytest.approx(0.5)
    assert person["keypoints"]["available_count"] == 12
    assert person["torso_center"] == pytest.approx([0.51, 0.62])


def test_capture_schema_has_no_raw_image_or_landmark_fields(tmp_path):
    sink = JsonlShadowResultSink("privacy-check", str(tmp_path))
    sink.accept(_result())
    text = sink.path.read_text(encoding="utf-8").lower()
    for forbidden in ("frame_bytes", "image", "crop", "tensor", "raw_landmark", "image_hash"):
        assert forbidden not in text


def test_capture_filename_uses_sanitized_label(tmp_path):
    sink = JsonlShadowResultSink("normal couch / ember", str(tmp_path))
    assert "normal-couch-ember" in sink.path.name
    assert sink.path.suffix == ".jsonl"
    assert sink.path.parent == tmp_path
