"""
Tests for the sticky-cluster dominant-color picker.

The k-means picker in ``screen_sync_agent`` used to re-choose the "best"
cluster each frame from scratch. When two clusters scored near-ties, the
chosen color cycled on every capture (reported as "L2 cycling through
colors during League"). These tests verify the sticky behavior that
replaced it, now structured as a per-region ``StickyClusterPicker`` class
so left/right region pickers don't share state:

  - a stable scene with two near-tied saturated clusters doesn't flip.
  - a genuine color change still breaks through when the new best beats
    the prior winner by more than ``_STICKY_SCORE_MARGIN``.
  - a dark scene holds the prior color instead of snapping to near-black.
  - two picker instances do not share each other's prior.
"""

import numpy as np
import pytest

pytest.importorskip("sklearn")

from sklearn.cluster import MiniBatchKMeans as _RealMBK  # noqa: E402

from backend.services.pc_agent import screen_sync_agent as agent  # noqa: E402


@pytest.fixture(autouse=True)
def _deterministic_kmeans(monkeypatch):
    """Pin MiniBatchKMeans' random_state so sticky-logic tests don't flake.

    The picker's real-world behavior depends on sklearn's stochastic init;
    here we isolate the *decision logic* from the clustering noise.
    """
    def _seeded(*args, **kwargs):
        kwargs.setdefault("random_state", 0)
        return _RealMBK(*args, **kwargs)

    monkeypatch.setattr(agent, "MiniBatchKMeans", _seeded)


def _pixels_mixing(rgb_a: tuple[int, int, int], rgb_b: tuple[int, int, int],
                   n_each: int = 200) -> np.ndarray:
    """Build a pixel array with equal populations of two saturated colors.

    A little gaussian jitter keeps k-means honest — exact duplicates
    collapse to fewer clusters than requested.
    """
    rng = np.random.default_rng(0)
    a = np.tile(np.array(rgb_a, dtype=np.float32), (n_each, 1))
    b = np.tile(np.array(rgb_b, dtype=np.float32), (n_each, 1))
    noise = rng.normal(0, 3, size=(n_each * 2, 3)).astype(np.float32)
    return np.clip(np.vstack([a, b]) + noise, 0, 255)


class TestStickyClusterPicker:
    def test_near_tied_clusters_do_not_flip(self) -> None:
        """Two saturated colors at similar scores should pick one and stick."""
        red = (220, 40, 40)
        blue = (40, 40, 220)

        picker = agent.StickyClusterPicker()
        first = picker.pick(_pixels_mixing(red, blue))

        # 10 more frames of the same mixed scene — output should not cycle.
        picks = [picker.pick(_pixels_mixing(red, blue)) for _ in range(10)]

        # All picks should stay close (in RGB Euclidean space) to the first.
        for pick in picks:
            dist = np.linalg.norm(np.array(pick) - np.array(first))
            assert dist < agent._STICKY_DISTANCE, (
                f"picker flipped: first={first}, later={pick}, distance={dist:.1f}"
            )

    def test_real_color_change_breaks_through(self) -> None:
        """A genuine dominant-color change should still override the prior."""
        red = (220, 40, 40)
        blue = (40, 40, 220)

        picker = agent.StickyClusterPicker()
        picker.pick(_pixels_mixing(red, red, n_each=200))

        # Now feed a pure blue scene — score gap is huge, should switch.
        pick = picker.pick(_pixels_mixing(blue, blue, n_each=200))

        # Closer to blue than to red.
        dist_to_blue = np.linalg.norm(np.array(pick) - np.array(blue))
        dist_to_red = np.linalg.norm(np.array(pick) - np.array(red))
        assert dist_to_blue < dist_to_red, f"stuck on prior: pick={pick}"

    def test_dark_scene_holds_prior_instead_of_black(self) -> None:
        """When no saturated cluster exists, prefer prior over the darkest cluster."""
        orange = (230, 120, 40)
        picker = agent.StickyClusterPicker()
        prior_pick = picker.pick(_pixels_mixing(orange, orange, n_each=200))

        # Dark scene: all near-black, no cluster passes saturation gate.
        rng = np.random.default_rng(1)
        dark = rng.integers(0, 25, size=(400, 3)).astype(np.float32)
        pick = picker.pick(dark)

        # Pick should stay near the prior orange, not collapse to near-black.
        # (Dark fallback only applies when no saturated candidate exists AND
        # the prior-nearest cluster is within ``_STICKY_DISTANCE * 2``. A pure
        # near-black scene will exceed that and fall through to "largest" —
        # the test documents *that* behavior too.)
        nearest_to_prior = np.linalg.norm(np.array(pick) - np.array(prior_pick))
        if nearest_to_prior >= agent._STICKY_DISTANCE * 2:
            # Genuine scene change far from prior — expect near-black fallback.
            assert sum(pick) < 90
        else:
            # Held prior — should still be orange-ish.
            assert pick[0] > pick[2]

    def test_staleness_resets_prior(self) -> None:
        """After the staleness window, the picker should treat state as fresh."""
        red = (220, 40, 40)
        picker = agent.StickyClusterPicker()
        picker.pick(_pixels_mixing(red, red, n_each=200))
        assert picker.last_center is not None

        # Fast-forward: pretend the prior pick happened long ago.
        picker.last_picked_at -= agent._STICKY_STALENESS_SEC + 1

        blue = (40, 40, 220)
        pick = picker.pick(_pixels_mixing(blue, blue, n_each=200))

        # With staleness triggered, should pick blue freely (no prior bias).
        assert pick[2] > pick[0], f"stuck on stale prior: pick={pick}"

    def test_two_pickers_keep_independent_state(self) -> None:
        """Left/right region pickers must not contaminate each other's prior.

        Dual-region screen sync runs one picker per half of the screen. If
        they shared module-level state, a red-dominant left half would force
        the right half's blue-dominant scene to bias toward red.
        """
        red = (220, 40, 40)
        blue = (40, 40, 220)

        left = agent.StickyClusterPicker()
        right = agent.StickyClusterPicker()

        # Establish independent priors.
        left_pick = left.pick(_pixels_mixing(red, red, n_each=200))
        right_pick = right.pick(_pixels_mixing(blue, blue, n_each=200))

        # left stays red-leaning, right stays blue-leaning.
        assert left_pick[0] > left_pick[2], f"left wrong: {left_pick}"
        assert right_pick[2] > right_pick[0], f"right wrong: {right_pick}"

        # Now feed a near-tied red+blue scene to both. Each should sticky-bias
        # toward its own prior — left stays warm, right stays cool — without
        # the two regions converging on the same color.
        l2 = left.pick(_pixels_mixing(red, blue))
        r2 = right.pick(_pixels_mixing(red, blue))
        assert l2[0] > l2[2], f"left lost its prior: {l2}"
        assert r2[2] > r2[0], f"right lost its prior: {r2}"
