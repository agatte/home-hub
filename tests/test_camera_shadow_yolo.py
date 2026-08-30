"""Focused tests for the native OpenVINO YOLO26n-pose shadow adapter."""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path

import numpy as np
import pytest

from backend.config import settings
from backend.services.camera_service import CameraService
from backend.services.camera_shadow import ShadowFrameMetadata
from backend.services.camera_shadow_capture import JsonlShadowResultSink
from backend.services.camera_shadow_yolo import (
    MODEL_OUTPUT_COLUMNS,
    MODEL_OUTPUT_ROWS,
    Yolo26OpenVinoPoseAdapter,
)


def _metadata() -> ShadowFrameMetadata:
    return ShadowFrameMetadata(
        run_id="test-yolo",
        frame_seq=1,
        captured_at=datetime.now(timezone.utc),
        width=640,
        height=480,
    )


def _raw_output() -> np.ndarray:
    return np.zeros((1, MODEL_OUTPUT_ROWS, MODEL_OUTPUT_COLUMNS), dtype=np.float32)


def test_yolo_registration_is_still_gated_by_bakeoff(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_SHADOW_BAKEOFF_ENABLED", False)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_ENABLED", True)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_MODEL_PATH", "unused")
    service = CameraService(object(), object())
    assert service._shadow_coordinator is None


def test_yolo_registration_is_lazy_and_import_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "CAMERA_SHADOW_BAKEOFF_ENABLED", True)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_ENABLED", True)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_MODEL_PATH", "C:/models/yolo26")
    monkeypatch.setattr(settings, "CAMERA_SHADOW_CAPTURE_LABEL", "unit-test")
    monkeypatch.setattr(settings, "CAMERA_SHADOW_CAPTURE_DIR", str(tmp_path))
    service = CameraService(object(), object())
    coordinator = service._shadow_coordinator
    assert coordinator is not None
    assert len(coordinator._adapters) == 1
    assert isinstance(coordinator._adapters[0], Yolo26OpenVinoPoseAdapter)
    assert isinstance(coordinator._sink, JsonlShadowResultSink)
    assert not coordinator.worker_alive


def test_yolo_without_explicit_capture_label_registers_no_adapter(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_SHADOW_BAKEOFF_ENABLED", True)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_ENABLED", True)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_MODEL_PATH", "C:/models/yolo26")
    monkeypatch.setattr(settings, "CAMERA_SHADOW_CAPTURE_LABEL", "")
    service = CameraService(object(), object())
    assert service._shadow_coordinator is not None
    assert service._shadow_coordinator._adapters == ()

def test_yolo_enabled_without_model_path_registers_no_adapter(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_SHADOW_BAKEOFF_ENABLED", True)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_ENABLED", True)
    monkeypatch.setattr(settings, "CAMERA_SHADOW_YOLO_MODEL_PATH", "")
    service = CameraService(object(), object())
    assert service._shadow_coordinator is not None
    assert service._shadow_coordinator._adapters == ()

def test_preprocess_letterboxes_640x480_without_distortion():
    adapter = Yolo26OpenVinoPoseAdapter("unused")
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    tensor, transform = adapter._preprocess(frame)
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    assert transform == (1.0, 0.0, 80.0, 640, 480)
    assert np.allclose(tensor[:, :, :80, :], 114.0 / 255.0)


def test_postprocess_recovers_original_normalized_geometry():
    adapter = Yolo26OpenVinoPoseAdapter("unused")
    raw = _raw_output()
    row = raw[0, 0]
    row[:6] = [160.0, 200.0, 480.0, 500.0, 0.8, 0.0]
    keypoints = row[6:].reshape(17, 3)
    for index, x, y in (
        (5, 200.0, 280.0),
        (6, 440.0, 280.0),
        (11, 240.0, 440.0),
        (12, 400.0, 440.0),
    ):
        keypoints[index] = [x, y, 0.9]

    persons, max_confidence = adapter._postprocess(
        raw, (1.0, 0.0, 80.0, 640, 480),
    )
    assert max_confidence == pytest.approx(0.8)
    assert len(persons) == 1

    person = persons[0]
    assert person.confidence == pytest.approx(0.8)
    assert person.bbox.center_x == pytest.approx(0.5)
    assert person.bbox.center_y == pytest.approx(0.5625)
    assert person.bbox.width == pytest.approx(0.5)
    assert person.bbox.height == pytest.approx(0.625)
    assert person.keypoints.available_count == 4
    assert person.keypoints.mean_confidence == pytest.approx(0.9)
    assert person.torso_center == pytest.approx((0.5, 280.0 / 480.0))
    assert person.association_type == "native_pose_instance"


def test_postprocess_suppresses_near_duplicate_rows_but_keeps_distinct_people():
    adapter = Yolo26OpenVinoPoseAdapter("unused")
    raw = _raw_output()
    raw[0, 0, :6] = [100.0, 180.0, 300.0, 500.0, 0.9, 0.0]
    raw[0, 1, :6] = [101.0, 181.0, 301.0, 501.0, 0.8, 0.0]
    raw[0, 2, :6] = [360.0, 180.0, 520.0, 500.0, 0.7, 0.0]
    persons, max_confidence = adapter._postprocess(
        raw, (1.0, 0.0, 80.0, 640, 480),
    )
    assert max_confidence == pytest.approx(0.9)
    assert len(persons) == 2
    assert [person.confidence for person in persons] == pytest.approx([0.9, 0.7])


def _set_torso(row, x: float, y: float) -> None:
    keypoints = row[6:].reshape(17, 3)
    for index in (5, 6, 11, 12):
        keypoints[index] = [x, y, 0.9]


def test_postprocess_suppresses_horizontal_same_body_duplicates():
    adapter = Yolo26OpenVinoPoseAdapter("unused")
    raw = _raw_output()
    raw[0, 0, :6] = [100.0, 180.0, 500.0, 500.0, 0.9, 0.0]
    raw[0, 1, :6] = [200.0, 180.0, 600.0, 500.0, 0.8, 0.0]
    _set_torso(raw[0, 0], 320.0, 320.0)
    _set_torso(raw[0, 1], 326.0, 324.0)
    persons, _ = adapter._postprocess(raw, (1.0, 0.0, 80.0, 640, 480))
    assert len(persons) == 1
    assert persons[0].confidence == pytest.approx(0.9)


def test_postprocess_keeps_overlapping_people_with_distinct_torsos():
    adapter = Yolo26OpenVinoPoseAdapter("unused")
    raw = _raw_output()
    raw[0, 0, :6] = [100.0, 180.0, 500.0, 500.0, 0.9, 0.0]
    raw[0, 1, :6] = [200.0, 180.0, 600.0, 500.0, 0.8, 0.0]
    _set_torso(raw[0, 0], 250.0, 320.0)
    _set_torso(raw[0, 1], 450.0, 320.0)
    persons, _ = adapter._postprocess(raw, (1.0, 0.0, 80.0, 640, 480))
    assert len(persons) == 2


def test_postprocess_preserves_max_confidence_when_abstaining():
    adapter = Yolo26OpenVinoPoseAdapter(
        "unused", person_confidence_threshold=0.2,
    )
    raw = _raw_output()
    raw[0, 0, 4] = 0.17
    persons, max_confidence = adapter._postprocess(
        raw, (1.0, 0.0, 80.0, 640, 480),
    )
    assert persons == []
    assert max_confidence == pytest.approx(0.17)


def test_invalid_box_is_not_persisted_as_person():
    adapter = Yolo26OpenVinoPoseAdapter("unused")
    raw = _raw_output()
    raw[0, 0, :6] = [500.0, 200.0, 400.0, 300.0, 0.9, 0.0]
    persons, max_confidence = adapter._postprocess(
        raw, (1.0, 0.0, 80.0, 640, 480),
    )
    assert persons == []
    assert max_confidence == pytest.approx(0.9)


def test_initialize_requires_expected_ir_files(tmp_path: Path):
    adapter = Yolo26OpenVinoPoseAdapter(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        adapter.initialize()


def test_combined_checksum_is_stable(tmp_path: Path):
    xml_path = tmp_path / "yolo26n-pose.xml"
    bin_path = tmp_path / "yolo26n-pose.bin"
    xml_path.write_bytes(b"xml")
    bin_path.write_bytes(b"bin")
    first = Yolo26OpenVinoPoseAdapter._combined_checksum(xml_path, bin_path)
    second = Yolo26OpenVinoPoseAdapter._combined_checksum(xml_path, bin_path)
    assert first == second
    assert len(first) == 64


def test_real_openvino_model_smoke_when_explicitly_available():
    model_dir = os.environ.get("HOMEHUB_TEST_YOLO26_OPENVINO_MODEL")
    if not model_dir:
        pytest.skip("real YOLO26 OpenVINO artifact not supplied")
    pytest.importorskip("openvino")

    adapter = Yolo26OpenVinoPoseAdapter(model_dir)
    adapter.initialize()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    result = adapter.infer(frame, _metadata())
    assert result.model_id == adapter.model_id
    assert result.artifact_checksum is not None
    assert len(result.artifact_checksum) == 64
    assert result.status in {"ok", "abstain"}
    assert result.person_count == len(result.persons)
    assert result.max_person_confidence is not None
