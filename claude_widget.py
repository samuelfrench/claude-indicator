#!/usr/bin/env python3
"""Translucent desktop widget showing Claude usage plus local Codex totals."""

import getpass
import json
import os
import re
import select
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from PySide6.QtCore import QPoint, QRectF, QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from smart_todos import SmartTodoDialog

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
CODEX_HOME = Path.home() / ".codex"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_BETA = "oauth-2025-04-20"
REFRESH_INTERVAL_MS = 5 * 60 * 1000  # 5 minutes
DEPLOY_REFRESH_MS = 5 * 60 * 1000  # 5 minutes
COUNTDOWN_INTERVAL_MS = 1000  # 1 second
HISTORY_PATH = Path.home() / ".claude" / "usage_history.json"
LAST_USAGE_PATH = Path.home() / ".claude" / "last_usage.json"
RATE_LIMIT_STATE_PATH = Path.home() / ".claude" / "widget_rate_limit.json"
LOG_PATH = Path.home() / ".claude" / "widget.log"
STATS_CACHE_PATH = Path.home() / ".claude" / "stats-cache.json"
MAX_HISTORY_AGE_S = 24 * 3600  # 24 hours
MAX_HISTORY_POINTS = 1440  # 24h at 60-sec intervals
SYSTEM_METRICS_INTERVAL_MS = 3000  # 3 seconds
RUNNER_REFRESH_MS = 60 * 1000  # 60 seconds
TASK_LOOP_REFRESH_MS = 60 * 1000  # 60 seconds
TASK_GROUP_REFRESH_MS = 60 * 1000  # 60 seconds
CODEX_REFRESH_MS = 60 * 1000  # 1 minute; avoid repeatedly starting app-server
TRAY_RETRY_INTERVAL_MS = 5 * 1000  # retry while the desktop tray host is absent
CRON_REFRESH_MS = 5 * 60 * 1000  # 5 minutes — crontab/journal state changes slowly
CRON_JOURNAL_WINDOW_HOURS = 48
CRON_LATE_GRACE_S = 180  # allow journal lag before flagging a run as missed
CODEX_SESSIONS_DIR = CODEX_HOME / "sessions"
CODEX_RATE_LIMIT_SCAN_FILES = 20
CODEX_RATE_LIMIT_TAIL_BYTES = 4 * 1024 * 1024
CODEX_APP_SERVER_TIMEOUT_S = 3.0
CODEX_APP_SERVER_STOP_TIMEOUT_S = 0.5
# A cached event may cover at most five missed one-minute live polls. Older or
# already-reset values are omitted instead of being presented as current usage.
CODEX_CACHED_RATE_LIMIT_MAX_AGE_S = 5 * 60
# Rate-limit backoff: /api/oauth/usage rate-limits aggressively (GH anthropics/claude-code#31637)
RATE_LIMIT_MIN_BACKOFF_S = 60        # 1 minute after first 429
RATE_LIMIT_MAX_BACKOFF_S = 32 * 60   # 32 minute cap


def build_task_compass_icon(size: int = 64) -> QIcon:
    """Build the tray's task-compass mark at the requested square size."""
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    scale = size / 64.0
    ring_width = max(1.5, 5.0 * scale)
    inset = ring_width / 2.0 + max(1.0, 2.0 * scale)
    field = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    painter.setBrush(QColor("#14141E"))
    painter.setPen(QPen(QColor("#D4A574"), ring_width))
    painter.drawEllipse(field)

    check = QPainterPath()
    check.moveTo(17 * scale, 33 * scale)
    check.lineTo(27 * scale, 43 * scale)
    check.lineTo(44 * scale, 23 * scale)
    check_pen = QPen(QColor("#FFFFFF"), max(1.5, 4.5 * scale))
    check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(check_pen)
    painter.drawPath(check)

    needle_pen = QPen(QColor("#8B5CF6"), max(1.25, 3.5 * scale))
    needle_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(needle_pen)
    painter.drawLine(
        int(38 * scale),
        int(27 * scale),
        int(49 * scale),
        int(16 * scale),
    )
    needle = QPainterPath()
    needle.moveTo(49 * scale, 16 * scale)
    needle.lineTo(47 * scale, 25 * scale)
    needle.moveTo(49 * scale, 16 * scale)
    needle.lineTo(40 * scale, 18 * scale)
    painter.drawPath(needle)
    painter.end()
    return QIcon(px)


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
class ModelLimit:
    """A usage limit scoped to one model (e.g. the Fable weekly cap)."""

    name: str    # display name from the API scope, e.g. "Fable"
    window: str  # window label for the bar, e.g. "7-Day"
    entry: UsageEntry = field(default_factory=UsageEntry)


@dataclass
class UsageData:
    five_hour: UsageEntry = field(default_factory=UsageEntry)
    seven_day: UsageEntry = field(default_factory=UsageEntry)
    seven_day_sonnet: UsageEntry | None = None
    seven_day_opus: UsageEntry | None = None
    model_limits: list[ModelLimit] = field(default_factory=list)
    extra_usage_enabled: bool = False
    extra_usage_utilization: float | None = None
    extra_usage_used_credits: float | None = None
    extra_usage_monthly_limit: float | None = None
    error: str = ""
    fetched_at: float = 0.0
    retry_after_s: float = 0.0  # From 429 Retry-After header

    @property
    def plan_name(self) -> str:
        if self.seven_day_opus is not None:
            return "CLAUDE MAX"
        if self.seven_day_sonnet is not None:
            return "CLAUDE PRO"
        return "CLAUDE"

    @property
    def display_model_limits(self) -> list[ModelLimit]:
        """Scoped limits from the API plus legacy opus/sonnet keys, deduped."""
        limits = list(self.model_limits)
        seen = {ml.name.lower() for ml in limits}
        for name, entry in (
            ("Opus", self.seven_day_opus),
            ("Sonnet", self.seven_day_sonnet),
        ):
            if entry is not None and name.lower() not in seen:
                limits.append(ModelLimit(name=name, window="7-Day", entry=entry))
                seen.add(name.lower())
        return limits

    @property
    def model_name(self) -> str:
        limits = self.display_model_limits
        if limits:
            return limits[0].name.lower()
        return "unknown"

    @property
    def model_pct(self) -> float:
        limits = self.display_model_limits
        if limits:
            return limits[0].entry.utilization
        return 0.0


@dataclass
class DeployInfo:
    project_name: str      # e.g. "coffee-explorer"
    repo_slug: str         # e.g. "owner/coffee-explorer"
    last_deploy_at: str    # ISO 8601 timestamp or ""
    workflow_name: str     # e.g. "Deploy"
    error: str             # "" if ok, error message otherwise

    def relative_time(self) -> str:
        if self.error:
            return self.error
        if not self.last_deploy_at:
            return "no runs"
        try:
            dt = datetime.fromisoformat(self.last_deploy_at.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - dt
            secs = int(delta.total_seconds())
            if secs < 60:
                return "just now"
            if secs < 3600:
                return f"{secs // 60}m ago"
            if secs < 86400:
                return f"{secs // 3600}h ago"
            return f"{secs // 86400}d ago"
        except (ValueError, TypeError):
            return "unknown"


@dataclass
class RunnerInfo:
    name: str           # runner agent name
    target: str         # repo slug (owner/repo) or org name
    status: str         # "online", "offline", "active"
    labels: list[str] = field(default_factory=list)
    runner_dir: str = ""
    error: str = ""


@dataclass
class TaskLoopInfo:
    name: str            # project name
    model: str           # e.g. "claude-sonnet-4-6"
    effort: str          # e.g. "xhigh"
    cooldown_minutes: int
    last_task_ts: float | None = None   # Unix timestamp of last completed task, or None
    error: str = ""

    def next_run_str(self) -> str:
        if self.last_task_ts is None:
            return "last run: unknown"
        elapsed = time.time() - self.last_task_ts
        remaining = self.cooldown_minutes * 60 - elapsed
        if remaining <= 0:
            return "next run: any time"
        mins = int(remaining // 60)
        secs = int(remaining % 60)
        if mins >= 60:
            return f"next run: ~{mins // 60}h {mins % 60}m"
        if mins > 0:
            return f"next run: ~{mins}m"
        return f"next run: ~{secs}s"


@dataclass
class TaskGroupInfo:
    """Path-scoped activity tracker — last commit timestamp for files under a sub-path."""
    label: str
    last_activity_ts: float | None = None
    error: str = ""

    def status_str(self) -> str:
        if self.error:
            return self.error
        if self.last_activity_ts is None:
            return "no activity"
        elapsed = time.time() - self.last_activity_ts
        if elapsed < 60:
            return "just now"
        if elapsed < 3600:
            return f"{int(elapsed // 60)}m ago"
        if elapsed < 86400:
            return f"{int(elapsed // 3600)}h ago"
        return f"{int(elapsed // 86400)}d ago"


@dataclass
class CronJobInfo:
    """One user crontab entry plus run history recovered from the journal."""
    label: str
    schedule: str
    command: str
    last_run_ts: float | None = None
    runs_24h: int = 0
    next_run_ts: float | None = None
    status: str = "unknown"  # ok | late | unknown
    error: str = ""

    def last_run_str(self) -> str:
        if self.last_run_ts is None:
            return "no runs" if self.status == "late" else "n/a"
        elapsed = time.time() - self.last_run_ts
        if elapsed < 60:
            return "just now"
        if elapsed < 3600:
            return f"{int(elapsed // 60)}m ago"
        if elapsed < 86400:
            return f"{int(elapsed // 3600)}h ago"
        return f"{int(elapsed // 86400)}d ago"

    def next_run_str(self) -> str:
        if self.next_run_ts is None:
            return ""
        remaining = self.next_run_ts - time.time()
        if remaining <= 0:
            return "next: now"
        if remaining < 3600:
            return f"next {int(remaining // 60)}m"
        if remaining < 86400:
            return f"next {int(remaining // 3600)}h"
        return f"next {int(remaining // 86400)}d"


@dataclass
class SystemMetrics:
    cpu_pct: float = 0.0
    mem_used_gb: float = 0.0
    mem_total_gb: float = 0.0
    gpu_pct: float = 0.0
    gpu_mem_used_gb: float = 0.0
    gpu_mem_total_gb: float = 0.0
    gpu_temp: int = 0
    gpu_available: bool = False


@dataclass
class CodexUsageSummary:
    latest_thread_tokens: int = 0
    total_tokens: int = 0
    thread_count: int = 0
    latest_thread_title: str = ""
    latest_model: str = ""
    latest_updated_at: int = 0
    latest_cwd: str = ""
    primary_limit_used_percent: float | None = None
    primary_limit_window_minutes: int = 0
    primary_limit_resets_at: int = 0
    secondary_limit_used_percent: float | None = None
    secondary_limit_window_minutes: int = 0
    secondary_limit_resets_at: int = 0
    plan_type: str = ""
    rate_limit_reached_type: str = ""
    rate_limit_source: str = ""
    rate_limit_observed_at: float = 0.0


@dataclass
class CodexRateLimit:
    primary_used_percent: float | None = None
    primary_window_minutes: int = 0
    primary_resets_at: int = 0
    secondary_used_percent: float | None = None
    secondary_window_minutes: int = 0
    secondary_resets_at: int = 0
    plan_type: str = ""
    rate_limit_reached_type: str = ""
    source: str = ""
    observed_at: float = 0.0


class SystemMetricsReader:
    """Reads CPU, RAM, and GPU metrics from /proc and nvidia-smi."""

    def __init__(self):
        self._prev_cpu: list[int] | None = None
        self._gpu_available = False
        # Seed CPU baseline
        try:
            self._prev_cpu = self._read_cpu_times()
        except OSError:
            pass
        # Check nvidia-smi availability once
        try:
            subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, timeout=3,
            )
            self._gpu_available = True
        except (FileNotFoundError, subprocess.SubprocessError):
            self._gpu_available = False

    @staticmethod
    def _read_cpu_times() -> list[int]:
        with open("/proc/stat") as f:
            line = f.readline()  # first line: cpu  user nice system idle ...
        parts = line.split()
        # user nice system idle iowait irq softirq steal
        return [int(x) for x in parts[1:9]]

    def read(self) -> SystemMetrics:
        m = SystemMetrics()

        # CPU
        try:
            cur = self._read_cpu_times()
            if self._prev_cpu:
                prev_total = sum(self._prev_cpu)
                cur_total = sum(cur)
                prev_idle = self._prev_cpu[3]  # idle is index 3
                cur_idle = cur[3]
                total_d = cur_total - prev_total
                idle_d = cur_idle - prev_idle
                if total_d > 0:
                    m.cpu_pct = 100.0 * (1 - idle_d / total_d)
            self._prev_cpu = cur
        except OSError:
            pass

        # RAM
        try:
            with open("/proc/meminfo") as f:
                meminfo = {}
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        meminfo[parts[0].rstrip(":")] = int(parts[1])
            total_kb = meminfo.get("MemTotal", 0)
            avail_kb = meminfo.get("MemAvailable", 0)
            m.mem_total_gb = total_kb / (1024 * 1024)
            m.mem_used_gb = (total_kb - avail_kb) / (1024 * 1024)
        except (OSError, ValueError):
            pass

        # GPU
        m.gpu_available = self._gpu_available
        if self._gpu_available:
            try:
                result = subprocess.run(
                    ["nvidia-smi",
                     "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0:
                    vals = result.stdout.strip().split(",")
                    if len(vals) >= 4:
                        m.gpu_pct = float(vals[0].strip())
                        m.gpu_mem_used_gb = float(vals[1].strip()) / 1024
                        m.gpu_mem_total_gb = float(vals[2].strip()) / 1024
                        m.gpu_temp = int(float(vals[3].strip()))
            except (FileNotFoundError, subprocess.SubprocessError, ValueError):
                m.gpu_available = False

        return m


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

    def estimated_time_left(self, current_pct: float) -> str:
        """Estimate time until 100% based on last 5 minutes of usage rate."""
        if not self.points or current_pct >= 100:
            return ""

        now = time.time()
        five_min_ago = now - 5 * 60
        recent = [p for p in self.points if p.timestamp >= five_min_ago]

        if len(recent) < 2:
            return ""

        oldest = recent[0]
        newest = recent[-1]
        time_delta_min = (newest.timestamp - oldest.timestamp) / 60

        if time_delta_min < 0.5:
            return ""

        rate = (newest.five_hour_pct - oldest.five_hour_pct) / time_delta_min

        if rate <= 0:
            return "not increasing"

        remaining_min = (100 - current_pct) / rate

        if remaining_min > 1440:
            return ">24h left at current rate"

        hours = int(remaining_min // 60)
        minutes = int(remaining_min % 60)

        if hours > 0:
            return f"~{hours}h {minutes}m left at current rate"
        return f"~{minutes}m left at current rate"

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


def _entry_to_dict(e: UsageEntry | None) -> dict | None:
    if e is None:
        return None
    return {"utilization": e.utilization, "resets_at": e.resets_at}


# Maps the API `limits[].group` value to the window label shown on the bar.
LIMIT_GROUP_WINDOWS = {"session": "5-Hour", "weekly": "7-Day"}


def _parse_model_limits(data: dict) -> list[ModelLimit]:
    """Extract model-scoped limits from the /api/oauth/usage `limits` array.

    Model-specific caps (e.g. the Fable weekly limit) are reported as
    entries whose scope names a model; plan-wide entries have no scope.
    """
    limits: list[ModelLimit] = []
    seen: set[str] = set()
    raw = data.get("limits")
    if not isinstance(raw, list):
        return limits
    for item in raw:
        if not isinstance(item, dict):
            continue
        scope = item.get("scope")
        model = scope.get("model") if isinstance(scope, dict) else None
        if not isinstance(model, dict):
            continue
        name = model.get("display_name") or model.get("id") or ""
        if not name or name.lower() in seen:
            continue
        group = item.get("group") or ""
        try:
            pct = float(item.get("percent") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        limits.append(
            ModelLimit(
                name=name,
                window=LIMIT_GROUP_WINDOWS.get(group, group.title()),
                entry=UsageEntry(
                    utilization=pct,
                    resets_at=item.get("resets_at") or "",
                ),
            )
        )
        seen.add(name.lower())
    return limits


def save_last_usage(data: UsageData) -> None:
    """Persist successful usage to disk so it survives widget restarts."""
    payload = {
        "five_hour": _entry_to_dict(data.five_hour),
        "seven_day": _entry_to_dict(data.seven_day),
        "seven_day_sonnet": _entry_to_dict(data.seven_day_sonnet),
        "seven_day_opus": _entry_to_dict(data.seven_day_opus),
        "model_limits": [
            {
                "name": ml.name,
                "window": ml.window,
                "entry": _entry_to_dict(ml.entry),
            }
            for ml in data.model_limits
        ],
        "extra_usage_enabled": data.extra_usage_enabled,
        "extra_usage_utilization": data.extra_usage_utilization,
        "extra_usage_used_credits": data.extra_usage_used_credits,
        "extra_usage_monthly_limit": data.extra_usage_monthly_limit,
        "fetched_at": data.fetched_at,
    }
    tmp_path = LAST_USAGE_PATH.with_suffix(".tmp")
    try:
        LAST_USAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w") as f:
            json.dump(payload, f)
        os.replace(tmp_path, LAST_USAGE_PATH)
    except OSError:
        pass


def load_last_usage() -> UsageData | None:
    """Load persisted usage from disk, if any."""
    try:
        with open(LAST_USAGE_PATH) as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    try:
        return UsageData(
            five_hour=_parse_entry(raw.get("five_hour")) or UsageEntry(),
            seven_day=_parse_entry(raw.get("seven_day")) or UsageEntry(),
            seven_day_sonnet=_parse_entry(raw.get("seven_day_sonnet")),
            seven_day_opus=_parse_entry(raw.get("seven_day_opus")),
            model_limits=[
                ModelLimit(
                    name=str(ml.get("name", "")),
                    window=str(ml.get("window", "")),
                    entry=_parse_entry(ml.get("entry")) or UsageEntry(),
                )
                for ml in raw.get("model_limits") or []
                if isinstance(ml, dict) and ml.get("name")
            ],
            extra_usage_enabled=bool(raw.get("extra_usage_enabled", False)),
            extra_usage_utilization=raw.get("extra_usage_utilization"),
            extra_usage_used_credits=raw.get("extra_usage_used_credits"),
            extra_usage_monthly_limit=raw.get("extra_usage_monthly_limit"),
            fetched_at=float(raw.get("fetched_at", 0.0)),
        )
    except (TypeError, ValueError):
        return None


def save_rate_limit_until(until_ts: float, consecutive_429s: int) -> None:
    """Persist rate-limit state so restarts don't re-hit a live window."""
    tmp = RATE_LIMIT_STATE_PATH.with_suffix(".tmp")
    try:
        RATE_LIMIT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump({"until": until_ts, "consecutive_429s": consecutive_429s}, f)
        os.replace(tmp, RATE_LIMIT_STATE_PATH)
    except OSError:
        pass


def load_rate_limit_until() -> tuple[float, int]:
    """Return (until_ts, consecutive_429s) from disk; (0, 0) if absent/stale."""
    try:
        with open(RATE_LIMIT_STATE_PATH) as f:
            raw = json.load(f)
        until = float(raw.get("until", 0.0))
        count = int(raw.get("consecutive_429s", 0))
        # If the window has already elapsed, treat as cleared.
        if until <= time.time():
            return 0.0, 0
        return until, count
    except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
        return 0.0, 0


def log_line(msg: str) -> None:
    """Append a timestamped line to ~/.claude/widget.log."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Deploy detection helpers
# ---------------------------------------------------------------------------

_GITHUB_SSH_RE = re.compile(r"git@github\.com:(.+?)(?:\.git)?$")
_GITHUB_HTTPS_RE = re.compile(r"https?://github\.com/(.+?)(?:\.git)?$")


def _parse_github_slug(remote_url: str) -> str | None:
    """Extract OWNER/REPO from a GitHub SSH or HTTPS remote URL."""
    remote_url = remote_url.strip()
    m = _GITHUB_SSH_RE.match(remote_url)
    if m:
        return m.group(1)
    m = _GITHUB_HTTPS_RE.match(remote_url)
    if m:
        return m.group(1)
    return None


def scan_claude_projects() -> list[dict]:
    """Find running Claude Code processes and resolve their project repos."""
    seen_roots: set[str] = set()
    projects: list[dict] = []

    try:
        proc_path = Path("/proc")
        if not proc_path.exists():
            return projects
        pids = [p.name for p in proc_path.iterdir() if p.name.isdigit()]
    except OSError:
        return projects

    for pid in pids:
        try:
            cmdline_path = proc_path / pid / "cmdline"
            cmdline = cmdline_path.read_bytes().decode("utf-8", errors="replace")
            # cmdline is null-separated
            if "claude" not in cmdline.lower():
                continue
            # Skip this widget process itself
            if "claude_widget" in cmdline:
                continue
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except (OSError, PermissionError):
            continue

        if cwd in seen_roots:
            continue

        # Find git root
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=cwd, capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            git_root = result.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            continue

        if git_root in seen_roots:
            continue
        seen_roots.add(git_root)

        # Get remote URL
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=git_root, capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                continue
            remote_url = result.stdout.strip()
        except (subprocess.SubprocessError, OSError):
            continue

        slug = _parse_github_slug(remote_url)
        if not slug:
            continue

        project_name = Path(git_root).name
        projects.append({
            "project_name": project_name,
            "repo_slug": slug,
            "git_root": git_root,
        })

    return projects


def fetch_deploy_info(project: dict) -> DeployInfo:
    """Query GitHub Actions for the latest successful deploy on the default branch."""
    slug = project["repo_slug"]
    name = project["project_name"]

    # Get default branch
    try:
        result = subprocess.run(
            ["gh", "repo", "view", slug, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return DeployInfo(name, slug, "", "", result.stderr.strip()[:40] or "gh error")
        default_branch = result.stdout.strip()
        if not default_branch:
            default_branch = "main"
    except FileNotFoundError:
        return DeployInfo(name, slug, "", "", "gh not found")
    except subprocess.SubprocessError:
        return DeployInfo(name, slug, "", "", "query failed")

    # Get latest successful run on default branch
    try:
        result = subprocess.run(
            ["gh", "run", "list", "-R", slug, "--status", "success",
             "--branch", default_branch, "--limit", "1",
             "--json", "updatedAt,workflowName"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return DeployInfo(name, slug, "", "", result.stderr.strip()[:40] or "gh error")

        runs = json.loads(result.stdout)
        if not runs:
            return DeployInfo(name, slug, "", "", "")

        run = runs[0]
        return DeployInfo(
            project_name=name,
            repo_slug=slug,
            last_deploy_at=run.get("updatedAt", ""),
            workflow_name=run.get("workflowName", ""),
            error="",
        )
    except (json.JSONDecodeError, KeyError):
        return DeployInfo(name, slug, "", "", "parse error")
    except subprocess.SubprocessError:
        return DeployInfo(name, slug, "", "", "query failed")


# ---------------------------------------------------------------------------
# Runner detection helpers
# ---------------------------------------------------------------------------

def scan_runner_dirs() -> list[dict]:
    """Find local GitHub Actions runner installations by scanning for .runner config files."""
    runners = []
    home = Path.home()

    for runner_file in sorted(home.glob("actions-runner*/.runner")):
        try:
            with open(runner_file, encoding="utf-8-sig") as f:
                config = json.load(f)
            runners.append({
                "name": config.get("agentName", "unknown"),
                "github_url": config.get("gitHubUrl", ""),
                "runner_dir": str(runner_file.parent),
            })
        except (OSError, json.JSONDecodeError, KeyError):
            continue

    return runners


def fetch_runners_status() -> list[RunnerInfo]:
    """Scan local runner dirs and query GitHub API for their status."""
    local_runners = scan_runner_dirs()
    if not local_runners:
        return []

    # Group by GitHub URL to minimize API calls
    by_url: dict[str, list[dict]] = {}
    for r in local_runners:
        by_url.setdefault(r["github_url"], []).append(r)

    results: list[RunnerInfo] = []

    for github_url, group in by_url.items():
        parts = github_url.rstrip("/").split("github.com/")
        if len(parts) != 2:
            for r in group:
                results.append(RunnerInfo(r["name"], "", "unknown", error="bad URL"))
            continue

        slug = parts[1]
        slug_parts = slug.split("/")

        try:
            if len(slug_parts) == 2:
                endpoint = f"repos/{slug}/actions/runners"
            elif len(slug_parts) == 1:
                endpoint = f"orgs/{slug}/actions/runners"
            else:
                for r in group:
                    results.append(RunnerInfo(r["name"], slug, "unknown", error="invalid slug"))
                continue

            result = subprocess.run(
                ["gh", "api", endpoint, "--jq", ".runners"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                err = result.stderr.strip()[:30] or "gh error"
                for r in group:
                    results.append(RunnerInfo(r["name"], slug, "unknown", error=err))
                continue

            api_runners = json.loads(result.stdout)
            status_map: dict[str, tuple[str, list[str]]] = {}
            for ar in api_runners:
                name = ar.get("name", "")
                status = ar.get("status", "offline")
                busy = ar.get("busy", False)
                labels = [lb.get("name", "") for lb in ar.get("labels", [])
                          if lb.get("name", "") not in ("self-hosted", "Linux", "X64")]
                if busy:
                    status = "active"
                status_map[name] = (status, labels)

            for r in group:
                name = r["name"]
                if name in status_map:
                    st, labels = status_map[name]
                    results.append(RunnerInfo(name, slug, st, labels, r["runner_dir"]))
                else:
                    results.append(RunnerInfo(name, slug, "offline", runner_dir=r["runner_dir"]))

        except FileNotFoundError:
            for r in group:
                results.append(RunnerInfo(r["name"], slug, "unknown", error="gh not found"))
        except (subprocess.SubprocessError, json.JSONDecodeError):
            for r in group:
                results.append(RunnerInfo(r["name"], slug, "unknown", error="query failed"))

    return results


PROJECTS_JSON_PATH = Path.home() / "claude-workspace" / "clawd-bot" / "config" / "projects.json"


def fetch_task_loop_status() -> list[TaskLoopInfo]:
    """Read configured autonomous task loops without remote service calls."""
    try:
        with open(PROJECTS_JSON_PATH) as f:
            projects_cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    enabled = {
        name: cfg
        for name, cfg in projects_cfg.items()
        if cfg.get("autonomous", {}).get("enabled", False)
    }
    results: list[TaskLoopInfo] = []
    for name, cfg in enabled.items():
        auto = cfg["autonomous"]
        results.append(
            TaskLoopInfo(
                name=name,
                model=auto.get("model", "unknown"),
                effort=auto.get("effort", "—"),
                cooldown_minutes=int(auto.get("cooldown_minutes", 0)),
                last_task_ts=None,
            )
        )
    return results


# Path-scoped task groups: (label, repo_path, sub_path).
# Status = last commit touching <repo>/<sub_path>; sub_path "" means whole repo.
# Append a tuple to add a new group (e.g. SEO content, distribution drafts).
TASK_GROUPS_CONFIG: list[tuple[str, Path, str]] = [
    (
        "honey-explorer outreach",
        Path.home() / "claude-workspace" / "honey-explorer",
        "outreach/",
    ),
]


def fetch_task_groups() -> list[TaskGroupInfo]:
    """Per configured task group, return last-commit timestamp for the sub-path."""
    results: list[TaskGroupInfo] = []
    for label, repo, sub in TASK_GROUPS_CONFIG:
        info = TaskGroupInfo(label=label)
        if not repo.exists():
            info.error = "repo missing"
            results.append(info)
            continue
        cmd = ["git", "-C", str(repo), "log", "-1", "--format=%ct"]
        if sub:
            cmd += ["--", sub]
        try:
            out = subprocess.check_output(
                cmd, text=True, timeout=5, stderr=subprocess.DEVNULL
            ).strip()
            if out:
                info.last_activity_ts = float(out)
        except (subprocess.SubprocessError, ValueError, OSError):
            info.error = "git error"
        results.append(info)
    return results


# ---------------------------------------------------------------------------
# Cron job manager
# ---------------------------------------------------------------------------

_CRON_ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@weekly": "0 0 * * 0",
    "@monthly": "0 0 1 * *",
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
}
_CRON_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")
_CRON_JOURNAL_CMD_RE = re.compile(r"^\((?P<user>[^)]+)\) CMD \((?P<cmd>.*)\)\s*$")


def parse_crontab_text(text: str) -> list[CronJobInfo]:
    """Parse `crontab -l` output into jobs.

    Labels come from a trailing inline `# comment`, else the nearest full-line
    comment above (cleared by blank lines), else the command itself. The
    command keeps its inline comment verbatim because cron logs it that way.
    """
    jobs: list[CronJobInfo] = []
    pending_comment = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            pending_comment = ""
            continue
        if line.startswith("#"):
            pending_comment = line.lstrip("#").strip()
            continue
        if _CRON_ENV_RE.match(line):
            continue
        if line.startswith("@"):
            parts = line.split(None, 1)
            if len(parts) < 2:
                continue
            schedule, command = parts[0], parts[1]
        else:
            parts = line.split(None, 5)
            if len(parts) < 6:
                continue
            schedule, command = " ".join(parts[:5]), parts[5]

        label = ""
        if " #" in command:
            head, _, tail = command.rpartition(" #")
            if head.strip() and tail.strip():
                label = tail.strip()
        if not label:
            label = pending_comment or command.strip()
        jobs.append(CronJobInfo(label=label, schedule=schedule, command=command))
    return jobs


def _parse_cron_field(field_text: str, lo: int, hi: int, dow: bool = False) -> set[int]:
    values: set[int] = set()
    for part in field_text.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = max(1, int(step_text))
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        values.update(v for v in range(start, end + 1) if (v - start) % step == 0)
    if dow:
        values = {0 if v == 7 else v for v in values}
    return {v for v in values if lo <= v <= hi}


def _parse_cron_schedule(schedule: str):
    """Return (minutes, hours, doms, months, dows, dom_star, dow_star) or None."""
    schedule = _CRON_ALIASES.get(schedule, schedule)
    fields = schedule.split()
    if len(fields) != 5:
        return None
    try:
        return (
            _parse_cron_field(fields[0], 0, 59),
            _parse_cron_field(fields[1], 0, 23),
            _parse_cron_field(fields[2], 1, 31),
            _parse_cron_field(fields[3], 1, 12),
            _parse_cron_field(fields[4], 0, 6, dow=True),
            fields[2] == "*",
            fields[4] == "*",
        )
    except ValueError:
        return None


def _cron_day_matches(d: date, parsed) -> bool:
    _, _, doms, months, dows, dom_star, dow_star = parsed
    if d.month not in months:
        return False
    dom_ok = d.day in doms
    dow_ok = (d.weekday() + 1) % 7 in dows  # cron: Sunday=0
    if dom_star and dow_star:
        return True
    if dom_star:
        return dow_ok
    if dow_star:
        return dom_ok
    return dom_ok or dow_ok  # standard cron OR semantics when both restricted


def cron_next_fire(schedule: str, after: datetime) -> datetime | None:
    """First scheduled fire strictly after `after` (local time), or None."""
    parsed = _parse_cron_schedule(schedule)
    if parsed is None:
        return None
    minutes, hours = sorted(parsed[0]), sorted(parsed[1])
    start = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for offset in range(0, 367):
        d = (start + timedelta(days=offset)).date() if offset else start.date()
        if not _cron_day_matches(d, parsed):
            continue
        floor = start if d == start.date() else None
        for h in hours:
            for m in minutes:
                candidate = datetime(d.year, d.month, d.day, h, m)
                if floor is None or candidate >= floor:
                    return candidate
    return None


def cron_prev_fire(schedule: str, before: datetime) -> datetime | None:
    """Most recent scheduled fire at or before `before` (local time), or None."""
    parsed = _parse_cron_schedule(schedule)
    if parsed is None:
        return None
    minutes, hours = sorted(parsed[0], reverse=True), sorted(parsed[1], reverse=True)
    end = before.replace(second=0, microsecond=0)
    for offset in range(0, 367):
        d = (end - timedelta(days=offset)).date()
        if not _cron_day_matches(d, parsed):
            continue
        ceiling = end if d == end.date() else None
        for h in hours:
            for m in minutes:
                candidate = datetime(d.year, d.month, d.day, h, m)
                if ceiling is None or candidate <= ceiling:
                    return candidate
    return None


def _parse_cron_journal_line(line: str, user: str) -> tuple[float, str] | None:
    """Parse one `journalctl -o short-unix` CRON line into (ts, command)."""
    parts = line.split(None, 3)
    if len(parts) < 4 or not parts[2].startswith("CRON["):
        return None
    try:
        ts = float(parts[0])
    except ValueError:
        return None
    m = _CRON_JOURNAL_CMD_RE.match(parts[3])
    if not m or m.group("user") != user:
        return None
    return ts, m.group("cmd").strip()


def _read_user_crontab() -> str:
    try:
        return subprocess.check_output(
            ["crontab", "-l"], text=True, timeout=5, stderr=subprocess.DEVNULL
        )
    except (subprocess.SubprocessError, OSError):
        return ""


def _read_cron_journal_entries(
    since_hours: int = CRON_JOURNAL_WINDOW_HOURS,
) -> list[tuple[float, str]]:
    try:
        out = subprocess.check_output(
            [
                "journalctl", "_COMM=cron", "--no-pager", "-o", "short-unix",
                "--since", f"-{since_hours}h", "-q",
            ],
            text=True, timeout=15, stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError):
        return []
    user = getpass.getuser()
    entries = []
    for line in out.splitlines():
        parsed = _parse_cron_journal_line(line, user)
        if parsed:
            entries.append(parsed)
    return entries


def _system_boot_ts() -> float:
    try:
        with open("/proc/uptime") as f:
            return time.time() - float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def attach_cron_run_history(
    jobs: list[CronJobInfo],
    entries: list[tuple[float, str]],
    now: float,
    journal_start: float,
    boot_ts: float,
) -> None:
    """Fill last_run_ts / runs_24h / next_run_ts / status from journal entries."""
    now_dt = datetime.fromtimestamp(now)
    for job in jobs:
        cmd = job.command.strip()
        runs = [ts for ts, entry_cmd in entries if entry_cmd == cmd]
        if runs:
            job.last_run_ts = max(runs)
            job.runs_24h = sum(1 for ts in runs if ts >= now - 86400)

        if job.schedule == "@reboot":
            if job.last_run_ts is not None and job.last_run_ts >= boot_ts - CRON_LATE_GRACE_S:
                job.status = "ok"
            elif boot_ts >= journal_start:
                job.status = "late"
            else:
                job.status = "unknown"
            continue

        next_dt = cron_next_fire(job.schedule, now_dt)
        job.next_run_ts = next_dt.timestamp() if next_dt else None
        prev_dt = cron_prev_fire(job.schedule, now_dt)
        if prev_dt is None:
            job.status = "unknown"
            continue
        prev_ts = prev_dt.timestamp()
        if job.last_run_ts is not None and job.last_run_ts >= prev_ts - CRON_LATE_GRACE_S:
            job.status = "ok"
        elif prev_ts >= journal_start:
            job.status = "late"
        else:
            job.status = "unknown"


def fetch_cron_jobs() -> list[CronJobInfo]:
    """Read the user crontab and score each job's health from the journal."""
    jobs = parse_crontab_text(_read_user_crontab())
    if not jobs:
        return []
    now = time.time()
    attach_cron_run_history(
        jobs,
        _read_cron_journal_entries(),
        now,
        now - CRON_JOURNAL_WINDOW_HOURS * 3600,
        _system_boot_ts(),
    )
    return jobs


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
        # NOTE: /api/oauth/usage does NOT accept the long-lived
        # `sk-ant-oat01-` tokens generated by `claude setup-token`
        # (verified 2026-04-20: returns HTTP 403). The endpoint only
        # accepts the short-lived claude.ai OAuth session token stored in
        # ~/.claude/.credentials.json. So we use the credentials file
        # here regardless of whether CLAUDE_CODE_OAUTH_TOKEN is set.
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
            if resp.status_code == 429:
                retry_after = resp.headers.get("retry-after", "")
                try:
                    retry_after_s = float(retry_after) if retry_after else 0.0
                except ValueError:
                    retry_after_s = 0.0
                return UsageData(error="Rate Limited", retry_after_s=retry_after_s)
            if resp.status_code != 200:
                return UsageData(error=f"API Error ({resp.status_code})")
            data = resp.json()
        except requests.RequestException:
            return UsageData(error="Offline")
        except (json.JSONDecodeError, ValueError):
            return UsageData(error="Data Unavailable")

        extra = data.get("extra_usage", {})
        return UsageData(
            five_hour=_parse_entry(data.get("five_hour")) or UsageEntry(),
            seven_day=_parse_entry(data.get("seven_day")) or UsageEntry(),
            seven_day_sonnet=_parse_entry(data.get("seven_day_sonnet")),
            seven_day_opus=_parse_entry(data.get("seven_day_opus")),
            model_limits=_parse_model_limits(data),
            extra_usage_enabled=bool(extra.get("is_enabled", False)),
            extra_usage_utilization=extra.get("utilization"),
            extra_usage_used_credits=extra.get("used_credits"),
            extra_usage_monthly_limit=extra.get("monthly_limit"),
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


class DeployFetchWorker(QThread):
    finished = Signal(list)

    def run(self):
        projects = scan_claude_projects()
        deploys = [fetch_deploy_info(p) for p in projects]
        self.finished.emit(deploys)


class RunnerFetchWorker(QThread):
    finished = Signal(list)

    def run(self):
        runners = fetch_runners_status()
        self.finished.emit(runners)


class TaskLoopFetchWorker(QThread):
    finished = Signal(list)

    def run(self):
        loops = fetch_task_loop_status()
        self.finished.emit(loops)


class TaskGroupFetchWorker(QThread):
    finished = Signal(list)

    def run(self):
        groups = fetch_task_groups()
        self.finished.emit(groups)


class CronJobsFetchWorker(QThread):
    finished = Signal(list)

    def __init__(self, fetcher=None):
        super().__init__()
        self._fetcher = fetcher

    def run(self):
        fetcher = self._fetcher or fetch_cron_jobs
        self.finished.emit(fetcher())


class CodexUsageWorker(QThread):
    result = Signal(object)

    def __init__(self, reader=None):
        super().__init__()
        self._reader = reader

    def run(self):
        reader = self._reader or read_codex_usage_summary
        self.result.emit(reader())


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


class UsageLimitsWidget(QWidget):
    """Collapsible group containing the Claude usage limit bars."""

    _HEADER_H = 20
    _BAR_H = 44
    _ESTIMATE_H = 16
    _SPACING = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._header = QLabel("Usage Limits ▾")
        self._header.setFixedHeight(self._HEADER_H)
        self._header.setStyleSheet("color: #666680; font-size: 9px;")
        layout.addWidget(self._header)

        self.five_hour_bar = UsageBar("5-Hour Window")
        layout.addWidget(self.five_hour_bar)

        self.estimate_label = QLabel("")
        self.estimate_label.setStyleSheet(
            "color: #888898; font-size: 10px; padding-left: 2px;"
        )
        self.estimate_label.setFixedHeight(16)
        layout.addWidget(self.estimate_label)

        self.seven_day_bar = UsageBar("7-Day Window")
        layout.addWidget(self.seven_day_bar)

        # One bar per model-scoped limit (Fable, Opus, ...), built on demand
        # from UsageData.display_model_limits.
        self.model_bars: list[UsageBar] = []

        self._update_children_visibility()

    def is_expanded(self) -> bool:
        return self._expanded

    def toggle_expanded(self):
        self._expanded = not self._expanded
        self._update_children_visibility()
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None

    def set_data(self, data: UsageData, estimate: str = ""):
        self.five_hour_bar.set_data(
            data.five_hour.utilization,
            data.five_hour.time_remaining(),
        )
        self.seven_day_bar.set_data(
            data.seven_day.utilization,
            data.seven_day.time_remaining(),
        )
        self._sync_model_bars(data.display_model_limits)

        self.estimate_label.setText(estimate)
        self._update_children_visibility()
        self.update()

    def _sync_model_bars(self, limits: list[ModelLimit]):
        labels = [
            f"{ml.name} ({ml.window})" if ml.window else ml.name for ml in limits
        ]
        if labels != [bar._label for bar in self.model_bars]:
            for bar in self.model_bars:
                self.layout().removeWidget(bar)
                bar.setParent(None)
                bar.deleteLater()
            self.model_bars = [UsageBar(label) for label in labels]
            for bar in self.model_bars:
                self.layout().addWidget(bar)
        for bar, ml in zip(self.model_bars, limits):
            bar.set_data(ml.entry.utilization, ml.entry.time_remaining())

    def _expanded_height(self) -> int:
        base = (
            self._HEADER_H
            + self._SPACING + self._BAR_H       # 5-hour bar
            + self._SPACING + self._ESTIMATE_H  # pace estimate
            + self._SPACING + self._BAR_H       # 7-day bar
        )
        return base + (self._SPACING + self._BAR_H) * len(self.model_bars)

    def _update_children_visibility(self):
        visible = self._expanded
        self.five_hour_bar.setVisible(visible)
        self.estimate_label.setVisible(visible and bool(self.estimate_label.text()))
        self.seven_day_bar.setVisible(visible)
        for bar in self.model_bars:
            bar.setVisible(visible)
        self._header.setText("Usage Limits ▾" if visible else "Usage Limits ▸")
        self.setFixedHeight(self._expanded_height() if visible else self._HEADER_H)

    def mousePressEvent(self, event):
        self.toggle_expanded()
        event.accept()


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


def read_fast_mode() -> bool:
    """Read fast mode setting from Claude Code's settings.json."""
    try:
        with open(SETTINGS_PATH) as f:
            data = json.load(f)
        return bool(data.get("fastMode", False))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return False


class StatsRow(QWidget):
    """Compact row showing AVG, PEAK, TREND, FAST, and EXTRA status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        self._avg = 0.0
        self._peak = 0.0
        self._trend = "—"
        self._extra = False
        self._extra_credits: str = ""
        self._fast = False

    def set_data(self, avg: float, peak: float, trend: str, extra: bool,
                 extra_credits: str = "", fast: bool = False):
        self._avg = avg
        self._peak = peak
        self._trend = trend
        self._extra = extra
        self._extra_credits = extra_credits
        self._fast = fast
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()

        col_w = w // 5
        y = 14

        # AVG
        p.setPen(QColor(100, 100, 120))
        p.drawText(4, y, "AVG:")
        avg_x = fm.horizontalAdvance("AVG: ") + 4
        p.setPen(QColor(180, 180, 200))
        p.drawText(avg_x, y, f"{self._avg:.0f}%")

        # PEAK
        x2 = col_w
        p.setPen(QColor(100, 100, 120))
        p.drawText(x2, y, "PK:")
        peak_x = x2 + fm.horizontalAdvance("PK: ")
        p.setPen(_bar_color(self._peak))
        p.drawText(peak_x, y, f"{self._peak:.0f}%")

        # TREND
        x3 = col_w * 2
        p.setPen(QColor(100, 100, 120))
        p.drawText(x3, y, "TR:")
        trend_x = x3 + fm.horizontalAdvance("TR: ")
        trend_color = QColor(34, 197, 94) if self._trend == "↓" else (
            QColor(239, 68, 68) if self._trend == "↑" else QColor(180, 180, 200)
        )
        p.setPen(trend_color)
        p.drawText(trend_x, y, self._trend)

        # FAST
        x4 = col_w * 3
        p.setPen(QColor(100, 100, 120))
        p.drawText(x4, y, "FAST:")
        fast_x = x4 + fm.horizontalAdvance("FAST: ")
        if self._fast:
            p.setPen(QColor(250, 204, 21))  # yellow/gold bolt color
            p.drawText(fast_x, y, "ON")
        else:
            p.setPen(QColor(160, 160, 180))
            p.drawText(fast_x, y, "OFF")

        # EXTRA
        x5 = col_w * 4
        p.setPen(QColor(100, 100, 120))
        p.drawText(x5, y, "EXT:")
        ext_x = x5 + fm.horizontalAdvance("EXT: ")
        if self._extra and self._extra_credits:
            p.setPen(QColor(34, 197, 94))
            p.drawText(ext_x, y, self._extra_credits)
        elif self._extra:
            p.setPen(QColor(34, 197, 94))
            p.drawText(ext_x, y, "ON")
        else:
            p.setPen(QColor(160, 160, 180))
            p.drawText(ext_x, y, "OFF")

        p.end()


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}%"


def _format_codex_window(minutes: int) -> str:
    if minutes == 300:
        return "5h"
    if minutes == 10080:
        return "7d"
    if minutes and minutes % 1440 == 0:
        return f"{minutes // 1440}d"
    if minutes and minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m" if minutes else "limit"


def _format_epoch_remaining(epoch_seconds: int) -> str:
    if not epoch_seconds:
        return "unknown"
    delta = int(epoch_seconds - time.time())
    if delta <= 0:
        return "now"
    days = delta // 86400
    hours = (delta % 86400) // 3600
    minutes = (delta % 3600) // 60
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def read_token_stats() -> dict:
    """Read token stats from Claude Code's stats-cache.json."""
    try:
        with open(STATS_CACHE_PATH) as f:
            data = json.load(f)

        total_output = 0
        total_cache = 0
        for usage in data.get("modelUsage", {}).values():
            total_output += usage.get("outputTokens", 0)
            total_cache += usage.get("cacheReadInputTokens", 0)

        return {
            "total_output": total_output,
            "total_cache": total_cache,
        }
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return {}


def _latest_codex_state_path() -> Path | None:
    try:
        candidates = sorted(
            CODEX_HOME.glob("state_*.sqlite"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None
    return candidates[0] if candidates else None


def _recent_codex_session_files(
    sessions_dir: Path = CODEX_SESSIONS_DIR,
    limit: int = CODEX_RATE_LIMIT_SCAN_FILES,
) -> list[Path]:
    candidates: list[Path] = []
    try:
        for year_dir in sorted(
            (path for path in sessions_dir.iterdir() if path.is_dir()),
            key=lambda path: path.name,
            reverse=True,
        )[:2]:
            for month_dir in sorted(
                (path for path in year_dir.iterdir() if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )[:2]:
                day_dirs = sorted(
                    (path for path in month_dir.iterdir() if path.is_dir()),
                    key=lambda path: path.name,
                    reverse=True,
                )
                for day_dir in day_dirs[:7]:
                    candidates.extend(path for path in day_dir.glob("*.jsonl") if path.is_file())
                    if len(candidates) >= limit * 4:
                        break
                if len(candidates) >= limit * 4:
                    break
            if len(candidates) >= limit * 4:
                break

        if not candidates:
            candidates = [path for path in sessions_dir.glob("*.jsonl") if path.is_file()]
        if not candidates:
            candidates = [path for path in sessions_dir.rglob("*.jsonl") if path.is_file()]
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return candidates[:limit]


def _tail_text_lines(path: Path, max_bytes: int = CODEX_RATE_LIMIT_TAIL_BYTES) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            start = max(0, size - max_bytes)
            f.seek(start)
            data = f.read()
    except OSError:
        return []

    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if start > 0 and lines:
        lines = lines[1:]
    return lines


def _parse_codex_event_timestamp(value, fallback_timestamp: float = 0.0) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            pass
    return fallback_timestamp


def _parse_codex_rate_limit_event(
    line: str,
    fallback_timestamp: float = 0.0,
) -> CodexRateLimit | None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return None

    if event.get("type") != "event_msg":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    limits = payload.get("rate_limits") or event.get("rate_limits")
    if not isinstance(limits, dict) or limits.get("limit_id") != "codex":
        return None

    primary = limits.get("primary") if isinstance(limits.get("primary"), dict) else {}
    secondary = limits.get("secondary") if isinstance(limits.get("secondary"), dict) else {}
    return CodexRateLimit(
        primary_used_percent=_safe_float(primary.get("used_percent")),
        primary_window_minutes=_safe_int(primary.get("window_minutes")),
        primary_resets_at=_safe_int(primary.get("resets_at")),
        secondary_used_percent=_safe_float(secondary.get("used_percent")),
        secondary_window_minutes=_safe_int(secondary.get("window_minutes")),
        secondary_resets_at=_safe_int(secondary.get("resets_at")),
        plan_type=str(limits.get("plan_type") or ""),
        rate_limit_reached_type=str(limits.get("rate_limit_reached_type") or ""),
        source="cached",
        observed_at=_parse_codex_event_timestamp(
            event.get("timestamp"), fallback_timestamp
        ),
    )


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _write_codex_app_server_message(
    process: subprocess.Popen,
    message: dict,
) -> bool:
    if process.stdin is None:
        return False
    try:
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        process.stdin.write(payload)
        process.stdin.flush()
    except (BrokenPipeError, OSError, ValueError):
        return False
    return True


def _read_codex_app_server_response(
    process: subprocess.Popen,
    request_id: int,
    deadline: float,
    pending: bytearray,
) -> dict | None:
    """Read one matching app-server JSONL response before ``deadline``."""
    if process.stdout is None:
        return None

    while time.monotonic() < deadline:
        while b"\n" in pending:
            raw_line, _, remainder = pending.partition(b"\n")
            pending[:] = remainder
            if not raw_line.strip():
                continue
            try:
                message = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
            if isinstance(message, dict) and message.get("id") == request_id:
                return message

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            ready, _, _ = select.select([process.stdout], [], [], remaining)
        except (OSError, ValueError):
            return None
        if not ready:
            return None
        try:
            chunk = os.read(process.stdout.fileno(), 64 * 1024)
        except OSError:
            return None
        if not chunk:
            return None
        pending.extend(chunk)
    return None


def _stop_codex_app_server(process: subprocess.Popen) -> None:
    """Close app-server input and ensure the short-lived child is reaped."""
    try:
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=CODEX_APP_SERVER_STOP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=CODEX_APP_SERVER_STOP_TIMEOUT_S)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass
    finally:
        if process.stdout is not None:
            try:
                process.stdout.close()
            except OSError:
                pass


def _request_codex_app_server_rate_limits(
    timeout_s: float = CODEX_APP_SERVER_TIMEOUT_S,
) -> dict | None:
    """Perform the official app-server JSONL handshake and rate-limit read."""
    process: subprocess.Popen | None = None
    try:
        process = subprocess.Popen(
            ["codex", "app-server", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        deadline = time.monotonic() + timeout_s
        pending = bytearray()
        if not _write_codex_app_server_message(
            process,
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {
                        "name": "claude_indicator",
                        "title": "Claude Indicator",
                        "version": "1.0",
                    }
                },
            },
        ):
            return None
        initialized = _read_codex_app_server_response(process, 1, deadline, pending)
        if initialized is None or "error" in initialized:
            return None
        if not _write_codex_app_server_message(
            process, {"method": "initialized", "params": {}}
        ):
            return None
        if not _write_codex_app_server_message(
            process, {"method": "account/rateLimits/read", "id": 2}
        ):
            return None
        response = _read_codex_app_server_response(process, 2, deadline, pending)
        if response is None or "error" in response:
            return None
        return response
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    finally:
        if process is not None:
            _stop_codex_app_server(process)


def _parse_codex_app_server_rate_limit(response: dict) -> CodexRateLimit | None:
    """Parse the base Codex bucket from an app-server camelCase response."""
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None

    limits = None
    buckets = result.get("rateLimitsByLimitId")
    if isinstance(buckets, dict) and isinstance(buckets.get("codex"), dict):
        limits = buckets["codex"]
    single_bucket = result.get("rateLimits")
    if not isinstance(limits, dict) and isinstance(single_bucket, dict):
        if single_bucket.get("limitId") == "codex":
            limits = single_bucket
    if not isinstance(limits, dict) or limits.get("limitId") != "codex":
        return None

    primary = limits.get("primary")
    secondary = limits.get("secondary")
    if not isinstance(primary, dict) and not isinstance(secondary, dict):
        return None
    primary = primary if isinstance(primary, dict) else {}
    secondary = secondary if isinstance(secondary, dict) else {}
    return CodexRateLimit(
        primary_used_percent=_safe_float(primary.get("usedPercent")),
        primary_window_minutes=_safe_int(primary.get("windowDurationMins")),
        primary_resets_at=_safe_int(primary.get("resetsAt")),
        secondary_used_percent=_safe_float(secondary.get("usedPercent")),
        secondary_window_minutes=_safe_int(secondary.get("windowDurationMins")),
        secondary_resets_at=_safe_int(secondary.get("resetsAt")),
        plan_type=str(limits.get("planType") or ""),
        rate_limit_reached_type=str(limits.get("rateLimitReachedType") or ""),
        source="live",
        observed_at=time.time(),
    )


def read_live_codex_rate_limit(
    timeout_s: float = CODEX_APP_SERVER_TIMEOUT_S,
) -> CodexRateLimit | None:
    response = _request_codex_app_server_rate_limits(timeout_s=timeout_s)
    return _parse_codex_app_server_rate_limit(response) if response is not None else None


def read_latest_codex_rate_limit(
    sessions_dir: Path = CODEX_SESSIONS_DIR,
    now_ts: float | None = None,
    max_age_s: float = CODEX_CACHED_RATE_LIMIT_MAX_AGE_S,
) -> CodexRateLimit | None:
    """Read a recent, unexpired cached Codex rate limit as a fail-safe."""
    now_ts = time.time() if now_ts is None else now_ts
    for session_path in _recent_codex_session_files(sessions_dir):
        try:
            file_timestamp = session_path.stat().st_mtime
        except OSError:
            continue
        for line in reversed(_tail_text_lines(session_path)):
            rate_limit = _parse_codex_rate_limit_event(
                line, fallback_timestamp=file_timestamp
            )
            if rate_limit is not None and _cached_codex_rate_limit_is_current(
                rate_limit, now_ts=now_ts, max_age_s=max_age_s
            ):
                return rate_limit
    return None


def _cached_codex_rate_limit_is_current(
    rate_limit: CodexRateLimit,
    now_ts: float,
    max_age_s: float = CODEX_CACHED_RATE_LIMIT_MAX_AGE_S,
) -> bool:
    observed_at = rate_limit.observed_at
    if observed_at <= 0 or observed_at > now_ts + CODEX_REFRESH_MS / 1000:
        return False
    if now_ts - observed_at > max_age_s:
        return False

    has_window = False
    for used_percent, window_minutes, resets_at in (
        (
            rate_limit.primary_used_percent,
            rate_limit.primary_window_minutes,
            rate_limit.primary_resets_at,
        ),
        (
            rate_limit.secondary_used_percent,
            rate_limit.secondary_window_minutes,
            rate_limit.secondary_resets_at,
        ),
    ):
        if used_percent is None and not window_minutes and not resets_at:
            continue
        has_window = True
        if resets_at and resets_at <= now_ts:
            return False
    return has_window


def read_codex_rate_limit(
    sessions_dir: Path = CODEX_SESSIONS_DIR,
    timeout_s: float = CODEX_APP_SERVER_TIMEOUT_S,
    now_ts: float | None = None,
) -> CodexRateLimit | None:
    """Read current limits from app-server, falling back to cached sessions."""
    live_rate_limit = read_live_codex_rate_limit(timeout_s=timeout_s)
    if live_rate_limit is not None:
        return live_rate_limit
    return read_latest_codex_rate_limit(sessions_dir=sessions_dir, now_ts=now_ts)


def read_codex_usage_summary(
    db_path: Path | None = None,
    sessions_dir: Path = CODEX_SESSIONS_DIR,
) -> CodexUsageSummary | None:
    """Read local Codex token totals from the state database."""
    summary = CodexUsageSummary()
    has_state = False
    db_path = db_path or _latest_codex_state_path()
    if db_path is not None:
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1) as conn:
                columns = {row[1] for row in conn.execute("PRAGMA table_info(threads)")}
                cwd_expr = "COALESCE(cwd, '')" if "cwd" in columns else "''"
                query = f"""
                    WITH codex_threads AS (
                        SELECT title, COALESCE(model, '') AS model, updated_at, tokens_used,
                               {cwd_expr} AS cwd
                        FROM threads
                        WHERE model_provider = 'openai'
                    ),
                    latest AS (
                        SELECT title, model, updated_at, tokens_used, cwd
                        FROM codex_threads
                        ORDER BY updated_at DESC
                        LIMIT 1
                    )
                    SELECT
                        (SELECT COUNT(*) FROM codex_threads),
                        COALESCE((SELECT SUM(tokens_used) FROM codex_threads), 0),
                        COALESCE((SELECT tokens_used FROM latest), 0),
                        COALESCE((SELECT title FROM latest), ''),
                        COALESCE((SELECT model FROM latest), ''),
                        COALESCE((SELECT updated_at FROM latest), 0),
                        COALESCE((SELECT cwd FROM latest), '')
                """
                row = conn.execute(query).fetchone()
        except sqlite3.Error:
            row = None

        if row is not None:
            summary.thread_count = int(row[0] or 0)
            summary.total_tokens = int(row[1] or 0)
            summary.latest_thread_tokens = int(row[2] or 0)
            summary.latest_thread_title = row[3] or ""
            summary.latest_model = row[4] or ""
            summary.latest_updated_at = int(row[5] or 0)
            summary.latest_cwd = row[6] or ""
            has_state = True

    rate_limit = read_codex_rate_limit(sessions_dir=sessions_dir)
    if rate_limit is not None:
        summary.primary_limit_used_percent = rate_limit.primary_used_percent
        summary.primary_limit_window_minutes = rate_limit.primary_window_minutes
        summary.primary_limit_resets_at = rate_limit.primary_resets_at
        summary.secondary_limit_used_percent = rate_limit.secondary_used_percent
        summary.secondary_limit_window_minutes = rate_limit.secondary_window_minutes
        summary.secondary_limit_resets_at = rate_limit.secondary_resets_at
        summary.plan_type = rate_limit.plan_type
        summary.rate_limit_reached_type = rate_limit.rate_limit_reached_type
        summary.rate_limit_source = rate_limit.source
        summary.rate_limit_observed_at = rate_limit.observed_at

    if not has_state and rate_limit is None:
        return None
    return summary


class TokenRow(QWidget):
    """Compact row showing token usage stats from Claude Code."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        self._total_out = 0
        self._total_cache = 0

    def set_data(self, total_out: int, total_cache: int):
        self._total_out = total_out
        self._total_cache = total_cache
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()

        col_w = w // 2
        y = 14

        # OUTPUT (lifetime)
        p.setPen(QColor(100, 100, 120))
        p.drawText(4, y, "OUT:")
        out_x = 4 + fm.horizontalAdvance("OUT: ")
        p.setPen(QColor(180, 180, 200))
        p.drawText(out_x, y, _fmt_tokens(self._total_out))

        # CACHE (lifetime)
        x3 = col_w
        p.setPen(QColor(100, 100, 120))
        p.drawText(x3, y, "CACHE:")
        cache_x = x3 + fm.horizontalAdvance("CACHE: ")
        p.setPen(QColor(139, 92, 246))
        p.drawText(cache_x, y, _fmt_tokens(self._total_cache))

        p.end()


class CodexUsageRow(QWidget):
    """Compact row showing local Codex token usage totals."""

    _COLLAPSED_H = 20
    _EXPANDED_BASE_H = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self.setFixedHeight(self._COLLAPSED_H)
        self._summary: CodexUsageSummary | None = None
        self._available = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("No local Codex usage found yet.")

    def is_expanded(self) -> bool:
        return self._expanded

    def toggle_expanded(self):
        self._expanded = not self._expanded
        self._update_height()
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None
        self.update()

    def set_data(self, summary: CodexUsageSummary | None):
        self._summary = summary
        self._available = summary is not None and (
            summary.thread_count > 0
            or summary.primary_limit_used_percent is not None
            or summary.secondary_limit_used_percent is not None
        )
        if not self._available:
            self.setToolTip("No local Codex usage found yet.")
        else:
            title = summary.latest_thread_title or "Untitled thread"
            model = summary.latest_model or "unknown"
            cwd = summary.latest_cwd or "unknown"
            limit_lines = [
                f"{label.lower()} limit: {_fmt_percent(used_percent)} used; "
                f"resets in {_format_epoch_remaining(resets_at)}"
                for label, used_percent, resets_at in self._rate_limit_windows(summary)
            ]
            detail_lines = limit_lines + [
                f"Rate-limit source: {self._rate_limit_source_label(summary)}\n"
                f"Plan: {summary.plan_type or 'unknown'}\n"
                f"Latest Codex thread: {title}\n"
                f"Model: {model}\n"
                f"Updated: {self._format_updated_at(summary)}\n"
                f"CWD: {cwd}\n"
                f"Latest tokens: {_fmt_tokens(summary.latest_thread_tokens)}\n"
                f"Total tokens: {_fmt_tokens(summary.total_tokens)} across "
                f"{summary.thread_count} threads"
            ]
            self.setToolTip("\n".join(detail_lines))
        self._update_height()
        self.update()

    def _update_height(self):
        if not self._expanded:
            self.setFixedHeight(self._COLLAPSED_H)
            return
        detail_count = len(self._expanded_details(self._summary or CodexUsageSummary()))
        self.setFixedHeight(self._EXPANDED_BASE_H + 14 * detail_count)

    @staticmethod
    def _format_updated_at(summary: CodexUsageSummary) -> str:
        if not summary.latest_updated_at:
            return "unknown"
        return datetime.fromtimestamp(
            summary.latest_updated_at, tz=timezone.utc
        ).astimezone().strftime("%Y-%m-%d %I:%M:%S %p")

    @staticmethod
    def _rate_limit_source_label(summary: CodexUsageSummary) -> str:
        if summary.rate_limit_source == "live":
            return "live Codex account"
        if summary.rate_limit_source == "cached":
            if summary.rate_limit_observed_at:
                age_s = max(0, int(time.time() - summary.rate_limit_observed_at))
                age_text = f"{age_s}s" if age_s < 60 else f"{age_s // 60}m"
                return f"cached local session fallback ({age_text} old)"
            return "cached local session fallback"
        return "unavailable"

    @staticmethod
    def _title_text(summary: CodexUsageSummary, arrow: str) -> str:
        marker = " CACHE" if summary.rate_limit_source == "cached" else ""
        return f"CODEX{marker} {arrow}"

    @staticmethod
    def _rate_limit_windows(summary: CodexUsageSummary):
        windows = []
        for used_percent, window_minutes, resets_at in (
            (
                summary.primary_limit_used_percent,
                summary.primary_limit_window_minutes,
                summary.primary_limit_resets_at,
            ),
            (
                summary.secondary_limit_used_percent,
                summary.secondary_limit_window_minutes,
                summary.secondary_limit_resets_at,
            ),
        ):
            if used_percent is None and not window_minutes and not resets_at:
                continue
            windows.append(
                (
                    _format_codex_window(window_minutes).upper(),
                    used_percent,
                    resets_at,
                )
            )
        return windows

    @classmethod
    def _collapsed_metrics(cls, summary: CodexUsageSummary):
        metrics = [
            (label, _fmt_percent(used_percent), QColor(16, 163, 127))
            for label, used_percent, _resets_at in cls._rate_limit_windows(summary)
        ]
        metrics.append(
            (
                "LAST",
                _fmt_tokens(summary.latest_thread_tokens),
                QColor(180, 180, 200),
            )
        )
        return metrics

    @classmethod
    def _expanded_details(cls, summary: CodexUsageSummary):
        details = [
            (
                f"{label} LIMIT",
                f"{_fmt_percent(used_percent)} used · "
                f"resets {_format_epoch_remaining(resets_at)}",
            )
            for label, used_percent, resets_at in cls._rate_limit_windows(summary)
        ]
        details.extend(
            [
                ("SOURCE", cls._rate_limit_source_label(summary)),
                ("PLAN", summary.plan_type or "unknown"),
                ("THREAD", summary.latest_thread_title or "Untitled thread"),
                ("MODEL", summary.latest_model or "unknown"),
                ("UPDATED", cls._format_updated_at(summary)),
                ("CWD", summary.latest_cwd or "unknown"),
                (
                    "TOKENS",
                    f"latest {_fmt_tokens(summary.latest_thread_tokens)} · "
                    f"total {_fmt_tokens(summary.total_tokens)} · "
                    f"{summary.thread_count} threads",
                ),
            ]
        )
        return details

    def mousePressEvent(self, event):
        self.toggle_expanded()
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()
        y = 14
        arrow = "▾" if self._expanded else "▸"
        summary = self._summary or CodexUsageSummary()

        if summary.rate_limit_source == "cached":
            title_color = QColor(245, 158, 11)
        else:
            title_color = (
                QColor(16, 163, 127) if self._available else QColor(100, 100, 120)
            )
        p.setPen(title_color)
        title_text = self._title_text(summary, arrow)
        p.drawText(4, y, title_text)

        title_w = fm.horizontalAdvance(title_text) + 12
        metrics = self._collapsed_metrics(summary)
        col_w = max(1, (w - title_w - 8) // len(metrics))

        for idx, (label, value_text, value_color) in enumerate(metrics):
            x = 4 + title_w + idx * col_w
            p.setPen(QColor(100, 100, 120))
            p.drawText(x, y, f"{label}:")
            value_x = x + fm.horizontalAdvance(f"{label}: ")
            p.setPen(value_color if self._available else QColor(160, 160, 180))
            p.drawText(value_x, y, value_text if self._available else "—")

        if self._expanded:
            details = self._expanded_details(summary)
            detail_font = QFont("sans-serif", 8)
            detail_font.setWeight(QFont.Weight.Normal)
            p.setFont(detail_font)
            detail_fm = p.fontMetrics()
            label_w = max(detail_fm.horizontalAdvance(label) for label, _ in details) + 8
            row_y = 32
            for label, value in details:
                p.setPen(QColor(100, 100, 120))
                p.drawText(12, row_y, f"{label}:")
                p.setPen(QColor(180, 180, 200) if self._available else QColor(120, 120, 140))
                text = detail_fm.elidedText(value if self._available else "—", Qt.TextElideMode.ElideMiddle, max(20, w - label_w - 18))
                p.drawText(12 + label_w, row_y, text)
                row_y += 14

        p.end()


class DeployRow(QWidget):
    """Collapsible row showing deploy status per active Claude project."""

    _HEADER_H = 18
    _ROW_H = 16
    _PAD = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deploys: list[DeployInfo] = []
        self._expanded = False
        self.setFixedHeight(0)
        self.hide()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, deploys: list[DeployInfo]):
        self._deploys = deploys
        if deploys:
            self._update_height()
            self.show()
        else:
            self.setFixedHeight(0)
            self.hide()
        self.update()

    def _update_height(self):
        if not self._deploys:
            self.setFixedHeight(0)
            return
        if self._expanded:
            h = self._HEADER_H + self._ROW_H * len(self._deploys) + self._PAD
        else:
            h = self._HEADER_H
        self.setFixedHeight(h)

    def _deploy_time_color(self, d: DeployInfo) -> QColor:
        if d.error:
            return QColor(239, 68, 68)
        if not d.last_deploy_at:
            return QColor(160, 160, 180)
        try:
            dt = datetime.fromisoformat(d.last_deploy_at.replace("Z", "+00:00"))
            age_s = (datetime.now(timezone.utc) - dt).total_seconds()
            if age_s < 3600:
                return QColor(34, 197, 94)
            if age_s < 86400:
                return QColor(234, 179, 8)
            return QColor(249, 115, 22)
        except (ValueError, TypeError):
            return QColor(160, 160, 180)

    def mousePressEvent(self, event):
        if not self._deploys:
            return
        self._expanded = not self._expanded
        self._update_height()
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None
        event.accept()

    def paintEvent(self, event):
        if not self._deploys:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        hdr_font = QFont("sans-serif", 8)
        hdr_font.setWeight(QFont.Weight.Medium)
        p.setFont(hdr_font)
        fm = p.fontMetrics()

        arrow = "▾" if self._expanded else "▸"
        p.setPen(QColor(100, 100, 120))
        header_text = f"DEPLOYS {arrow}"
        p.drawText(4, 13, header_text)

        if not self._expanded:
            # Inline summary: project time · project time
            x = 4 + fm.horizontalAdvance(header_text) + 8
            for i, d in enumerate(self._deploys):
                if x > w - 20:
                    break
                if i > 0:
                    p.setPen(QColor(80, 80, 100))
                    p.drawText(x, 13, "·")
                    x += fm.horizontalAdvance("· ")
                p.setPen(QColor(160, 160, 180))
                p.drawText(x, 13, d.project_name)
                x += fm.horizontalAdvance(d.project_name) + 4
                rel = d.relative_time()
                p.setPen(self._deploy_time_color(d))
                p.drawText(x, 13, rel)
                x += fm.horizontalAdvance(rel) + 8
            p.end()
            return

        # Expanded: per-project rows
        for i, d in enumerate(self._deploys):
            y = self._HEADER_H + self._ROW_H * i + 12

            p.setPen(QColor(180, 180, 200))
            name_text = d.project_name
            name_w = fm.horizontalAdvance(name_text)
            p.drawText(8, y, name_text)

            p.setPen(QColor(80, 80, 100))
            p.drawText(8 + name_w + 4, y, "·")
            time_x = 8 + name_w + 4 + fm.horizontalAdvance("· ")

            rel = d.relative_time()
            p.setPen(self._deploy_time_color(d))
            p.drawText(time_x, y, rel)

            if d.workflow_name:
                wf_text = d.workflow_name
                max_wf_w = 80
                wf_w = fm.horizontalAdvance(wf_text)
                if wf_w > max_wf_w:
                    while wf_w > max_wf_w - fm.horizontalAdvance("…") and len(wf_text) > 1:
                        wf_text = wf_text[:-1]
                        wf_w = fm.horizontalAdvance(wf_text)
                    wf_text += "…"
                    wf_w = fm.horizontalAdvance(wf_text)
                p.setPen(QColor(80, 80, 100))
                p.drawText(w - wf_w - 4, y, wf_text)

        p.end()


class RunnersRow(QWidget):
    """Collapsible row showing local GitHub Actions runner status."""

    _HEADER_H = 22
    _ROW_H = 16
    _PAD = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._runners: list[RunnerInfo] = []
        self._expanded = False
        self.setFixedHeight(0)
        self.hide()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, runners: list[RunnerInfo]):
        self._runners = runners
        if runners:
            self._update_height()
            self.show()
        else:
            self.setFixedHeight(0)
            self.hide()
        self.update()

    def _update_height(self):
        if not self._runners:
            self.setFixedHeight(0)
            return
        if self._expanded:
            h = self._HEADER_H + self._ROW_H * len(self._runners) + self._PAD
        else:
            h = self._HEADER_H
        self.setFixedHeight(h)

    @staticmethod
    def _status_color(status: str) -> QColor:
        if status == "active":
            return QColor(59, 130, 246)    # blue - busy/working
        if status == "online":
            return QColor(34, 197, 94)     # green
        if status == "offline":
            return QColor(239, 68, 68)     # red
        return QColor(160, 160, 180)       # dim gray - unknown

    def mousePressEvent(self, event):
        if not self._runners:
            return
        self._expanded = not self._expanded
        self._update_height()
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None
        event.accept()

    def paintEvent(self, event):
        if not self._runners:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()

        y = 14
        arrow = "▾" if self._expanded else "▸"
        p.setPen(QColor(100, 100, 120))
        header_text = f"RUNNERS {arrow}"
        p.drawText(4, y, header_text)

        if not self._expanded:
            # Inline summary: N online · N active · N offline
            online = sum(1 for r in self._runners if r.status == "online")
            active = sum(1 for r in self._runners if r.status == "active")
            offline = sum(1 for r in self._runners if r.status == "offline")
            x = 4 + fm.horizontalAdvance(header_text) + 8

            if online:
                p.setPen(QColor(34, 197, 94))
                txt = f"{online} online"
                p.drawText(x, y, txt)
                x += fm.horizontalAdvance(txt) + 6
            if active:
                p.setPen(QColor(59, 130, 246))
                txt = f"{active} active"
                p.drawText(x, y, txt)
                x += fm.horizontalAdvance(txt) + 6
            if offline:
                p.setPen(QColor(239, 68, 68))
                txt = f"{offline} offline"
                p.drawText(x, y, txt)

            p.end()
            return

        # Expanded: per-runner rows
        for i, r in enumerate(self._runners):
            row_y = self._HEADER_H + self._ROW_H * i + 12

            # Runner name
            p.setPen(QColor(180, 180, 200))
            p.drawText(8, row_y, r.name)
            name_w = fm.horizontalAdvance(r.name)

            # Dot separator
            p.setPen(QColor(80, 80, 100))
            p.drawText(8 + name_w + 4, row_y, "·")
            sx = 8 + name_w + 4 + fm.horizontalAdvance("· ")

            # Status
            status_text = r.error if r.error else r.status
            p.setPen(self._status_color(r.status))
            p.drawText(sx, row_y, status_text)

            # Labels (right-aligned, dim)
            if r.labels:
                label_text = ", ".join(r.labels[:3])
                lw = fm.horizontalAdvance(label_text)
                p.setPen(QColor(80, 80, 100))
                p.drawText(w - lw - 4, row_y, label_text)

        p.end()


class TaskLoopWidget(QWidget):
    """Collapsible row showing active autonomous task loop parameters for each clawd-bot project."""

    _HEADER_H = 22
    _ROW_H = 18
    _PAD = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loops: list[TaskLoopInfo] = []
        self._expanded = False
        self.setFixedHeight(0)
        self.hide()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, loops: list[TaskLoopInfo]):
        self._loops = loops
        if loops:
            self._update_height()
            self.show()
        else:
            self.setFixedHeight(0)
            self.hide()
        self.update()

    def _update_height(self):
        if not self._loops:
            self.setFixedHeight(0)
            return
        if self._expanded:
            h = self._HEADER_H + self._ROW_H * len(self._loops) + self._PAD
        else:
            h = self._HEADER_H
        self.setFixedHeight(h)

    def mousePressEvent(self, event):
        if not self._loops:
            return
        self._expanded = not self._expanded
        self._update_height()
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None
        event.accept()

    def paintEvent(self, event):
        if not self._loops:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()

        y = 14
        arrow = "▾" if self._expanded else "▸"
        p.setPen(QColor(100, 100, 120))
        header_text = f"CLAWD TASK LOOPS {arrow}"
        p.drawText(4, y, header_text)

        if not self._expanded:
            # Inline summary: N active loops
            x = 4 + fm.horizontalAdvance(header_text) + 8
            p.setPen(QColor(180, 140, 80))
            p.drawText(x, y, f"{len(self._loops)} active")
            p.end()
            return

        # Expanded: per-project rows
        for i, loop in enumerate(self._loops):
            row_y = self._HEADER_H + self._ROW_H * i + 13

            # Project name
            p.setPen(QColor(180, 180, 200))
            p.drawText(8, row_y, loop.name)
            name_w = fm.horizontalAdvance(loop.name)

            # Separator dot
            p.setPen(QColor(80, 80, 100))
            dot_x = 8 + name_w + 4
            p.drawText(dot_x, row_y, "·")
            sx = dot_x + fm.horizontalAdvance("· ")

            # Model (abbreviated) + effort
            model_short = loop.model.replace("claude-", "").replace("-", "-")
            detail = f"{model_short} {loop.effort} {loop.cooldown_minutes}m"
            p.setPen(QColor(120, 120, 150))
            p.drawText(sx, row_y, detail)

            # Next run (right-aligned)
            next_str = loop.next_run_str()
            nw = fm.horizontalAdvance(next_str)
            p.setPen(QColor(100, 160, 100))
            p.drawText(w - nw - 4, row_y, next_str)

        p.end()


class TaskGroupWidget(QWidget):
    """Collapsible row showing path-scoped task groups (last git activity per group)."""

    _HEADER_H = 22
    _ROW_H = 18
    _PAD = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._groups: list[TaskGroupInfo] = []
        self._expanded = False
        self.setFixedHeight(0)
        self.hide()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, groups: list[TaskGroupInfo]):
        self._groups = groups
        if groups:
            self._update_height()
            self.show()
        else:
            self.setFixedHeight(0)
            self.hide()
        self.update()

    def _update_height(self):
        if not self._groups:
            self.setFixedHeight(0)
            return
        if self._expanded:
            h = self._HEADER_H + self._ROW_H * len(self._groups) + self._PAD
        else:
            h = self._HEADER_H
        self.setFixedHeight(h)

    def mousePressEvent(self, event):
        if not self._groups:
            return
        self._expanded = not self._expanded
        self._update_height()
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None
        event.accept()

    @staticmethod
    def _activity_color(group: TaskGroupInfo) -> QColor:
        if group.error or group.last_activity_ts is None:
            return QColor(239, 68, 68)  # red
        elapsed = time.time() - group.last_activity_ts
        if elapsed >= 24 * 3600:
            return QColor(239, 68, 68)  # red — days
        if elapsed >= 6 * 3600:
            return QColor(249, 115, 22)  # orange — 6h+
        if elapsed >= 2 * 3600:
            return QColor(234, 179, 8)  # yellow — 2h+
        return QColor(34, 197, 94)  # green — fresh

    def _stalest(self) -> TaskGroupInfo | None:
        # Surface the group most likely to be stuck so the collapsed header is informative.
        with_ts = [g for g in self._groups if g.last_activity_ts is not None]
        errored = [g for g in self._groups if g.error or g.last_activity_ts is None]
        if errored:
            return errored[0]
        if with_ts:
            return min(with_ts, key=lambda g: g.last_activity_ts or 0)
        return None

    def paintEvent(self, event):
        if not self._groups:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()

        y = 14
        arrow = "▾" if self._expanded else "▸"
        p.setPen(QColor(100, 100, 120))
        header_text = f"TASK GROUPS {arrow}"
        p.drawText(4, y, header_text)

        if not self._expanded:
            stale = self._stalest()
            if stale is not None:
                summary = f"{stale.label}: {stale.status_str()}"
                x = 4 + fm.horizontalAdvance(header_text) + 8
                p.setPen(self._activity_color(stale))
                p.drawText(x, y, summary)
            p.end()
            return

        for i, group in enumerate(self._groups):
            row_y = self._HEADER_H + self._ROW_H * i + 13
            p.setPen(QColor(180, 180, 200))
            p.drawText(8, row_y, group.label)

            status = group.status_str()
            sw = fm.horizontalAdvance(status)
            p.setPen(self._activity_color(group))
            p.drawText(w - sw - 4, row_y, status)

        p.end()


class CronJobsWidget(QWidget):
    """Collapsible row showing user crontab jobs with per-job run health."""

    _HEADER_H = 22
    _ROW_H = 18
    _PAD = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self._jobs: list[CronJobInfo] = []
        self._expanded = False
        self.setFixedHeight(0)
        self.hide()
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, jobs: list[CronJobInfo]):
        self._jobs = jobs
        if jobs:
            self._update_height()
            self.setToolTip(
                "\n".join(f"{j.schedule}  {j.command}" for j in jobs)
            )
            self.show()
        else:
            self.setFixedHeight(0)
            self.setToolTip("")
            self.hide()
        self.update()

    def _update_height(self):
        if not self._jobs:
            self.setFixedHeight(0)
            return
        if self._expanded:
            h = self._HEADER_H + self._ROW_H * len(self._jobs) + self._PAD
        else:
            h = self._HEADER_H
        self.setFixedHeight(h)

    def mousePressEvent(self, event):
        if not self._jobs:
            return
        self._expanded = not self._expanded
        self._update_height()
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None
        event.accept()

    def _summary_text(self) -> str:
        late = sum(1 for j in self._jobs if j.status == "late")
        if late:
            return f"{len(self._jobs)} jobs · {late} late"
        return f"{len(self._jobs)} jobs · all ok"

    @staticmethod
    def _status_color(status: str) -> QColor:
        if status == "ok":
            return QColor(34, 197, 94)  # green
        if status == "late":
            return QColor(239, 68, 68)  # red
        return QColor(120, 120, 150)  # gray — unknown/no data

    def paintEvent(self, event):
        if not self._jobs:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()

        y = 14
        arrow = "▾" if self._expanded else "▸"
        p.setPen(QColor(100, 100, 120))
        header_text = f"CRON JOBS {arrow}"
        p.drawText(4, y, header_text)

        if not self._expanded:
            x = 4 + fm.horizontalAdvance(header_text) + 8
            late = any(j.status == "late" for j in self._jobs)
            p.setPen(self._status_color("late" if late else "ok"))
            p.drawText(x, y, self._summary_text())
            p.end()
            return

        for i, job in enumerate(self._jobs):
            row_y = self._HEADER_H + self._ROW_H * i + 13

            # Right side: last run (health-colored) plus next run (dim)
            last_str = job.last_run_str()
            next_str = job.next_run_str()
            right = last_str if not next_str else f"{last_str} · {next_str}"
            rw = fm.horizontalAdvance(right)
            if next_str:
                nx = w - 4 - fm.horizontalAdvance(f" · {next_str}")
                p.setPen(QColor(100, 100, 130))
                p.drawText(nx, row_y, f" · {next_str}")
            p.setPen(self._status_color(job.status))
            p.drawText(w - rw - 4, row_y, last_str)

            # Left side: label elided to the remaining space
            label = fm.elidedText(
                job.label, Qt.TextElideMode.ElideRight, w - rw - 20
            )
            p.setPen(QColor(180, 180, 200))
            p.drawText(8, row_y, label)

        p.end()


class SystemMetricsRow(QWidget):
    """Collapsible row showing CPU, RAM, and GPU system metrics."""

    _COLLAPSED_H = 22
    _EXPANDED_H = 90  # adjusted if no GPU

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._metrics: SystemMetrics | None = None
        self.setFixedHeight(self._COLLAPSED_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_data(self, metrics: SystemMetrics):
        self._metrics = metrics
        eh = self._COLLAPSED_H + 22 * (3 if metrics.gpu_available else 2)
        self._EXPANDED_H = eh
        if self._expanded:
            self.setFixedHeight(self._EXPANDED_H)
        self.update()

    def mousePressEvent(self, event):
        self._expanded = not self._expanded
        if self._expanded:
            self.setFixedHeight(self._EXPANDED_H)
        else:
            self.setFixedHeight(self._COLLAPSED_H)
        # Resize parent widget
        parent = self.parent()
        while parent:
            if hasattr(parent, "adjustSize"):
                parent.adjustSize()
                break
            parent = parent.parent() if hasattr(parent, "parent") else None
        event.accept()

    def paintEvent(self, event):
        m = self._metrics
        if m is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()

        font = QFont("sans-serif", 8)
        font.setWeight(QFont.Weight.Medium)
        p.setFont(font)
        fm = p.fontMetrics()

        y = 14
        arrow = "▾" if self._expanded else "▸"

        # Header: SYSTEM ▸/▾
        p.setPen(QColor(100, 100, 120))
        p.drawText(4, y, f"SYSTEM {arrow}")
        header_w = fm.horizontalAdvance(f"SYSTEM {arrow}  ")

        if not self._expanded:
            # Collapsed: inline summary
            x = 4 + header_w
            mem_pct = (m.mem_used_gb / m.mem_total_gb * 100) if m.mem_total_gb > 0 else 0

            # CPU
            p.setPen(QColor(100, 100, 120))
            p.drawText(x, y, "CPU ")
            x += fm.horizontalAdvance("CPU ")
            p.setPen(_bar_color(m.cpu_pct))
            cpu_text = f"{m.cpu_pct:.0f}%"
            p.drawText(x, y, cpu_text)
            x += fm.horizontalAdvance(cpu_text) + 8

            # RAM
            p.setPen(QColor(100, 100, 120))
            p.drawText(x, y, "RAM ")
            x += fm.horizontalAdvance("RAM ")
            p.setPen(_bar_color(mem_pct))
            ram_text = f"{mem_pct:.0f}%"
            p.drawText(x, y, ram_text)
            x += fm.horizontalAdvance(ram_text) + 8

            # GPU
            if m.gpu_available:
                p.setPen(QColor(100, 100, 120))
                p.drawText(x, y, "GPU ")
                x += fm.horizontalAdvance("GPU ")
                p.setPen(_bar_color(m.gpu_pct))
                gpu_text = f"{m.gpu_pct:.0f}%"
                p.drawText(x, y, gpu_text)

                # Temp right-aligned
                temp_text = f"{m.gpu_temp}°C"
                temp_w = fm.horizontalAdvance(temp_text)
                if m.gpu_temp >= 80:
                    p.setPen(QColor(239, 68, 68))  # red
                elif m.gpu_temp >= 70:
                    p.setPen(QColor(249, 115, 22))  # orange
                else:
                    p.setPen(QColor(180, 180, 200))
                p.drawText(w - temp_w - 4, y, temp_text)
        else:
            # Expanded: mini progress bars
            mem_pct = (m.mem_used_gb / m.mem_total_gb * 100) if m.mem_total_gb > 0 else 0
            bar_h = 8
            bar_radius = 4
            label_w = 32
            detail_w = 80
            bar_left = label_w + 4
            bar_right = w - detail_w - 4
            bar_w = bar_right - bar_left

            rows = [
                ("CPU", m.cpu_pct, f"{m.cpu_pct:.0f}%"),
                ("RAM", mem_pct, f"{m.mem_used_gb:.1f}/{m.mem_total_gb:.0f} GB"),
            ]
            if m.gpu_available:
                gpu_detail = f"{m.gpu_pct:.0f}%  {m.gpu_mem_used_gb:.1f}/{m.gpu_mem_total_gb:.0f} GB  {m.gpu_temp}°C"
                rows.append(("GPU", m.gpu_pct, gpu_detail))

            for i, (label, pct, detail) in enumerate(rows):
                row_y = self._COLLAPSED_H + 22 * i
                text_y = row_y + 14
                bar_y = row_y + 8

                # Label
                p.setPen(QColor(100, 100, 120))
                p.drawText(8, text_y, label)

                # Bar background
                bg_path = QPainterPath()
                bg_path.addRoundedRect(bar_left, bar_y, bar_w, bar_h, bar_radius, bar_radius)
                p.fillPath(bg_path, QColor(40, 40, 55))

                # Bar fill
                fill_w = max(bar_h, bar_w * pct / 100)
                fill_path = QPainterPath()
                fill_path.addRoundedRect(bar_left, bar_y, fill_w, bar_h, bar_radius, bar_radius)
                p.fillPath(fill_path, _bar_color(pct))

                # Detail text
                p.setPen(QColor(180, 180, 200))
                p.drawText(bar_right + 6, text_y, detail)

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
        self.setFixedWidth(340)
        self._tray: QSystemTrayIcon | None = None
        self._smart_todo_action: QAction | None = None
        self._smart_todo_dialog: SmartTodoDialog | None = None
        self._shutdown_started = False
        self._tray_unavailable_logged = False
        self._tray_retry_timer = QTimer(self)
        self._tray_retry_timer.setInterval(TRAY_RETRY_INTERVAL_MS)
        self._tray_retry_timer.timeout.connect(self._setup_tray_icon)

        self._drag_pos = QPoint()
        self._usage: UsageData | None = load_last_usage()
        self._client = ClaudeUsageClient()
        self._worker: FetchWorker | None = None
        self._deploy_worker: DeployFetchWorker | None = None
        self._runner_worker: RunnerFetchWorker | None = None
        self._task_loop_worker: TaskLoopFetchWorker | None = None
        self._task_group_worker: TaskGroupFetchWorker | None = None
        self._cron_worker: CronJobsFetchWorker | None = None
        self._codex_worker: CodexUsageWorker | None = None
        self._history = UsageHistory()
        self._next_fetch_at: float = 0.0
        saved_until, saved_count = load_rate_limit_until()
        self._rate_limit_until: float = saved_until
        self._consecutive_429s: int = saved_count
        if saved_until > time.time():
            remaining = int(saved_until - time.time())
            log_line(
                f"startup: resuming rate-limit cooldown from disk, "
                f"{remaining}s remaining (#{saved_count} consecutive 429s)"
            )
            # Schedule the one-shot retry for when the persisted window ends
            QTimer.singleShot(
                int((saved_until - time.time()) * 1000) + 1000,
                self._fetch_usage,
            )
        self._sys_reader = SystemMetricsReader()

        self._build_ui()
        self.adjustSize()
        self._setup_tray_icon()
        self._setup_timers()
        self._fetch_usage()
        self._fetch_deploys()
        self._fetch_runners()
        self._fetch_task_loops()
        self._fetch_task_groups()
        self._fetch_cron_jobs()

        # Initial system metrics read so widget isn't blank
        self._update_system_metrics()

        # Initialize token stats
        tstats = read_token_stats()
        if tstats:
            self._token_row.set_data(
                tstats.get("total_output", 0),
                tstats.get("total_cache", 0),
            )
        self._refresh_codex_usage()

        # Initialize graph with persisted history
        if self._history.points:
            self._graph.set_points(self._history.points)

        # Seed display from persisted last-good usage so values survive restarts
        if self._usage and not self._usage.error:
            self._title_label.setText(self._usage.plan_name)
            self._seed_stats_row_from_usage(self._usage)
            self._update_display()
        elif self._history.points:
            # No last_usage.json but we have history. Synthesize a UsageData
            # from the most recent point so the bars show *something* instead
            # of "Rate Limited" with nothing behind it.
            latest = self._history.points[-1]
            model_entry = UsageEntry(utilization=latest.model_pct)
            self._usage = UsageData(
                five_hour=UsageEntry(utilization=latest.five_hour_pct),
                seven_day=UsageEntry(utilization=latest.seven_day_pct),
                seven_day_sonnet=model_entry if latest.model_name == "sonnet" else None,
                seven_day_opus=model_entry if latest.model_name == "opus" else None,
                model_limits=(
                    [
                        ModelLimit(
                            name=latest.model_name.title(),
                            window="7-Day",
                            entry=model_entry,
                        )
                    ]
                    if latest.model_name not in ("opus", "sonnet", "unknown", "")
                    else []
                ),
                fetched_at=latest.timestamp,
            )
            self._title_label.setText(self._usage.plan_name)
            self._stats_row.set_data(
                self._history.avg_five_hour,
                self._history.peak_five_hour,
                self._history.trend,
                False,
                fast=read_fast_mode(),
            )
            self._update_display()

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

        self._minimize_btn = QLabel("–")
        self._minimize_btn.setStyleSheet(
            "color: #666680; font-size: 14px; padding: 2px 6px;"
        )
        self._minimize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._minimize_btn.mousePressEvent = lambda _: (
            self._toggle_from_tray() if self._tray else self.close()
        )
        header.addWidget(self._minimize_btn)

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
        self._usage_limits = UsageLimitsWidget()
        layout.addWidget(self._usage_limits)
        self._five_hour_bar = self._usage_limits.five_hour_bar
        self._estimate_label = self._usage_limits.estimate_label
        self._seven_day_bar = self._usage_limits.seven_day_bar
        layout.addSpacing(2)

        # Graph separator
        sep_g = QWidget()
        sep_g.setFixedHeight(1)
        sep_g.setStyleSheet("background-color: rgba(100, 100, 120, 80);")
        layout.addWidget(sep_g)
        layout.addSpacing(2)

        # Graph header with window tabs (collapsible)
        self._history_expanded = True
        graph_header = QHBoxLayout()
        self._graph_title = QLabel("Usage History ▾")
        self._graph_title.setStyleSheet("color: #666680; font-size: 9px;")
        self._graph_title.setCursor(Qt.CursorShape.PointingHandCursor)
        self._graph_title.mousePressEvent = lambda _: self._toggle_history()
        graph_header.addWidget(self._graph_title)
        graph_header.addStretch()

        self._window_labels: list[QLabel] = []
        self._window_spacers: list[QLabel] = []
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
                self._window_spacers.append(spacer)

        layout.addLayout(graph_header)

        # Usage graph
        self._graph = UsageGraph()
        layout.addWidget(self._graph)
        self._update_window_tabs()

        layout.addSpacing(2)

        # Stats separator
        self._stats_sep = QWidget()
        self._stats_sep.setFixedHeight(1)
        self._stats_sep.setStyleSheet("background-color: rgba(100, 100, 120, 80);")
        layout.addWidget(self._stats_sep)
        layout.addSpacing(2)

        # Stats row
        self._stats_row = StatsRow()
        layout.addWidget(self._stats_row)

        # Token stats row
        self._token_row = TokenRow()
        layout.addWidget(self._token_row)

        # Codex usage row
        self._codex_row = CodexUsageRow()
        layout.addWidget(self._codex_row)

        # Deploy status row
        self._deploy_row = DeployRow()
        layout.addWidget(self._deploy_row)

        # Runners status row
        self._runners_row = RunnersRow()
        layout.addWidget(self._runners_row)

        # Clawd task loop row
        self._task_loop_row = TaskLoopWidget()
        layout.addWidget(self._task_loop_row)

        # Path-scoped task groups row
        self._task_group_row = TaskGroupWidget()
        layout.addWidget(self._task_group_row)

        # Cron job manager row
        self._cron_row = CronJobsWidget()
        layout.addWidget(self._cron_row)

        # System metrics row
        self._sys_row = SystemMetricsRow()
        layout.addWidget(self._sys_row)

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
        # Click = force a fetch, bypassing the rate-limit cooldown. Useful when
        # the user believes the server window has cleared. Long-running 429
        # loops may keep extending the window, so use sparingly.
        refresh_btn.mousePressEvent = lambda _: self._fetch_usage(force=True)
        refresh_btn.setToolTip("Refresh now (bypasses rate-limit cooldown)")
        status_layout.addWidget(refresh_btn)

        layout.addLayout(status_layout)

    def _setup_timers(self):
        # Fetch timer — polls on the normal cadence; _fetch_usage no-ops while
        # a backoff window is active, and a one-shot QTimer fires when it ends.
        self._fetch_timer = QTimer(self)
        self._fetch_timer.timeout.connect(self._fetch_usage)
        self._fetch_timer.start(REFRESH_INTERVAL_MS)

        # Countdown timer - every second
        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdowns)
        self._countdown_timer.start(COUNTDOWN_INTERVAL_MS)

        # Deploy timer - every 5 minutes
        self._deploy_timer = QTimer(self)
        self._deploy_timer.timeout.connect(self._fetch_deploys)
        self._deploy_timer.start(DEPLOY_REFRESH_MS)

        # Runner timer - every 60 seconds
        self._runner_timer = QTimer(self)
        self._runner_timer.timeout.connect(self._fetch_runners)
        self._runner_timer.start(RUNNER_REFRESH_MS)

        # Task loop timer - every 60 seconds
        self._task_loop_timer = QTimer(self)
        self._task_loop_timer.timeout.connect(self._fetch_task_loops)
        self._task_loop_timer.start(TASK_LOOP_REFRESH_MS)

        # Task group timer - every 60 seconds
        self._task_group_timer = QTimer(self)
        self._task_group_timer.timeout.connect(self._fetch_task_groups)
        self._task_group_timer.start(TASK_GROUP_REFRESH_MS)

        # Cron jobs timer - every 5 minutes
        self._cron_timer = QTimer(self)
        self._cron_timer.timeout.connect(self._fetch_cron_jobs)
        self._cron_timer.start(CRON_REFRESH_MS)

        # System metrics timer - every 3 seconds
        self._sys_timer = QTimer(self)
        self._sys_timer.timeout.connect(self._update_system_metrics)
        self._sys_timer.start(SYSTEM_METRICS_INTERVAL_MS)

        # Codex usage timer - short local app-server read plus SQLite totals
        self._codex_timer = QTimer(self)
        self._codex_timer.timeout.connect(self._refresh_codex_usage)
        self._codex_timer.start(CODEX_REFRESH_MS)

    def _fetch_usage(self, force: bool = False):
        if self._worker and self._worker.isRunning():
            return
        if not force and time.time() < self._rate_limit_until:
            # Still rate-limited; next one-shot QTimer fires when window expires
            remaining = int(self._rate_limit_until - time.time())
            log_line(f"skip fetch: rate-limit cooldown, {remaining}s remaining")
            return
        log_line(f"fetch start (force={force})")
        self._next_fetch_at = time.time() + REFRESH_INTERVAL_MS / 1000
        self._worker = FetchWorker(self._client)
        self._worker.finished.connect(self._on_usage_fetched)
        self._worker.start()

    def _seed_stats_row_from_usage(self, data: UsageData):
        """Push extra_usage state from data into the stats row."""
        extra_credits = ""
        if data.extra_usage_enabled and data.extra_usage_used_credits is not None:
            used = data.extra_usage_used_credits
            if data.extra_usage_monthly_limit is not None:
                extra_credits = f"${used:.2f}/${data.extra_usage_monthly_limit:.0f}"
            else:
                extra_credits = f"${used:.2f}"
        self._stats_row.set_data(
            self._history.avg_five_hour,
            self._history.peak_five_hour,
            self._history.trend,
            data.extra_usage_enabled,
            extra_credits=extra_credits,
            fast=read_fast_mode(),
        )

    def _on_usage_fetched(self, data: UsageData):
        # Rate-limited: set backoff and reschedule, keep previous data on screen
        if data.error == "Rate Limited":
            self._consecutive_429s += 1
            exp_delay = min(
                RATE_LIMIT_MIN_BACKOFF_S * (2 ** (self._consecutive_429s - 1)),
                RATE_LIMIT_MAX_BACKOFF_S,
            )
            delay = max(data.retry_after_s, exp_delay)
            self._rate_limit_until = time.time() + delay
            self._next_fetch_at = self._rate_limit_until
            save_rate_limit_until(self._rate_limit_until, self._consecutive_429s)
            log_line(
                f"429 #{self._consecutive_429s} retry_after={data.retry_after_s:.0f}s "
                f"exp={exp_delay}s -> next fetch in {int(delay)}s"
            )
            QTimer.singleShot(int(delay * 1000) + 1000, self._fetch_usage)
            if self._usage and not self._usage.error:
                # Preserve last-good _usage; just annotate status
                return
            # First fetch ever returned 429; store the error so display shows it
            self._usage = data
            self._update_display()
            return

        # Any non-429 response resets the backoff
        if self._consecutive_429s > 0 or self._rate_limit_until > 0:
            log_line(
                f"rate-limit cleared after {self._consecutive_429s} consecutive 429s"
            )
        self._consecutive_429s = 0
        self._rate_limit_until = 0.0
        save_rate_limit_until(0.0, 0)

        self._usage = data

        if not data.error:
            self._title_label.setText(data.plan_name)
            self._history.add(data)
            self._graph.set_points(self._history.points)
            self._seed_stats_row_from_usage(data)
            save_last_usage(data)
            scoped = "".join(
                f" {ml.name.lower()}={ml.entry.utilization:.0f}%"
                for ml in data.model_limits
            )
            log_line(
                f"fetch ok: 5h={data.five_hour.utilization:.0f}% "
                f"7d={data.seven_day.utilization:.0f}%{scoped} "
                f"plan={data.plan_name}"
            )
        elif data.error:
            log_line(f"fetch error: {data.error}")

        # Read token stats from Claude Code's local cache
        tstats = read_token_stats()
        if tstats:
            self._token_row.set_data(
                tstats.get("total_output", 0),
                tstats.get("total_cache", 0),
            )

        self._update_display()

    def _update_display(self):
        data = self._usage
        if data is None:
            return

        # Show error when we have no cached data to fall back on
        if data.error:
            now = time.time()
            if data.error == "Rate Limited" and now < self._rate_limit_until:
                delay = int(self._rate_limit_until - now)
                if delay >= 60:
                    delay_str = f"{delay // 60}m {delay % 60:02d}s"
                else:
                    delay_str = f"{delay}s"
                self._status_label.setText(f"Rate limited · retry in {delay_str}")
                self._status_label.setStyleSheet("color: #f59e0b; font-size: 10px;")
            else:
                self._status_label.setText(data.error)
                self._status_label.setStyleSheet("color: #ef4444; font-size: 10px;")
            return

        # Cached-good path: if we're in a rate-limit window, indicate stale data
        if time.time() < self._rate_limit_until:
            self._status_label.setStyleSheet("color: #f59e0b; font-size: 10px;")
        else:
            self._status_label.setStyleSheet("color: #666680; font-size: 10px;")

        estimate = self._history.estimated_time_left(data.five_hour.utilization)
        self._usage_limits.set_data(data, estimate=estimate)

        # Status line: if rate-limited, show "Stale · next in Xm Ys" countdown,
        # otherwise show true data age and next-update countdown.
        now = time.time()
        if now < self._rate_limit_until:
            delay = int(self._rate_limit_until - now)
            if delay >= 60:
                delay_str = f"{delay // 60}m {delay % 60:02d}s"
            else:
                delay_str = f"{delay}s"
            age = self._format_age(now - data.fetched_at) if data.fetched_at else "?"
            self._status_label.setText(
                f"Rate limited · {age} old · retry in {delay_str}"
            )
        else:
            remaining = max(0, int(self._next_fetch_at - now))
            age = self._format_age(now - data.fetched_at) if data.fetched_at else "just now"
            self._status_label.setText(f"Updated: {age}  ·  Next: {remaining}s")

    @staticmethod
    def _format_age(seconds: float) -> str:
        seconds = int(max(0, seconds))
        if seconds < 10:
            return "just now"
        if seconds < 60:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        return f"{hours}h {minutes % 60}m ago"

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

    def _toggle_history(self):
        self._history_expanded = not self._history_expanded
        visible = self._history_expanded
        for w in self._window_labels + self._window_spacers:
            w.setVisible(visible)
        self._graph.setVisible(visible)
        self._stats_sep.setVisible(visible)
        self._stats_row.setVisible(visible)
        self._token_row.setVisible(visible)

        arrow = "▾" if visible else "▸"
        if visible:
            self._graph_title.setText(f"Usage History {arrow}")
        else:
            avg = self._history.avg_five_hour
            peak = self._history.peak_five_hour
            trend = self._history.trend
            self._graph_title.setText(
                f"Usage History {arrow}  AVG {avg:.0f}%  PK {peak:.0f}%  {trend}"
            )
        self._update_window_tabs()
        self.adjustSize()

    def _update_countdowns(self):
        """Update countdown strings every second without re-fetching."""
        if self._usage:
            self._update_display()

    def _fetch_deploys(self):
        if self._deploy_worker and self._deploy_worker.isRunning():
            return
        self._deploy_worker = DeployFetchWorker()
        self._deploy_worker.finished.connect(self._on_deploys_fetched)
        self._deploy_worker.start()

    def _on_deploys_fetched(self, deploys: list):
        self._deploy_row.set_data(deploys)
        self.adjustSize()

    def _fetch_runners(self):
        if self._runner_worker and self._runner_worker.isRunning():
            return
        self._runner_worker = RunnerFetchWorker()
        self._runner_worker.finished.connect(self._on_runners_fetched)
        self._runner_worker.start()

    def _on_runners_fetched(self, runners: list):
        self._runners_row.set_data(runners)
        self.adjustSize()

    def _fetch_task_loops(self):
        if self._task_loop_worker and self._task_loop_worker.isRunning():
            return
        self._task_loop_worker = TaskLoopFetchWorker()
        self._task_loop_worker.finished.connect(self._on_task_loops_fetched)
        self._task_loop_worker.start()

    def _on_task_loops_fetched(self, loops: list):
        self._task_loop_row.set_data(loops)
        self.adjustSize()

    def _fetch_task_groups(self):
        if self._task_group_worker and self._task_group_worker.isRunning():
            return
        self._task_group_worker = TaskGroupFetchWorker()
        self._task_group_worker.finished.connect(self._on_task_groups_fetched)
        self._task_group_worker.start()

    def _fetch_cron_jobs(self):
        if self._cron_worker and self._cron_worker.isRunning():
            return
        self._cron_worker = CronJobsFetchWorker()
        self._cron_worker.finished.connect(self._on_cron_jobs_fetched)
        self._cron_worker.start()

    def _on_cron_jobs_fetched(self, jobs: list):
        self._cron_row.set_data(jobs)
        self.adjustSize()

    def _on_task_groups_fetched(self, groups: list):
        self._task_group_row.set_data(groups)
        self.adjustSize()

    def _update_system_metrics(self):
        metrics = self._sys_reader.read()
        self._sys_row.set_data(metrics)

    def _refresh_codex_usage(self):
        if self._codex_worker and self._codex_worker.isRunning():
            return
        self._codex_worker = CodexUsageWorker()
        self._codex_worker.result.connect(self._on_codex_usage_read)
        self._codex_worker.start()

    def _on_codex_usage_read(self, summary: CodexUsageSummary | None):
        self._codex_row.set_data(summary)
        self.adjustSize()

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

    def _setup_tray_icon(self):
        if self._shutdown_started or self._tray is not None:
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            if not self._tray_unavailable_logged:
                log_line("system tray unavailable; waiting for tray host")
                self._tray_unavailable_logged = True
            if not self._tray_retry_timer.isActive():
                self._tray_retry_timer.start()
            return

        self._tray_retry_timer.stop()
        icon = build_task_compass_icon()
        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("Claude Indicator · Smart TODOs")
        self._tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        self._smart_todo_action = QAction("Smart TODOs…", self)
        self._smart_todo_action.triggered.connect(self._show_smart_todos)
        menu.addAction(self._smart_todo_action)
        self._show_hide_action = QAction("Show/Hide", self)
        self._show_hide_action.triggered.connect(self._toggle_from_tray)
        menu.addAction(self._show_hide_action)
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _show_smart_todos(self):
        if self._smart_todo_dialog is None:
            self._smart_todo_dialog = SmartTodoDialog(parent=self)
            self._smart_todo_dialog.summary_changed.connect(
                self._on_todo_summary_changed
            )
        self._smart_todo_dialog.show_and_refresh()
        self._smart_todo_dialog.raise_()
        self._smart_todo_dialog.activateWindow()

    def _on_todo_summary_changed(self, focus_count: int, overdue_count: int):
        if self._tray is not None:
            self._tray.setToolTip(
                f"Claude Indicator · {focus_count} focus · "
                f"{overdue_count} overdue"
            )

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_from_tray()

    def _show_from_tray(self):
        if self._tray is None:
            return
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        if self._tray is None:
            return
        self.hide()

    def _toggle_from_tray(self):
        if self.isVisible():
            self.hide_to_tray()
        else:
            self._show_from_tray()

    def shutdown(self):
        if self._shutdown_started:
            return
        self._shutdown_started = True
        self._tray_retry_timer.stop()
        if self._smart_todo_dialog is not None:
            self._smart_todo_dialog.shutdown()

    def closeEvent(self, event):
        if self._tray is not None:
            event.ignore()
            self.hide_to_tray()
            return
        self.shutdown()
        event.accept()

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
    app.setQuitOnLastWindowClosed(False)

    widget = ClaudeWidget()
    app.aboutToQuit.connect(widget.shutdown)
    widget.show()
    widget.adjustSize()
    widget.raise_()
    widget.activateWindow()

    # Position at top-right of screen with some padding
    screen = app.primaryScreen().geometry()
    widget.move(screen.width() - widget.width() - 20, 40)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
