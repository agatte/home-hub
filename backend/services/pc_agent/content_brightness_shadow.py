"""Offline #371 proposals only. No device, network, image or title retention."""
from dataclasses import dataclass
import math
import threading



@dataclass(frozen=True)
class Signal:
    monotonic: float
    wall: float
    white_share: float
    luma: float
    media: bool | None
    sustained: bool
    source: str = "mss-primary-unmapped"


class ContentSignal:
    """Explicitly injected same-process mailbox; no singleton or IPC discovery.

    Four samples spanning >=7.5s enter; three nonwhite samples release.
    Unknown/media, gaps >6s, backwards clocks and suspend clock divergence
    reset immediately. Only aggregate scalars survive publication.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._signal = None
        self._count = 0
        self._start = 0.0
        self._release = 0

    def invalidate(self):
        with self._lock:
            self._signal = None
            self._count = self._release = 0

    def publish(self, pixels, media, now, wall):
        try:
            if not math.isfinite(now) or not math.isfinite(wall):
                raise ValueError("invalid clock")
            rows = pixels.tolist() if hasattr(pixels, "tolist") else pixels

            def flatten(items):
                if not isinstance(items, (list, tuple)):
                    raise ValueError("invalid RGB rows")
                for item in items:
                    if not isinstance(item, (list, tuple)):
                        raise ValueError("invalid RGB row")
                    if len(item) == 3 and all(isinstance(v, (int, float)) for v in item):
                        yield item
                    else:
                        yield from flatten(item)

            rgb = list(flatten(rows))
            if not rgb or any(not math.isfinite(v) or not 0 <= v <= 255
                              for row in rgb for v in row):
                raise ValueError("invalid pixels")
            white = sum(min(row) >= 225 and max(row) - min(row) <= 20
                        for row in rgb) / len(rgb)
            luma = sum(r * .299 + g * .587 + b * .114 for r, g, b in rgb) / len(rgb)
        except (TypeError, ValueError, OverflowError):
            self.invalidate()
            return
        with self._lock:
            old = self._signal
            continuous = (old is not None and 0 < now - old.monotonic <= 6
                          and abs((wall - old.wall) - (now - old.monotonic)) <= 2)
            active = bool(old and old.sustained and continuous)
            if not continuous or media is not False:
                self._count = self._release = 0
                active = False
            if media is False and white >= .70 and luma >= 200:
                if not self._count:
                    self._start = now
                self._count += 1
                self._release = 0
                active = active or (self._count >= 4 and now - self._start >= 7.5)
            else:
                self._count = 0
                self._release += 1
                if self._release >= 3:
                    active = False
            self._signal = Signal(now, wall, white, luma, media, active)

    def snapshot(self, now, wall):
        with self._lock:
            s = self._signal
            if s is None:
                return None
            age = now - s.monotonic
            if (not math.isfinite(age) or not math.isfinite(wall) or not 0 <= age <= 6
                    or abs((wall - s.wall) - age) > 2):
                self._signal = None
                self._count = self._release = 0
                return None
            return s


@dataclass(frozen=True)
class Proposal:
    percent: int
    native: int | None
    reason: str


def propose(signal, *, mode, period, shipped_target, samsung_vcp_max=None,
            mapping_accepted=False, media_trustworthy=False, manual_override=None):
    """Pure hypothetical target. Caller supplies a fresh mailbox snapshot.

    Mapping and media qualification are deliberately unaccepted by runtime.
    Never feed this result into resolve_target, Reconciler or a device writer.
    """
    if manual_override is None:
        reason = "manual-ownership-unknown"
    elif manual_override:
        reason = "manual-override"
    elif mode.lower() in {"sleeping", "gaming"} or period != "late_night":
        reason = "mode-or-period"
    elif signal is None:
        reason = "missing-or-stale"
    elif signal.media is not False:
        reason = "media-active-or-unknown"
    elif not mapping_accepted or not media_trustworthy or samsung_vcp_max != 50:
        reason = "unaccepted-source-or-native-range"
    elif signal.sustained:
        return Proposal(2, 1, "shadow-white-page")
    else:
        reason = "content-dwell"
    return Proposal(shipped_target, None, reason)


class ShadowObserver:
    """Scalar-only classification transitions, at most once per 30 seconds."""

    def __init__(self):
        self._last = None
        self._logged_at = -math.inf

    def observe(self, signal, *, now, mode, period, shipped_target, logger):
        classification = ("missing" if signal is None else
                          "white-like-sustained" if signal.sustained else
                          "white-like" if signal.white_share >= .70 and signal.luma >= 200
                          else "nonwhite")
        key = (classification, mode.lower() not in {"sleeping", "gaming"}
               and period == "late_night")
        if key == self._last or now - self._logged_at < 30:
            return
        self._last, self._logged_at = key, now
        candidate = propose(signal, mode=mode, period=period, shipped_target=shipped_target,
                            mapping_accepted=False, media_trustworthy=False,
                            samsung_vcp_max=None, manual_override=None)
        logger.info(
            "Content brightness SHADOW visual=%s policy_eligible=%s "
            "visual_hypothesis_percent=%s retained_percent=%s "
            "mapping_accepted=False media_trustworthy=False native_range_accepted=False "
            "manual_ownership=unknown foreground_nonmedia_verified=False actuation=False",
            classification, key[1], 2 if signal and signal.sustained and key[1] else None,
            candidate.percent,
        )
