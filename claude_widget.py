#!/usr/bin/env python3
"""Translucent desktop widget showing Claude Code Max subscription usage."""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from PySide6.QtCore import QPoint, QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_BETA = "oauth-2025-04-20"
REFRESH_INTERVAL_MS = 60 * 1000  # 60 seconds
COUNTDOWN_INTERVAL_MS = 1000  # 1 second
HISTORY_PATH = Path.home() / ".claude" / "usage_history.json"
MAX_HISTORY_AGE_S = 24 * 3600  # 24 hours
MAX_HISTORY_POINTS = 1440  # 24h at 60-sec intervals


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

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

    @property
    def plan_name(self) -> str:
        if self.seven_day_opus is not None:
            return "CLAUDE MAX"
        if self.seven_day_sonnet is not None:
            return "CLAUDE PRO"
        return "CLAUDE"

    @property
    def model_name(self) -> str:
        if self.seven_day_opus is not None:
            return "opus"
        if self.seven_day_sonnet is not None:
            return "sonnet"
        return "unknown"

    @property
    def model_pct(self) -> float:
        if self.seven_day_opus is not None:
            return self.seven_day_opus.utilization
        if self.seven_day_sonnet is not None:
            return self.seven_day_sonnet.utilization
        return 0.0


# ---------------------------------------------------------------------------
# History persistence
# ---------------------------------------------------------------------------

@dataclass
class HistoryPoint:
    timestamp: float
    five_hour_pct: float
    seven_day_pct: float
    model_pct: float
    model_name: str


class UsageHistory:
    """Stores usage data points to disk for graphing."""

    def __init__(self, path: Path = HISTORY_PATH):
        self._path = path
        self.points: list[HistoryPoint] = []
        self._load()

    def _load(self):
        try:
            with open(self._path) as f:
                raw = json.load(f)
            self.points = [
                HistoryPoint(
                    timestamp=p["timestamp"],
                    five_hour_pct=p["five_hour_pct"],
                    seven_day_pct=p["seven_day_pct"],
                    model_pct=p["model_pct"],
                    model_name=p.get("model_name", "unknown"),
                )
                for p in raw
            ]
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
            self.points = []

    def add(self, data: UsageData):
        if data.error:
            return
        pt = HistoryPoint(
            timestamp=data.fetched_at,
            five_hour_pct=data.five_hour.utilization,
            seven_day_pct=data.seven_day.utilization,
            model_pct=data.model_pct,
            model_name=data.model_name,
        )
        self.points.append(pt)
        self._prune()
        self._save()

    def _prune(self):
        cutoff = time.time() - MAX_HISTORY_AGE_S
        self.points = [p for p in self.points if p.timestamp >= cutoff]
        if len(self.points) > MAX_HISTORY_POINTS:
            self.points = self.points[-MAX_HISTORY_POINTS:]

    def _save(self):
        data = [
            {
                "timestamp": p.timestamp,
                "five_hour_pct": p.five_hour_pct,
                "seven_day_pct": p.seven_day_pct,
                "model_pct": p.model_pct,
                "model_name": p.model_name,
            }
            for p in self.points
        ]
        tmp_path = self._path.with_suffix(".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "w") as f:
                json.dump(data, f)
            os.replace(tmp_path, self._path)
        except OSError:
            pass

    @property
    def avg_five_hour(self) -> float:
        if not self.points:
            return 0.0
        return sum(p.five_hour_pct for p in self.points) / len(self.points)

    @property
    def peak_five_hour(self) -> float:
        if not self.points:
            return 0.0
        return max(p.five_hour_pct for p in self.points)

    @property
    def trend(self) -> str:
        """Compare last 3 vs prior 3 data points. Returns arrow."""
        if len(self.points) < 6:
            return "—"
        recent = sum(p.five_hour_pct for p in self.points[-3:]) / 3
        prior = sum(p.five_hour_pct for p in self.points[-6:-3]) / 3
        diff = recent - prior
        if diff > 2:
            return "↑"
        if diff < -2:
            return "↓"
        return "→"


def _parse_entry(data: dict | None) -> UsageEntry | None:
    if data is None:
        return None
    return UsageEntry(
        utilization=float(data.get("utilization", 0)),
        resets_at=data.get("resets_at", ""),
    )


# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

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


class UsageGraph(QWidget):
    """Line chart showing 5-hour utilization with selectable time window."""

    ACCENT = QColor(139, 92, 246)  # #8b5cf6 purple

    # (label, duration_seconds, x-axis ticks as (label, seconds_ago))
    WINDOWS = [
        ("30m", 30 * 60, [("-30m", 30), ("-20m", 20), ("-10m", 10), ("now", 0)]),
        ("5h", 5 * 3600, [("-5h", 5), ("-4h", 4), ("-3h", 3), ("-2h", 2), ("-1h", 1), ("now", 0)]),
        ("24h", MAX_HISTORY_AGE_S, [("-24h", 24), ("-18h", 18), ("-12h", 12), ("-6h", 6), ("now", 0)]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(110)
        self._points: list[HistoryPoint] = []
        self._window_idx = 2  # default to 24h

    @property
    def _window(self):
        return self.WINDOWS[self._window_idx]

    def set_window(self, idx: int):
        self._window_idx = idx
        self.update()

    def set_points(self, points: list[HistoryPoint]):
        self._points = points
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        # Margins for axes labels
        left_m = 30
        right_m = 8
        top_m = 4
        bottom_m = 16
        chart_w = w - left_m - right_m
        chart_h = h - top_m - bottom_m

        tiny_font = QFont("sans-serif", 7)
        p.setFont(tiny_font)
        fm = p.fontMetrics()

        # Y-axis labels & grid lines
        dim_pen = QPen(QColor(60, 60, 80), 1, Qt.PenStyle.SolidLine)
        for pct in (25, 50, 75):
            y = top_m + chart_h * (1 - pct / 100)
            p.setPen(dim_pen)
            p.drawLine(left_m, int(y), w - right_m, int(y))
            p.setPen(QColor(100, 100, 120))
            label = f"{pct}%"
            lw = fm.horizontalAdvance(label)
            p.drawText(left_m - lw - 4, int(y) + fm.ascent() // 2, label)

        # 80% threshold dashed line
        threshold_y = top_m + chart_h * (1 - 80 / 100)
        dash_pen = QPen(QColor(239, 68, 68, 100), 1, Qt.PenStyle.DashLine)
        p.setPen(dash_pen)
        p.drawLine(left_m, int(threshold_y), w - right_m, int(threshold_y))

        now = time.time()
        _, duration_s, ticks = self._window
        t_start = now - duration_s

        # X-axis tick labels
        p.setPen(QColor(100, 100, 120))
        is_minutes = duration_s <= 3600  # 30m window uses minutes
        for label, ago in ticks:
            if is_minutes:
                t = now - ago * 60
            else:
                t = now - ago * 3600
            x = left_m + chart_w * ((t - t_start) / duration_s)
            lw = fm.horizontalAdvance(label)
            p.drawText(int(x - lw // 2), h - 2, label)

        # Filter points to current window
        visible = [pt for pt in self._points if pt.timestamp >= t_start]

        # Not enough data placeholder
        if len(visible) < 2:
            p.setPen(QColor(100, 100, 120))
            placeholder_font = QFont("sans-serif", 9)
            p.setFont(placeholder_font)
            text = "Collecting data..."
            tw = p.fontMetrics().horizontalAdvance(text)
            p.drawText(left_m + (chart_w - tw) // 2, top_m + chart_h // 2, text)
            p.end()
            return

        # Build path from points
        def to_xy(pt: HistoryPoint):
            x = left_m + chart_w * ((pt.timestamp - t_start) / duration_s)
            y = top_m + chart_h * (1 - pt.five_hour_pct / 100)
            return x, y

        line_path = QPainterPath()
        fill_path = QPainterPath()
        first_x, first_y = to_xy(visible[0])
        line_path.moveTo(first_x, first_y)
        fill_path.moveTo(first_x, top_m + chart_h)  # bottom
        fill_path.lineTo(first_x, first_y)

        last_x, last_y = first_x, first_y
        for pt in visible[1:]:
            x, y = to_xy(pt)
            line_path.lineTo(x, y)
            fill_path.lineTo(x, y)
            last_x, last_y = x, y

        # Close fill path along bottom
        fill_path.lineTo(last_x, top_m + chart_h)
        fill_path.closeSubpath()

        # Gradient fill
        grad = QLinearGradient(0, top_m, 0, top_m + chart_h)
        grad.setColorAt(0, QColor(139, 92, 246, 50))
        grad.setColorAt(1, QColor(139, 92, 246, 5))
        p.fillPath(fill_path, grad)

        # Line
        line_pen = QPen(self.ACCENT, 2)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(line_pen)
        p.drawPath(line_path)

        # Current value dot
        p.setBrush(self.ACCENT)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(last_x - 3, last_y - 3, 6, 6))

        p.end()


class StatsRow(QWidget):
    """Compact row showing AVG, PEAK, TREND, and EXTRA status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        self._avg = 0.0
        self._peak = 0.0
        self._trend = "—"
        self._extra = False

    def set_data(self, avg: float, peak: float, trend: str, extra: bool):
        self._avg = avg
        self._peak = peak
        self._trend = trend
        self._extra = extra
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)

        col_w = w // 4
        y = 14

        # AVG
        p.setPen(QColor(100, 100, 120))
        p.drawText(4, y, "AVG:")
        avg_x = p.fontMetrics().horizontalAdvance("AVG: ") + 4
        p.setPen(QColor(180, 180, 200))
        p.drawText(avg_x, y, f"{self._avg:.0f}%")

        # PEAK
        x2 = col_w
        p.setPen(QColor(100, 100, 120))
        p.drawText(x2, y, "PEAK:")
        peak_x = x2 + p.fontMetrics().horizontalAdvance("PEAK: ")
        p.setPen(_bar_color(self._peak))
        p.drawText(peak_x, y, f"{self._peak:.0f}%")

        # TREND
        x3 = col_w * 2
        p.setPen(QColor(100, 100, 120))
        p.drawText(x3, y, "TREND:")
        trend_x = x3 + p.fontMetrics().horizontalAdvance("TREND: ")
        trend_color = QColor(34, 197, 94) if self._trend == "↓" else (
            QColor(239, 68, 68) if self._trend == "↑" else QColor(180, 180, 200)
        )
        p.setPen(trend_color)
        p.drawText(trend_x, y, self._trend)

        # EXTRA
        x4 = col_w * 3
        p.setPen(QColor(100, 100, 120))
        p.drawText(x4, y, "EXT:")
        ext_x = x4 + p.fontMetrics().horizontalAdvance("EXT: ")
        ext_text = "ON" if self._extra else "OFF"
        ext_color = QColor(34, 197, 94) if self._extra else QColor(160, 160, 180)
        p.setPen(ext_color)
        p.drawText(ext_x, y, ext_text)

        p.end()


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

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
        self.setFixedSize(340, 420)

        self._drag_pos = QPoint()
        self._usage: UsageData | None = None
        self._client = ClaudeUsageClient()
        self._worker: FetchWorker | None = None
        self._history = UsageHistory()
        self._next_fetch_at: float = 0.0

        self._build_ui()
        self._setup_timers()
        self._fetch_usage()

        # Initialize graph with persisted history
        if self._history.points:
            self._graph.set_points(self._history.points)
            self._stats_row.set_data(
                self._history.avg_five_hour,
                self._history.peak_five_hour,
                self._history.trend,
                False,
            )

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        self._title_label = QLabel("CLAUDE")
        title_font = QFont("sans-serif", 13)
        title_font.setWeight(QFont.Weight.Bold)
        title_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        self._title_label.setFont(title_font)
        self._title_label.setStyleSheet("color: #d4a574;")  # warm gold
        header.addWidget(self._title_label)
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

        # Graph separator
        sep_g = QWidget()
        sep_g.setFixedHeight(1)
        sep_g.setStyleSheet("background-color: rgba(100, 100, 120, 80);")
        layout.addWidget(sep_g)
        layout.addSpacing(2)

        # Graph header with window tabs
        graph_header = QHBoxLayout()
        graph_title = QLabel("Usage History")
        graph_title.setStyleSheet("color: #666680; font-size: 9px;")
        graph_header.addWidget(graph_title)
        graph_header.addStretch()

        self._window_labels: list[QLabel] = []
        for i, (wlabel, _, _) in enumerate(UsageGraph.WINDOWS):
            tab = QLabel(wlabel)
            tab.setCursor(Qt.CursorShape.PointingHandCursor)
            tab.mousePressEvent = lambda _, idx=i: self._set_graph_window(idx)
            self._window_labels.append(tab)
            graph_header.addWidget(tab)
            if i < len(UsageGraph.WINDOWS) - 1:
                spacer = QLabel("·")
                spacer.setStyleSheet("color: #444460; font-size: 9px; padding: 0 1px;")
                graph_header.addWidget(spacer)

        layout.addLayout(graph_header)

        # Usage graph
        self._graph = UsageGraph()
        layout.addWidget(self._graph)
        self._update_window_tabs()

        layout.addSpacing(2)

        # Stats separator
        sep_s = QWidget()
        sep_s.setFixedHeight(1)
        sep_s.setStyleSheet("background-color: rgba(100, 100, 120, 80);")
        layout.addWidget(sep_s)
        layout.addSpacing(2)

        # Stats row
        self._stats_row = StatsRow()
        layout.addWidget(self._stats_row)

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
        self._next_fetch_at = time.time() + REFRESH_INTERVAL_MS / 1000
        self._worker = FetchWorker(self._client)
        self._worker.finished.connect(self._on_usage_fetched)
        self._worker.start()

    def _on_usage_fetched(self, data: UsageData):
        self._usage = data

        if not data.error:
            # Update title with detected plan name
            self._title_label.setText(data.plan_name)

            # Persist history and update graph/stats
            self._history.add(data)
            self._graph.set_points(self._history.points)
            self._stats_row.set_data(
                self._history.avg_five_hour,
                self._history.peak_five_hour,
                self._history.trend,
                data.extra_usage_enabled,
            )

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

        # Updated time + next update countdown
        remaining = max(0, int(self._next_fetch_at - time.time()))
        self._status_label.setText(f"Updated: just now  ·  Next: {remaining}s")

    def _set_graph_window(self, idx: int):
        self._graph.set_window(idx)
        self._update_window_tabs()

    def _update_window_tabs(self):
        active_idx = self._graph._window_idx
        for i, tab in enumerate(self._window_labels):
            if i == active_idx:
                tab.setStyleSheet(
                    "color: #8b5cf6; font-size: 9px; font-weight: bold; padding: 0 2px;"
                )
            else:
                tab.setStyleSheet(
                    "color: #555570; font-size: 9px; padding: 0 2px;"
                )

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
