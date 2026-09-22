"""Focused lifecycle and semantic-health regressions for desktop face capture."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np


class _Frame:
    def __init__(self, mean: float):
        self._mean = mean

    def mean(self):
        return self._mean


class _Cap:
    def __init__(self, *, reads: list[tuple[bool, object | None]] | None = None):
        self._reads = reads or [(True, object())]
        self.release_calls = 0

    def read(self):
        if len(self._reads) > 1:
            return self._reads.pop(0)
        return self._reads[0]

    def release(self):
        self.release_calls += 1


class _Landmarker:
    def __init__(self, results):
        self._results = list(results)
        self.close_calls = 0

    def detect(self, _image):
        result = self._results.pop(0) if len(self._results) > 1 else self._results[0]
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.close_calls += 1


class _FaceDetector:
    def __init__(self, detections):
        self._detections = detections
        self.close_calls = 0

    def detect(self, _image):
        return SimpleNamespace(detections=self._detections)

    def close(self):
        self.close_calls += 1


def _empty_result():
    return SimpleNamespace(face_blendshapes=[], face_landmarks=[])


def _usable_result():
    return SimpleNamespace(
        face_blendshapes=[
            [
                SimpleNamespace(category_name="_neutral", score=0.1),
                SimpleNamespace(category_name="mouthSmileLeft", score=0.7),
            ]
        ],
        face_landmarks=[[
            SimpleNamespace(x=0.40),
            SimpleNamespace(x=0.60),
        ]],
    )


def _neutral_face_result():
    return SimpleNamespace(
        face_blendshapes=[
            [
                SimpleNamespace(category_name="_neutral", score=0.2),
                SimpleNamespace(category_name="mouthSmileLeft", score=0.258),
            ]
        ],
        face_landmarks=[[
            SimpleNamespace(x=0.40),
            SimpleNamespace(x=0.60),
        ]],
    )


def _configure_tick_fakes(monkeypatch, agent):
    class Image:
        def __init__(self, **_kwargs):
            pass

    mp = SimpleNamespace(
        Image=Image,
        ImageFormat=SimpleNamespace(SRGB="srgb"),
    )
    cv2 = SimpleNamespace(
        COLOR_BGR2RGB=1,
        COLOR_BGR2GRAY=2,
        cvtColor=lambda frame, _code: frame,
    )
    monkeypatch.setitem(sys.modules, "mediapipe", mp)
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setattr(agent, "_maybe_upload_snapshot", lambda **_kwargs: None)
    monkeypatch.setattr(agent, "_post_blendshapes", lambda *_args, **_kwargs: None)


def _agent(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = ec.EmotionCapture("http://test:8000")
    _configure_tick_fakes(monkeypatch, agent)
    # Existing recovery tests exercise FaceLandmarker lifecycle in isolation.
    # Tests that need temporal burst/full-range fallback override explicitly.
    monkeypatch.setattr(ec, "FACE_MISS_BURST_RETRIES", 0)
    monkeypatch.setattr(ec, "_init_face_detector", lambda: None)
    agent.set_enabled(emotion=True)
    return agent


def test_segmenter_presence_requires_dwell_and_debounces_single_dip():
    from backend.services.pc_agent import emotion_capture as ec

    agent = ec.EmotionCapture("http://test:8000")
    try:
        assert agent._update_segmenter_candidate(True) is None
        assert agent._update_segmenter_candidate(True) is None
        assert agent._update_segmenter_candidate(True) is True
        # One weak frame cannot demote established human presence.
        assert agent._update_segmenter_candidate(False) is True
        assert agent._update_segmenter_candidate(True) is True
        # Five consecutive negatives are required to demote it.
        assert agent._update_segmenter_candidate(False) is True
        assert agent._update_segmenter_candidate(False) is True
        assert agent._update_segmenter_candidate(False) is True
        assert agent._update_segmenter_candidate(False) is True
        assert agent._update_segmenter_candidate(False) is False
    finally:
        agent.close()


def test_segmenter_shape_gate_accepts_person_and_rejects_chair_geometry():
    from backend.services.pc_agent import emotion_capture as ec

    class Mask:
        def __init__(self, array):
            self._array = array

        def numpy_view(self):
            return self._array

    def result_for(array):
        return SimpleNamespace(confidence_masks=[Mask(array)])

    agent = ec.EmotionCapture("http://test:8000")
    try:
        person = np.zeros((8, 8), dtype=np.float32)
        person[2:, 1:7] = 1.0
        agent._person_segmenter = SimpleNamespace(
            segment=lambda _image: result_for(person)
        )
        assert agent._detect_segmented_person(object())[0] is None
        assert agent._detect_segmented_person(object())[0] is None
        assert agent._detect_segmented_person(object())[0] is True

        chair = np.zeros((8, 8), dtype=np.float32)
        chair[5:, :4] = 1.0
        agent._person_segmenter = SimpleNamespace(
            segment=lambda _image: result_for(chair)
        )
        for _ in range(4):
            assert agent._detect_segmented_person(object())[0] is True
        assert agent._detect_segmented_person(object())[0] is False
    finally:
        agent.close()


def test_segmenter_fallback_posts_presence_without_inventing_desk(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    agent.set_enabled(presence=True)
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: _Landmarker([_empty_result()]))
    monkeypatch.setattr(agent, "_landmark_haar_face_crop", lambda **_kwargs: (None, None))
    monkeypatch.setattr(agent, "_detect_pose_landmarks", lambda _image: None)
    monkeypatch.setattr(agent, "_detect_segmented_person", lambda _image: (True, 0.35))
    posts = []
    monkeypatch.setattr(agent, "_post_observation", lambda **kwargs: posts.append(kwargs))
    agent._cap = _Cap()
    try:
        agent.tick()
        assert len(posts) == 1
        assert posts[0]["face_present"] is True
        assert posts[0]["face_confidence"] == 0.0
        assert posts[0]["detection_source"] == "segmenter"
        assert posts[0]["zone"] is None
        assert posts[0]["posture"] is None
    finally:
        agent.close()


def test_segmenter_startup_ambiguity_abstains_instead_of_posting_absence(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    agent.set_enabled(presence=True)
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: _Landmarker([_empty_result()]))
    monkeypatch.setattr(agent, "_landmark_haar_face_crop", lambda **_kwargs: (None, None))
    monkeypatch.setattr(agent, "_detect_pose_landmarks", lambda _image: None)
    monkeypatch.setattr(agent, "_detect_segmented_person", lambda _image: (None, 0.31))
    posts = []
    monkeypatch.setattr(agent, "_post_observation", lambda **kwargs: posts.append(kwargs))
    agent._cap = _Cap()
    try:
        agent.tick()
        assert posts == []
    finally:
        agent.close()


def test_sleeping_boundary_discards_landmarker_before_next_active_tick(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    created = []

    def init():
        landmarker = _Landmarker([_empty_result()])
        created.append(landmarker)
        return landmarker

    monkeypatch.setattr(ec, "_init_face_landmarker", init)
    first_cap = _Cap()
    second_cap = _Cap()
    agent._cap = first_cap
    try:
        agent.tick()
        agent.set_mode_sleeping(True)
        agent.tick()

        assert created[0].close_calls == 1
        assert agent._landmarker is None
        assert first_cap.release_calls == 1

        agent.set_mode_sleeping(False)
        agent._cap = second_cap
        agent.tick()
        assert len(created) == 2
        assert created[1] is agent._landmarker
    finally:
        agent.close()


def test_capture_reacquisition_discards_old_landmarker(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    created = []

    def init():
        landmarker = _Landmarker([_empty_result()])
        created.append(landmarker)
        return landmarker

    monkeypatch.setattr(ec, "_init_face_landmarker", init)
    failed_cap = _Cap(reads=[(False, None)])
    recovered_cap = _Cap()
    agent._cap = failed_cap
    try:
        agent.tick()
        assert created[0].close_calls == 1
        assert failed_cap.release_calls == 1

        agent._cap = recovered_cap
        agent.tick()
        assert len(created) == 2
        assert agent._landmarker is created[1]
    finally:
        agent.close()


def test_zero_face_streak_recycles_only_landmarker_and_respects_cooldown(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    monkeypatch.setattr(ec, "FACE_SEMANTIC_DEAD_STREAK_LIMIT", 3)
    monkeypatch.setattr(ec, "FACE_SEMANTIC_RECOVERY_COOLDOWN_S", 60.0)
    monkeypatch.setattr(ec.time, "monotonic", lambda: 100.0)
    agent = _agent(monkeypatch)
    created = []

    def init():
        landmarker = _Landmarker([_empty_result()])
        created.append(landmarker)
        return landmarker

    monkeypatch.setattr(ec, "_init_face_landmarker", init)
    cap = _Cap()
    agent._cap = cap
    try:
        for _ in range(3):
            agent.tick()
        assert created[0].close_calls == 1
        assert cap.release_calls == 0

        # The next active tick creates one replacement. Its continued misses
        # reach the threshold but the same monotonic time holds the cooldown.
        for _ in range(3):
            agent.tick()
        assert len(created) == 2
        assert created[1].close_calls == 0
        assert cap.release_calls == 0
    finally:
        agent.close()


def test_detect_exceptions_do_not_advance_semantic_dead_streak(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    monkeypatch.setattr(ec, "FACE_SEMANTIC_DEAD_STREAK_LIMIT", 3)
    agent = _agent(monkeypatch)
    landmarker = _Landmarker([RuntimeError("detect failed")])
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: landmarker)
    agent._cap = _Cap()
    try:
        for _ in range(4):
            agent.tick()
        assert landmarker.close_calls == 0
        assert agent._face_semantic_dead_streak == 0
    finally:
        agent.close()


def test_usable_face_resets_semantic_dead_streak(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    monkeypatch.setattr(ec, "FACE_SEMANTIC_DEAD_STREAK_LIMIT", 3)
    agent = _agent(monkeypatch)
    landmarker = _Landmarker(
        [_empty_result(), _empty_result(), _usable_result(), _empty_result()]
    )
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: landmarker)
    agent._cap = _Cap()
    try:
        for _ in range(4):
            agent.tick()
        assert landmarker.close_calls == 0
        assert agent._face_semantic_dead_streak == 1
    finally:
        agent.close()


def test_neutral_face_landmarks_are_present_without_expression_threshold(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    agent.set_enabled(presence=True)
    landmarker = _Landmarker([_neutral_face_result()])
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: landmarker)
    monkeypatch.setattr(agent, "_detect_pose_landmarks", lambda _image: None)
    observations = []
    monkeypatch.setattr(
        agent, "_post_observation", lambda **kwargs: observations.append(kwargs)
    )
    agent._cap = _Cap()
    try:
        agent.tick()
        assert len(observations) == 1
        assert observations[0]["face_present"] is True
        assert observations[0]["face_confidence"] == 1.0
        assert agent._face_semantic_dead_streak == 0
        assert landmarker.close_calls == 0
    finally:
        agent.close()


def test_short_burst_recovers_intermittent_full_frame_face(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    monkeypatch.setattr(ec.time, "sleep", lambda _seconds: None)
    agent = _agent(monkeypatch)
    monkeypatch.setattr(ec, "FACE_MISS_BURST_RETRIES", 2)
    agent.set_enabled(presence=True)
    landmarker = _Landmarker([_empty_result(), _usable_result()])
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: landmarker)
    monkeypatch.setattr(agent, "_detect_pose_landmarks", lambda _image: None)
    observations = []
    monkeypatch.setattr(
        agent, "_post_observation", lambda **kwargs: observations.append(kwargs)
    )
    agent._cap = _Cap(
        reads=[
            (True, np.zeros((480, 640, 3), dtype=np.uint8)),
            (True, np.ones((480, 640, 3), dtype=np.uint8)),
        ]
    )
    try:
        agent.tick()
        assert len(observations) == 1
        assert observations[0]["face_present"] is True
        assert observations[0]["face_confidence"] == 1.0
        assert observations[0]["detection_source"] == "face"
        assert observations[0]["zone"] == "desk"
        assert agent._face_semantic_dead_streak == 0
    finally:
        agent.close()


def test_full_range_fallback_recovers_profile_face_and_blendshapes(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    agent.set_enabled(presence=True)
    landmarker = _Landmarker([_empty_result(), _usable_result()])
    detection = SimpleNamespace(
        categories=[SimpleNamespace(score=0.66)],
        bounding_box=SimpleNamespace(
            origin_x=254, origin_y=198, width=254, height=254,
        ),
    )
    detector = _FaceDetector([detection])
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: landmarker)
    monkeypatch.setattr(ec, "_init_face_detector", lambda: detector)
    monkeypatch.setattr(agent, "_detect_pose_landmarks", lambda _image: None)
    observations = []
    blendshape_posts = []
    monkeypatch.setattr(
        agent, "_post_observation", lambda **kwargs: observations.append(kwargs)
    )
    monkeypatch.setattr(
        agent,
        "_post_blendshapes",
        lambda shapes, confidence, **kwargs: blendshape_posts.append(
            (shapes, confidence)
        ),
    )
    agent._cap = _Cap(
        reads=[(True, np.zeros((480, 640, 3), dtype=np.uint8))]
    )
    try:
        agent.tick()
        assert len(observations) == 1
        assert observations[0]["face_present"] is True
        assert observations[0]["face_confidence"] == 0.66
        assert observations[0]["detection_source"] == "face"
        assert observations[0]["zone"] == "desk"
        assert len(blendshape_posts) == 1
        assert agent._face_semantic_dead_streak == 0
        assert landmarker.close_calls == 0
    finally:
        agent.close()


def test_haar_roi_fallback_requires_mediapipe_validation_and_preserves_desk_width(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    agent.set_enabled(presence=True)
    landmarker = _Landmarker([_empty_result()])
    detector = _FaceDetector([])
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: landmarker)
    monkeypatch.setattr(ec, "_init_face_detector", lambda: detector)
    monkeypatch.setattr(
        agent,
        "_landmark_haar_face_crop",
        lambda **_kwargs: (_usable_result(), ec.DESKTOP_DESK_MIN_FACE_WIDTH + 0.03),
    )
    monkeypatch.setattr(agent, "_detect_pose_landmarks", lambda _image: None)
    observations = []
    blendshape_posts = []
    monkeypatch.setattr(
        agent, "_post_observation", lambda **kwargs: observations.append(kwargs)
    )
    monkeypatch.setattr(
        agent,
        "_post_blendshapes",
        lambda shapes, confidence, **kwargs: blendshape_posts.append(
            (shapes, confidence)
        ),
    )
    agent._cap = _Cap(
        reads=[(True, np.zeros((480, 640, 3), dtype=np.uint8))]
    )
    try:
        agent.tick()
        assert len(observations) == 1
        assert observations[0]["face_present"] is True
        assert observations[0]["face_confidence"] == 1.0
        assert observations[0]["detection_source"] == "face"
        assert observations[0]["zone"] == "desk"
        assert len(blendshape_posts) == 1
        assert agent._face_semantic_dead_streak == 0
    finally:
        agent.close()


def test_lux_reopen_gate_blocks_dark_actual_frame_then_allows_second_bright(monkeypatch):
    from backend.services.pc_agent import emotion_capture as ec

    agent = _agent(monkeypatch)
    agent.set_enabled(presence=True)
    landmarker = _Landmarker([_empty_result()])
    monkeypatch.setattr(ec, "_init_face_landmarker", lambda: landmarker)
    monkeypatch.setattr(agent, "_detect_pose_landmarks", lambda _image: None)
    posts = []
    monkeypatch.setattr(agent, "_post_observation", lambda **kwargs: posts.append(kwargs))
    agent._cap = _Cap(reads=[
        (True, _Frame(2.0)),
        (True, _Frame(12.0)),
        (True, _Frame(13.0)),
    ])
    agent._lux_reopen_reference_mean = 24.5
    try:
        agent.tick()
        assert posts == []
        assert agent._lux_reopen_reference_mean == 24.5

        agent.tick()
        assert posts == []
        assert agent._lux_reopen_ready_streak == 1

        agent.tick()
        assert len(posts) == 1
        assert posts[0]["face_present"] is False
        assert posts[0]["zone"] is None
        assert agent._lux_reopen_reference_mean is None
    finally:
        agent.close()


def test_capture_inactive_clears_lux_reopen_recovery(monkeypatch):
    agent = _agent(monkeypatch)
    agent._cap = _Cap()
    agent._lux_reopen_reference_mean = 42.0
    agent._lux_reopen_started_at = 100.0
    agent._lux_reopen_ready_streak = 1
    agent._lux_reopen_recycle_count = 1
    agent._lux_reopen_exhausted = True
    try:
        agent.set_enabled(emotion=False, presence=False)
        agent.tick()
        assert agent._cap is None
        assert agent._lux_reopen_reference_mean is None
        assert agent._lux_reopen_started_at is None
        assert agent._lux_reopen_ready_streak == 0
        assert agent._lux_reopen_recycle_count == 0
        assert agent._lux_reopen_exhausted is False
    finally:
        agent.close()
