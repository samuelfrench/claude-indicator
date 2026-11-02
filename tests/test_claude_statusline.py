"""The local quota feed must preserve privacy and never fall through to HTTP."""
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


@pytest.fixture
def feed(tmp_path):
    directory = tmp_path / ".claude"
    directory.mkdir()
    (directory / "settings.json").write_text(json.dumps({"statusLine": {"command": "python3 scripts/claude_statusline.py"}}))
    destination = directory / "indicator_quota.json"
    with patch.object(Path, "home", return_value=tmp_path), patch.object(widget, "CLAUDE_STATUSLINE_PATH", destination):
        yield destination


def payload():
    return {"rate_limits": {name: {"used_percentage": used, "resets_at": time.time() + reset, "private": "discard"} for name, used, reset in [("five_hour", 23.5, 3600), ("seven_day", 41.2, 86400)]}, "prompt": "discard"}


def test_capture_and_read_without_provider_calls(feed):
    collector.capture(payload(), feed)
    raw = json.loads(feed.read_text())
    assert set(raw) == {"rate_limits", "fetched_at"}
    assert "discard" not in feed.read_text()
    assert feed.stat().st_mode & 0o777 == 0o600
    result = widget.ClaudeUsageClient().fetch()
    assert result.error == ""
    assert result.source == "statusline"
    assert result.five_hour.utilization == 23.5
    assert result.seven_day.utilization == 41.2


@pytest.mark.parametrize("kind", ["missing", "malformed", "too_old", "future"])
def test_unavailable_feed_never_probes_or_invents_quota(feed, kind):
    collector.capture(payload(), feed)
    raw = json.loads(feed.read_text())
    if kind == "missing":
        feed.unlink()
    elif kind == "malformed":
        feed.write_text("{")
    else:
        if kind == "too_old": raw["fetched_at"] -= 7 * 86400 + 1
        if kind == "future": raw["fetched_at"] += 60
        if kind == "expired": raw["rate_limits"]["five_hour"]["resets_at"] = 1
        if kind == "partial": del raw["rate_limits"]["seven_day"]
        if kind == "nan": raw["rate_limits"]["five_hour"]["used_percentage"] = float("nan")
        feed.write_text(json.dumps(raw))
    result = widget.ClaudeUsageClient().fetch()
    assert result.error
    assert result.source == "statusline"


def test_absent_rate_limits_does_not_refresh_snapshot(feed):
    collector.capture(payload(), feed)
    before = feed.read_bytes()
    collector.capture({"model": {"id": "irrelevant"}}, feed)
    assert feed.read_bytes() == before


@pytest.mark.parametrize("kind", ["partial", "expired", "nan"])
def test_independent_windows(feed, kind):
    raw = payload()
    if kind == "partial": del raw["rate_limits"]["five_hour"]
    if kind == "expired": raw["rate_limits"]["five_hour"]["resets_at"] = 1
    if kind == "nan": raw["rate_limits"]["five_hour"]["used_percentage"] = float("nan")
    collector.capture(raw, feed)
    result = widget.ClaudeUsageClient().fetch()
    assert not result.error
    assert not result.five_hour.resets_at
    assert result.seven_day.utilization == 41.2


def test_render_partial_windows_without_zero_meter(feed):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    raw = payload()
    del raw["rate_limits"]["five_hour"]
    collector.capture(raw, feed)
    limits = widget.UsageLimitsWidget()
    limits.set_data(widget.ClaudeUsageClient().fetch())
    assert limits.five_hour_bar.isHidden()
    assert not limits.seven_day_bar.isHidden()
    limits.close()


@pytest.mark.parametrize("age", [301, 3600, 10 * 3600])
def test_idle_snapshot_preserves_weekly_quota_until_reset(feed, age):
    collector.capture(payload(), feed)
    raw = json.loads(feed.read_text())
    raw["fetched_at"] -= age
    # Five-hour window has reset; weekly observation remains useful.
    raw["rate_limits"]["five_hour"]["resets_at"] = time.time() - 1
    feed.write_text(json.dumps(raw))
    result = widget.ClaudeUsageClient().fetch()
    assert not result.error
    assert result.fetched_at == raw["fetched_at"]
    assert result.seven_day.utilization == 41.2
    assert not result.five_hour.resets_at


def test_all_windows_reset_waits_without_inventing_zero(feed):
    raw = payload()
    for window in raw["rate_limits"].values():
        window["resets_at"] = time.time() - 1
    collector.capture(raw, feed)
    result = widget.ClaudeUsageClient().fetch()
    assert result.error == "Waiting for Claude Code quota"
    assert not result.five_hour.resets_at
    assert not result.seven_day.resets_at


def test_loaded_local_meters_hide_at_reset_without_waiting_for_fetch(feed):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    collector.capture(payload(), feed)
    result = widget.ClaudeUsageClient().fetch()
    limits = widget.UsageLimitsWidget()
    limits.set_data(result, estimate="old estimate")
    assert not limits.five_hour_bar.isHidden()
    with patch("claude_widget.time.time", return_value=time.time() + 86401):
        limits.set_data(result, estimate="old estimate")
    assert limits.five_hour_bar.isHidden()
    assert limits.seven_day_bar.isHidden()
    assert limits.estimate_label.text() == ""
    limits.close()
