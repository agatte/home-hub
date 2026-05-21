"""Tests for ``backend.services.lan_presence_service``.

Covers:
- Configured/unconfigured surface (empty IP disables cleanly).
- ARP-table parsing across the four neighbor-state shapes the kernel emits.
- The miss-threshold state machine — symmetric semantics on edges:
  N consecutive misses to leave, 1 hit to arrive.
"""
from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.lan_presence_service import (
    DEFAULT_MISS_THRESHOLD,
    DEFAULT_POLL_INTERVAL_SECONDS,
    LanPresenceService,
)


# ---------------------------------------------------------------------------
# Surface — configured/connected/is_home defaults
# ---------------------------------------------------------------------------


class TestSurface:
    def test_empty_ip_means_unconfigured(self):
        svc = LanPresenceService(automation=None, phone_ip="")
        assert svc.configured is False
        assert svc.connected is False
        assert svc.is_home is None

    def test_whitespace_ip_treated_as_unconfigured(self):
        svc = LanPresenceService(automation=None, phone_ip="   ")
        assert svc.configured is False

    def test_set_ip_is_configured_but_not_connected(self):
        # Configured (we have an IP) but no poll has run yet (no reading).
        svc = LanPresenceService(automation=None, phone_ip="192.168.1.148")
        assert svc.configured is True
        assert svc.connected is False
        assert svc.is_home is None


# ---------------------------------------------------------------------------
# ARP-table parsing — _is_phone_in_arp_table
# ---------------------------------------------------------------------------


class TestArpParsing:
    """Cover the four neighbor-state shapes `ip neigh show` emits."""

    @pytest.fixture
    def svc(self) -> LanPresenceService:
        return LanPresenceService(automation=None, phone_ip="192.168.1.148")

    def _mock_neigh(self, stdout: str):
        """Patch subprocess.run to return a fake CompletedProcess."""
        result = MagicMock(spec=subprocess.CompletedProcess)
        result.stdout = stdout
        return patch(
            "backend.services.lan_presence_service.subprocess.run",
            return_value=result,
        )

    def test_reachable_returns_true(self, svc):
        with self._mock_neigh(
            "192.168.1.148 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n"
        ):
            assert svc._is_phone_in_arp_table() is True

    def test_stale_returns_true(self, svc):
        # STALE = cache aging but the device responded recently. Real signal.
        with self._mock_neigh(
            "192.168.1.148 dev wlan0 lladdr aa:bb:cc:dd:ee:ff STALE\n"
        ):
            assert svc._is_phone_in_arp_table() is True

    def test_failed_returns_false(self, svc):
        # FAILED = kernel probed and got no response. Device is absent.
        with self._mock_neigh(
            "192.168.1.148 dev wlan0  FAILED\n"
        ):
            assert svc._is_phone_in_arp_table() is False

    def test_incomplete_returns_false(self, svc):
        # INCOMPLETE = probing in progress, no MAC yet. Treat as absent.
        with self._mock_neigh(
            "192.168.1.148 dev wlan0  INCOMPLETE\n"
        ):
            assert svc._is_phone_in_arp_table() is False

    def test_empty_output_returns_false(self, svc):
        # No neighbor entry at all yet — never seen this IP.
        with self._mock_neigh(""):
            assert svc._is_phone_in_arp_table() is False

    def test_subprocess_timeout_returns_false(self, svc):
        # Stuck `ip` shouldn't crash the poll loop or falsely mark present.
        with patch(
            "backend.services.lan_presence_service.subprocess.run",
            side_effect=subprocess.TimeoutExpired("ip", 2.0),
        ):
            assert svc._is_phone_in_arp_table() is False

    def test_missing_ip_command_returns_false(self, svc):
        # Windows / minimal Linux without iproute2 — graceful degrade.
        with patch(
            "backend.services.lan_presence_service.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            assert svc._is_phone_in_arp_table() is False


# ---------------------------------------------------------------------------
# State machine — miss threshold for leaving, single hit for arriving
# ---------------------------------------------------------------------------


class TestStateMachine:
    """Drives the poll loop one iteration at a time via direct method calls
    and verifies set_manual_override / clear_override fire at the right edges.
    """

    def _make_svc(self, miss_threshold: int = 3):
        automation = MagicMock()
        automation.set_manual_override = AsyncMock()
        automation.clear_override = AsyncMock()
        automation._override_source = None
        automation._override_mode = None
        svc = LanPresenceService(
            automation=automation,
            phone_ip="192.168.1.148",
            poll_interval_seconds=30,
            miss_threshold=miss_threshold,
        )
        return svc, automation

    async def _tick(self, svc: LanPresenceService, present: bool) -> None:
        """Manually drive one poll iteration's state-machine logic.

        Mirrors the body of poll_loop without the sleep / heartbeat /
        cancellation paths — keeps the unit under test focused on edges.
        """
        svc._poll_count += 1
        if present:
            if svc._is_home is False:
                await svc._on_arrived()
            svc._is_home = True
            svc._consecutive_misses = 0
        else:
            svc._consecutive_misses += 1
            if (
                svc._consecutive_misses >= svc._miss_threshold
                and svc._is_home is not False
            ):
                await svc._on_left()
                svc._is_home = False

    async def test_one_hit_makes_us_home(self):
        svc, automation = self._make_svc(miss_threshold=3)
        await self._tick(svc, present=True)
        assert svc.is_home is True
        assert svc.connected is True
        # Going unknown → home is not a "return from away" — no clear fired.
        automation.clear_override.assert_not_called()
        automation.set_manual_override.assert_not_called()

    async def test_misses_below_threshold_dont_flip_away(self):
        svc, automation = self._make_svc(miss_threshold=3)
        await self._tick(svc, present=True)   # home
        await self._tick(svc, present=False)  # 1 miss
        await self._tick(svc, present=False)  # 2 misses
        assert svc.is_home is True
        automation.set_manual_override.assert_not_called()

    async def test_threshold_misses_flip_to_away(self):
        svc, automation = self._make_svc(miss_threshold=3)
        await self._tick(svc, present=True)
        for _ in range(3):
            await self._tick(svc, present=False)
        assert svc.is_home is False
        automation.set_manual_override.assert_awaited_once_with(
            "away", source="presence",
        )

    async def test_single_hit_after_away_clears_override(self):
        svc, automation = self._make_svc(miss_threshold=3)
        # Drive into away first.
        await self._tick(svc, present=True)
        for _ in range(3):
            await self._tick(svc, present=False)
        assert svc.is_home is False

        # Simulate our away override being active so _on_arrived clears it.
        automation._override_source = "presence"
        automation._override_mode = "away"

        await self._tick(svc, present=True)
        assert svc.is_home is True
        automation.clear_override.assert_awaited_once_with(source="presence")

    async def test_return_does_not_clear_other_overrides(self):
        """If the user manually set watching/gaming/etc while away,
        coming home shouldn't undo it — only our own away push."""
        svc, automation = self._make_svc(miss_threshold=3)
        await self._tick(svc, present=True)
        for _ in range(3):
            await self._tick(svc, present=False)

        # Different source is now holding the override (e.g. manual API call).
        automation._override_source = "api:192.168.1.30"
        automation._override_mode = "watching"

        await self._tick(svc, present=True)
        # Bounced — leave the foreign override alone.
        automation.clear_override.assert_not_called()

    async def test_hit_resets_miss_counter(self):
        svc, automation = self._make_svc(miss_threshold=3)
        await self._tick(svc, present=True)
        await self._tick(svc, present=False)  # miss=1
        await self._tick(svc, present=False)  # miss=2
        await self._tick(svc, present=True)   # reset
        assert svc._consecutive_misses == 0
        # Future misses need a fresh 3-streak.
        await self._tick(svc, present=False)
        await self._tick(svc, present=False)
        assert svc.is_home is True


# ---------------------------------------------------------------------------
# Defaults exposed for env-var binding
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_constants_are_sensible(self):
        # The values pydantic-settings ships in config.py should match.
        assert DEFAULT_POLL_INTERVAL_SECONDS == 30
        assert DEFAULT_MISS_THRESHOLD == 5

    def test_constructor_clamps_low_values(self):
        # 0 / negative poll intervals would burn CPU — clamped to 5s floor.
        svc = LanPresenceService(
            automation=None, phone_ip="1.1.1.1",
            poll_interval_seconds=0, miss_threshold=0,
        )
        assert svc._poll_interval >= 5
        assert svc._miss_threshold >= 1
