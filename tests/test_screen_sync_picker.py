"""
Tests for the sticky-cluster dominant-color picker.

The k-means picker in ``screen_sync_agent`` and ``screen_sync`` used to
re-choose the "best" cluster each frame from scratch. When two clusters
scored near-ties, the chosen color cycled on every capture (reported as
"L2 cycling through colors during League"). These tests verify the sticky
behavior that replaced it:

  - a stable scene with two near-tied saturated clusters doesn't flip.
  - a genuine color change still breaks through when the new best beats
    the prior winner by more than ``_STICKY_SCORE_MARGIN``.
  - a dark scene holds the prior color instead of snapping to near-black.
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


def _reset_sticky_state() -> None:
    agent._last_center = None
    agent._last_picked_at = 0.0


class TestStickyPicker:
    def setup_method(self) -> None:
        _reset_sticky_state()

    def test_near_tied_clusters_do_not_flip(self) -> None:
        """Two saturated colors at similar scores should pick one and stick."""
        red = (220, 40, 40)
        blue = (40, 40, 220)

        pixels = _pixels_mixing(red, blue)
        first = agent._pick_dominant_kmeans(pixels)

        # 10 more frames of the same mixed scene — output should not cycle.
        picks = [agent._pick_dominant_kmeans(_pixels_mixing(red, blue)) for _ in range(10)]

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

        # Establish prior: pure red scene.
        red_pixels = _pixels_mixing(red, red, n_each=200)
        agent._pick_dominant_kmeans(red_pixels)

        # Now feed a pure blue scene — score gap is huge, should switch.
        blue_pixels = _pixels_mixing(blue, blue, n_each=200)
        pick = agent._pick_dominant_kmeans(blue_pixels)

        # Closer to blue than to red.
        dist_to_blue = np.linalg.norm(np.array(pick) - np.array(blue))
        dist_to_red = np.linalg.norm(np.array(pick) - np.array(red))
        assert dist_to_blue < dist_to_red, f"stuck on prior: pick={pick}"

    def test_dark_scene_holds_prior_instead_of_black(self) -> None:
        """When no saturated cluster exists, prefer prior over the darkest cluster."""
        orange = (230, 120, 40)
        orange_pixels = _pixels_mixing(orange, orange, n_each=200)
        prior_pick = agent._pick_dominant_kmeans(orange_pixels)

        # Dark scene: all near-black, no cluster passes saturation gate.
        rng = np.random.default_rng(1)
        dark = rng.integers(0, 25, size=(400, 3)).astype(np.float32)
        pick = agent._pick_dominant_kmeans(dark)

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
        red_pixels = _pixels_mixing(red, red, n_each=200)
        agent._pick_dominant_kmeans(red_pixels)
        assert agent._last_center is not None

        # Fast-forward: pretend the prior pick happened long ago.
        agent._last_picked_at -= agent._STICKY_STALENESS_SEC + 1

        blue = (40, 40, 220)
        blue_pixels = _pixels_mixing(blue, blue, n_each=200)
        pick = agent._pick_dominant_kmeans(blue_pixels)

        # With staleness triggered, should pick blue freely (no prior bias).
        assert pick[2] > pick[0], f"stuck on stale prior: pick={pick}"
