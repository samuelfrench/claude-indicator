---
title: Automatically sync Crons with Cron Manager
status: now
area: product
due: null
updated: 2026-11-04
owner: agent
brief: Replace the independent crontab view with automatic read-only Cron Manager snapshot polling.
test: tests/test_cron_jobs.py
refs:
  - claude_widget.py
  - tests/test_cron_jobs.py
---

## What / Why / Next

The existing Crons section reads only the user crontab and infers trigger health; Cron Manager aggregates scheduler inventory and recorded results at `http://127.0.0.1:4741/api/snapshot`. Make that snapshot the widget's source of truth, poll automatically every minute, retain source result/enablement semantics, and expose stale/unavailable collection state. Keep the expanded inventory usable with the larger job count. No scheduler changes or job execution are authorized or needed.

Implemented shared snapshot polling every 60 seconds, all-source inventory and disabled/result semantics, retained stale rows during outages, coverage and snapshot-time details, and ten-row paging. Focused tests cover automatic timer/worker update-removal, outage/recovery, visibility and paging. Local isolated-HOME full suite: 577 passed, 49 subtests; TODO gates: 25 passed and drift clean; fresh-package inert install/render passed. Running the suite with the real HOME first exposed eight unrelated provider-adapter expectations overridden by the owner statusline opt-in; use the isolated environment in `scripts/verify_install.py` or CI. Independent review found and fixed the Next-label hit area before release. Offscreen live-snapshot render: 183 jobs, expanded 340x222, private audit under `~/.local/share/claude-indicator/audits/cron-sync-20261104/`.

Next: final review verdict, commit/push and green CI, existing user-service deployment, native runtime verification of repeated minute polling and API parity, then shared-memory closeout. No scheduler mutations, new billing, external approval clocks or upstream contribution are needed for this app-specific integration.
