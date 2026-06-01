"""
Desktop notifier — custom toast widget that subscribes to Home Hub's
``notification`` WS event and pops a frameless slide-in on the user's
desktop.

Runs as a standalone PyQt6 process on Anthony's Windows desktop
(192.168.86.30), separate from the backend on the Latitude. Pattern
mirrors ``activity_detector.py``: PID lock, rotating logfile, sigterm
handler, exponential-backoff reconnect.

Architecture inside the process:

  ┌────────────────────────────────────────────────────────────────┐
  │ Main thread (Qt event loop)                                    │
  │ ┌──────────────────┐    Qt signal     ┌──────────────────────┐ │
  │ │ NotificationBus  │  ──────────────> │ ToastWidget          │ │
  │ │  (QObject)       │                  │  slide-in / fade-out │ │
  │ └──────▲───────────┘                  └──────────────────────┘ │
  │        │ emit (thread-safe)                                    │
  └────────┼───────────────────────────────────────────────────────┘
           │
  ┌────────┴───────────────────────────────────────────────────────┐
  │ WS worker thread (blocking websockets.sync)                    │
  │ recv loop → filter type=="notification" → bus.notification     │
  └────────────────────────────────────────────────────────────────┘

Silence is a local concern (tray menu → write `silence_until` epoch to
a small text file). Phone push from the backend is unaffected — silence
only mutes the desktop surface.
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QObject,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

import psutil
import urllib.request
import webbrowser
import websockets
import websockets.sync.client

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SERVER = "ws://192.168.86.210:8000/ws"

# Reconnect cadence — matches the v2 stream loop in hue_v2_service.
RECONNECT_INITIAL_S = 1.0
RECONNECT_MAX_S = 30.0

# Toast dimensions + lifetime.
TOAST_WIDTH = 360
TOAST_HEIGHT = 180
TOAST_EXPANDED_HEIGHT = 360
TOAST_MARGIN = 24       # px from screen edge
TOAST_LIFETIME_MS = 8000  # auto-dismiss after 8s
TOAST_SLIDE_DURATION_MS = 280
TOAST_FADE_DURATION_MS = 220

LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "desktop_notifier.log"
PID_FILE = LOG_DIR / "desktop_notifier.pid"
SILENCE_FILE = LOG_DIR / "desktop_notifier_silence_until.txt"

LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger("home_hub.desktop_notifier")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
_console = logging.StreamHandler()
_console.setFormatter(_fmt)
logger.addHandler(_console)
_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2, encoding="utf-8",
)
_file_handler.setFormatter(_fmt)
logger.addHandler(_file_handler)


# ---------------------------------------------------------------------------
# PID lock — single-instance enforcement
# ---------------------------------------------------------------------------

def acquire_pid_lock() -> None:
    """Refuse to launch if another desktop_notifier owns the PID file."""
    if PID_FILE.exists():
        try:
            existing_pid = int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            existing_pid = -1
        if existing_pid > 0 and psutil.pid_exists(existing_pid):
            logger.error(
                "Another desktop_notifier is running (PID %d). Refusing to start.",
                existing_pid,
            )
            sys.exit(1)
        if existing_pid > 0:
            logger.info("Stale PID file (PID %d not alive) — cleaning up", existing_pid)
    PID_FILE.write_text(str(os.getpid()))
    logger.info("PID lock acquired (PID %d, file: %s)", os.getpid(), PID_FILE)


def release_pid_lock() -> None:
    """Best-effort PID file cleanup on exit."""
    try:
        if PID_FILE.exists():
            stored = int(PID_FILE.read_text().strip())
            if stored == os.getpid():
                PID_FILE.unlink()
                logger.info("PID lock released")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Silence management — toggled from the tray menu
# ---------------------------------------------------------------------------

def silence_until_epoch() -> Optional[float]:
    """Read the silence-until epoch from disk, or None if not silenced."""
    try:
        if not SILENCE_FILE.exists():
            return None
        ts = float(SILENCE_FILE.read_text().strip())
        return ts if ts > time.time() else None
    except (ValueError, OSError):
        return None


def set_silence(duration_s: float) -> None:
    """Persist a silence-until epoch. Pass 0 to clear."""
    if duration_s <= 0:
        try:
            SILENCE_FILE.unlink(missing_ok=True)
        except OSError:
            logger.debug("silence clear failed", exc_info=True)
        logger.info("Silence cleared")
        return
    epoch = time.time() + duration_s
    SILENCE_FILE.write_text(f"{epoch:.0f}")
    logger.info("Silenced for %.0fs (until epoch %.0f)", duration_s, epoch)


def is_silenced() -> bool:
    return silence_until_epoch() is not None


# ---------------------------------------------------------------------------
# Notification bus — bridges WS thread → Qt main thread
# ---------------------------------------------------------------------------

class NotificationBus(QObject):
    """Qt signal carrier. Safe to ``emit`` from any thread."""
    notification = pyqtSignal(dict)


# ---------------------------------------------------------------------------
# Toast widget
# ---------------------------------------------------------------------------

# Apartment palette — Bebas Neue's missing on most systems; we use a
# bold sans fallback that's universal on Windows. Keep colors aligned
# with the dashboard's glass-card aesthetic (dark translucent panel,
# warm accent for the headline, muted body text).
BG_COLOR = QColor(20, 22, 26, 240)
ACCENT_COLOR = QColor(255, 184, 92)      # warm amber, like relax lighting
TEXT_PRIMARY = QColor(245, 245, 245)
TEXT_SECONDARY = QColor(170, 170, 175)
BORDER_COLOR = QColor(70, 75, 85, 200)


class ToastWidget(QWidget):
    """Frameless slide-in toast. Click to expand, click again or wait to dismiss."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(TOAST_WIDTH)
        self.setMinimumHeight(TOAST_HEIGHT)

        self._expanded = False
        self._payload: dict[str, Any] = {}
        self._slide_anim: Optional[QPropertyAnimation] = None

        self._build_ui()

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.start_hide)

    # ---- UI -----------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        self._title_label = QLabel("")
        title_font = QFont("Segoe UI", 16, QFont.Weight.Bold)
        self._title_label.setFont(title_font)
        self._title_label.setStyleSheet(f"color: rgb({ACCENT_COLOR.red()}, {ACCENT_COLOR.green()}, {ACCENT_COLOR.blue()});")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._subtitle_label = QLabel("")
        subtitle_font = QFont("Segoe UI", 9)
        self._subtitle_label.setFont(subtitle_font)
        self._subtitle_label.setStyleSheet(f"color: rgb({TEXT_SECONDARY.red()}, {TEXT_SECONDARY.green()}, {TEXT_SECONDARY.blue()});")
        # 360px fixed-width toast + a ~120-char suggestion body needs wrap or
        # the right edge clips. Default QLabel behavior truncates instead of
        # wrapping; opt in explicitly. Only output_label had this before.
        self._subtitle_label.setWordWrap(True)
        layout.addWidget(self._subtitle_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: rgba({BORDER_COLOR.red()}, {BORDER_COLOR.green()}, {BORDER_COLOR.blue()}, 80); border: none; max-height: 1px;")
        layout.addWidget(sep)

        # Factors list — populated dynamically.
        self._factors_layout = QVBoxLayout()
        self._factors_layout.setSpacing(4)
        layout.addLayout(self._factors_layout)

        self._output_label = QLabel("")
        output_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        self._output_label.setFont(output_font)
        self._output_label.setStyleSheet(f"color: rgb({TEXT_SECONDARY.red()}, {TEXT_SECONDARY.green()}, {TEXT_SECONDARY.blue()}); padding-top: 4px;")
        self._output_label.setWordWrap(True)
        layout.addWidget(self._output_label)

        # Action-button row — populated when a suggestion-kind notification
        # arrives (payload.actions non-empty). Renders Accept / Dismiss
        # buttons that POST to the supplied URLs in a worker thread.
        self._actions_layout = QHBoxLayout()
        self._actions_layout.setSpacing(8)
        layout.addLayout(self._actions_layout)

        layout.addStretch(1)

    def _populate(self, payload: dict[str, Any]) -> None:
        """Update labels from a new notification payload."""
        self._payload = payload
        title = payload.get("title", "Home Hub")
        subtitle = payload.get("subtitle") or ""
        self._title_label.setText(title)
        # For mode_flip / brightness_shift the subtitle is a short "source"
        # descriptor (e.g. "process") — "source: X" reads cleanly. For
        # suggestion-kind the subtitle IS the full body sentence
        # ("You've been setting L3 to ~44%…") — prefixing "source:" makes
        # the toast read as a malformed log line, drop the prefix.
        if subtitle:
            if payload.get("kind") == "suggestion":
                self._subtitle_label.setText(subtitle)
            else:
                self._subtitle_label.setText(f"source: {subtitle}")
        else:
            self._subtitle_label.setText("")

        # Clear and repopulate factors.
        while self._factors_layout.count():
            item = self._factors_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        factors = payload.get("factors") or []
        visible = factors if self._expanded else factors[:3]
        for f in visible:
            row = self._build_factor_row(f)
            self._factors_layout.addWidget(row)

        # Suggestion-kind notifications intentionally have no fusion
        # factors (they're user-prompts, not autonomous decisions). Don't
        # show the empty-state placeholder — reads as a bug/missing data.
        if not visible and payload.get("kind") != "suggestion":
            empty = QLabel("(no fusion factors available)")
            empty.setStyleSheet(f"color: rgb({TEXT_SECONDARY.red()}, {TEXT_SECONDARY.green()}, {TEXT_SECONDARY.blue()}); font-style: italic;")
            self._factors_layout.addWidget(empty)

        output_delta = payload.get("output_delta")
        if output_delta:
            self._output_label.setText(f"→ {output_delta}")
            self._output_label.show()
        else:
            self._output_label.hide()

        # Clear and repopulate action buttons.
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        actions = payload.get("actions") or []
        if actions:
            for action in actions:
                btn = self._build_action_button(action)
                self._actions_layout.addWidget(btn)
            self._actions_layout.addStretch(1)
            # Keep the toast around longer when action buttons are visible —
            # gives the user time to read and click.
            self._dismiss_timer.start(TOAST_LIFETIME_MS * 3)

        # Size shrinks/grows for expanded view.
        self.setMinimumHeight(TOAST_EXPANDED_HEIGHT if self._expanded else TOAST_HEIGHT)
        self.adjustSize()

    def _build_action_button(self, action: dict[str, Any]) -> QPushButton:
        label = action.get("label", "Action")
        url = action.get("url", "")
        method = action.get("method", "POST")
        headers = action.get("headers") or {}
        # ntfy.sh-style action types: "http" (default — POST/GET with optional
        # headers, for Accept/Dismiss-style suggestions) and "view" (open the
        # URL in the user's default browser). View actions ignore method and
        # headers — they're just deeplinks (used by calibration_nudge to
        # open /personality).
        action_type = (action.get("type") or "http").lower()
        btn = QPushButton(label)
        btn.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        # Two-tier styling: first button = accent (Accept), others muted.
        if self._actions_layout.count() == 0:
            btn.setStyleSheet(
                f"QPushButton {{"
                f" background: rgb({ACCENT_COLOR.red()}, {ACCENT_COLOR.green()}, {ACCENT_COLOR.blue()});"
                f" color: rgb(20, 22, 28);"
                f" padding: 6px 14px;"
                f" border-radius: 6px;"
                f" border: none;"
                f"}}"
                f"QPushButton:hover {{ background: rgb(180, 215, 255); }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{"
                f" background: rgba({BORDER_COLOR.red()}, {BORDER_COLOR.green()}, {BORDER_COLOR.blue()}, 100);"
                f" color: rgb({TEXT_PRIMARY.red()}, {TEXT_PRIMARY.green()}, {TEXT_PRIMARY.blue()});"
                f" padding: 6px 14px;"
                f" border-radius: 6px;"
                f" border: 1px solid rgba({BORDER_COLOR.red()}, {BORDER_COLOR.green()}, {BORDER_COLOR.blue()}, 160);"
                f"}}"
                f"QPushButton:hover {{ background: rgba({BORDER_COLOR.red()}, {BORDER_COLOR.green()}, {BORDER_COLOR.blue()}, 150); }}"
            )
        if action_type == "view":
            btn.clicked.connect(
                lambda _checked=False, u=url: self._dispatch_view(u)
            )
        else:
            btn.clicked.connect(
                lambda _checked=False, u=url, m=method, h=dict(headers): (
                    self._dispatch_action(u, m, h)
                )
            )
        return btn

    def _dispatch_view(self, url: str) -> None:
        """Open a URL in the user's default browser and dismiss the toast.

        Used by view-type actions (e.g. calibration_nudge's 'Open calibration'
        button). The HTTP-action path is reserved for buttons that mutate
        backend state (Accept / Dismiss); view is purely a deeplink.
        """
        if not url:
            return
        try:
            webbrowser.open(url, new=2)
        except Exception:
            logger.warning("view dispatch failed: %s", url, exc_info=True)
        self.start_hide()

    def _dispatch_action(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
    ) -> None:
        """Fire the HTTP request in a worker thread + dismiss the toast.

        Best-effort: success/failure is not surfaced to the UI (the user
        sees the toast disappear, and the next backend tick will either
        broadcast a 'brightness_suggestion_resolved' event or be silent).
        """
        if not url:
            return

        def _send() -> None:
            try:
                req = urllib.request.Request(  # noqa: S310 — known LAN URL
                    url, method=method, headers=headers, data=b"",
                )
                urllib.request.urlopen(req, timeout=4.0).close()  # noqa: S310
            except Exception:
                logger.warning("action dispatch failed: %s", url, exc_info=True)

        threading.Thread(target=_send, daemon=True).start()
        self.start_hide()

    def _build_factor_row(self, factor: dict[str, Any]) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        lane = factor.get("lane", "")
        label = factor.get("label", "")
        value = factor.get("value", "")

        lane_label = QLabel(f"[{lane}]" if lane else "")
        lane_label.setFont(QFont("Segoe UI", 9))
        lane_label.setStyleSheet(f"color: rgb({TEXT_SECONDARY.red()}, {TEXT_SECONDARY.green()}, {TEXT_SECONDARY.blue()}); min-width: 60px;")
        h.addWidget(lane_label)

        key_label = QLabel(f"{label}:")
        key_label.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        key_label.setStyleSheet(f"color: rgb({TEXT_PRIMARY.red()}, {TEXT_PRIMARY.green()}, {TEXT_PRIMARY.blue()});")
        h.addWidget(key_label)

        value_label = QLabel(str(value))
        value_label.setFont(QFont("Segoe UI", 10))
        value_label.setStyleSheet(f"color: rgb({TEXT_PRIMARY.red()}, {TEXT_PRIMARY.green()}, {TEXT_PRIMARY.blue()});")
        h.addWidget(value_label, stretch=1)

        return row

    # ---- Custom paint -------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802 — Qt API
        """Rounded rect background with subtle accent border."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        radius = 12
        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect.toRectF(), radius, radius)

        painter.fillPath(path, BG_COLOR)
        painter.setPen(BORDER_COLOR)
        painter.drawPath(path)

        # Accent stripe down the left edge — visual signature
        stripe = path.toFillPolygon().boundingRect()
        accent_rect = stripe.adjusted(0, 0, -stripe.width() + 4, 0)
        painter.fillRect(accent_rect, ACCENT_COLOR)

    # ---- Interaction --------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        # Toggle expanded mode if there are more than 3 factors to show,
        # otherwise click dismisses.
        factors = self._payload.get("factors") or []
        if not self._expanded and len(factors) > 3:
            self._expanded = True
            self._populate(self._payload)
            self._dismiss_timer.start(TOAST_LIFETIME_MS * 2)  # keep around longer when expanded
        else:
            self.start_hide()

    # ---- Show / hide --------------------------------------------------

    def show_with_payload(self, payload: dict[str, Any]) -> None:
        """Entry point from the bus signal. Populate, animate, arm dismiss."""
        try:
            self._expanded = False
            self._populate(payload)
            self._position_and_slide_in()
            self._dismiss_timer.start(TOAST_LIFETIME_MS)
        except Exception:
            logger.exception("toast show failed")

    def _position_and_slide_in(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.show()
            return
        geo = screen.availableGeometry()
        target_x = geo.right() - TOAST_WIDTH - TOAST_MARGIN
        target_y = geo.bottom() - self.height() - TOAST_MARGIN
        start_x = geo.right()

        self.move(start_x, target_y)
        self.show()
        self.raise_()

        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(TOAST_SLIDE_DURATION_MS)
        anim.setStartValue(QPoint(start_x, target_y))
        anim.setEndValue(QPoint(target_x, target_y))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._slide_anim = anim

    def start_hide(self) -> None:
        self._dismiss_timer.stop()
        screen = QApplication.primaryScreen()
        if screen is None:
            self.hide()
            return
        geo = screen.availableGeometry()
        start_pos = self.pos()
        end_x = geo.right()
        anim = QPropertyAnimation(self, b"pos", self)
        anim.setDuration(TOAST_FADE_DURATION_MS)
        anim.setStartValue(start_pos)
        anim.setEndValue(QPoint(end_x, start_pos.y()))
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self.hide)
        anim.start()
        self._slide_anim = anim


# ---------------------------------------------------------------------------
# WebSocket worker thread
# ---------------------------------------------------------------------------

class WsWorker(threading.Thread):
    """Connects to the Home Hub WS, filters ``notification`` events, emits to bus."""

    def __init__(
        self,
        server_url: str,
        bus: NotificationBus,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="ws-worker", daemon=True)
        self._url = server_url
        self._bus = bus
        self._stop = stop_event

    def run(self) -> None:  # noqa: D401 — Thread.run override
        backoff = RECONNECT_INITIAL_S
        while not self._stop.is_set():
            try:
                logger.info("Connecting to %s", self._url)
                # close_timeout caps how long a clean shutdown waits on the
                # server's ack — desktop teardown shouldn't hang on it.
                with websockets.sync.client.connect(
                    self._url, close_timeout=2.0,
                ) as ws:
                    logger.info("WS connected")
                    backoff = RECONNECT_INITIAL_S
                    self._recv_loop(ws)
            except (OSError, websockets.exceptions.WebSocketException) as e:
                logger.warning(
                    "WS disconnect: %s (reconnecting in %.1fs)", e, backoff,
                )
            except Exception:
                logger.exception("WS worker unexpected error")
            finally:
                if self._stop.is_set():
                    return
                self._stop.wait(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_S)

    def _recv_loop(self, ws) -> None:
        while not self._stop.is_set():
            try:
                raw = ws.recv(timeout=5.0)
            except TimeoutError:
                # Periodic timeout lets us check stop_event between messages
                # without blocking forever on a quiet WS.
                continue
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if msg.get("type") != "notification":
                continue
            if is_silenced():
                logger.debug("notification suppressed (silenced)")
                continue
            try:
                self._bus.notification.emit(msg.get("data") or {})
            except Exception:
                logger.exception("bus emit failed")


# ---------------------------------------------------------------------------
# Tray icon + app shell
# ---------------------------------------------------------------------------

def _build_tray_icon() -> QIcon:
    """Generate a small bell-ish icon on a transparent pixmap."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    # Background dot
    painter.setBrush(QColor(28, 30, 36, 230))
    painter.drawEllipse(2, 2, 28, 28)
    # Inner accent (the "bell")
    painter.setBrush(ACCENT_COLOR)
    painter.drawEllipse(10, 8, 12, 14)
    painter.setBrush(QColor(245, 245, 245))
    painter.drawEllipse(13, 21, 6, 4)
    painter.end()
    return QIcon(pixmap)


class TrayApp:
    """Top-level app shell. Owns the QApplication + tray + toast + WS worker."""

    def __init__(self, server_url: str) -> None:
        self._app = QApplication.instance() or QApplication(sys.argv)
        # Toast hides itself; the app must keep running until the user quits.
        self._app.setQuitOnLastWindowClosed(False)

        self._toast = ToastWidget()
        self._bus = NotificationBus()
        self._bus.notification.connect(self._toast.show_with_payload)

        self._tray = QSystemTrayIcon(_build_tray_icon())
        self._tray.setToolTip("Home Hub Notifier")
        self._tray.setContextMenu(self._build_menu())
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self._stop = threading.Event()
        self._worker = WsWorker(server_url, self._bus, self._stop)
        self._worker.start()
        logger.info("TrayApp ready — server=%s", server_url)

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        silence_1h = QAction("Silence 1 hour", menu)
        silence_1h.triggered.connect(lambda: set_silence(3600))
        menu.addAction(silence_1h)

        silence_4h = QAction("Silence 4 hours", menu)
        silence_4h.triggered.connect(lambda: set_silence(4 * 3600))
        menu.addAction(silence_4h)

        clear = QAction("Clear silence", menu)
        clear.triggered.connect(lambda: set_silence(0))
        menu.addAction(clear)

        menu.addSeparator()

        test = QAction("Test toast", menu)
        test.triggered.connect(self._test_toast)
        menu.addAction(test)

        menu.addSeparator()

        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self.quit)
        menu.addAction(quit_act)
        return menu

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Double-click the tray icon to fire a test toast — quick verification
        # without diving into the right-click menu.
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._test_toast()

    def _test_toast(self) -> None:
        self._bus.notification.emit({
            "title": "Test toast",
            "subtitle": "tray menu",
            "factors": [
                {"lane": "test", "label": "synthetic", "value": "fire from tray", "impact": 1.0},
            ],
            "output_delta": None,
        })

    def quit(self) -> None:
        logger.info("Quitting desktop notifier")
        self._stop.set()
        self._tray.hide()
        self._app.quit()

    def run(self) -> int:
        return self._app.exec()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Home Hub Desktop Notifier")
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER,
        help=f"Home Hub WebSocket URL (default: {DEFAULT_SERVER})",
    )
    args = parser.parse_args()

    acquire_pid_lock()
    atexit.register(release_pid_lock)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    app = TrayApp(args.server)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
