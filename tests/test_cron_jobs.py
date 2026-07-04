import os
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from claude_widget import (
    CronJobInfo,
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
0 10 1 3 * cd /home/sam/proj && python3 scripts/batch.py --batch 4 >> /tmp/b4.log 2>&1
0 10 2 3 * cd /home/sam/proj && python3 scripts/batch.py --batch 5 >> /tmp/b5.log 2>&1

*/15 * * * * /home/sam/scripts/watchdog.sh  # weather-capture watchdog
17 3 * * * do_thing --quiet

# supabase keep-alive
@reboot /home/sam/keepalive/backup.sh >> /home/sam/keepalive/cron.log 2>&1
0 */6 * * * /home/sam/keepalive/backup.sh >> /home/sam/keepalive/cron.log 2>&1
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
            "cd /home/sam/proj && python3 scripts/batch.py --batch 4 >> /tmp/b4.log 2>&1",
        )
        # Preceding comment applies to consecutive jobs
        self.assertEqual(jobs[1].label, "GSC batch submissions")

        # Trailing inline comment wins as label; command keeps the full text
        # (cron passes it verbatim to the shell and logs it verbatim)
        self.assertEqual(jobs[2].schedule, "*/15 * * * *")
        self.assertEqual(jobs[2].label, "weather-capture watchdog")
        self.assertEqual(
            jobs[2].command,
            "/home/sam/scripts/watchdog.sh  # weather-capture watchdog",
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
            "*/15 * * * * /home/sam/scripts/watchdog.sh  # watchdog\n"
            "17 3 * * * do_thing --quiet\n"
            "0 10 1 3 * yearly_thing\n"
        )
        watchdog_cmd = "/home/sam/scripts/watchdog.sh  # watchdog"
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
            jobs = fetch_cron_jobs()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].label, "run_thing")
        self.assertEqual(jobs[0].status, "ok")
        self.assertEqual(jobs[0].runs_24h, 1)

    def test_cron_jobs_worker_emits_fetcher_result(self):
        job = CronJobInfo(label="x", schedule="* * * * *", command="x")
        received = []
        worker = CronJobsFetchWorker(fetcher=lambda: [job])
        worker.finished.connect(received.append)

        worker.run()

        self.assertEqual(received, [[job]])


class CronWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    class _FakeEvent:
        def accept(self):
            pass

    def _jobs(self):
        return [
            CronJobInfo(
                label="watchdog", schedule="*/15 * * * *",
                command="/home/sam/scripts/watchdog.sh", status="ok",
            ),
            CronJobInfo(
                label="backup", schedule="0 */6 * * *",
                command="/home/sam/keepalive/backup.sh", status="late",
            ),
        ]

    def test_widget_hidden_when_no_jobs(self):
        w = CronJobsWidget()
        w.set_data([])
        self.assertEqual(w.height(), 0)
        self.assertTrue(w.isHidden())

    def test_widget_expands_and_collapses(self):
        w = CronJobsWidget()
        jobs = self._jobs()
        w.set_data(jobs)
        self.assertFalse(w.isHidden())
        collapsed = w.height()

        w.mousePressEvent(self._FakeEvent())
        self.assertGreater(w.height(), collapsed)
        self.assertEqual(w.height(), collapsed + 18 * len(jobs) + 2)

        w.mousePressEvent(self._FakeEvent())
        self.assertEqual(w.height(), collapsed)

    def test_widget_summary_counts_late_jobs(self):
        w = CronJobsWidget()
        w.set_data(self._jobs())
        self.assertEqual(w._summary_text(), "2 jobs · 1 late")

        ok_jobs = self._jobs()
        ok_jobs[1].status = "ok"
        w.set_data(ok_jobs)
        self.assertEqual(w._summary_text(), "2 jobs · all ok")

    def test_widget_tooltip_lists_full_commands(self):
        w = CronJobsWidget()
        w.set_data(self._jobs())
        self.assertIn("/home/sam/scripts/watchdog.sh", w.toolTip())
        self.assertIn("0 */6 * * *", w.toolTip())


if __name__ == "__main__":
    unittest.main()
