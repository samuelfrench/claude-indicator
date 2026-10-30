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
