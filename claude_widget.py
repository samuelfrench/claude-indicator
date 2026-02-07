#!/usr/bin/env python3
"""Translucent desktop widget showing Claude Code Max subscription usage."""

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from PySide6.QtCore import QPoint, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_BETA = "oauth-2025-04-20"
REFRESH_INTERVAL_MS = 5 * 60 * 1000  # 5 minutes
COUNTDOWN_INTERVAL_MS = 1000  # 1 second


@dataclass
class UsageEntry:
    utilization: float = 0.0
    resets_at: str = ""

    @property
    def reset_dt(self) -> datetime | None:
        if not self.resets_at:
            return None
        try:
            return datetime.fromisoformat(self.resets_at)
        except ValueError:
            return None

    def time_remaining(self) -> str:
        dt = self.reset_dt
        if dt is None:
            return "—"
        now = datetime.now(timezone.utc)
        delta = dt - now
        total_seconds = int(delta.total_seconds())
        if total_seconds <= 0:
            return "now"
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"


@dataclass
class UsageData:
    five_hour: UsageEntry = field(default_factory=UsageEntry)
    seven_day: UsageEntry = field(default_factory=UsageEntry)
    seven_day_sonnet: UsageEntry | None = None
    seven_day_opus: UsageEntry | None = None
    extra_usage_enabled: bool = False
    error: str = ""
    fetched_at: float = 0.0


def _parse_entry(data: dict | None) -> UsageEntry | None:
    if data is None:
        return None
    return UsageEntry(
        utilization=float(data.get("utilization", 0)),
        resets_at=data.get("resets_at", ""),
    )


class ClaudeUsageClient:
    """Reads OAuth credentials and fetches usage data."""

    def _read_credentials(self) -> dict | None:
        try:
            with open(CREDENTIALS_PATH) as f:
                return json.load(f).get("claudeAiOauth")
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return None

    def _refresh_token(self, refresh_token: str) -> dict | None:
        try:
            resp = requests.post(
                TOKEN_URL,
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                },
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def fetch(self) -> UsageData:
        creds = self._read_credentials()
        if creds is None:
            return UsageData(error="Not Logged In")

        token = creds.get("accessToken", "")
        if not token:
            return UsageData(error="Not Logged In")

        # Check if token is near expiry and refresh if needed
        expires_at = creds.get("expiresAt", 0)
        if expires_at and (time.time() * 1000 + 300_000) >= expires_at:
            # Re-read in case Claude Code already refreshed
            creds = self._read_credentials()
            if creds:
                token = creds.get("accessToken", "")
                expires_at = creds.get("expiresAt", 0)
                if (time.time() * 1000 + 300_000) >= expires_at:
                    refresh_token = creds.get("refreshToken", "")
                    if refresh_token:
                        result = self._refresh_token(refresh_token)
                        if result and "access_token" in result:
                            token = result["access_token"]
                        else:
                            # Re-read one more time in case Claude Code refreshed
                            creds = self._read_credentials()
                            if creds:
                                token = creds.get("accessToken", "")

        try:
            resp = requests.get(
                USAGE_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": OAUTH_BETA,
                    "x-app": "cli",
                },
                timeout=15,
            )
            if resp.status_code == 401:
                return UsageData(error="Session Expired")
            if resp.status_code != 200:
                return UsageData(error=f"API Error ({resp.status_code})")
            data = resp.json()
        except requests.RequestException:
            return UsageData(error="Offline")
        except (json.JSONDecodeError, ValueError):
            return UsageData(error="Data Unavailable")

        return UsageData(
            five_hour=_parse_entry(data.get("five_hour")) or UsageEntry(),
            seven_day=_parse_entry(data.get("seven_day")) or UsageEntry(),
            seven_day_sonnet=_parse_entry(data.get("seven_day_sonnet")),
            seven_day_opus=_parse_entry(data.get("seven_day_opus")),
            extra_usage_enabled=bool(
                data.get("extra_usage", {}).get("is_enabled", False)
            ),
            fetched_at=time.time(),
        )


class FetchWorker(QThread):
    finished = Signal(UsageData)

    def __init__(self, client: ClaudeUsageClient):
        super().__init__()
        self.client = client

    def run(self):
        data = self.client.fetch()
        self.finished.emit(data)


def _bar_color(pct: float) -> QColor:
    if pct >= 90:
        return QColor(239, 68, 68)  # red
    if pct >= 75:
        return QColor(249, 115, 22)  # orange
    if pct >= 50:
        return QColor(234, 179, 8)  # yellow
    return QColor(34, 197, 94)  # green


class UsageBar(QWidget):
    """Single usage bar with label, progress, percentage, and countdown."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self._pct = 0.0
        self._time_str = "—"
        self.setFixedHeight(44)

    def set_data(self, pct: float, time_str: str):
        self._pct = pct
        self._time_str = time_str
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        # Label
        label_font = QFont("sans-serif", 9)
        label_font.setWeight(QFont.Weight.Medium)
        p.setFont(label_font)
        p.setPen(QColor(160, 160, 180))
        p.drawText(0, 14, self._label)

        # Percentage text (right-aligned on the label line)
        pct_text = f"{self._pct:.0f}%"
        p.setPen(QColor(200, 200, 220))
        fm = p.fontMetrics()
        pct_w = fm.horizontalAdvance(pct_text)

        # Reset countdown (far right)
        reset_text = f"Resets: {self._time_str}"
        reset_w = fm.horizontalAdvance(reset_text)
        p.setPen(QColor(120, 120, 140))
        p.drawText(w - reset_w, 14, reset_text)

        # Percentage just left of reset
        p.setPen(_bar_color(self._pct))
        p.drawText(w - reset_w - pct_w - 12, 14, pct_text)

        # Progress bar background
        bar_y = 22
        bar_h = 14
        bar_radius = 7
        bg_path = QPainterPath()
        bg_path.addRoundedRect(0, bar_y, w, bar_h, bar_radius, bar_radius)
        p.fillPath(bg_path, QColor(40, 40, 55))

        # Progress bar fill
        fill_w = max(bar_h, w * self._pct / 100)  # min width = height for rounded ends
        fill_path = QPainterPath()
        fill_path.addRoundedRect(0, bar_y, fill_w, bar_h, bar_radius, bar_radius)
        p.fillPath(fill_path, _bar_color(self._pct))

        p.end()


class ClaudeWidget(QWidget):
    """Translucent always-on-top widget displaying Claude Max usage."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(340, 280)

        self._drag_pos = QPoint()
        self._usage: UsageData | None = None
        self._client = ClaudeUsageClient()
        self._worker: FetchWorker | None = None

        self._build_ui()
        self._setup_timers()
        self._fetch_usage()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        title = QLabel("CLAUDE MAX")
        title_font = QFont("sans-serif", 13)
        title_font.setWeight(QFont.Weight.Bold)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        title.setFont(title_font)
        title.setStyleSheet("color: #d4a574;")  # warm gold
        header.addWidget(title)
        header.addStretch()

        # Close button
        close_btn = QLabel("✕")
        close_btn.setStyleSheet(
            "color: #666680; font-size: 14px; padding: 2px 6px;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.mousePressEvent = lambda _: self.close()
        header.addWidget(close_btn)

        layout.addLayout(header)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: rgba(100, 100, 120, 80);")
        layout.addWidget(sep)
        layout.addSpacing(4)

        # Usage bars
        self._five_hour_bar = UsageBar("5-Hour Window")
        layout.addWidget(self._five_hour_bar)
        layout.addSpacing(2)

        self._seven_day_bar = UsageBar("7-Day Window")
        layout.addWidget(self._seven_day_bar)
        layout.addSpacing(2)

        self._model_bar = UsageBar("Sonnet (7-Day)")
        layout.addWidget(self._model_bar)

        layout.addSpacing(2)

        # Bottom separator
        sep2 = QWidget()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background-color: rgba(100, 100, 120, 80);")
        layout.addWidget(sep2)

        # Status row
        status_layout = QHBoxLayout()
        self._status_label = QLabel("Fetching...")
        self._status_label.setStyleSheet("color: #666680; font-size: 10px;")
        status_layout.addWidget(self._status_label)
        status_layout.addStretch()

        refresh_btn = QLabel("⟳")
        refresh_btn.setStyleSheet(
            "color: #666680; font-size: 16px; padding: 0 4px;"
        )
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.mousePressEvent = lambda _: self._fetch_usage()
        status_layout.addWidget(refresh_btn)

        layout.addLayout(status_layout)

    def _setup_timers(self):
        # Fetch timer - every 5 minutes
        self._fetch_timer = QTimer(self)
        self._fetch_timer.timeout.connect(self._fetch_usage)
        self._fetch_timer.start(REFRESH_INTERVAL_MS)

        # Countdown timer - every second
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdowns)
        self._countdown_timer.start(COUNTDOWN_INTERVAL_MS)

    def _fetch_usage(self):
        if self._worker and self._worker.isRunning():
            return
        self._worker = FetchWorker(self._client)
        self._worker.finished.connect(self._on_usage_fetched)
        self._worker.start()

    def _on_usage_fetched(self, data: UsageData):
        self._usage = data
        self._update_display()

    def _update_display(self):
        data = self._usage
        if data is None:
            return

        if data.error:
            self._status_label.setText(data.error)
            self._status_label.setStyleSheet("color: #ef4444; font-size: 10px;")
            return

        self._status_label.setStyleSheet("color: #666680; font-size: 10px;")

        self._five_hour_bar.set_data(
            data.five_hour.utilization,
            data.five_hour.time_remaining(),
        )
        self._seven_day_bar.set_data(
            data.seven_day.utilization,
            data.seven_day.time_remaining(),
        )

        # Show opus or sonnet model-specific limit, whichever exists
        if data.seven_day_opus:
            self._model_bar._label = "Opus (7-Day)"
            self._model_bar.set_data(
                data.seven_day_opus.utilization,
                data.seven_day_opus.time_remaining(),
            )
            self._model_bar.show()
        elif data.seven_day_sonnet:
            self._model_bar._label = "Sonnet (7-Day)"
            self._model_bar.set_data(
                data.seven_day_sonnet.utilization,
                data.seven_day_sonnet.time_remaining(),
            )
            self._model_bar.show()
        else:
            self._model_bar.hide()

        # Updated time
        elapsed = int(time.time() - data.fetched_at)
        if elapsed < 60:
            self._status_label.setText("Updated: just now")
        else:
            mins = elapsed // 60
            self._status_label.setText(f"Updated: {mins}m ago")

    def _update_countdowns(self):
        """Update countdown strings every second without re-fetching."""
        if self._usage and not self._usage.error:
            self._update_display()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dark translucent background
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 16, 16)
        p.fillPath(path, QColor(20, 20, 30, 200))

        # Subtle border
        p.setPen(QPen(QColor(80, 80, 100, 60), 1))
        p.drawPath(path)

        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Claude Usage Widget")

    widget = ClaudeWidget()
    widget.show()

    # Position at top-right of screen with some padding
    screen = app.primaryScreen().geometry()
    widget.move(screen.width() - widget.width() - 20, 40)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
