"""usage_history.json must keep recording weekly-only local quota snapshots."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import time
from unittest.mock import patch

import pytest
import claude_widget as widget

spec = importlib.util.spec_from_file_location("collector", Path(__file__).parents[1] / "scripts/claude_statusline.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)

POINT_KEYS = {"timestamp", "five_hour_pct", "seven_day_pct", "model_pct", "model_name"}


@pytest.fixture
def feed(tmp_path):
    directory = tmp_path / ".claude"
    directory.mkdir()
    (directory / "settings.json").write_text(json.dumps({"statusLine": {"command": "python3 scripts/claude_statusline.py"}}))
    destination = directory / "indicator_quota.json"
    with patch.object(Path, "home", return_value=tmp_path), patch.object(widget, "CLAUDE_STATUSLINE_PATH", destination):
        yield destination


def weekly_only(used, fetched_at):
    reset = datetime_iso(fetched_at + 3 * 86400)
    return widget.UsageData(seven_day=widget.UsageEntry(used, reset), fetched_at=fetched_at, source=widget.USAGE_SOURCE_STATUSLINE)


def datetime_iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def test_weekly_only_status_line_capture_is_recorded(feed, tmp_path):
    # Ultra accounts: Claude Code's status line carries no five_hour window.
    collector.capture({"rate_limits": {"seven_day": {"used_percentage": 36, "resets_at": time.time() + 86400}}}, feed)
    data = widget.read_claude_statusline_usage()
    assert data.error == "" and data.five_hour.resets_at == ""
    history_path = tmp_path / ".claude" / "usage_history.json"
    history = widget.UsageHistory(history_path)
    assert history.add(data) is True
    raw = json.loads(history_path.read_text())
    assert len(raw) == 1 and set(raw[0]) == POINT_KEYS
    assert raw[0]["seven_day_pct"] == 36.0
    assert raw[0]["five_hour_pct"] == 0.0
    assert raw[0]["timestamp"] == data.fetched_at
    assert widget.history_series_for(data) == widget.HISTORY_SERIES_SEVEN_DAY


def test_repeated_snapshots_keep_one_point_per_minute(tmp_path):
    history = widget.UsageHistory(tmp_path / "usage_history.json")
    start = time.time() - 3600
    assert history.add(weekly_only(30, start))
    assert not history.add(weekly_only(30, start)), "same snapshot re-read"
    assert not history.add(weekly_only(31, start + 20)), "status line re-rendered within a minute"
    assert history.add(weekly_only(31, start + widget.HISTORY_MIN_INTERVAL_S))
    assert not history.add(widget.UsageData(error="Waiting for Claude Code quota", source=widget.USAGE_SOURCE_STATUSLINE))
    assert [p.seven_day_pct for p in history.points] == [30, 31]
    assert len(json.loads((tmp_path / "usage_history.json").read_text())) == 2


def test_history_stays_bounded_at_status_line_rate(tmp_path):
    path = tmp_path / "usage_history.json"
    history = widget.UsageHistory(path)
    now = time.time()
    # Two days of snapshots every 20 seconds, as concurrent sessions produce.
    with patch.object(history, "_save"):
        for i in range(2 * 86400 // 20):
            history.add(weekly_only(10 + i * 0.001, now - 2 * 86400 + i * 20))
    history._save()
    raw = json.loads(path.read_text())
    assert len(raw) <= widget.MAX_HISTORY_POINTS
    assert len(raw) >= widget.MAX_HISTORY_POINTS - 2
    assert now - raw[0]["timestamp"] <= widget.MAX_HISTORY_AGE_S
    assert raw[-1]["timestamp"] > now - 60


def test_load_drops_points_older_than_the_window_and_graphs_weekly_series(tmp_path):
    path = tmp_path / "usage_history.json"
    now = time.time()
    path.write_text(json.dumps([
        {"timestamp": now - 6 * 86400, "five_hour_pct": 25.0, "seven_day_pct": 93.0, "model_pct": 0.0, "model_name": "unknown"},
        {"timestamp": now - 120, "five_hour_pct": 0.0, "seven_day_pct": 35.0, "model_pct": 0.0, "model_name": "unknown"},
        {"timestamp": now - 60, "five_hour_pct": 0.0, "seven_day_pct": 37.0, "model_pct": 0.0, "model_name": "unknown"},
    ]))
    history = widget.UsageHistory(path)
    assert [p.seven_day_pct for p in history.points] == [35.0, 37.0]
    history.series = widget.HISTORY_SERIES_SEVEN_DAY
    assert history.avg_pct == 36.0
    assert history.peak_pct == 37.0
    history.series = widget.HISTORY_SERIES_FIVE_HOUR
    assert history.peak_pct == 0.0


def test_series_follows_available_windows():
    now = time.time()
    both = widget.UsageData(
        five_hour=widget.UsageEntry(5, datetime_iso(now + 3600)),
        seven_day=widget.UsageEntry(40, datetime_iso(now + 86400)),
        fetched_at=now, source=widget.USAGE_SOURCE_STATUSLINE,
    )
    assert widget.history_series_for(both) == widget.HISTORY_SERIES_FIVE_HOUR
    assert widget.history_series_for(weekly_only(40, now)) == widget.HISTORY_SERIES_SEVEN_DAY
    headers = widget.UsageData(five_hour=widget.UsageEntry(5), seven_day=widget.UsageEntry(40), source=widget.USAGE_SOURCE_RATELIMIT_HEADERS)
    assert widget.history_series_for(headers) == widget.HISTORY_SERIES_FIVE_HOUR
