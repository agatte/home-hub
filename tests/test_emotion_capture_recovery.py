"""Focused lifecycle and semantic-health regressions for desktop face capture."""
from __future__ import annotations

import sys
from types import SimpleNamespace


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


def _empty_result():
    return SimpleNamespace(face_blendshapes=[])


def _usable_result():
    return SimpleNamespace(
        face_blendshapes=[
            [
                SimpleNamespace(category_name="_neutral", score=0.1),
                SimpleNamespace(category_name="mouthSmileLeft", score=0.7),
            ]
        ]
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
    agent.set_enabled(emotion=True)
    return agent


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
