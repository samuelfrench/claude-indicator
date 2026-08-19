import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ollama_watchdog import (
    STUCK_AFTER_S,
    restart_command,
    evaluate,
    expiry_lag_s,
    probe_body,
    update_state,
)


class ExpiryLagTest(unittest.TestCase):
    def test_no_loaded_models_has_no_lag(self):
        self.assertIsNone(expiry_lag_s({"models": []}, now=1_800_000_000.0))

    def test_lag_is_seconds_since_the_latest_expiry_passed(self):
        payload = {"models": [{"expires_at": "2026-08-19T08:19:49.256357059-05:00"}]}
        # 2026-08-19T13:19:49Z == 1787145589 epoch seconds
        self.assertAlmostEqual(
            expiry_lag_s(payload, now=1787145589.0 + 600), 600, delta=1
        )

    def test_future_expiry_reports_negative_lag(self):
        payload = {"models": [{"expires_at": "2026-08-19T08:19:49.256357059-05:00"}]}
        self.assertLess(expiry_lag_s(payload, now=1787145589.0 - 120), 0)

    def test_unparseable_expiry_is_ignored_rather_than_assumed_stuck(self):
        payload = {"models": [{"expires_at": "not-a-timestamp"}]}
        self.assertIsNone(expiry_lag_s(payload, now=1_800_000_000.0))


class EvaluateTest(unittest.TestCase):
    NOW = 1787145589.0

    def _payload(self, offset_s):
        # expires_at rendered relative to NOW by the caller's chosen offset
        import datetime
        moment = datetime.datetime.fromtimestamp(
            self.NOW + offset_s, datetime.timezone.utc
        )
        return {"models": [{"expires_at": moment.isoformat()}]}

    def test_idle_server_with_no_models_is_healthy_without_probing(self):
        probes = []
        healthy, reason = evaluate(
            {"models": []}, now=self.NOW, probe=lambda: probes.append(1) or True
        )
        self.assertTrue(healthy)
        self.assertEqual(probes, [])
        self.assertEqual(reason, "idle")

    def test_model_held_past_expiry_is_unhealthy_without_probing(self):
        probes = []
        healthy, reason = evaluate(
            self._payload(-3600), now=self.NOW, probe=lambda: probes.append(1) or True
        )
        self.assertFalse(healthy)
        self.assertEqual(probes, [])
        self.assertIn("expired", reason)

    def test_recently_expired_model_is_within_grace(self):
        healthy, _ = evaluate(self._payload(-5), now=self.NOW, probe=lambda: True)
        self.assertTrue(healthy)

    def test_live_model_is_healthy_when_the_scheduler_answers_the_probe(self):
        healthy, reason = evaluate(self._payload(120), now=self.NOW, probe=lambda: True)
        self.assertTrue(healthy)
        self.assertEqual(reason, "probe ok")

    def test_live_model_is_unhealthy_when_the_probe_hangs(self):
        healthy, reason = evaluate(self._payload(120), now=self.NOW, probe=lambda: False)
        self.assertFalse(healthy)
        self.assertIn("probe", reason)


class RestartCommandTest(unittest.TestCase):
    def test_restart_never_waits_on_an_interactive_polkit_prompt(self):
        # A user-level timer has no tty; a password prompt would hang the unit.
        command = restart_command({})
        self.assertIn("--no-ask-password", command)
        self.assertEqual(command[-2:], ["restart", "ollama"])

    def test_restart_command_is_overridable_for_verification(self):
        self.assertEqual(
            restart_command({"OLLAMA_WATCHDOG_RESTART_CMD": "systemctl --user restart dummy"}),
            ["systemctl", "--user", "restart", "dummy"],
        )


class ProbeBodyTest(unittest.TestCase):
    def test_probe_preserves_the_models_remaining_keep_alive(self):
        body = json.loads(probe_body("qwen3.6:27b", remaining_s=240.0))
        self.assertEqual(body["model"], "qwen3.6:27b")
        self.assertEqual(body["prompt"], "")
        self.assertEqual(body["keep_alive"], "240s")

    def test_probe_never_sends_a_negative_keep_alive(self):
        # Ollama reads a negative keep_alive as "hold this model forever".
        body = json.loads(probe_body("qwen3.6:27b", remaining_s=-30.0))
        self.assertEqual(body["keep_alive"], "1s")


class UpdateStateTest(unittest.TestCase):
    def test_healthy_check_clears_a_pending_unhealthy_streak(self):
        state, restart = update_state({"unhealthy_since": 100.0}, healthy=True, now=200.0)
        self.assertEqual(state, {})
        self.assertFalse(restart)

    def test_first_unhealthy_check_starts_the_streak_without_restarting(self):
        state, restart = update_state({}, healthy=False, now=200.0)
        self.assertEqual(state, {"unhealthy_since": 200.0})
        self.assertFalse(restart)

    def test_restart_waits_for_the_full_stuck_window(self):
        state, restart = update_state(
            {"unhealthy_since": 200.0}, healthy=False, now=200.0 + STUCK_AFTER_S - 1
        )
        self.assertEqual(state, {"unhealthy_since": 200.0})
        self.assertFalse(restart)

    def test_restart_fires_once_the_stuck_window_elapses(self):
        state, restart = update_state(
            {"unhealthy_since": 200.0}, healthy=False, now=200.0 + STUCK_AFTER_S
        )
        self.assertTrue(restart)
        self.assertEqual(state, {})


if __name__ == "__main__":
    unittest.main()
