---
title: "Email responder status row"
status: done
area: product
due: null
updated: 2026-10-30
owner: agent
brief: "One aggregate-only row shows the reply bot working, idle, paused, error, stalled or stale from a local status file."
refs: []
test: "tests/test_widget_ui.py -k email_responder"
---
- **What:** Add `EmailResponderRow` directly after the task-group row. It reads `~/.local/state/email-responder/status.json` (schema 1, mode 0600) every 15 seconds in a QThread and paints one line: green `idle · last run 12m ago · 4 handled, 2 for you`, blue `working: draft`, amber `paused`, red `error: <text>`, amber `stalled 7m` when a running stage has no heartbeat for 5 minutes, and amber idle text when the last run is older than 2 hours (dead timer). No file means hidden, not zero.
- **Why:** Sam asked on 2026-10-30 for a small indicator showing the email responder is working, so a silent or crashed bot is visible without opening its logs.
- **Next:** Complete. The frozen schema-1 contract stays aggregate-only: counts and timestamps, never addresses, subjects or bodies. Error text is flattened to one line and truncated to 60 characters. Keep the reader offline and dependency-free.
- **Authority:** Sam's explicit request and the authorized existing-service restart after green CI. Local file read only; no network, no credentials, no new dependency, no account or billing change.

**Implementation/validation:** `EmailResponderRow` paints at 340px as `EMAIL ● <summary>` with a 3px status dot. Full gates: 548 tests + 46 subtests, 25 Node task tests, `build.mjs --check`, fresh-venv install verifier (340×783 offscreen render) and `git diff --check` all passed. Offscreen fixture renders covered idle, running, paused, error, stalled and stale states, plus a missing file hiding the row at height 0.

**Pushed:** `4b051b705fed2cea3efd73f25843d2aaa0448667`. Repository guards [41118610602](https://github.com/samuelfrench/claude-indicator/actions/runs/41118610602) and Python tests/beta install [41118610553](https://github.com/samuelfrench/claude-indicator/actions/runs/41118610553) green.

**Accepted 2026-10-30 CT:** Restarted `claude-indicator.service` after green CI: active/running, PID 1277372, NRestarts 0, no journal errors. Native capture `/tmp/indicator-responder-live.png` shows the row between CLAWD TASK LOOPS and CRON JOBS reading `EMAIL ● idle · last run 3m ago · 0 handled, 0 for you` from the bot's live mode-0600 status file; a second capture one minute later reads `4m ago`, proving the 15-second local refresh. No new billing or provider probes.
