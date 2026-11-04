import os
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from claude_widget import (
    CronJobInfo,
    CronSnapshot,
    parse_cron_snapshot,
    fetch_user_cron_jobs,
    CronJobsFetchWorker,
    CronJobsWidget,
    attach_cron_run_history,
    cron_next_fire,
    cron_prev_fire,
    fetch_cron_jobs,
    parse_crontab_text,
    _parse_cron_journal_line,
)


SAMPLE_CRONTAB = """\
# GSC batch submissions
0 10 1 3 * cd /home/user/proj && python3 scripts/batch.py --batch 4 >> /tmp/b4.log 2>&1
0 10 2 3 * cd /home/user/proj && python3 scripts/batch.py --batch 5 >> /tmp/b5.log 2>&1

*/15 * * * * /home/user/scripts/watchdog.sh  # weather-capture watchdog
17 3 * * * do_thing --quiet

# supabase keep-alive
@reboot /home/user/keepalive/backup.sh >> /home/user/keepalive/cron.log 2>&1
0 */6 * * * /home/user/keepalive/backup.sh >> /home/user/keepalive/cron.log 2>&1
SHELL=/bin/bash
"""


class CronParsingTest(unittest.TestCase):
    def test_parse_crontab_text_extracts_jobs_and_labels(self):
        jobs = parse_crontab_text(SAMPLE_CRONTAB)

        self.assertEqual(len(jobs), 6)

        self.assertEqual(jobs[0].schedule, "0 10 1 3 *")
        self.assertEqual(jobs[0].label, "GSC batch submissions")
        self.assertEqual(
            jobs[0].command,
            "cd /home/user/proj && python3 scripts/batch.py --batch 4 >> /tmp/b4.log 2>&1",
        )
        # Preceding comment applies to consecutive jobs
        self.assertEqual(jobs[1].label, "GSC batch submissions")

        # Trailing inline comment wins as label; command keeps the full text
        # (cron passes it verbatim to the shell and logs it verbatim)
        self.assertEqual(jobs[2].schedule, "*/15 * * * *")
        self.assertEqual(jobs[2].label, "weather-capture watchdog")
        self.assertEqual(
            jobs[2].command,
            "/home/user/scripts/watchdog.sh  # weather-capture watchdog",
        )

        # Blank line clears the pending comment; label falls back to command
        self.assertEqual(jobs[3].label, "do_thing --quiet")

        self.assertEqual(jobs[4].schedule, "@reboot")
        self.assertEqual(jobs[4].label, "supabase keep-alive")
        self.assertEqual(jobs[5].schedule, "0 */6 * * *")
        self.assertEqual(jobs[5].label, "supabase keep-alive")

    def test_parse_cron_journal_line_extracts_cmd_entries_for_user(self):
        line = (
            "1751648401.905447 sam-MS-7D75 CRON[353465]: (sam) CMD "
            "(cd /x && run  # label)"
        )
        parsed = _parse_cron_journal_line(line, "sam")
        self.assertIsNotNone(parsed)
        ts, command = parsed
        self.assertAlmostEqual(ts, 1751648401.905447)
        self.assertEqual(command, "cd /x && run  # label")

        self.assertIsNone(
            _parse_cron_journal_line(
                "1751648401.0 host CRON[1]: pam_unix(cron:session): "
                "session closed for user sam",
                "sam",
            )
        )
        self.assertIsNone(
            _parse_cron_journal_line(
                "1751648401.0 host CRON[1]: (root) CMD (run)", "sam"
            )
        )


class CronScheduleTest(unittest.TestCase):
    BASE = datetime(2026, 7, 4, 12, 7)  # Saturday

    def test_cron_next_fire(self):
        self.assertEqual(
            cron_next_fire("*/15 * * * *", self.BASE), datetime(2026, 7, 4, 12, 15)
        )
        self.assertEqual(
            cron_next_fire("17 3 * * *", self.BASE), datetime(2026, 7, 5, 3, 17)
        )
        self.assertEqual(
            cron_next_fire("0 */6 * * *", self.BASE), datetime(2026, 7, 4, 18, 0)
        )
        self.assertEqual(
            cron_next_fire("0 10 1 3 *", self.BASE), datetime(2027, 3, 1, 10, 0)
        )
        # Monday after Saturday 2026-07-04
        self.assertEqual(
            cron_next_fire("30 9 * * 1", self.BASE), datetime(2026, 7, 6, 9, 30)
        )
        self.assertIsNone(cron_next_fire("@reboot", self.BASE))

    def test_cron_prev_fire(self):
        self.assertEqual(
            cron_prev_fire("*/15 * * * *", self.BASE), datetime(2026, 7, 4, 12, 0)
        )
        self.assertEqual(
            cron_prev_fire("17 3 * * *", self.BASE), datetime(2026, 7, 4, 3, 17)
        )
        self.assertEqual(
            cron_prev_fire("0 10 1 3 *", self.BASE), datetime(2026, 3, 1, 10, 0)
        )
        self.assertIsNone(cron_prev_fire("@reboot", self.BASE))


class CronHealthTest(unittest.TestCase):
    NOW = datetime(2026, 7, 4, 12, 7).timestamp()
    JOURNAL_START = NOW - 48 * 3600
    BOOT = NOW - 6 * 3600

    def test_attach_cron_run_history_sets_last_run_and_status(self):
        jobs = parse_crontab_text(
            "*/15 * * * * /home/user/scripts/watchdog.sh  # watchdog\n"
            "17 3 * * * do_thing --quiet\n"
            "0 10 1 3 * yearly_thing\n"
        )
        watchdog_cmd = "/home/user/scripts/watchdog.sh  # watchdog"
        entries = [
            (self.NOW - 420, watchdog_cmd),   # 12:00 run
            (self.NOW - 1320, watchdog_cmd),  # 11:45 run
        ]

        attach_cron_run_history(
            jobs, entries, self.NOW, self.JOURNAL_START, self.BOOT
        )

        watchdog, daily, yearly = jobs
        self.assertEqual(watchdog.runs_24h, 2)
        self.assertAlmostEqual(watchdog.last_run_ts, self.NOW - 420)
        self.assertEqual(watchdog.status, "ok")
        self.assertIsNotNone(watchdog.next_run_ts)

        # Was due at 03:17 today, inside the journal window, but never logged
        self.assertIsNone(daily.last_run_ts)
        self.assertEqual(daily.status, "late")

        # Last due in March, before the journal window — can't tell
        self.assertEqual(yearly.status, "unknown")

    def test_attach_cron_run_history_reboot_jobs(self):
        ran = parse_crontab_text("@reboot backup.sh\n")
        attach_cron_run_history(
            ran, [(self.BOOT + 30, "backup.sh")],
            self.NOW, self.JOURNAL_START, self.BOOT,
        )
        self.assertEqual(ran[0].status, "ok")

        missed = parse_crontab_text("@reboot backup.sh\n")
        attach_cron_run_history(
            missed, [], self.NOW, self.JOURNAL_START, self.BOOT
        )
        self.assertEqual(missed[0].status, "late")

        # Boot predates the journal window: absence of a log proves nothing
        old_boot = parse_crontab_text("@reboot backup.sh\n")
        attach_cron_run_history(
            old_boot, [], self.NOW, self.JOURNAL_START,
            self.JOURNAL_START - 3600,
        )
        self.assertEqual(old_boot[0].status, "unknown")


class CronFetchTest(unittest.TestCase):
    def test_fetch_cron_jobs_assembles_jobs_from_crontab_and_journal(self):
        from unittest.mock import patch

        now = datetime(2026, 7, 4, 12, 7).timestamp()
        with patch(
            "claude_widget._read_user_crontab",
            return_value="*/15 * * * * run_thing\n",
        ), patch(
            "claude_widget._read_cron_journal_entries",
            return_value=[(now - 420, "run_thing")],
        ), patch(
            "claude_widget._system_boot_ts", return_value=now - 3600
        ), patch("claude_widget.time.time", return_value=now):
            jobs = fetch_user_cron_jobs()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].label, "run_thing")
        self.assertEqual(jobs[0].status, "ok")
        self.assertEqual(jobs[0].runs_24h, 1)

    def test_cron_jobs_worker_emits_fetcher_result(self):
        job = CronJobInfo(label="x", schedule="* * * * *", command="x")
        received = []
        snapshot = CronSnapshot(jobs=[job])
        worker = CronJobsFetchWorker(fetcher=lambda: snapshot)
        worker.finished.connect(received.append)

        worker.run()

        self.assertEqual(received, [snapshot])


def manager_payload():
    return {
        "generatedAt": datetime.now().astimezone().isoformat(),
        "sources": [{"name": "Cron", "status": "ok", "message": "Read-only inventory"}],
        "jobs": [{"id": "a", "name": "Backup", "source": "systemd-user", "project": "tools",
                  "schedule": "daily", "command": "backup.sh", "description": "Backs up files",
                  "enabled": False, "status": "unknown", "lastRunAt": "2026-11-01T10:00:00Z", "nextRunAt": None}],
    }


class CronManagerFetchTest(unittest.TestCase):
    def test_snapshot_keeps_all_sources_statuses_and_disabled_jobs(self):
        payload = manager_payload()
        statuses = ["success", "failed", "running", "unknown", "never", "skipped", "cancelled"]
        payload["jobs"] = [{**payload["jobs"][0], "id": str(i), "status": status, "source": source}
                           for i, (status, source) in enumerate(zip(statuses, ["cron", "systemd-user", "systemd-system", "hermes", "codex", "github", "cron"]))]
        snapshot = parse_cron_snapshot(payload)
        self.assertEqual([j.status for j in snapshot.jobs], statuses)
        self.assertTrue(all(j.enabled is False for j in snapshot.jobs))
        job = snapshot.jobs[0]
        self.assertEqual((job.id, job.label, job.description, job.schedule, job.command, job.project),
                         ("0", "Backup", "Backs up files", "daily", "backup.sh", "tools"))
        self.assertEqual(job.last_run_ts, 1793527200.0)
        self.assertIsNone(job.next_run_ts)

    def test_fetch_uses_only_loopback_snapshot_without_forced_refresh(self):
        from unittest.mock import Mock, patch
        response = Mock(status_code=200)
        response.json.return_value = manager_payload()
        with patch("claude_widget.requests.Session") as session_type, patch("claude_widget._read_user_crontab", side_effect=AssertionError("must not fall back")):
            session = session_type.return_value.__enter__.return_value
            session.get.return_value = response
            snapshot = fetch_cron_jobs()
        session.get.assert_called_once_with("http://127.0.0.1:4741/api/snapshot", timeout=(3, 90), allow_redirects=False)
        self.assertIs(session.trust_env, False)
        self.assertFalse(snapshot.error)
        self.assertEqual(snapshot.jobs[0].label, "Backup")

    def test_failures_and_invalid_payload_are_explicit(self):
        import requests
        from unittest.mock import Mock, patch
        for payload in ({}, {**manager_payload(), "jobs": [None]}, {**manager_payload(), "sources": [None]}):
            with self.assertRaises(ValueError):
                parse_cron_snapshot(payload)
        with patch("claude_widget.requests.Session.get", side_effect=requests.ConnectionError("private details")):
            snapshot = fetch_cron_jobs()
        self.assertIn("unavailable", snapshot.error)
        self.assertNotIn("private details", snapshot.error)
        with patch("claude_widget.requests.Session.get", return_value=Mock(status_code=302)):
            self.assertIn("unavailable", fetch_cron_jobs().error)


class CronWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_success_and_first_failure_stay_visible(self):
        w = CronJobsWidget()
        w.set_data(CronSnapshot())
        self.assertEqual(w.height(), w._HEADER_H)
        self.assertFalse(w.isHidden())
        self.assertEqual(w._summary_text(), "0 jobs")
        w.set_data(CronSnapshot(error="Cron Manager unavailable"))
        self.assertIn("unavailable", w._summary_text())
        self.assertFalse(w.isHidden())

    def test_real_timer_worker_path_updates_inventory_and_recovers_from_outage(self):
        from PySide6.QtCore import QTimer, QEventLoop
        from PySide6.QtWidgets import QWidget
        from unittest.mock import patch
        import claude_widget
        payload = manager_payload()
        first = parse_cron_snapshot(payload)
        second = parse_cron_snapshot({**payload, "jobs": [{**payload["jobs"][0], "id": "new", "name": "Added", "status": "failed"}]})
        snapshots = iter([first, CronSnapshot(error="Cron Manager unavailable"), second, CronSnapshot()])
        observed = []
        loop = QEventLoop()
        class Harness(QWidget):
            _fetch_cron_jobs = claude_widget.ClaudeWidget._fetch_cron_jobs
            def __init__(self):
                super().__init__()
                self._cron_row = CronJobsWidget(self)
                self._cron_worker = None
                self._shutdown_started = False
            def __getattr__(self, name):
                # Other timers in the real setup remain inert.
                return lambda: None
            def _section_visible(self, section):
                return True
            def _on_cron_jobs_fetched(self, snapshot):
                claude_widget.ClaudeWidget._on_cron_jobs_fetched(self, snapshot)
                observed.append(([j.id for j in self._cron_row._jobs], self._cron_row._summary_text()))
                if len(observed) == 4:
                    self._cron_timer.stop()
                    loop.quit()
        w = Harness()
        with patch("claude_widget.fetch_cron_jobs", side_effect=lambda: next(snapshots)), patch("claude_widget.log_line"):
            claude_widget.ClaudeWidget._setup_timers(w)
            self.assertEqual(w._cron_timer.interval(), 60000)
            w._cron_timer.setInterval(5)
            QTimer.singleShot(1000, loop.quit)
            loop.exec()
            for timer in w.findChildren(QTimer):
                timer.stop()
            if w._cron_worker:
                w._cron_worker.wait()
        self.assertEqual([ids for ids, _ in observed], [["a"], ["a"], ["new"], []])
        self.assertIn("stale", observed[1][1])
        self.assertIn("failed", observed[2][1])
        self.assertNotIn("unavailable", observed[2][1])
        w.deleteLater()

    def test_hidden_section_does_not_poll_or_reappear_after_inflight_result(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from claude_widget import ClaudeWidget
        w = SimpleNamespace(_cron_row=CronJobsWidget(), _shutdown_started=False,
                            _section_visible=lambda name: False, adjustSize=Mock())
        with patch("claude_widget.CronJobsFetchWorker") as worker, patch("claude_widget.log_line"):
            ClaudeWidget._fetch_cron_jobs(w)
            worker.assert_not_called()
            ClaudeWidget._on_cron_jobs_fetched(w, CronSnapshot(error="unavailable"))
        self.assertTrue(w._cron_row.isHidden())

    def test_partial_unknown_stale_and_details_are_honest(self):
        payload = manager_payload()
        payload["sources"].append({"name": "Remote", "status": "unavailable", "message": "No local registry"})
        snapshot = parse_cron_snapshot(payload)
        w = CronJobsWidget()
        w.set_data(snapshot)
        self.assertIn("1 unknown", w._summary_text())
        self.assertIn("partial coverage", w._summary_text())
        self.assertNotIn("all ok", w._summary_text())
        self.assertIn("Last updated:", w.toolTip())
        self.assertIn("Remote: unavailable", w.toolTip())
        detail = w._job_detail(w._jobs[0])
        for text in ("disabled", "daily", "Backs up files", "backup.sh", "unknown", "systemd-user"):
            self.assertIn(text, detail)
        snapshot.generated_at = 1
        self.assertIn("stale", w._summary_text())

    def test_large_inventory_is_bounded_and_all_pages_are_accessible(self):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        w = CronJobsWidget()
        w.resize(340, 22)
        jobs = [CronJobInfo(id=str(i), label=f"Job {i}", schedule="daily", command="x", status="unknown") for i in range(183)]
        w.set_data(CronSnapshot(jobs=jobs))
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        self.assertTrue(w._expanded)
        self.assertLessEqual(w.height(), 224)
        visited = []
        for page in range(w._last_page() + 1):
            visited.extend(j.id for j in w._page_jobs())
            QTest.keyClick(w, Qt.Key.Key_PageDown)
        self.assertEqual(visited, [j.id for j in jobs])
        self.assertEqual(w._page, 18)
        # Clicking the visible labels follows their direction at compact width.
        from PySide6.QtGui import QFont, QFontMetrics
        fm = QFontMetrics(QFont("sans-serif", 8))
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(8 + fm.horizontalAdvance("‹ Previous") // 2, w.height() - 8))
        self.assertEqual(w._page, 17)
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(w.width() - 8 - fm.horizontalAdvance("Next ›") // 2, w.height() - 8))
        self.assertEqual(w._page, 18)
        w.grab()  # exercise actual paint at compact widget width
        QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=QPoint(5, 5))
        self.assertEqual(w.height(), w._HEADER_H)


if __name__ == "__main__":
    unittest.main()
