"""Native OpenVINO YOLO26n-pose adapter for the #198 shadow bake-off.

This module intentionally imports OpenVINO only inside ``initialize()`` so the
normal HomeHub runtime has no dependency on the experimental model unless the
shadow challenger is explicitly enabled.  It emits only the privacy-light
``ShadowAdapterOutput`` contract; raw detections and keypoint arrays stay inside
the spawned shadow worker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import time
from typing import Any

from backend.services.camera_shadow import (
    KeypointSummary,
    NormalizedBox,
    ShadowAdapterOutput,
    ShadowFrameMetadata,
    ShadowPerson,
)


MODEL_ID = "yolo26n-pose-openvino-fp32-640"
MODEL_INPUT_SIZE = 640
MODEL_OUTPUT_ROWS = 300
MODEL_OUTPUT_COLUMNS = 57
KEYPOINT_COUNT = 17
NEAR_DUPLICATE_IOU_THRESHOLD = 0.95
SAME_BODY_IOU_THRESHOLD = 0.30
SAME_BODY_TORSO_DISTANCE_THRESHOLD = 0.03


@dataclass
class Yolo26OpenVinoPoseAdapter:
    """YOLO26n-pose challenger backed by native OpenVINO Runtime."""

    model_dir: str
    person_confidence_threshold: float = 0.05
    keypoint_confidence_threshold: float = 0.25
    max_persons: int = 10
    model_id: str = MODEL_ID
    _compiled_model: Any = field(init=False, default=None, repr=False)
    _output_port: Any = field(init=False, default=None, repr=False)
    _artifact_checksum: str | None = field(init=False, default=None, repr=False)
    _artifact_id: str | None = field(init=False, default=None, repr=False)

    def initialize(self) -> None:
        """Load and compile the exported model inside the spawned worker."""
        if not 0.0 <= self.person_confidence_threshold <= 1.0:
            raise ValueError("person_confidence_threshold must be between 0 and 1")
        if not 0.0 <= self.keypoint_confidence_threshold <= 1.0:
            raise ValueError("keypoint_confidence_threshold must be between 0 and 1")
        if self.max_persons < 1:
            raise ValueError("max_persons must be positive")

        model_dir = Path(self.model_dir)
        xml_path = model_dir / "yolo26n-pose.xml"
        bin_path = model_dir / "yolo26n-pose.bin"
        if not xml_path.is_file() or not bin_path.is_file():
            raise FileNotFoundError(f"YOLO26 OpenVINO IR not found under {model_dir}")

        try:
            from openvino import Core
        except ImportError as exc:  # dependency is optional unless challenger is enabled
            raise RuntimeError("OpenVINO Runtime is not installed") from exc

        core = Core()
        model = core.read_model(str(xml_path))
        input_shape = self._static_shape(model.input(0).partial_shape)
        output_shape = self._static_shape(model.output(0).partial_shape)
        if input_shape != (1, 3, MODEL_INPUT_SIZE, MODEL_INPUT_SIZE):
            raise ValueError(f"unexpected YOLO26 input shape: {input_shape}")
        if output_shape != (1, MODEL_OUTPUT_ROWS, MODEL_OUTPUT_COLUMNS):
            raise ValueError(f"unexpected YOLO26 output shape: {output_shape}")

        self._compiled_model = core.compile_model(model, "CPU")
        self._output_port = self._compiled_model.output(0)
        self._artifact_checksum = self._combined_checksum(xml_path, bin_path)
        self._artifact_id = f"{self.model_id}:{self._artifact_checksum[:12]}"

    def infer(self, frame: Any, metadata: ShadowFrameMetadata) -> ShadowAdapterOutput:
        """Shadow entry point; metadata does not affect model output."""
        del metadata
        return self.infer_frame(frame)

    def infer_frame(self, frame: Any) -> ShadowAdapterOutput:
        """Run one pose inference for shadow or authority consumers."""
        if self._compiled_model is None or self._output_port is None:
            raise RuntimeError("YOLO26 adapter has not been initialized")

        preprocess_started = time.perf_counter()
        tensor, transform = self._preprocess(frame)
        preprocess_ms = (time.perf_counter() - preprocess_started) * 1000.0

        inference_started = time.perf_counter()
        raw = self._compiled_model([tensor])[self._output_port]
        inference_ms = (time.perf_counter() - inference_started) * 1000.0

        postprocess_started = time.perf_counter()
        persons, max_confidence = self._postprocess(raw, transform)
        postprocess_ms = (time.perf_counter() - postprocess_started) * 1000.0

        return ShadowAdapterOutput(
            model_id=self.model_id,
            artifact_id=self._artifact_id or self.model_id,
            artifact_checksum=self._artifact_checksum,
            status="ok" if persons else "abstain",
            person_detected=bool(persons),
            person_count=len(persons),
            max_person_confidence=max_confidence,
            persons=tuple(persons),
            preprocess_ms=preprocess_ms,
            inference_ms=inference_ms,
            postprocess_ms=postprocess_ms,
        )

    @staticmethod
    def _static_shape(partial_shape: Any) -> tuple[int, ...]:
        return tuple(int(dim.get_length()) for dim in partial_shape)

    @staticmethod
    def _combined_checksum(xml_path: Path, bin_path: Path) -> str:
        digest = hashlib.sha256()
        for path in (xml_path, bin_path):
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _preprocess(frame: Any) -> tuple[Any, tuple[float, float, float, int, int]]:
        import cv2
        import numpy as np

        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("YOLO26 shadow input must be a BGR HxWx3 NumPy frame")
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            raise ValueError("YOLO26 shadow input frame is empty")

        scale = min(MODEL_INPUT_SIZE / width, MODEL_INPUT_SIZE / height)
        resized_width = max(1, round(width * scale))
        resized_height = max(1, round(height * scale))
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)

        pad_width = MODEL_INPUT_SIZE - resized_width
        pad_height = MODEL_INPUT_SIZE - resized_height
        left = round(pad_width / 2 - 0.1)
        right = round(pad_width / 2 + 0.1)
        top = round(pad_height / 2 - 0.1)
        bottom = round(pad_height / 2 + 0.1)
        letterboxed = cv2.copyMakeBorder(
            resized, top, bottom, left, right,
            cv2.BORDER_CONSTANT, value=(114, 114, 114),
        )

        rgb = letterboxed[..., ::-1].transpose(2, 0, 1)
        tensor = np.ascontiguousarray(rgb, dtype=np.float32) / 255.0
        tensor = tensor[None, ...]
        return tensor, (scale, float(left), float(top), width, height)

    def _postprocess(
        self,
        raw: Any,
        transform: tuple[float, float, float, int, int],
    ) -> tuple[list[ShadowPerson], float | None]:
        import numpy as np

        rows = np.asarray(raw, dtype=np.float32)
        expected_shape = (1, MODEL_OUTPUT_ROWS, MODEL_OUTPUT_COLUMNS)
        if rows.shape != expected_shape:
            raise ValueError(f"unexpected YOLO26 result shape: {rows.shape}")
        rows = rows[0]
        scores = rows[:, 4]
        finite_scores = scores[np.isfinite(scores)]
        max_confidence = float(finite_scores.max()) if finite_scores.size else None

        eligible = [
            row for row in rows
            if np.isfinite(row[4])
            and float(row[4]) >= self.person_confidence_threshold
            and int(round(float(row[5]))) == 0
        ]
        eligible.sort(key=lambda row: float(row[4]), reverse=True)

        scale, pad_x, pad_y, width, height = transform
        persons: list[ShadowPerson] = []
        for row in eligible:
            box = self._normalize_box(row[:4], scale, pad_x, pad_y, width, height)
            if box is None:
                continue
            keypoints = row[6:].reshape(KEYPOINT_COUNT, 3)
            confidences = keypoints[:, 2]
            available = np.isfinite(confidences) & (
                confidences >= self.keypoint_confidence_threshold
            )
            available_count = int(available.sum())
            mean_confidence = (
                float(confidences[available].mean()) if available_count else None
            )
            torso_center = self._torso_center(
                keypoints, scale, pad_x, pad_y, width, height,
            )
            if any(
                self._is_same_body_duplicate(box, torso_center, existing)
                for existing in persons
            ):
                continue

            persons.append(ShadowPerson(
                bbox=box,
                keypoints=KeypointSummary(
                    available_count=available_count,
                    mean_confidence=mean_confidence,
                ),
                confidence=float(row[4]),
                torso_center=torso_center,
                association_type="native_pose_instance",
            ))
            if len(persons) >= self.max_persons:
                break
        return persons, max_confidence

    @classmethod
    def _is_same_body_duplicate(
        cls,
        box: NormalizedBox,
        torso_center: tuple[float, float] | None,
        existing: ShadowPerson,
    ) -> bool:
        overlap = cls._box_iou(box, existing.bbox)
        if overlap >= NEAR_DUPLICATE_IOU_THRESHOLD:
            return True
        if (
            overlap < SAME_BODY_IOU_THRESHOLD
            or torso_center is None
            or existing.torso_center is None
        ):
            return False
        dx = torso_center[0] - existing.torso_center[0]
        dy = torso_center[1] - existing.torso_center[1]
        return (dx * dx + dy * dy) ** 0.5 <= SAME_BODY_TORSO_DISTANCE_THRESHOLD

    @staticmethod
    def _box_iou(a: NormalizedBox, b: NormalizedBox) -> float:
        ax1 = a.center_x - a.width / 2.0
        ay1 = a.center_y - a.height / 2.0
        ax2 = a.center_x + a.width / 2.0
        ay2 = a.center_y + a.height / 2.0
        bx1 = b.center_x - b.width / 2.0
        by1 = b.center_y - b.height / 2.0
        bx2 = b.center_x + b.width / 2.0
        by2 = b.center_y + b.height / 2.0
        inter_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        inter_h = max(0.0, min(ay2, by2) - max(ay1, by1))
        inter = inter_w * inter_h
        union = a.width * a.height + b.width * b.height - inter
        return inter / union if union > 0.0 else 0.0

    @classmethod
    def _normalize_box(
        cls,
        raw_box: Any,
        scale: float,
        pad_x: float,
        pad_y: float,
        width: int,
        height: int,
    ) -> NormalizedBox | None:
        x1 = cls._clip(float((raw_box[0] - pad_x) / scale), 0.0, float(width))
        y1 = cls._clip(float((raw_box[1] - pad_y) / scale), 0.0, float(height))
        x2 = cls._clip(float((raw_box[2] - pad_x) / scale), 0.0, float(width))
        y2 = cls._clip(float((raw_box[3] - pad_y) / scale), 0.0, float(height))
        if x2 <= x1 or y2 <= y1:
            return None
        return NormalizedBox(
            center_x=((x1 + x2) / 2.0) / width,
            center_y=((y1 + y2) / 2.0) / height,
            width=(x2 - x1) / width,
            height=(y2 - y1) / height,
        )

    def _torso_center(
        self,
        keypoints: Any,
        scale: float,
        pad_x: float,
        pad_y: float,
        width: int,
        height: int,
    ) -> tuple[float, float] | None:
        import numpy as np

        torso_indices = (5, 6, 11, 12)  # shoulders + hips in COCO-17 order
        usable: list[tuple[float, float]] = []
        for index in torso_indices:
            x, y, confidence = keypoints[index]
            if not np.isfinite(confidence) or confidence < self.keypoint_confidence_threshold:
                continue
            original_x = self._clip(float((x - pad_x) / scale), 0.0, float(width))
            original_y = self._clip(float((y - pad_y) / scale), 0.0, float(height))
            usable.append((original_x / width, original_y / height))
        if len(usable) < 2:
            return None
        return (
            sum(point[0] for point in usable) / len(usable),
            sum(point[1] for point in usable) / len(usable),
        )

    @staticmethod
    def _clip(value: float, lower: float, upper: float) -> float:
        return min(max(value, lower), upper)
