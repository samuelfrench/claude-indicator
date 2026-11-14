---
title: "Correct Codex expiry after a weekly refresh"
status: done
area: product
due: null
updated: 2026-11-14
owner: agent
brief: "208b756 deployed with green CI; newest cached quota wins and tooltips show the exact local reset date."
test: null
refs:
  - claude_widget.py
  - tests/test_widget_ui.py
---

- **What:** Sam reports that Codex expiry is incorrect after using a weekly refresh. Inspect the existing app-server reader, cached fallback and row/tray display without changing account state or generating model requests.
- **Current evidence:** Baseline clean `master` matched fetched `origin/master` at `8400da1`. Read-only app-server status and the native Codex tray both report the changed weekly window ending `2026-11-20 08:56 CST` (`1795186560`); no current server/display disagreement was observed. Historical session quota events show the reset moved between November 12 and 13. OpenAI documents that a weekly reset can replace the previous schedule: https://help.openai.com/en/articles/20001498-how-resets-work-in-codex. Do not infer another date from purchase/redemption time or consume a reset for testing.
- **Follow-up clarification (November 14):** Sam questioned why the widget still showed five days, then supplied the Usage page showing `Resets in 5d 15h` and `45% left`, agreeing with a fresh official app-server reading of 55% used and the November 20 reset. Sam accepted that the current countdown appears correct and recalled a surprising earlier reset; its cause is unverified. The cache fix did not change the five-day value and was not established as the cause of the original report. No additional application change is indicated by this evidence.
- **Reproduced defect and fix:** Cached fallback selected the first unexpired event by file mtime, so continued writing to an old session could revive its pre-refresh reset time. Select each session's newest quota event and compare event timestamps across sessions; validate the winning event afterward so an expired newest window cannot revive an older one. Add the exact local reset date/time/timezone to row and tray tooltips. Three new regression tests failed before the fix, including both same-file and cross-file expiry cases; focused Codex checks now pass (`19 passed, 2 subtests passed`).
- **Validation:** Isolated-HOME full suite `590 passed, 51 subtests passed`; focused Codex tests `19 passed, 2 subtests passed`; TODO tests 25/25; generated state check and `git diff --check` pass. Fresh-venv/isolated-HOME installation and inert offscreen render passed without provider requests or touching the service. Independent review found no actionable issues and separately reproduced the green focused tests. This proves a fallback defect, not that fallback caused Sam's observed discrepancy.
- **Release:** Runtime commit `208b756bc85d511a74e3f8edda1c87a82d2cac49` pushed to master. Repository guards `43649979878` and Python/install CI `43649979785` passed; hosted suite also reports `590 passed, 51 subtests passed`. Existing `claude-indicator.service` restarted at `2026-11-14 16:49:40 CST`, active/running PID `373581`, `NRestarts=0`, executing this checkout. Native D-Bus Codex tooltip reads `Next reset: Fri 20 Nov 2026 08:56 CST` alongside the countdown, matching the provider timestamp. No model request, account change, reset redemption, new billing or outward posting.
- **Shared memory:** Verified outcome is retained in `~/.codex/memories/extensions/ad_hoc/notes/20261114T225010Z-codex-codex-weekly-refresh-expiry-fixed-20261114-20c811d4.md`, linked to the exact Claude project memory directory. The reset date is a dated observation, not a permanent schedule.
- **Next:** None for this fix.
- **Done:** Cached fallback cannot bring back a superseded reset countdown; exact provider reset dates are visible, required tests/CI pass and deployment evidence is recorded.
