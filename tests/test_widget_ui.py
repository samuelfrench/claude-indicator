import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import claude_widget
from claude_widget import (
    ClaudeWidget,
    ClaudeUsageClient,
    CodexUsageWorker,
    CodexUsageRow,
    CodexUsageSummary,
    ModelLimit,
    _parse_codex_app_server_rate_limit,
    _parse_codex_rate_limit_event,
    _parse_model_limits,
    load_last_usage,
    read_codex_rate_limit,
    read_latest_codex_rate_limit,
    read_codex_usage_summary,
    save_last_usage,
    UsageData,
    UsageEntry,
    UsageLimitsWidget,
)


class WidgetUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_task_loop_status_reads_local_config_without_aws(self):
        config = {
            "honey-explorer": {
                "autonomous": {
                    "enabled": True,
                    "model": "claude-opus-4-6",
                    "effort": "high",
                    "cooldown_minutes": 10,
                }
            },
            "disabled-project": {"autonomous": {"enabled": False}},
        }
        fake_boto3 = ModuleType("boto3")
        fake_boto3.resource = Mock()
        fake_dynamodb = ModuleType("boto3.dynamodb")
        fake_conditions = ModuleType("boto3.dynamodb.conditions")
        fake_conditions.Key = Mock()

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "projects.json"
            config_path.write_text(json.dumps(config))
            with (
                patch.object(claude_widget, "PROJECTS_JSON_PATH", config_path),
                patch.dict(
                    sys.modules,
                    {
                        "boto3": fake_boto3,
                        "boto3.dynamodb": fake_dynamodb,
                        "boto3.dynamodb.conditions": fake_conditions,
                    },
                ),
            ):
                loops = claude_widget.fetch_task_loop_status()

        self.assertEqual(len(loops), 1)
        self.assertEqual(loops[0].name, "honey-explorer")
        self.assertEqual(loops[0].model, "claude-opus-4-6")
        self.assertEqual(loops[0].effort, "high")
        self.assertEqual(loops[0].cooldown_minutes, 10)
        self.assertIsNone(loops[0].last_task_ts)
        fake_boto3.resource.assert_not_called()

    def test_usage_limits_widget_collapses_all_usage_bars_as_one_group(self):
        widget = UsageLimitsWidget()
        widget.set_data(
            UsageData(
                five_hour=UsageEntry(utilization=21, resets_at=""),
                seven_day=UsageEntry(utilization=32, resets_at=""),
                seven_day_sonnet=UsageEntry(utilization=43, resets_at=""),
            ),
            estimate="At current pace: 2h left",
        )

        expanded_height = widget.height()
        self.assertTrue(widget.is_expanded())
        self.assertFalse(widget.five_hour_bar.isHidden())
        self.assertFalse(widget.estimate_label.isHidden())
        self.assertFalse(widget.seven_day_bar.isHidden())
        self.assertEqual(
            [bar._label for bar in widget.model_bars], ["Sonnet (7-Day)"]
        )
        self.assertFalse(widget.model_bars[0].isHidden())

        widget.toggle_expanded()

        self.assertFalse(widget.is_expanded())
        self.assertLess(widget.height(), expanded_height)
        self.assertTrue(widget.five_hour_bar.isHidden())
        self.assertTrue(widget.estimate_label.isHidden())
        self.assertTrue(widget.seven_day_bar.isHidden())
        self.assertTrue(widget.model_bars[0].isHidden())

    _SCOPED_LIMITS_PAYLOAD = {
        "five_hour": {"utilization": 9.0, "resets_at": "2026-07-04T14:39:59+00:00"},
        "seven_day": {"utilization": 3.0, "resets_at": "2026-07-07T07:59:59+00:00"},
        "seven_day_opus": None,
        "seven_day_sonnet": None,
        "extra_usage": {"is_enabled": False},
        "limits": [
            {
                "kind": "session",
                "group": "session",
                "percent": 9,
                "severity": "normal",
                "resets_at": "2026-07-04T14:39:59+00:00",
                "scope": None,
                "is_active": True,
            },
            {
                "kind": "weekly_all",
                "group": "weekly",
                "percent": 3,
                "severity": "normal",
                "resets_at": "2026-07-07T07:59:59+00:00",
                "scope": None,
                "is_active": False,
            },
            {
                "kind": "weekly_scoped",
                "group": "weekly",
                "percent": 3,
                "severity": "normal",
                "resets_at": "2026-07-07T07:59:59+00:00",
                "scope": {
                    "model": {"id": None, "display_name": "Fable"},
                    "surface": None,
                },
                "is_active": False,
            },
        ],
    }

    def test_parse_model_limits_extracts_model_scoped_entries_only(self):
        limits = _parse_model_limits(self._SCOPED_LIMITS_PAYLOAD)

        self.assertEqual(len(limits), 1)
        self.assertEqual(limits[0].name, "Fable")
        self.assertEqual(limits[0].window, "7-Day")
        self.assertEqual(limits[0].entry.utilization, 3.0)
        self.assertEqual(limits[0].entry.resets_at, "2026-07-07T07:59:59+00:00")

    def test_fetch_populates_model_limits_from_limits_array(self):
        client = ClaudeUsageClient()

        class FakeResponse:
            status_code = 200

            def json(self):
                return WidgetUiTest._SCOPED_LIMITS_PAYLOAD

        creds = {"accessToken": "token", "expiresAt": 4_102_444_800_000}
        with patch.object(
            ClaudeUsageClient, "_read_credentials", return_value=creds
        ), patch("claude_widget.requests.get", return_value=FakeResponse()):
            data = client.fetch()

        self.assertEqual(data.error, "")
        self.assertEqual([ml.name for ml in data.model_limits], ["Fable"])
        self.assertEqual(data.model_name, "fable")
        self.assertEqual(data.model_pct, 3.0)

    def test_display_model_limits_merges_scoped_and_legacy_without_duplicates(self):
        data = UsageData(
            model_limits=[
                ModelLimit(
                    name="Fable", window="7-Day", entry=UsageEntry(utilization=3.0)
                )
            ],
            seven_day_opus=UsageEntry(utilization=55.0),
        )

        self.assertEqual(
            [(ml.name, ml.entry.utilization) for ml in data.display_model_limits],
            [("Fable", 3.0), ("Opus", 55.0)],
        )

        deduped = UsageData(
            model_limits=[
                ModelLimit(
                    name="Opus", window="7-Day", entry=UsageEntry(utilization=41.0)
                )
            ],
            seven_day_opus=UsageEntry(utilization=55.0),
        )
        self.assertEqual(
            [(ml.name, ml.entry.utilization) for ml in deduped.display_model_limits],
            [("Opus", 41.0)],
        )

    def test_last_usage_round_trips_model_limits(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "last_usage.json"
            saved = UsageData(
                five_hour=UsageEntry(
                    utilization=9.0, resets_at="2026-07-04T14:39:59+00:00"
                ),
                seven_day=UsageEntry(
                    utilization=3.0, resets_at="2026-07-07T07:59:59+00:00"
                ),
                model_limits=[
                    ModelLimit(
                        name="Fable",
                        window="7-Day",
                        entry=UsageEntry(
                            utilization=3.0, resets_at="2026-07-07T07:59:59+00:00"
                        ),
                    )
                ],
                fetched_at=1_783_158_609.0,
            )
            with patch("claude_widget.LAST_USAGE_PATH", path):
                save_last_usage(saved)
                loaded = load_last_usage()

        self.assertIsNotNone(loaded)
        self.assertEqual([ml.name for ml in loaded.model_limits], ["Fable"])
        self.assertEqual(loaded.model_limits[0].window, "7-Day")
        self.assertEqual(loaded.model_limits[0].entry.utilization, 3.0)
        self.assertEqual(
            loaded.model_limits[0].entry.resets_at, "2026-07-07T07:59:59+00:00"
        )

    def test_usage_limits_widget_builds_one_bar_per_model_limit(self):
        widget = UsageLimitsWidget()
        widget.set_data(
            UsageData(
                five_hour=UsageEntry(utilization=9.0),
                seven_day=UsageEntry(utilization=3.0),
                model_limits=[
                    ModelLimit(
                        name="Fable",
                        window="7-Day",
                        entry=UsageEntry(utilization=3.0),
                    )
                ],
            )
        )

        self.assertEqual([bar._label for bar in widget.model_bars], ["Fable (7-Day)"])
        self.assertEqual(widget.model_bars[0]._pct, 3.0)
        self.assertFalse(widget.model_bars[0].isHidden())
        self.assertEqual(widget.height(), 176)

        widget.toggle_expanded()
        self.assertTrue(widget.model_bars[0].isHidden())

    def test_usage_limits_widget_rebuilds_bars_when_limits_change(self):
        widget = UsageLimitsWidget()
        fable = ModelLimit(
            name="Fable", window="7-Day", entry=UsageEntry(utilization=3.0)
        )
        opus = ModelLimit(
            name="Opus", window="7-Day", entry=UsageEntry(utilization=41.0)
        )

        widget.set_data(UsageData(model_limits=[fable]))
        self.assertEqual([bar._label for bar in widget.model_bars], ["Fable (7-Day)"])

        widget.set_data(UsageData(model_limits=[opus, fable]))
        self.assertEqual(
            [bar._label for bar in widget.model_bars],
            ["Opus (7-Day)", "Fable (7-Day)"],
        )
        self.assertEqual(widget.height(), 222)

        widget.set_data(UsageData())
        self.assertEqual(widget.model_bars, [])
        self.assertEqual(widget.height(), 130)

    class _FakeSignal:
        def __init__(self):
            self.slot = None

        def connect(self, slot):
            self.slot = slot

        def emit(self, *args):
            if self.slot is not None:
                self.slot(*args)

    class _FakeSmartTodoDialog:
        def __init__(self, *, parent=None):
            self.parent = parent
            self.summary_changed = WidgetUiTest._FakeSignal()
            self.show_and_refresh = Mock()
            self.raise_ = Mock()
            self.activateWindow = Mock()
            self.shutdown = Mock()

    def _make_inert_claude_widget(
        self,
        *,
        tray_available: bool = False,
        smart_todo_dialog_factory=None,
    ):
        dialog_factory = smart_todo_dialog_factory or Mock(
            side_effect=self._FakeSmartTodoDialog
        )
        patches = [
            patch.object(
                QSystemTrayIcon,
                "isSystemTrayAvailable",
                side_effect=(
                    tray_available if callable(tray_available) else None
                ),
                return_value=tray_available if not callable(tray_available) else False,
            ),
            patch.object(ClaudeWidget, "_setup_timers", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_usage", lambda self, force=False: None),
            patch.object(ClaudeWidget, "_fetch_deploys", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_runners", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_task_loops", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_task_groups", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_cron_jobs", lambda self: None),
            patch.object(ClaudeWidget, "_update_system_metrics", lambda self: None),
            patch.object(ClaudeWidget, "_refresh_codex_usage", lambda self: None),
            patch.object(claude_widget, "SmartTodoDialog", dialog_factory),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        widget = ClaudeWidget()
        self.addCleanup(widget.deleteLater)
        return widget

    def test_task_compass_icon_renders_common_tray_sizes(self):
        for size in (16, 32, 64):
            with self.subTest(size=size):
                icon = claude_widget.build_task_compass_icon(size)
                self.assertFalse(icon.isNull())
                self.assertFalse(icon.pixmap(size, size).isNull())

    def test_claude_tray_menu_places_smart_todos_first(self):
        widget = self._make_inert_claude_widget(tray_available=True)

        actions = widget._tray.contextMenu().actions()

        self.assertEqual(
            [action.text() for action in actions],
            ["Smart TODOs…", "Show/Hide", "", "Quit"],
        )
        self.assertTrue(actions[2].isSeparator())

    def test_smart_todo_tray_has_exact_initial_tooltip(self):
        widget = self._make_inert_claude_widget(tray_available=True)

        self.assertEqual(widget._tray.toolTip(), "Claude Indicator · Smart TODOs")

    def test_smart_todo_action_creates_one_dialog_and_reuses_it(self):
        dialog_factory = Mock(side_effect=self._FakeSmartTodoDialog)
        widget = self._make_inert_claude_widget(
            tray_available=True,
            smart_todo_dialog_factory=dialog_factory,
        )

        widget._smart_todo_action.trigger()
        dialog = widget._smart_todo_dialog
        widget._smart_todo_action.trigger()

        dialog_factory.assert_called_once_with(parent=widget)
        self.assertIsNotNone(dialog)
        self.assertIs(widget._smart_todo_dialog, dialog)
        self.assertEqual(dialog.show_and_refresh.call_count, 2)
        self.assertEqual(dialog.raise_.call_count, 2)
        self.assertEqual(dialog.activateWindow.call_count, 2)

    def test_smart_todo_summary_updates_tray_tooltip(self):
        widget = self._make_inert_claude_widget(tray_available=True)
        widget._smart_todo_action.trigger()

        widget._smart_todo_dialog.summary_changed.emit(7, 2)

        self.assertEqual(
            widget._tray.toolTip(),
            "Claude Indicator · 7 focus · 2 overdue",
        )

    def test_tray_unavailable_does_not_create_smart_todo_action(self):
        widget = self._make_inert_claude_widget(tray_available=False)

        self.assertIsNone(widget._tray)
        self.assertIsNone(widget._smart_todo_action)
        self.assertIsNone(widget._smart_todo_dialog)

    def test_tray_unavailable_retries_and_creates_controls_exactly_once(self):
        available = [False]
        widget = self._make_inert_claude_widget(
            tray_available=lambda: available[0]
        )

        retry_timer = getattr(widget, "_tray_retry_timer", None)
        self.assertIsNotNone(retry_timer)
        self.assertTrue(retry_timer.isActive())

        available[0] = True
        retry_timer.timeout.emit()

        tray = widget._tray
        self.assertIsNotNone(tray)
        self.assertFalse(retry_timer.isActive())
        self.assertEqual(
            [action.text() for action in tray.contextMenu().actions()],
            ["Smart TODOs…", "Show/Hide", "", "Quit"],
        )

        retry_timer.timeout.emit()

        self.assertIs(widget._tray, tray)
        self.assertEqual(len(tray.contextMenu().actions()), 4)

    def test_repeated_unavailable_tray_retries_log_only_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "widget.log"
            with patch.object(claude_widget, "LOG_PATH", log_path):
                widget = self._make_inert_claude_widget(tray_available=False)
                retry_timer = getattr(widget, "_tray_retry_timer", None)
                self.assertIsNotNone(retry_timer)
                retry_timer.timeout.emit()
                retry_timer.timeout.emit()

            lines = log_path.read_text().splitlines()

        self.assertEqual(
            sum("system tray unavailable" in line for line in lines),
            1,
        )

    def test_shutdown_stops_tray_retry_and_blocks_late_creation(self):
        available = [False]
        widget = self._make_inert_claude_widget(
            tray_available=lambda: available[0]
        )
        retry_timer = getattr(widget, "_tray_retry_timer", None)
        self.assertIsNotNone(retry_timer)
        self.assertTrue(retry_timer.isActive())

        widget.shutdown()
        available[0] = True
        retry_timer.timeout.emit()

        self.assertFalse(retry_timer.isActive())
        self.assertIsNone(widget._tray)
        self.assertIsNone(widget._smart_todo_action)

    def test_close_and_application_shutdown_stop_dialog_exactly_once(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        dialog = self._FakeSmartTodoDialog(parent=widget)
        widget._smart_todo_dialog = dialog

        class Event:
            accepted = False

            def accept(self):
                self.accepted = True

        event = Event()
        widget.closeEvent(event)
        widget.shutdown()

        self.assertTrue(event.accepted)
        dialog.shutdown.assert_called_once_with()

    def test_widget_grows_when_model_limit_bar_appears(self):
        widget = self._make_inert_claude_widget()
        widget.show()
        widget._usage_limits.set_data(UsageData())
        widget.adjustSize()
        QApplication.processEvents()
        before = widget.height()

        widget._usage_limits.set_data(
            UsageData(
                model_limits=[
                    ModelLimit(
                        name="Fable",
                        window="7-Day",
                        entry=UsageEntry(utilization=3.0),
                    )
                ]
            )
        )
        widget.adjustSize()
        QApplication.processEvents()

        self.assertGreater(widget.height(), before)

    def test_claude_header_minimize_button_toggles_from_tray(self):
        widget = self._make_inert_claude_widget(tray_available=True)
        calls = []
        widget._toggle_from_tray = lambda: calls.append("toggle")

        widget._minimize_btn.mousePressEvent(None)

        self.assertEqual(calls, ["toggle"])

    def test_claude_header_minimize_button_closes_without_tray(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        calls = []
        widget.close = lambda: calls.append("close")

        widget._minimize_btn.mousePressEvent(None)

        self.assertEqual(calls, ["close"])

    def test_claude_close_event_uses_hide_to_tray(self):
        widget = self._make_inert_claude_widget(tray_available=True)
        calls = []
        widget.hide_to_tray = lambda: calls.append("hide")

        class Event:
            ignored = False

            def ignore(self):
                self.ignored = True

        event = Event()
        widget.closeEvent(event)

        self.assertTrue(event.ignored)
        self.assertEqual(calls, ["hide"])

    def test_claude_tray_show_hide_action_toggles_visibility(self):
        widget = self._make_inert_claude_widget(tray_available=True)

        self.assertEqual(widget._show_hide_action.text(), "Show/Hide")
        widget.show()
        widget._show_hide_action.trigger()
        self.assertFalse(widget.isVisible())

        widget._show_hide_action.trigger()
        self.assertTrue(widget.isVisible())

    def test_codex_usage_row_expands_to_show_detail_rows(self):
        row = CodexUsageRow()
        row.set_data(
            CodexUsageSummary(
                latest_thread_tokens=12_345,
                total_tokens=987_654,
                thread_count=42,
                latest_thread_title="Investigate local Codex accounting",
                latest_model="gpt-5.5",
                latest_updated_at=1_767_300_000,
                latest_cwd="/home/sam/claude-workspace/claude-indicator",
                primary_limit_used_percent=37.5,
                primary_limit_window_minutes=300,
                primary_limit_resets_at=1_767_318_000,
                secondary_limit_used_percent=12.0,
                secondary_limit_window_minutes=10080,
                secondary_limit_resets_at=1_767_900_000,
                plan_type="pro",
            )
        )

        collapsed_height = row.height()
        self.assertFalse(row.is_expanded())

        row.toggle_expanded()

        self.assertTrue(row.is_expanded())
        self.assertGreater(row.height(), collapsed_height)
        self.assertIn("Investigate local Codex accounting", row.toolTip())
        self.assertIn("5h limit: 37.5% used", row.toolTip())
        self.assertIn("7d limit: 12.0% used", row.toolTip())

    def test_codex_usage_row_collapsed_metrics_show_limit_windows(self):
        row = CodexUsageRow()
        summary = CodexUsageSummary(
            latest_thread_tokens=12_345,
            primary_limit_used_percent=37.5,
            primary_limit_window_minutes=300,
            secondary_limit_used_percent=12.0,
            secondary_limit_window_minutes=10080,
        )

        metrics = row._collapsed_metrics(summary)

        self.assertEqual(
            [(label, value) for label, value, _color in metrics],
            [("5H", "37.5%"), ("7D", "12.0%"), ("LAST", "12.3K")],
        )

    def test_codex_usage_row_only_formats_present_rate_limit_window(self):
        row = CodexUsageRow()
        summary = CodexUsageSummary(
            latest_thread_tokens=12_345,
            primary_limit_used_percent=70.0,
            primary_limit_window_minutes=10080,
            primary_limit_resets_at=1_786_159_934,
            secondary_limit_used_percent=None,
            secondary_limit_window_minutes=0,
            secondary_limit_resets_at=0,
        )

        row.set_data(summary)
        metrics = row._collapsed_metrics(summary)
        details = row._expanded_details(summary)

        self.assertEqual(
            [(label, value) for label, value, _color in metrics],
            [("7D", "70.0%"), ("LAST", "12.3K")],
        )
        self.assertEqual([label for label, _value in details if "LIMIT" in label], ["7D LIMIT"])
        self.assertEqual(row.toolTip().count("7d limit:"), 1)

    def test_codex_usage_row_marks_cached_rate_limit_source(self):
        now_ts = time.time()
        row = CodexUsageRow()
        summary = CodexUsageSummary(
            latest_thread_tokens=12_345,
            primary_limit_used_percent=70.0,
            primary_limit_window_minutes=10080,
            primary_limit_resets_at=int(now_ts + 3600),
            rate_limit_source="cached",
            rate_limit_observed_at=now_ts - 30,
        )

        row.set_data(summary)
        details = dict(row._expanded_details(summary))

        self.assertEqual(row._title_text(summary, "▸"), "CODEX CACHE ▸")
        self.assertIn("cached local session fallback", row.toolTip())
        self.assertIn("cached local session fallback", details["SOURCE"])

    def test_parse_live_codex_rate_limit_selects_base_camel_case_bucket(self):
        response = {
            "id": 2,
            "result": {
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {
                        "usedPercent": 99,
                        "windowDurationMins": 300,
                        "resetsAt": 1,
                    },
                    "secondary": None,
                },
                "rateLimitsByLimitId": {
                    "codex": {
                        "limitId": "codex",
                        "primary": {
                            "usedPercent": 70,
                            "windowDurationMins": 10080,
                            "resetsAt": 1_786_159_934,
                        },
                        "secondary": None,
                        "planType": "pro",
                        "rateLimitReachedType": None,
                    },
                    "codex_bengalfox": {
                        "limitId": "codex_bengalfox",
                        "primary": {
                            "usedPercent": 0,
                            "windowDurationMins": 10080,
                            "resetsAt": 1_786_409_468,
                        },
                        "secondary": None,
                    },
                },
            },
        }

        rate_limit = _parse_codex_app_server_rate_limit(response)

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.primary_used_percent, 70.0)
        self.assertEqual(rate_limit.primary_window_minutes, 10080)
        self.assertEqual(rate_limit.primary_resets_at, 1_786_159_934)
        self.assertIsNone(rate_limit.secondary_used_percent)
        self.assertEqual(rate_limit.plan_type, "pro")

    def test_parse_live_codex_rate_limit_supports_two_windows(self):
        response = {
            "result": {
                "rateLimits": {
                    "limitId": "codex",
                    "primary": {
                        "usedPercent": 37.5,
                        "windowDurationMins": 300,
                        "resetsAt": 1_767_318_000,
                    },
                    "secondary": {
                        "usedPercent": 12,
                        "windowDurationMins": 10080,
                        "resetsAt": 1_767_900_000,
                    },
                    "planType": "pro",
                }
            }
        }

        rate_limit = _parse_codex_app_server_rate_limit(response)

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.primary_window_minutes, 300)
        self.assertEqual(rate_limit.secondary_used_percent, 12.0)
        self.assertEqual(rate_limit.secondary_window_minutes, 10080)

    def test_read_codex_rate_limit_falls_back_when_subprocess_fails(self):
        resets_at = int(time.time() + 3600)
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            (sessions_dir / "cached.jsonl").write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "rate_limits": {
                                "limit_id": "codex",
                                "primary": {
                                    "used_percent": 44.0,
                                    "window_minutes": 300,
                                    "resets_at": resets_at,
                                },
                                "secondary": None,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(claude_widget.subprocess, "Popen", side_effect=OSError):
                rate_limit = read_codex_rate_limit(sessions_dir=sessions_dir)

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.primary_used_percent, 44.0)

    def test_read_codex_rate_limit_falls_back_on_malformed_live_response(self):
        resets_at = int(time.time() + 3600)
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            (sessions_dir / "cached.jsonl").write_text(
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "rate_limits": {
                                "limit_id": "codex",
                                "primary": {
                                    "used_percent": 31.0,
                                    "window_minutes": 10080,
                                    "resets_at": resets_at,
                                },
                                "secondary": None,
                            },
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            malformed = {
                "id": 2,
                "result": {
                    "rateLimits": {
                        "limitId": "codex",
                        "primary": "not-an-object",
                        "secondary": None,
                    }
                },
            }
            with patch.object(
                claude_widget,
                "_request_codex_app_server_rate_limits",
                return_value=malformed,
            ):
                rate_limit = read_codex_rate_limit(sessions_dir=sessions_dir)

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.primary_used_percent, 31.0)

    def test_read_latest_codex_rate_limit_rejects_stale_event_timestamp(self):
        now_ts = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            (sessions_dir / "stale.jsonl").write_text(
                '{"timestamp":1799999699,"type":"event_msg","payload":{'
                '"type":"token_count","rate_limits":{"limit_id":"codex",'
                '"primary":{"used_percent":44.0,"window_minutes":300,'
                '"resets_at":1800003600},"secondary":null}}}\n',
                encoding="utf-8",
            )

            rate_limit = read_latest_codex_rate_limit(
                sessions_dir=sessions_dir, now_ts=now_ts
            )

        self.assertIsNone(rate_limit)

    def test_read_latest_codex_rate_limit_rejects_expired_reset(self):
        now_ts = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            (sessions_dir / "expired.jsonl").write_text(
                '{"timestamp":1800000000,"type":"event_msg","payload":{'
                '"type":"token_count","rate_limits":{"limit_id":"codex",'
                '"primary":{"used_percent":44.0,"window_minutes":300,'
                '"resets_at":1799999999},"secondary":null}}}\n',
                encoding="utf-8",
            )

            rate_limit = read_latest_codex_rate_limit(
                sessions_dir=sessions_dir, now_ts=now_ts
            )

        self.assertIsNone(rate_limit)

    def test_parse_cached_codex_rate_limit_safely_handles_malformed_numbers(self):
        rate_limit = _parse_codex_rate_limit_event(
            '{"timestamp":1800000000,"type":"event_msg","payload":{'
            '"type":"token_count","rate_limits":{"limit_id":"codex",'
            '"primary":{"used_percent":44.0,"window_minutes":"bad",'
            '"resets_at":{"bad":true}},"secondary":{"used_percent":12.0,'
            '"window_minutes":[],"resets_at":"also-bad"}}}}'
        )

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.primary_window_minutes, 0)
        self.assertEqual(rate_limit.primary_resets_at, 0)
        self.assertEqual(rate_limit.secondary_window_minutes, 0)
        self.assertEqual(rate_limit.secondary_resets_at, 0)

    def test_read_latest_codex_rate_limit_uses_newest_session_event(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            stale = sessions_dir / "stale.jsonl"
            fresh = sessions_dir / "fresh.jsonl"
            stale.write_text(
                '{"type":"event_msg","payload":{"type":"token_count",'
                '"rate_limits":{"limit_id":"codex","primary":{"used_percent":91.0,'
                '"window_minutes":300,"resets_at":1767000000},"secondary":null,'
                '"plan_type":"plus"}}}\n',
                encoding="utf-8",
            )
            fresh.write_text(
                '{"type":"event_msg","payload":{"type":"token_count",'
                '"rate_limits":{"limit_id":"codex","primary":{"used_percent":37.5,'
                '"window_minutes":300,"resets_at":1767318000},"secondary":'
                '{"used_percent":12.0,"window_minutes":10080,"resets_at":1767900000},'
                '"plan_type":"pro"}}}\n',
                encoding="utf-8",
            )
            os.utime(stale, (1_767_000_000, 1_767_000_000))
            os.utime(fresh, (1_767_100_000, 1_767_100_000))

            rate_limit = read_latest_codex_rate_limit(
                sessions_dir=sessions_dir, now_ts=1_767_100_100
            )

        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.primary_used_percent, 37.5)
        self.assertEqual(rate_limit.primary_window_minutes, 300)
        self.assertEqual(rate_limit.primary_resets_at, 1_767_318_000)
        self.assertEqual(rate_limit.secondary_used_percent, 12.0)
        self.assertEqual(rate_limit.secondary_window_minutes, 10080)
        self.assertEqual(rate_limit.secondary_resets_at, 1_767_900_000)
        self.assertEqual(rate_limit.plan_type, "pro")

    def test_read_codex_usage_summary_preserves_sqlite_thread_totals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "state_test.sqlite"
            sessions_dir = tmp_path / "sessions"
            sessions_dir.mkdir()
            with sqlite3.connect(db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE threads (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        model TEXT,
                        updated_at INTEGER NOT NULL,
                        tokens_used INTEGER NOT NULL,
                        model_provider TEXT NOT NULL,
                        cwd TEXT NOT NULL
                    )
                    """
                )
                conn.executemany(
                    """
                    INSERT INTO threads
                    (id, title, model, updated_at, tokens_used, model_provider, cwd)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "codex-old",
                            "Older Codex thread",
                            "gpt-5.4",
                            1_767_000_000,
                            1_000,
                            "openai",
                            "/tmp/old",
                        ),
                        (
                            "codex-new",
                            "Newest Codex thread",
                            "gpt-5.5",
                            1_767_300_000,
                            2_500,
                            "openai",
                            "/tmp/new",
                        ),
                        (
                            "other-provider",
                            "Local model thread",
                            "qwen",
                            1_767_400_000,
                            99_999,
                            "ollama",
                            "/tmp/ollama",
                        ),
                    ],
                )
            (sessions_dir / "fresh.jsonl").write_text(
                '{"type":"event_msg","payload":{"type":"token_count",'
                '"rate_limits":{"limit_id":"codex","primary":{"used_percent":44.0,'
                '"window_minutes":300,"resets_at":1900000000},"secondary":null,'
                '"plan_type":"pro"}}}\n',
                encoding="utf-8",
            )

            with patch.object(
                claude_widget,
                "_request_codex_app_server_rate_limits",
                return_value=None,
            ):
                summary = read_codex_usage_summary(
                    db_path=db_path,
                    sessions_dir=sessions_dir,
                )

        self.assertIsNotNone(summary)
        self.assertEqual(summary.thread_count, 2)
        self.assertEqual(summary.total_tokens, 3_500)
        self.assertEqual(summary.latest_thread_tokens, 2_500)
        self.assertEqual(summary.latest_thread_title, "Newest Codex thread")
        self.assertEqual(summary.latest_model, "gpt-5.5")
        self.assertEqual(summary.latest_cwd, "/tmp/new")
        self.assertEqual(summary.primary_limit_used_percent, 44.0)
        self.assertEqual(summary.rate_limit_source, "cached")

    def test_codex_usage_worker_emits_reader_result(self):
        expected = CodexUsageSummary(
            thread_count=1,
            primary_limit_used_percent=22.0,
        )
        received = []
        worker = CodexUsageWorker(reader=lambda: expected)
        worker.result.connect(received.append)

        worker.run()

        self.assertEqual(received, [expected])


if __name__ == "__main__":
    unittest.main()
