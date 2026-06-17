import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from claude_widget import (
    ClaudeWidget,
    CodexUsageWorker,
    CodexUsageRow,
    CodexUsageSummary,
    read_latest_codex_rate_limit,
    read_codex_usage_summary,
    UsageData,
    UsageEntry,
    UsageLimitsWidget,
)


class WidgetUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
        self.assertFalse(widget.model_bar.isHidden())

        widget.toggle_expanded()

        self.assertFalse(widget.is_expanded())
        self.assertLess(widget.height(), expanded_height)
        self.assertTrue(widget.five_hour_bar.isHidden())
        self.assertTrue(widget.estimate_label.isHidden())
        self.assertTrue(widget.seven_day_bar.isHidden())
        self.assertTrue(widget.model_bar.isHidden())

    def _make_inert_claude_widget(self):
        patches = [
            patch.object(ClaudeWidget, "_setup_timers", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_usage", lambda self, force=False: None),
            patch.object(ClaudeWidget, "_fetch_deploys", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_runners", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_task_loops", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_task_groups", lambda self: None),
            patch.object(ClaudeWidget, "_update_system_metrics", lambda self: None),
            patch.object(ClaudeWidget, "_refresh_codex_usage", lambda self: None),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        widget = ClaudeWidget()
        self.addCleanup(widget.deleteLater)
        return widget

    def test_claude_header_minimize_button_hides_to_tray(self):
        widget = self._make_inert_claude_widget()
        calls = []
        widget.hide_to_tray = lambda: calls.append("hide")

        widget._minimize_btn.mousePressEvent(None)

        self.assertEqual(calls, ["hide"])

    def test_claude_close_event_uses_hide_to_tray(self):
        widget = self._make_inert_claude_widget()
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
        widget = self._make_inert_claude_widget()

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

            rate_limit = read_latest_codex_rate_limit(sessions_dir=sessions_dir)

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
                '"window_minutes":300,"resets_at":1767318000},"secondary":null,'
                '"plan_type":"pro"}}}\n',
                encoding="utf-8",
            )

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
