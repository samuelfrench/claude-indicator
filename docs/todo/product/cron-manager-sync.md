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

Implementation is in progress. Next: focused behavior tests, full repository gates, independent scoped review, commit/push and green CI, then existing user-service deployment and runtime verification. Completion requires automatic add/change/remove parity, honest unknown/outage state, generated TODO and shared-memory closeout. No external approval clocks or upstream contribution are needed for this app-specific integration.
