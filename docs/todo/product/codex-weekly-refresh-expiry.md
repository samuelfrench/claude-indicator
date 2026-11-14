---
title: "Correct Codex expiry after a weekly refresh"
status: now
area: product
due: null
updated: 2026-11-14
owner: agent
brief: "Cache reset selection fixed and validated; push, green CI and native deployment verification remain."
test: null
refs:
  - claude_widget.py
  - tests/test_widget_ui.py
---

- **What:** Sam reports that Codex expiry is incorrect after using a weekly refresh. Inspect the existing app-server reader, cached fallback and row/tray display without changing account state or generating model requests.
- **Current evidence:** Baseline clean `master` matched fetched `origin/master` at `8400da1`. Read-only app-server status and the native Codex tray both report the changed weekly window ending `2026-11-20 08:56 CST` (`1795186560`); no current server/display disagreement was observed. Historical session quota events show the reset moved between November 12 and 13. OpenAI documents that a weekly reset can replace the previous schedule: https://help.openai.com/en/articles/20001498-how-resets-work-in-codex. Do not infer another date from purchase/redemption time or consume a reset for testing.
- **Reproduced defect and fix:** Cached fallback selected the first unexpired event by file mtime, so continued writing to an old session could revive its pre-refresh reset time. Select each session's newest quota event and compare event timestamps across sessions; validate the winning event afterward so an expired newest window cannot revive an older one. Add the exact local reset date/time/timezone to row and tray tooltips. Three new regression tests failed before the fix, including both same-file and cross-file expiry cases; focused Codex checks now pass (`19 passed, 2 subtests passed`).
- **Validation:** Isolated-HOME full suite `590 passed, 51 subtests passed`; focused Codex tests `19 passed, 2 subtests passed`; TODO tests 25/25; generated state check and `git diff --check` pass. Fresh-venv/isolated-HOME installation and inert offscreen render passed without provider requests or touching the service. Independent review found no actionable issues and separately reproduced the green focused tests. This proves a fallback defect, not that fallback caused Sam's observed discrepancy.
- **Next:** Push this validated patch, wait for green CI and deploy through the existing user service. Verify the running display and record exact evidence.
- **Done:** A weekly refresh cannot leave an invalid or superseded reset countdown visible; required tests/CI pass and deployment evidence is recorded.
