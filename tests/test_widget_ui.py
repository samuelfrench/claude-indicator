import json
import os
import sqlite3
import stat
import sys
import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

import claude_widget
from claude_widget import (
    ClaudeWidget,
    ClaudeUsageClient,
    CodexUsageWorker,
    CodexUsageRow,
    CodexUsageSummary,
    BalanceSnapshot,
    ComfyUIStatus,
    DeepSeekUsageRow,
    DeepSeekUsageSummary,
    LoadedModel,
    LocalAISection,
    LocalTokenUsage,
    OpencodeModelUsage,
    OpencodeUsage,
    OpencodeUsageRow,
    MinimaxUsageRow,
    MinimaxUsageSummary,
    MinimaxWindow,
    MoneyBalance,
    OllamaStatus,
    SystemMetrics,
    TaskLoopInfo,
    TerminalSession,
    TerminalSessionsSnapshot,
    ModelLimit,
    _parse_codex_app_server_rate_limit,
    _parse_codex_rate_limit_event,
    _parse_model_limits,
    _normalize_model_name,
    load_last_usage,
    ModelLimitsWidget,
    read_codex_rate_limit,
    read_latest_codex_rate_limit,
    read_codex_usage_summary,
    balance_decrease_spend,
    load_deepseek_history,
    parse_deepseek_balance,
    read_deepseek_api_key,
    read_minimax_api_key,
    read_opencode_deepseek_spend,
    read_opencode_local_tokens,
    read_opencode_model_breakdown,
    read_opencode_usage,
    read_opencode_minimax_usage,
    parse_minimax_quota,
    record_deepseek_snapshot,
    save_last_usage,
    UsageData,
    UsageEntry,
    UsageLimitsWidget,
)


class WidgetUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    MINIMAX_QUOTA_PAYLOAD = {
        "model_remains": [
            {
                "model_name": "general",
                "start_time": 1787133600000,
                "end_time": 1787151600000,
                "remains_time": 7042618,
                "current_interval_total_count": 40,
                "current_interval_usage_count": 3,
                "current_interval_remaining_percent": 93,
                "current_interval_status": 1,
                "weekly_start_time": 1786924800000,
                "weekly_end_time": 1787529600000,
                "current_weekly_total_count": 400,
                "current_weekly_usage_count": 144,
                "current_weekly_remaining_percent": 64,
                "current_weekly_status": 1,
            },
            {
                "model_name": "video",
                "start_time": 1787097600000,
                "end_time": 1787184000000,
                "current_interval_total_count": 3,
                "current_interval_usage_count": 0,
                "current_interval_remaining_percent": 100,
                "current_interval_status": 1,
                "weekly_start_time": 1786924800000,
                "weekly_end_time": 1787529600000,
                "current_weekly_total_count": 21,
                "current_weekly_usage_count": 0,
                "current_weekly_remaining_percent": 100,
                "current_weekly_status": 1,
            },
        ],
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }

    def test_parse_minimax_quota_inverts_remaining_percent_for_general_family(self):
        five_hour, weekly = parse_minimax_quota(self.MINIMAX_QUOTA_PAYLOAD)

        self.assertEqual(five_hour.used_percent, 7.0)
        self.assertEqual(five_hour.resets_at, 1787151600)
        self.assertEqual(five_hour.usage_count, 3)
        self.assertEqual(five_hour.total_count, 40)
        self.assertEqual(weekly.used_percent, 36.0)
        self.assertEqual(weekly.resets_at, 1787529600)
        self.assertEqual(weekly.usage_count, 144)
        self.assertEqual(weekly.total_count, 400)

    def test_parse_minimax_quota_rejects_unsuccessful_base_resp(self):
        payload = json.loads(json.dumps(self.MINIMAX_QUOTA_PAYLOAD))
        payload["base_resp"] = {"status_code": 1004, "status_msg": "auth failed"}
        with self.assertRaises(ValueError):
            parse_minimax_quota(payload)

    def test_parse_minimax_quota_rejects_payload_without_requested_family(self):
        payload = {
            "model_remains": [self.MINIMAX_QUOTA_PAYLOAD["model_remains"][1]],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }
        with self.assertRaises(ValueError):
            parse_minimax_quota(payload)

    def test_parse_minimax_quota_rejects_out_of_range_percent(self):
        payload = json.loads(json.dumps(self.MINIMAX_QUOTA_PAYLOAD))
        payload["model_remains"][0]["current_interval_remaining_percent"] = 150
        with self.assertRaises(ValueError):
            parse_minimax_quota(payload)

    def test_parse_minimax_quota_rejects_non_numeric_percent(self):
        payload = json.loads(json.dumps(self.MINIMAX_QUOTA_PAYLOAD))
        payload["model_remains"][0]["current_weekly_remaining_percent"] = "64"
        with self.assertRaises(ValueError):
            parse_minimax_quota(payload)

    def test_minimax_api_key_prefers_environment_and_reads_protected_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = Path(tmpdir) / "auth.json"
            auth_path.write_text('{"minimax-coding-plan":{"type":"api","key":"file-key"}}')
            auth_path.chmod(0o600)

            self.assertEqual(
                read_minimax_api_key(
                    auth_path=auth_path, environ={"MINIMAX_API_KEY": "env-key"}
                ),
                "env-key",
            )
            self.assertEqual(
                read_minimax_api_key(auth_path=auth_path, environ={}),
                "file-key",
            )

            auth_path.chmod(0o644)
            with self.assertRaises(ValueError):
                read_minimax_api_key(auth_path=auth_path, environ={})

    def test_opencode_minimax_usage_sums_tokens_for_provider_rows_only(self):
        now = 1_800_000_000.0
        def tokens(inp, out, reasoning=0, read=0, write=0):
            return {
                "input": inp,
                "output": out,
                "reasoning": reasoning,
                "cache": {"read": read, "write": write},
            }
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                rows = [
                    ("old", int((now - 25 * 3600) * 1000),
                     {"role": "assistant", "providerID": "minimax-coding-plan",
                      "modelID": "MiniMax-M2.5", "tokens": tokens(900, 900)}),
                    ("a", int((now - 3600) * 1000),
                     {"role": "assistant", "providerID": "minimax-coding-plan",
                      "modelID": "MiniMax-M2.5-highspeed", "tokens": tokens(573, 128, 0, 56960, 0)}),
                    ("b", int((now - 60) * 1000),
                     {"role": "assistant", "providerID": "minimax-coding-plan",
                      "modelID": "MiniMax-M3", "tokens": tokens(73, 119, 12, 0, 100)}),
                    ("user", int((now - 30) * 1000),
                     {"role": "user", "providerID": "minimax-coding-plan",
                      "tokens": tokens(500, 500)}),
                    ("other", int((now - 20) * 1000),
                     {"role": "assistant", "providerID": "deepseek", "tokens": tokens(400, 400)}),
                ]
                conn.executemany(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    [(row_id, created, json.dumps(data)) for row_id, created, data in rows],
                )
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    ("malformed", int((now - 5) * 1000), "{not-json"),
                )

            total, count, coverage, model = read_opencode_minimax_usage(
                db_path=db_path, now=now
            )

        self.assertEqual(total, 573 + 128 + 56960 + 73 + 119 + 12 + 100)
        self.assertEqual(count, 2)
        self.assertEqual(coverage, 24 * 3600)
        self.assertEqual(model, "MiniMax-M3")

    def test_opencode_minimax_usage_rejects_non_numeric_token_counts(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    ("bad", int(now * 1000), json.dumps({
                        "role": "assistant",
                        "providerID": "minimax-coding-plan",
                        "modelID": "MiniMax-M3",
                        "tokens": {"input": "573", "output": 1},
                    })),
                )
            with self.assertRaises(ValueError):
                read_opencode_minimax_usage(db_path=db_path, now=now)

    def test_minimax_row_renders_window_utilization_and_token_total(self):
        row = MinimaxUsageRow()
        row.set_data(
            MinimaxUsageSummary(
                five_hour=MinimaxWindow(used_percent=7.0, resets_at=1787151600,
                                        usage_count=3, total_count=40),
                weekly=MinimaxWindow(used_percent=36.0, resets_at=1787529600,
                                     usage_count=144, total_count=400),
                quota_source="live",
                tokens_24h=995_128_372,
                message_count=3734,
                model_name="MiniMax-M3",
                usage_source="opencode",
            )
        )

        self.assertEqual(row.summary_text(), "5H 7%  ·  7D 36%")
        self.assertEqual(row.tokens_text(), "995.1M")
        self.assertIn("MiniMax-M3", row.toolTip())

    def test_minimax_row_shows_placeholder_when_quota_unavailable(self):
        row = MinimaxUsageRow()
        row.set_data(MinimaxUsageSummary(quota_error="Plan quota unavailable"))

        self.assertEqual(row.summary_text(), "5H —  ·  7D —")
        self.assertIn("Plan quota unavailable", row.toolTip())

    def test_widget_places_minimax_row_directly_after_deepseek_row(self):
        widget = self._make_inert_claude_widget()
        layout = widget._deepseek_row.parentWidget().layout()
        deepseek_index = layout.indexOf(widget._deepseek_row)
        self.assertEqual(layout.indexOf(widget._minimax_row), deepseek_index + 1)

    def test_opencode_local_tokens_splits_today_from_all_time(self):
        # 2026-08-19 12:00:00 local; "today" starts at the local midnight before it.
        now = time.mktime((2026, 8, 19, 12, 0, 0, 0, 0, -1))
        midnight = time.mktime((2026, 8, 19, 0, 0, 0, 0, 0, -1))

        def tokens(inp, out, read=0):
            return {"input": inp, "output": out, "reasoning": 0,
                    "cache": {"read": read, "write": 0}}

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                rows = [
                    ("older", int((midnight - 3 * 86400) * 1000),
                     {"role": "assistant", "providerID": "ollama",
                      "modelID": "qwen3.5", "tokens": tokens(1000, 500)}),
                    ("yesterday", int((midnight - 60) * 1000),
                     {"role": "assistant", "providerID": "ollama",
                      "modelID": "qwen3.5", "tokens": tokens(200, 100)}),
                    ("today_a", int((midnight + 3600) * 1000),
                     {"role": "assistant", "providerID": "ollama",
                      "modelID": "qwen3.6", "tokens": tokens(50, 25, 1000)}),
                    ("today_b", int((now - 60) * 1000),
                     {"role": "assistant", "providerID": "ollama",
                      "modelID": "qwen3.6-latest", "tokens": tokens(5, 5)}),
                    ("remote", int((now - 30) * 1000),
                     {"role": "assistant", "providerID": "minimax-coding-plan",
                      "modelID": "MiniMax-M3", "tokens": tokens(900, 900)}),
                    ("user_turn", int((now - 20) * 1000),
                     {"role": "user", "providerID": "ollama", "tokens": tokens(7, 7)}),
                ]
                conn.executemany(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    [(rid, created, json.dumps(data)) for rid, created, data in rows],
                )

            usage = read_opencode_local_tokens(db_path=db_path, now=now)

        self.assertEqual(usage.today_tokens, 50 + 25 + 1000 + 5 + 5)
        self.assertEqual(usage.today_messages, 2)
        self.assertEqual(usage.all_time_tokens, 1500 + 300 + 1085)
        self.assertEqual(usage.all_time_messages, 4)
        self.assertEqual(usage.latest_model, "qwen3.6-latest")
        self.assertEqual(usage.first_seen, int(midnight - 3 * 86400))

    def test_opencode_local_tokens_rejects_non_numeric_token_counts(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    ("bad", int(now * 1000), json.dumps({
                        "role": "assistant", "providerID": "ollama",
                        "modelID": "qwen3.6", "tokens": {"input": "5", "output": 1},
                    })),
                )
            with self.assertRaises(ValueError):
                read_opencode_local_tokens(db_path=db_path, now=now)

    def test_opencode_local_tokens_handles_an_empty_ledger(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")

            usage = read_opencode_local_tokens(db_path=db_path, now=now)

        self.assertEqual(usage.today_tokens, 0)
        self.assertEqual(usage.all_time_tokens, 0)
        self.assertEqual(usage.first_seen, 0)
        self.assertEqual(usage.latest_model, "")

    def _sample_opencode_usage(self):
        return OpencodeUsage(
            window_tokens=996_500_000 + 4_224_131 + 1_100_000,
            models=[
                OpencodeModelUsage(
                    provider="minimax-coding-plan", model="MiniMax-M3",
                    tokens=996_500_000, messages=3748, cost=Decimal("0"),
                    last_used=1787151600,
                ),
                OpencodeModelUsage(
                    provider="ollama", model="qwen3.6:27b-mtp-ctx32k",
                    tokens=4_224_131, messages=230, cost=Decimal("0"),
                    last_used=1787151500,
                ),
                OpencodeModelUsage(
                    provider="deepseek", model="deepseek-chat",
                    tokens=1_100_000, messages=38, cost=Decimal("0.26"),
                    last_used=1787100000,
                ),
            ],
            local=LocalTokenUsage(
                today_tokens=4_224_131, today_messages=230,
                all_time_tokens=51_220_203, all_time_messages=2902,
                first_seen=1786885971, latest_model="qwen3.6:27b-mtp-ctx32k",
            ),
        )

    def test_opencode_row_summarises_window_tokens_and_model_count(self):
        row = OpencodeUsageRow()
        row.set_data(self._sample_opencode_usage())

        self.assertEqual(row.label_text(), "OPENCODE")
        self.assertEqual(row.summary_text(), "24H 1.0B  ·  3 MODELS")

    def test_opencode_row_lists_each_provider_distinctly_by_model(self):
        row = OpencodeUsageRow()
        row.set_data(self._sample_opencode_usage())

        lines = row.model_lines()
        self.assertEqual(
            [line[0] for line in lines],
            ["MiniMax-M3", "qwen3.6:27b-mtp-ctx32k", "deepseek-chat"],
        )
        # Each line names the provider so same-family models stay distinguishable.
        self.assertEqual([line[2] for line in lines], ["minimax", "ollama", "deepseek"])
        self.assertEqual(lines[0][1], "996.5M")
        self.assertEqual(lines[2][3], "$0.26")

    def test_opencode_row_caps_the_model_list_and_keeps_the_heaviest(self):
        usage = self._sample_opencode_usage()
        usage.models = [
            OpencodeModelUsage(provider="ollama", model=f"model-{index}",
                               tokens=1000 - index, messages=1, cost=Decimal("0"),
                               last_used=1787151600)
            for index in range(9)
        ]
        row = OpencodeUsageRow()
        row.set_data(usage)

        lines = row.model_lines()
        self.assertLessEqual(len(lines), 5)
        self.assertEqual(lines[0][0], "model-0")

    def test_opencode_row_keeps_local_day_and_all_time_visible(self):
        row = OpencodeUsageRow()
        row.set_data(self._sample_opencode_usage())

        self.assertEqual(row.local_text(), "DAY 4.2M  ·  ALL 51.2M  ·  since 16 Aug")
        self.assertIn("51.2M", row.toolTip())
        self.assertIn("aider", row.toolTip())

    def test_opencode_row_shows_placeholders_before_first_read(self):
        row = OpencodeUsageRow()
        self.assertEqual(row.summary_text(), "24H —  ·  — MODELS")
        self.assertEqual(row.model_lines(), [])

    def test_opencode_model_breakdown_groups_by_provider_and_model(self):
        now = 1_800_000_000.0

        def tokens(inp, out):
            return {"input": inp, "output": out, "reasoning": 0,
                    "cache": {"read": 0, "write": 0}}

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                rows = [
                    ("stale", int((now - 25 * 3600) * 1000),
                     {"role": "assistant", "providerID": "ollama", "modelID": "qwen3.6",
                      "tokens": tokens(9000, 9000), "cost": 0}),
                    ("mm1", int((now - 7200) * 1000),
                     {"role": "assistant", "providerID": "minimax-coding-plan",
                      "modelID": "MiniMax-M3", "tokens": tokens(100, 50), "cost": 0}),
                    ("mm2", int((now - 60) * 1000),
                     {"role": "assistant", "providerID": "minimax-coding-plan",
                      "modelID": "MiniMax-M3", "tokens": tokens(10, 5), "cost": 0}),
                    ("ds", int((now - 3600) * 1000),
                     {"role": "assistant", "providerID": "deepseek",
                      "modelID": "deepseek-chat", "tokens": tokens(20, 10), "cost": 0.125}),
                    ("ol", int((now - 120) * 1000),
                     {"role": "assistant", "providerID": "ollama",
                      "modelID": "qwen3.6", "tokens": tokens(7, 3), "cost": 0}),
                    ("user", int((now - 30) * 1000),
                     {"role": "user", "providerID": "ollama", "modelID": "qwen3.6",
                      "tokens": tokens(500, 500), "cost": 0}),
                ]
                conn.executemany(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    [(rid, created, json.dumps(data)) for rid, created, data in rows],
                )

            models = read_opencode_model_breakdown(db_path=db_path, now=now)

        self.assertEqual([(m.provider, m.model, m.tokens, m.messages) for m in models], [
            ("minimax-coding-plan", "MiniMax-M3", 165, 2),
            ("deepseek", "deepseek-chat", 30, 1),
            ("ollama", "qwen3.6", 10, 1),
        ])
        self.assertEqual(models[1].cost, Decimal("0.125"))
        self.assertEqual(models[0].last_used, int(now - 60))

    def test_read_opencode_usage_combines_breakdown_with_local_totals(self):
        now = time.mktime((2026, 8, 19, 12, 0, 0, 0, 0, -1))
        midnight = time.mktime((2026, 8, 19, 0, 0, 0, 0, 0, -1))
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                conn.executemany(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    [
                        ("a", int((midnight + 60) * 1000), json.dumps(
                            {"role": "assistant", "providerID": "ollama", "modelID": "qwen3.6",
                             "tokens": {"input": 10, "output": 5}, "cost": 0})),
                        ("b", int((now - 60) * 1000), json.dumps(
                            {"role": "assistant", "providerID": "minimax-coding-plan",
                             "modelID": "MiniMax-M3", "tokens": {"input": 100, "output": 1},
                             "cost": 0})),
                    ],
                )

            usage = read_opencode_usage(db_path=db_path, now=now)

        self.assertEqual(usage.window_tokens, 116)
        self.assertEqual([m.model for m in usage.models], ["MiniMax-M3", "qwen3.6"])
        self.assertEqual(usage.local.today_tokens, 15)
        self.assertEqual(usage.error, "")

    def test_widget_places_opencode_row_directly_after_minimax_row(self):
        widget = self._make_inert_claude_widget()
        layout = widget._minimax_row.parentWidget().layout()
        self.assertEqual(
            layout.indexOf(widget._opencode_row),
            layout.indexOf(widget._minimax_row) + 1,
        )

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

        widget.toggle_expanded()

        self.assertFalse(widget.is_expanded())
        self.assertLess(widget.height(), expanded_height)
        self.assertTrue(widget.five_hour_bar.isHidden())
        self.assertTrue(widget.estimate_label.isHidden())
        self.assertTrue(widget.seven_day_bar.isHidden())

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
            {
                "kind": "weekly_scoped",
                "group": "weekly",
                "percent": 11,
                "severity": "normal",
                "resets_at": "2026-07-08T07:59:59+00:00",
                "scope": {
                    "model": {"id": "minimax", "display_name": None},
                    "surface": None,
                },
                "is_active": False,
            },
        ],
    }

    def test_parse_model_limits_extracts_model_scoped_entries_only(self):
        limits = _parse_model_limits(self._SCOPED_LIMITS_PAYLOAD)

        self.assertEqual(len(limits), 2)
        self.assertEqual(limits[0].name, "Fable")
        self.assertEqual(limits[0].window, "7-Day")
        self.assertEqual(limits[0].entry.utilization, 3.0)
        self.assertEqual(limits[0].entry.resets_at, "2026-07-07T07:59:59+00:00")
        self.assertEqual(limits[1].name, "Minimax")
        self.assertEqual(limits[1].window, "7-Day")
        self.assertEqual(limits[1].entry.utilization, 11.0)
        self.assertEqual(limits[1].entry.resets_at, "2026-07-08T07:59:59+00:00")

    def test_normalize_model_name_titlecases_plain_model_ids(self):
        self.assertEqual(_normalize_model_name("minimax"), "Minimax")
        self.assertEqual(_normalize_model_name("claude-opus"), "claude-opus")
        self.assertEqual(_normalize_model_name("Fable"), "Fable")

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
        self.assertEqual([ml.name for ml in data.model_limits], ["Fable", "Minimax"])
        self.assertEqual(data.model_name, "fable")
        self.assertEqual(data.model_pct, 3.0)

    def test_display_model_limits_merges_scoped_and_legacy_without_duplicates(self):
        data = UsageData(
            model_limits=[
                ModelLimit(
                    name="Fable", window="7-Day", entry=UsageEntry(utilization=3.0)
                ),
                ModelLimit(
                    name="Minimax", window="7-Day", entry=UsageEntry(utilization=11.0)
                )
            ],
            seven_day_opus=UsageEntry(utilization=55.0),
        )

        self.assertEqual(
            [(ml.name, ml.entry.utilization) for ml in data.display_model_limits],
            [("Fable", 3.0), ("Minimax", 11.0), ("Opus", 55.0)],
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

    def test_model_limits_widget_builds_one_bar_per_model_limit(self):
        widget = ModelLimitsWidget()
        widget.set_data(
            [
                ModelLimit(
                    name="Fable",
                    window="7-Day",
                    entry=UsageEntry(utilization=3.0),
                )
            ]
        )

        self.assertEqual([bar._label for bar in widget.model_bars], ["Fable (7-Day)"])
        self.assertEqual(widget.model_bars[0]._pct, 3.0)
        self.assertFalse(widget.model_bars[0].isHidden())
        self.assertEqual(widget.height(), 66)

        widget.toggle_expanded()
        self.assertTrue(widget.model_bars[0].isHidden())

    def test_model_limits_widget_rebuilds_bars_when_limits_change(self):
        widget = ModelLimitsWidget()
        fable = ModelLimit(
            name="Fable", window="7-Day", entry=UsageEntry(utilization=3.0)
        )
        opus = ModelLimit(
            name="Opus", window="7-Day", entry=UsageEntry(utilization=41.0)
        )

        widget.set_data([fable])
        self.assertEqual([bar._label for bar in widget.model_bars], ["Fable (7-Day)"])

        widget.set_data([opus, fable])
        self.assertEqual(
            [bar._label for bar in widget.model_bars],
            ["Opus (7-Day)", "Fable (7-Day)"],
        )
        self.assertEqual(widget.height(), 112)

        widget.set_data([])
        self.assertEqual(widget.model_bars, [])
        self.assertEqual(widget.height(), 20)

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
            patch.object(ClaudeWidget, "_refresh_deepseek_usage", lambda self: None),
            patch.object(ClaudeWidget, "_refresh_minimax_usage", lambda self: None),
            patch.object(ClaudeWidget, "_refresh_opencode_usage", lambda self: None),
            patch.object(
                ClaudeWidget, "_refresh_terminal_sessions", lambda self: None
            ),
            patch.object(ClaudeWidget, "_fetch_ollama", lambda self: None),
            patch.object(ClaudeWidget, "_fetch_comfyui", lambda self: None),
            patch.object(claude_widget, "SmartTodoDialog", dialog_factory),
        ]
        for active_patch in patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        widget = ClaudeWidget()
        self.addCleanup(widget.deleteLater)
        return widget

    @staticmethod
    def _terminal_session(key="1:1", parked=False, needs_attention=False):
        return TerminalSession(
            key=key, tool="CLAUDE", project="demo", cwd="/home/sam/demo",
            tty="pts/1", pid=int(key.split(":")[0]), busy=not needs_attention,
            parked=parked, idle_seconds=300.0 if needs_attention else 0.0,
            needs_attention=needs_attention,
        )

    def test_widget_reads_terminal_sessions_and_prunes_dead_state(self):
        widget = self._make_inert_claude_widget()
        widget._parked_sessions = {"1:1", "9:9"}
        widget._session_notes = {"1:1": "keep", "9:9": "gone"}
        snapshot = TerminalSessionsSnapshot(
            sessions=[self._terminal_session(key="1:1", parked=True)],
            updated_at=1.0,
        )

        with patch.object(claude_widget, "save_terminal_state",
                          return_value=({"1:1"}, {"1:1": "keep"})) as save:
            widget._on_terminal_sessions_read(snapshot)

        save.assert_called_once_with({"1:1"}, {"1:1": "keep"},
                                     live_keys={"1:1"})
        self.assertEqual(widget._parked_sessions, {"1:1"})
        self.assertEqual(widget._session_notes, {"1:1": "keep"})
        self.assertEqual(widget._terminal_sessions_row.summary_text(),
                         "1 OPEN · OK")
        self.assertEqual(widget._tabs_panel.card_summaries()[0][1], "demo")

    def test_widget_keeps_terminal_state_when_scan_errors(self):
        widget = self._make_inert_claude_widget()
        widget._parked_sessions = {"1:1"}

        with patch.object(claude_widget, "save_terminal_state") as save:
            widget._on_terminal_sessions_read(
                TerminalSessionsSnapshot(error="boom", updated_at=1.0)
            )

        save.assert_not_called()
        self.assertEqual(widget._parked_sessions, {"1:1"})
        self.assertEqual(widget._terminal_sessions_row.summary_text(), "—")

    def test_widget_park_toggle_persists_and_updates_both_views(self):
        widget = self._make_inert_claude_widget()
        widget._parked_sessions = set()
        widget._session_notes = {}
        snapshot = TerminalSessionsSnapshot(
            sessions=[self._terminal_session(key="5:5", needs_attention=True)],
            updated_at=1.0,
        )
        with patch.object(claude_widget, "save_terminal_state",
                          side_effect=lambda parked, notes, **kw: (set(parked), dict(notes))):
            widget._on_terminal_sessions_read(snapshot)
            self.assertEqual(widget._terminal_sessions_row.summary_text(),
                             "1 OPEN · 1 NEED YOU")

            widget._on_session_park_toggled("5:5", True)

        self.assertEqual(widget._parked_sessions, {"5:5"})
        self.assertEqual(widget._terminal_sessions_row.summary_text(),
                         "1 OPEN · OK")
        self.assertEqual(widget._tabs_panel.card_summaries()[0][2], "PARKED")

    def test_widget_note_change_persists(self):
        widget = self._make_inert_claude_widget()
        widget._parked_sessions = set()
        widget._session_notes = {}

        with patch.object(claude_widget, "save_terminal_state",
                          side_effect=lambda parked, notes, **kw: (set(parked), dict(notes))) as save:
            widget._on_session_note_changed("5:5", "deploying")
            widget._on_session_note_changed("5:5", "")

        self.assertEqual(save.call_args_list[0].args[1], {"5:5": "deploying"})
        self.assertEqual(save.call_args_list[1].args[1], {})
        self.assertEqual(widget._session_notes, {})

    def test_tabs_panel_slides_out_from_the_widget_left_edge(self):
        widget = self._make_inert_claude_widget()
        widget.show()
        widget.move(500, 40)

        widget._toggle_tabs_panel()
        anim = widget._tabs_panel_anim
        # The slide starts tucked under the widget's left edge...
        self.assertTrue(widget._tabs_panel.isVisible())
        self.assertTrue(widget._terminal_sessions_row._panel_open)
        self.assertEqual(anim.startValue().x(), 500)
        # ...and lands attached to it.
        anim.setCurrentTime(anim.duration())
        self.assertEqual(widget._tabs_panel.x(),
                         500 - widget._tabs_panel.width())
        self.assertEqual(widget._tabs_panel.y(), 40)

        widget._toggle_tabs_panel()
        self.assertFalse(widget._terminal_sessions_row._panel_open)
        # Jumping to the end of the slide emits finished, which hides the panel.
        anim.setCurrentTime(anim.duration())
        self.assertFalse(widget._tabs_panel.isVisible())

    def test_dragging_tabs_panel_moves_main_anchor_and_keeps_both_docked(self):
        widget = self._make_inert_claude_widget()
        widget.show()
        widget.move(500, 40)
        widget._toggle_tabs_panel()
        widget._tabs_panel_anim.setCurrentTime(widget._tabs_panel_anim.duration())
        original = widget.pos()

        widget._tabs_panel.drag_requested.emit(QPoint(27, 19))

        self.assertEqual(widget.pos(), original + QPoint(27, 19))
        self.assertEqual(widget._tabs_panel.pos(), widget._panel_positions()[0])
        self.assertTrue(widget._tabs_panel.isVisible())

    def test_tabs_panel_open_and_tucked_positions_clamp_above_bottom_edge(self):
        widget = self._make_inert_claude_widget()
        widget._tabs_panel.setFixedHeight(300)
        available = QApplication.primaryScreen().availableGeometry()
        widget.move(500, available.bottom() - 10)

        open_pos, tucked_pos = widget._panel_positions()

        expected_y = available.bottom() - widget._tabs_panel.height() + 1
        self.assertEqual(open_pos.y(), expected_y)
        self.assertEqual(tucked_pos.y(), expected_y)
        self.assertGreaterEqual(open_pos.y(), available.top())

    def test_hidden_anchor_drag_keeps_selector_visible_and_restores_docked(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        widget._tabs_panel.setFixedHeight(300)
        available = QApplication.primaryScreen().availableGeometry()
        widget.show()
        widget.move(500, available.bottom() - widget.height() + 1)
        widget.collapse_to_sliver()
        anchor_before = widget.pos()

        widget._tabs_panel.drag_requested.emit(QPoint(0, 500))

        self.assertFalse(widget.isVisible())
        self.assertTrue(widget._tabs_panel.isVisible())
        self.assertEqual(widget.pos(), anchor_before + QPoint(0, 500))
        self.assertGreaterEqual(widget._tabs_panel.y(), available.top())
        self.assertLessEqual(
            widget._tabs_panel.frameGeometry().bottom(), available.bottom()
        )

        widget._restore_sliver.restore_requested.emit()
        QApplication.processEvents()

        self.assertTrue(widget.isVisible())
        self.assertTrue(widget._tabs_panel.isVisible())
        self.assertEqual(widget._tabs_panel.pos(), widget._panel_positions()[0])
        self.assertLessEqual(
            widget._tabs_panel.frameGeometry().bottom(), available.bottom()
        )

    def test_navigate_request_spawns_a_focus_worker_for_that_session(self):
        widget = self._make_inert_claude_widget()
        session = self._terminal_session(key="5:5")
        snapshot = TerminalSessionsSnapshot(sessions=[session], updated_at=1.0)
        with patch.object(claude_widget, "save_terminal_state",
                          side_effect=lambda parked, notes, **kw: (set(parked), dict(notes))):
            widget._on_terminal_sessions_read(snapshot)

        with patch.object(claude_widget, "TerminalFocusWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = False
            widget._on_session_navigate("5:5")
            widget._on_session_navigate("no-such-key")

        worker_cls.assert_called_once_with(session)
        worker_cls.return_value.start.assert_called_once()

    def test_navigation_is_ignored_while_a_focus_worker_runs(self):
        widget = self._make_inert_claude_widget()
        session = self._terminal_session(key="5:5")
        snapshot = TerminalSessionsSnapshot(sessions=[session], updated_at=1.0)
        with patch.object(claude_widget, "save_terminal_state",
                          side_effect=lambda parked, notes, **kw: (set(parked), dict(notes))):
            widget._on_terminal_sessions_read(snapshot)

        with patch.object(claude_widget, "TerminalFocusWorker") as worker_cls:
            worker_cls.return_value.isRunning.return_value = True
            widget._on_session_navigate("5:5")
            widget._on_session_navigate("5:5")

        worker_cls.assert_called_once_with(session)

    def test_hide_to_tray_hides_the_tabs_panel(self):
        widget = self._make_inert_claude_widget(tray_available=True)
        widget.show()
        widget._toggle_tabs_panel()
        self.assertTrue(widget._tabs_panel.isVisible())

        widget.hide_to_tray()

        self.assertFalse(widget._tabs_panel.isVisible())

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
        widget._model_limits.set_data([])
        widget._model_limits.setVisible(True)
        widget.adjustSize()
        QApplication.processEvents()
        before = widget.height()

        widget._model_limits.set_data(
            [
                ModelLimit(
                    name="Fable",
                    window="7-Day",
                    entry=UsageEntry(utilization=3.0),
                )
            ]
        )
        widget.adjustSize()
        QApplication.processEvents()

        self.assertGreater(widget.height(), before)

    def test_claude_header_minimize_button_collapses_to_visible_sliver(self):
        widget = self._make_inert_claude_widget(tray_available=True)
        calls = []
        widget.collapse_to_sliver = lambda: calls.append("collapse")

        widget._minimize_btn.mousePressEvent(None)

        self.assertEqual(calls, ["collapse"])

    def test_claude_header_minimize_uses_sliver_without_tray(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        calls = []
        widget.collapse_to_sliver = lambda: calls.append("collapse")

        widget._minimize_btn.mousePressEvent(None)

        self.assertEqual(calls, ["collapse"])

    def test_collapsed_sliver_stays_on_right_edge_and_restores_widget(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        widget.show()
        QApplication.processEvents()
        available = QApplication.primaryScreen().availableGeometry()
        widget.move(available.right() - widget.width() + 1, available.top() + 40)

        widget.collapse_to_sliver()
        QApplication.processEvents()

        self.assertFalse(widget.isVisible())
        self.assertTrue(widget._restore_sliver.isVisible())
        self.assertTrue(widget._tabs_panel.isVisible())
        self.assertTrue(widget._terminal_sessions_row._panel_open)
        self.assertEqual(widget._tabs_panel.pos(), widget._panel_positions()[0])
        self.assertEqual(widget._restore_sliver.frameGeometry().right(), available.right())
        self.assertEqual(widget._restore_sliver.frameGeometry().top(), available.top() + 40)
        self.assertEqual(widget._restore_sliver.toolTip(), "Expand Claude Indicator")

        widget._restore_sliver.restore_requested.emit()
        QApplication.processEvents()

        self.assertFalse(widget._restore_sliver.isVisible())
        self.assertTrue(widget.isVisible())
        self.assertTrue(widget._tabs_panel.isVisible())
        self.assertEqual(widget._tabs_panel.pos(), widget._panel_positions()[0])

    def test_tray_toggle_hides_selector_and_sliver_when_main_is_collapsed(self):
        widget = self._make_inert_claude_widget(tray_available=True)
        widget.show()
        widget.collapse_to_sliver()
        self.assertTrue(widget._tabs_panel.isVisible())
        self.assertTrue(widget._restore_sliver.isVisible())

        widget._toggle_from_tray()

        self.assertFalse(widget.isVisible())
        self.assertFalse(widget._tabs_panel.isVisible())
        self.assertFalse(widget._restore_sliver.isVisible())

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

    def test_deepseek_api_key_prefers_environment_and_reads_protected_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = Path(tmpdir) / "auth.json"
            auth_path.write_text('{"deepseek":{"type":"api","key":"file-key"}}')
            auth_path.chmod(0o600)

            self.assertEqual(
                read_deepseek_api_key(
                    auth_path=auth_path, environ={"DEEPSEEK_API_KEY": "env-key"}
                ),
                "env-key",
            )
            self.assertEqual(
                read_deepseek_api_key(auth_path=auth_path, environ={}),
                "file-key",
            )

            auth_path.chmod(0o644)
            with self.assertRaises(ValueError):
                read_deepseek_api_key(auth_path=auth_path, environ={})

    def test_deepseek_api_key_rejects_symlink_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "target.json"
            target.write_text('{"deepseek":{"key":"secret"}}')
            target.chmod(0o600)
            link = Path(tmpdir) / "auth.json"
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                read_deepseek_api_key(auth_path=link, environ={})

    def test_parse_deepseek_balance_uses_official_string_money_schema(self):
        available, balances = parse_deepseek_balance(
            {
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "USD",
                        "total_balance": "47.63",
                        "granted_balance": "2.00",
                        "topped_up_balance": "45.63",
                    }
                ],
            }
        )

        self.assertTrue(available)
        self.assertEqual(balances[0].total, Decimal("47.63"))
        with self.assertRaises(ValueError):
            parse_deepseek_balance(
                {
                    "is_available": True,
                    "balance_infos": [
                        {
                            "currency": "USD",
                            "total_balance": "NaN",
                            "granted_balance": "0",
                            "topped_up_balance": "0",
                        }
                    ],
                }
            )

    def test_opencode_deepseek_spend_reads_only_matching_valid_cost_rows(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                rows = [
                    ("old", int((now - 25 * 3600) * 1000), {"role": "assistant", "providerID": "deepseek", "cost": 9}),
                    ("a", int((now - 60) * 1000), {"role": "assistant", "providerID": "deepseek", "cost": 1.25}),
                    ("b", int((now - 30) * 1000), {"role": "assistant", "providerID": "deepseek", "cost": 0.375}),
                    ("user", int((now - 20) * 1000), {"role": "user", "providerID": "deepseek", "cost": 7}),
                    ("other", int((now - 10) * 1000), {"role": "assistant", "providerID": "openai", "cost": 8}),
                ]
                conn.executemany(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    [(row_id, created, json.dumps(data)) for row_id, created, data in rows],
                )
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    ("malformed", int((now - 5) * 1000), "{not-json"),
                )

            spent, count, coverage = read_opencode_deepseek_spend(
                db_path=db_path, now=now
            )

        self.assertEqual(spent, Decimal("1.625"))
        self.assertEqual(count, 2)
        self.assertEqual(coverage, 24 * 3600)

    def test_opencode_deepseek_spend_rejects_missing_or_nonnumeric_cost(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
                conn.execute(
                    "INSERT INTO message VALUES (?, ?, ?)",
                    ("bad", int(now * 1000), json.dumps({"role": "assistant", "providerID": "deepseek", "cost": "1.00"})),
                )
            with self.assertRaises(ValueError):
                read_opencode_deepseek_spend(db_path=db_path, now=now)

    def test_deepseek_balance_history_is_private_atomic_and_topup_safe(self):
        now = 1_800_000_000.0
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            balances = [MoneyBalance("USD", Decimal("50"), Decimal("0"), Decimal("50"))]
            record_deepseek_snapshot(balances, now=now - 25 * 3600, path=path)
            record_deepseek_snapshot(
                [MoneyBalance("USD", Decimal("45"), Decimal("0"), Decimal("45"))],
                now=now - 20 * 3600,
                path=path,
            )
            record_deepseek_snapshot(
                [MoneyBalance("USD", Decimal("65"), Decimal("0"), Decimal("65"))],
                now=now - 10 * 3600,
                path=path,
            )
            points = record_deepseek_snapshot(
                [MoneyBalance("USD", Decimal("62"), Decimal("0"), Decimal("62"))],
                now=now,
                path=path,
            )
            spent, coverage = balance_decrease_spend(points, now=now, currency="USD")

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(load_deepseek_history(path), points)
        self.assertEqual(spent, Decimal("8"))
        self.assertEqual(coverage, 24 * 3600)

    def test_deepseek_row_discloses_local_only_spend_and_live_credit(self):
        row = DeepSeekUsageRow()
        summary = DeepSeekUsageSummary(
            balances=[MoneyBalance("USD", Decimal("47.63"), Decimal("0"), Decimal("47.63"))],
            balance_source="live",
            spent_24h=Decimal("2.61694"),
            spend_source="opencode",
            spend_coverage_s=24 * 3600,
            spend_message_count=1170,
        )
        row.set_data(summary)

        self.assertEqual(row._spend_text(summary), "$2.62")
        self.assertEqual(row._credit_text(summary), "$47.63")
        self.assertIn("OpenCode-recorded traffic only", row.toolTip())
        collapsed = row.height()

        class Event:
            def accept(self):
                pass

        row.mousePressEvent(Event())
        self.assertGreater(row.height(), collapsed)

    def test_deepseek_snapshot_credit_has_bounded_age_and_discloses_age(self):
        now = time.time()
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "history.json"
            db_path = Path(tmpdir) / "opencode.db"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE message (id TEXT, time_created INTEGER, data TEXT)")
            record_deepseek_snapshot(
                [MoneyBalance("USD", Decimal("12.34"), Decimal("0"), Decimal("12.34"))],
                now=now - 120,
                path=history_path,
            )
            with patch.object(claude_widget, "fetch_deepseek_balance", side_effect=OSError):
                recent = claude_widget.read_deepseek_usage(
                    now=now,
                    history_path=history_path,
                    db_path=db_path,
                    environ={"DEEPSEEK_API_KEY": "dummy"},
                )

            record_deepseek_snapshot(
                [MoneyBalance("USD", Decimal("11.11"), Decimal("0"), Decimal("11.11"))],
                now=now,
                path=history_path,
            )
            stale_now = now + claude_widget.DEEPSEEK_SNAPSHOT_MAX_AGE_S + 1
            with patch.object(claude_widget, "fetch_deepseek_balance", side_effect=OSError):
                stale = claude_widget.read_deepseek_usage(
                    now=stale_now,
                    history_path=history_path,
                    db_path=db_path,
                    environ={"DEEPSEEK_API_KEY": "dummy"},
                )

        self.assertEqual(recent.balance_source, "snapshot")
        self.assertEqual(recent.balances[0].total, Decimal("12.34"))
        row = DeepSeekUsageRow()
        with patch.object(claude_widget.time, "time", return_value=now):
            row.set_data(recent)
        self.assertIn("2m old", row.toolTip())
        self.assertEqual(stale.balance_source, "")
        self.assertEqual(stale.balances, [])

    def test_local_ai_section_is_compact_expandable_and_filters_local_ollama_loops(self):
        section = LocalAISection()
        section.set_ollama(
            OllamaStatus(running=True, version="0.11.0"),
            [LoadedModel(name="qwen:latest", size_vram=4 * 1024**3)],
            4,
        )
        section.set_gpu(
            SystemMetrics(
                gpu_available=True,
                gpu_pct=25,
                gpu_mem_used_gb=4,
                gpu_mem_total_gb=24,
                gpu_temp=52,
            )
        )
        section.set_comfyui(ComfyUIStatus(running=True))
        section.set_task_loops(
            [
                TaskLoopInfo("local", "ollama/qwen", "high", 10),
                TaskLoopInfo("cloud", "claude-opus", "high", 10),
            ]
        )
        collapsed = section.height()

        class Event:
            def accept(self):
                pass

        section.mousePressEvent(Event())

        self.assertEqual([loop.name for loop in section._task_loops], ["local"])
        self.assertGreater(section.height(), collapsed)
        self.assertLess(section.height(), 300)
        self.assertIn("no DynamoDB query", section.toolTip())

    def test_unified_widget_contains_deepseek_and_local_ai_rows(self):
        widget = self._make_inert_claude_widget(tray_available=False)

        self.assertIsInstance(widget._deepseek_row, DeepSeekUsageRow)
        self.assertIsInstance(widget._local_ai_section, LocalAISection)
        self.assertEqual(widget.width(), 340)

    def test_tall_sections_are_mutually_exclusive_and_fit_800px_screen(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        widget.show()
        widget._local_ai_section.set_ollama(
            OllamaStatus(running=True),
            [LoadedModel(name=f"model-{index}") for index in range(3)],
            3,
        )
        widget._local_ai_section.set_task_loops(
            [TaskLoopInfo(f"task-{index}", "ollama/qwen", "high", 10) for index in range(3)]
        )

        widget._local_ai_section.set_expanded(True)
        widget._deepseek_row.mousePressEvent(Mock())
        widget.adjustSize()
        QApplication.processEvents()

        self.assertTrue(widget._local_ai_section.is_expanded())
        self.assertFalse(widget._history_expanded)
        # 800px work area less a 10px margin; each provider row costs 30px collapsed.
        self.assertLessEqual(widget.height(), 790)

        widget._toggle_history()
        widget.adjustSize()
        QApplication.processEvents()

        self.assertTrue(widget._history_expanded)
        self.assertFalse(widget._local_ai_section.is_expanded())
        self.assertLessEqual(widget.height(), 790)

    def test_fable_and_max_expansions_reposition_inside_800px_work_area(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        widget.show()
        screen = QApplication.primaryScreen()
        self.assertIsNotNone(screen)
        available = screen.availableGeometry()
        self.assertEqual((available.width(), available.height()), (800, 800))
        widget.move(available.right() - widget.width() + 1, available.top() + 40)
        self.assertEqual(widget.frameGeometry().top(), available.top() + 40)

        widget._usage = UsageData(
            five_hour=UsageEntry(utilization=10),
            seven_day=UsageEntry(utilization=20),
            model_limits=[
                ModelLimit(
                    name="Fable",
                    window="7-Day",
                    entry=UsageEntry(utilization=30),
                )
            ],
            fetched_at=time.time(),
        )
        widget._update_display()
        widget._local_ai_section.set_ollama(
            OllamaStatus(running=True),
            [LoadedModel(name=f"model-{index}") for index in range(3)],
            3,
        )
        widget._local_ai_section.set_task_loops(
            [TaskLoopInfo(f"task-{index}", "ollama/qwen", "high", 10) for index in range(3)]
        )
        widget._local_ai_section.set_expanded(True)
        widget._deepseek_row.mousePressEvent(Mock())
        widget.adjustSize()
        QApplication.processEvents()

        frame = widget.frameGeometry()
        self.assertLessEqual(widget.height(), available.height())
        self.assertGreaterEqual(frame.left(), available.left())
        self.assertGreaterEqual(frame.top(), available.top())
        self.assertLessEqual(frame.right(), available.right())
        self.assertLessEqual(frame.bottom(), available.bottom())

        widget.move(frame.left(), available.bottom() - frame.height() + 21)
        self.assertGreater(widget.frameGeometry().bottom(), available.bottom())
        widget.clamp_to_available_screen()
        self.assertLessEqual(widget.frameGeometry().bottom(), available.bottom())

    def test_shutdown_stops_owned_timers_and_quiesces_new_workers_once(self):
        widget = self._make_inert_claude_widget(tray_available=False)
        timer = QTimer(widget)
        timer.start(1000)

        class Worker:
            def __init__(self):
                self.requestInterruption = Mock()
                self.wait = Mock(return_value=True)

        workers = [Worker(), Worker(), Worker()]
        widget._deepseek_worker, widget._ollama_worker, widget._comfyui_worker = workers

        widget.shutdown()
        widget.shutdown()

        self.assertFalse(timer.isActive())
        self.assertFalse(widget._tray_retry_timer.isActive())
        for worker in workers:
            worker.requestInterruption.assert_called_once_with()
            worker.wait.assert_called_once()
            timeout_ms = worker.wait.call_args.args[0]
            self.assertGreaterEqual(timeout_ms, 0)
            self.assertLessEqual(timeout_ms, 16_000)


class WindowDragTest(unittest.TestCase):
    """Dragging the frameless overlay must work on Wayland as well as X11."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class _FakeMouseEvent:
        def __init__(self, x, y, button=Qt.MouseButton.LeftButton,
                     buttons=Qt.MouseButton.LeftButton):
            self._pos = QPointF(x, y)
            self._button = button
            self._buttons = buttons
            self.accepted = False

        def button(self):
            return self._button

        def buttons(self):
            return self._buttons

        def globalPosition(self):
            return self._pos

        def accept(self):
            self.accepted = True

    def _widget(self, platform_name, system_move_result):
        widget = WidgetUiTest._make_inert_claude_widget(
            self, smart_todo_dialog_factory=Mock()
        )
        started = []

        class _Handle:
            def startSystemMove(self):
                started.append(True)
                return system_move_result

        widget.windowHandle = lambda: _Handle()
        patcher = patch.object(
            claude_widget, "_qt_platform_name", return_value=platform_name
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        moves = []
        widget.move = lambda *args: moves.append(args)
        return widget, started, moves

    def test_wayland_press_hands_the_drag_to_the_compositor(self):
        # Wayland clients cannot position their own top-level windows, so the
        # manual move path can never work there.
        widget, started, moves = self._widget("wayland", True)

        widget.mousePressEvent(self._FakeMouseEvent(500, 300))
        widget.mouseMoveEvent(self._FakeMouseEvent(540, 320))

        self.assertEqual(len(started), 1)
        self.assertEqual(moves, [])

    def test_wayland_falls_back_to_manual_move_when_compositor_refuses(self):
        widget, started, moves = self._widget("wayland", False)
        widget.setGeometry(100, 100, widget.width(), widget.height())

        widget.mousePressEvent(self._FakeMouseEvent(500, 300))
        widget.mouseMoveEvent(self._FakeMouseEvent(540, 320))

        self.assertEqual(len(started), 1)
        self.assertEqual(len(moves), 1)

    def test_x11_keeps_the_proven_manual_drag(self):
        widget, started, moves = self._widget("xcb", True)
        widget.setGeometry(100, 100, widget.width(), widget.height())

        widget.mousePressEvent(self._FakeMouseEvent(500, 300))
        widget.mouseMoveEvent(self._FakeMouseEvent(540, 320))

        self.assertEqual(started, [])
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0][0].x(), 140)
        self.assertEqual(moves[0][0].y(), 120)

    def test_right_button_press_never_starts_a_drag(self):
        widget, started, moves = self._widget("wayland", True)

        widget.mousePressEvent(
            self._FakeMouseEvent(
                500, 300, button=Qt.MouseButton.RightButton,
                buttons=Qt.MouseButton.RightButton,
            )
        )

        self.assertEqual(started, [])
        self.assertEqual(moves, [])


class PreferredQtPlatformTest(unittest.TestCase):
    """The overlay needs X11 semantics: self-positioning, stay-on-top, xdotool."""

    def test_wayland_session_with_x_display_prefers_xwayland(self):
        platform = claude_widget._preferred_qt_platform(
            {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0",
             "DISPLAY": ":0"}
        )
        self.assertEqual(platform, "xcb;wayland")

    def test_explicit_platform_choice_is_respected(self):
        platform = claude_widget._preferred_qt_platform(
            {"QT_QPA_PLATFORM": "wayland", "WAYLAND_DISPLAY": "wayland-0",
             "DISPLAY": ":0"}
        )
        self.assertIsNone(platform)

    def test_wayland_session_without_x_display_stays_on_wayland(self):
        platform = claude_widget._preferred_qt_platform(
            {"XDG_SESSION_TYPE": "wayland", "WAYLAND_DISPLAY": "wayland-0"}
        )
        self.assertIsNone(platform)

    def test_x11_session_is_left_alone(self):
        platform = claude_widget._preferred_qt_platform(
            {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}
        )
        self.assertIsNone(platform)


if __name__ == "__main__":
    unittest.main()
