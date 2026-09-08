"""Tests for prevalence-aware sticky ScreenSync color selection.

The picker must preserve stable representative color for genuinely chromatic
content without letting tiny saturated UI/video accents repaint the room.
Neutral/dark compositions deliberately release an old vivid pick, while broad
colored scenes still produce a corresponding bias color.
"""

import numpy as np
import pytest

pytest.importorskip("sklearn")

from backend.services.pc_agent import screen_sync_agent as agent  # noqa: E402


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


def _pixels_regions(
    regions: list[tuple[tuple[int, int, int], int]], seed: int = 0,
) -> np.ndarray:
    """Build a jittered frame from ``(rgb, pixel_count)`` regions."""
    rng = np.random.default_rng(seed)
    blocks = [
        np.tile(np.array(rgb, dtype=np.float32), (count, 1))
        for rgb, count in regions
    ]
    pixels = np.vstack(blocks)
    noise = rng.normal(0, 2.5, size=pixels.shape).astype(np.float32)
    return np.clip(pixels + noise, 0, 255)


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

    def test_dark_scene_releases_prior_vivid_color(self) -> None:
        """A neutral/dark composition must not inherit the last vivid scene."""
        orange = (230, 120, 40)
        picker = agent.StickyClusterPicker()
        picker.pick(_pixels_mixing(orange, orange, n_each=200))

        dark = _pixels_regions([((10, 10, 10), 850), ((30, 30, 30), 150)], seed=1)
        pick = picker.pick(dark)

        assert max(pick) < 40
        assert max(pick) - min(pick) < 8

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

    def test_twenty_percent_saturated_accent_does_not_beat_gray_page(self) -> None:
        gray = (80, 80, 80)
        red = (220, 40, 40)
        pixels = _pixels_regions([(gray, 800), (red, 200)], seed=7)

        pick = agent.StickyClusterPicker().pick(pixels)

        dist_to_red = np.linalg.norm(np.array(pick) - np.array(red))
        dist_to_gray = np.linalg.norm(np.array(pick) - np.array(gray))
        assert dist_to_gray < dist_to_red, f"minority accent dominated: pick={pick}"

    def test_known_dark_frame_tiny_blue_failure_stays_neutral(self) -> None:
        """~91% black + ~1.8% blue releases even a prior blue scene."""
        picker = agent.StickyClusterPicker()
        picker.pick(_pixels_mixing((25, 80, 220), (25, 80, 220), n_each=200))
        pixels = _pixels_regions([
            ((5, 5, 5), 910),
            ((35, 35, 35), 72),
            ((25, 80, 220), 18),
        ], seed=11)

        pick = picker.pick(pixels)

        assert max(pick) < 45
        assert max(pick) - min(pick) < 10

    def test_white_page_with_small_red_icon_stays_neutral(self) -> None:
        pixels = _pixels_regions([
            ((235, 235, 235), 900),
            ((190, 190, 190), 70),
            ((220, 35, 35), 30),
        ], seed=13)

        pick = agent.StickyClusterPicker().pick(pixels)

        assert min(pick) > 175
        assert max(pick) - min(pick) < 12

    @pytest.mark.parametrize(
        ("scene_color", "assert_channel"),
        [
            ((205, 110, 45), 0),
            ((45, 180, 75), 1),
        ],
    )
    def test_dominant_colored_scene_keeps_corresponding_bias(
        self, scene_color: tuple[int, int, int], assert_channel: int,
    ) -> None:
        pixels = _pixels_regions([
            (scene_color, 700),
            ((35, 35, 35), 300),
        ], seed=17 + assert_channel)

        pick = agent.StickyClusterPicker().pick(pixels)

        assert pick[assert_channel] == max(pick)
        assert max(pick) - min(pick) > 60

    def test_mixed_cinematic_frame_prefers_broad_scene_color(self) -> None:
        teal = (35, 125, 175)
        orange = (185, 95, 45)
        pixels = _pixels_regions([
            (teal, 520),
            ((55, 55, 55), 280),
            (orange, 200),
        ], seed=23)

        pick = agent.StickyClusterPicker().pick(pixels)

        assert np.linalg.norm(np.array(pick) - np.array(teal)) < np.linalg.norm(
            np.array(pick) - np.array(orange)
        )

    def test_identical_frame_is_deterministic_across_fresh_pickers(self) -> None:
        pixels = _pixels_regions([
            ((35, 125, 175), 520),
            ((55, 55, 55), 280),
            ((185, 95, 45), 200),
        ], seed=23)

        first = agent.StickyClusterPicker().pick(pixels)
        second = agent.StickyClusterPicker().pick(pixels.copy())

        assert first == second

    def test_near_identical_cinematic_frames_stay_on_same_color_family(self) -> None:
        picker = agent.StickyClusterPicker()
        first = picker.pick(_pixels_regions([
            ((35, 125, 175), 520),
            ((55, 55, 55), 280),
            ((185, 95, 45), 200),
        ], seed=29))
        second = picker.pick(_pixels_regions([
            ((35, 125, 175), 500),
            ((55, 55, 55), 300),
            ((185, 95, 45), 200),
        ], seed=30))

        assert np.linalg.norm(np.array(second) - np.array(first)) < agent._STICKY_DISTANCE

    def test_color_ownership_has_entry_release_hysteresis(self) -> None:
        red = (220, 40, 40)
        gray = (80, 80, 80)
        picker = agent.StickyClusterPicker()

        established = picker.pick(_pixels_regions([(gray, 700), (red, 300)], seed=41))
        borderline = picker.pick(_pixels_regions([(gray, 750), (red, 250)], seed=42))
        released = picker.pick(_pixels_regions([(gray, 800), (red, 200)], seed=43))
        fresh_borderline = agent.StickyClusterPicker().pick(
            _pixels_regions([(gray, 750), (red, 250)], seed=42)
        )

        assert established[0] > established[1] + 100
        assert borderline[0] > borderline[1] + 100
        assert max(fresh_borderline) - min(fresh_borderline) < 8
        assert max(released) - min(released) < 8
