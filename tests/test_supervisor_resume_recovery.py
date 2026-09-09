"""Focused suspend timing and detached-process recovery tests."""

from backend.services.pc_agent.supervisor import (
    AgentState,
    AgentSupervisor,
    SuspendAwareRuntimeClock,
    _agent_hung,
)
from backend.services.pc_agent.supervisor_recovery import (
    FileBreadcrumbs,
    IdentityInspection,
    ProcessIdentity,
    TerminationResult,
    recover_supervisor,
)


class _Clock:
    def __init__(self, runtime, wall):
        self.runtime = iter(runtime)
        self.wall = iter(wall)

    def r(self):
        return next(self.runtime)

    def w(self):
        return next(self.wall)


def test_four_hours_of_wall_sleep_does_not_age_heartbeat():
    c = _Clock([10.0, 10.0], [100.0, 14_500.0])
    clock = SuspendAwareRuntimeClock(c.r, c.w)
    assert clock.sample() == (10.0, False)
    now, resumed = clock.sample()
    state = AgentState(
        "a", lambda: None, heartbeat_timeout=60, heartbeat_wired=True, last_progress_at=10,
    )
    assert resumed and not _agent_hung(state, now)


def test_active_runtime_timeout_remains_a_true_hang():
    state = AgentState(
        "a", lambda: None, heartbeat_timeout=60, heartbeat_wired=True, last_progress_at=10,
    )
    assert _agent_hung(state, 71)


class _SampleClock:
    def __init__(self, samples):
        self.samples = iter(samples)

    def sample(self):
        return next(self.samples)


def _supervisor_clock_subject(samples):
    supervisor = object.__new__(AgentSupervisor)
    supervisor._clock = _SampleClock(samples)
    supervisor._resume_grace_until = 0.0
    supervisor._resume_detection_armed = True
    return supervisor


def test_repeated_forward_wall_jumps_do_not_extend_active_grace():
    supervisor = _supervisor_clock_subject([(10.0, True), (11.0, True), (20.0, True)])
    assert supervisor._active_now() == 10.0
    original_deadline = supervisor._resume_grace_until
    supervisor._active_now()
    supervisor._active_now()
    assert supervisor._resume_grace_until == original_deadline == 25.0


def test_later_resume_can_rearm_after_grace_and_normal_monitoring():
    supervisor = _supervisor_clock_subject([(10.0, True), (26.0, False), (30.0, True)])
    supervisor._active_now()
    assert supervisor._resume_grace_until == 25.0
    supervisor._active_now()
    supervisor._active_now()
    assert supervisor._resume_grace_until == 45.0


def test_repeated_wall_corrections_cannot_hide_active_runtime_hang():
    supervisor = _supervisor_clock_subject(
        [(0.0, True), (10.0, True), (20.0, True), (40.0, True), (70.0, True)],
    )
    times = [supervisor._active_now() for _ in range(5)]
    state = AgentState(
        "a", lambda: None, heartbeat_timeout=60, heartbeat_wired=True, last_progress_at=1,
    )
    assert supervisor._resume_grace_until == 15.0
    assert times[-1] >= supervisor._resume_grace_until
    assert _agent_hung(state, times[-1])


class _Ops:
    def __init__(
        self,
        inspections,
        termination=TerminationResult.TERMINATED,
        launch_error=None,
    ):
        self.inspections = list(inspections)
        self.last_inspection = self.inspections[-1]
        self.termination = termination
        self.launch_error = launch_error
        self.termination_requests = []
        self.killed_identities = []
        self.kicks = 0

    def inspect_identity(self, identity):
        if self.inspections:
            self.last_inspection = self.inspections.pop(0)
        return self.last_inspection

    def terminate_exact(self, identity):
        self.termination_requests.append(identity)
        if self.termination is TerminationResult.TERMINATED:
            self.killed_identities.append(identity)
        return self.termination

    def kick_canonical_launcher(self):
        self.kicks += 1
        if self.launch_error:
            raise self.launch_error


class _Breadcrumbs:
    def __init__(self):
        self.rows = []

    def write(self, *row):
        self.rows.append(row)

    @property
    def stages(self):
        return [row[1] for row in self.rows]


def _recover(old, ops, crumbs, verify_seconds=0):
    ticks = iter(range(100))
    return recover_supervisor(
        old,
        ops,
        crumbs,
        grace_seconds=0,
        verify_seconds=verify_seconds,
        sleep=lambda _: None,
        monotonic=lambda: next(ticks),
    )


def test_recovery_force_targets_exact_old_identity_then_kicks():
    old = ProcessIdentity(17452, 123)
    ops = _Ops([IdentityInspection.EXACT, IdentityInspection.ABSENT_OR_DIFFERENT])
    crumbs = _Breadcrumbs()
    assert _recover(old, ops, crumbs)
    assert ops.termination_requests == [old]
    assert ops.kicks == 1


def test_inspection_failure_never_launches_replacement():
    old = ProcessIdentity(17452, 123)
    ops = _Ops([IdentityInspection.INDETERMINATE])
    assert not _recover(old, ops, _Breadcrumbs())
    assert ops.termination_requests == []
    assert ops.kicks == 0


def test_pid_reuse_during_termination_revalidation_is_not_killed():
    old = ProcessIdentity(17452, 123)
    ops = _Ops(
        [IdentityInspection.EXACT, IdentityInspection.ABSENT_OR_DIFFERENT],
        termination=TerminationResult.ABSENT_OR_DIFFERENT,
    )
    assert _recover(old, ops, _Breadcrumbs())
    assert ops.termination_requests == [old]
    assert ops.termination is TerminationResult.ABSENT_OR_DIFFERENT
    assert ops.killed_identities == []
    assert ops.kicks == 1


def test_post_termination_inspection_failure_is_not_confirmed_gone():
    old = ProcessIdentity(17452, 123)
    ops = _Ops([IdentityInspection.EXACT, IdentityInspection.INDETERMINATE])
    crumbs = _Breadcrumbs()
    assert not _recover(old, ops, crumbs)
    assert ops.kicks == 0
    assert "old-identity-confirmed-gone" not in crumbs.stages


def test_launcher_exception_is_breadcrumbed_and_fails_recovery():
    old = ProcessIdentity(17452, 123)
    ops = _Ops(
        [IdentityInspection.ABSENT_OR_DIFFERENT],
        launch_error=RuntimeError("launcher broke"),
    )
    crumbs = _Breadcrumbs()
    assert not _recover(old, ops, crumbs)
    assert "replacement-launch-attempted" in crumbs.stages
    assert "replacement-launch-failed" in crumbs.stages


def test_breadcrumb_file_rotates_at_small_bound(tmp_path):
    path = tmp_path / "supervisor-recovery.log"
    breadcrumbs = FileBreadcrumbs(path, now=lambda: 1.0, max_bytes=50)
    breadcrumbs.write("one", "stage", "x" * 20)
    breadcrumbs.write("two", "stage", "y" * 20)
    assert path.exists()
    assert path.with_suffix(".log.1").exists()
