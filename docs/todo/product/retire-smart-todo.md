---
title: Retire unused Smart TODO GUI and scanner integration
status: now
area: product
due: null
updated: 2026-10-26
owner: agent
test: null
brief: Remove Smart TODO from the running indicator and future starts; verify no separate scheduler or model calls.
refs:
  - claude_widget.py
  - smart_todos.py
  - smart_todo_workflow.py
---

## What and why

Sam no longer uses the Smart TODO GUI and requested that its work stop, particularly any token consumption. Remove its tray action, dialog/scan entry point, summary and lifecycle integration from Claude Indicator. Preserve existing task files and local workflow data.

## Current evidence

The existing widget imports `SmartTodoDialog` at `claude_widget.py:63`, constructs it on tray activation at `claude_widget.py:10157`, and calls `show_and_refresh()` to launch `TodoScanWorker`. `smart_todos.py` and `smart_todo_workflow.py` implement deterministic filesystem scanning/ranking and local JSON state; the only subprocess launches a local source editor. No model request is present in that path. Current user/system unit listings, user crontab and inspected autostart entries contain no separate Smart TODO service/timer/job. The live widget uses `claude-indicator.service` from the primary checkout.

## Next and done criteria

Remove the feature integration and update affected tray/lifecycle tests and current documentation. Run focused tests, the full offline Python suite, task tests/build drift check, clean-install verification and diff checks; independently review the patch. Commit/push through normal CI, fast-forward the primary checkout and restart the existing user service. Verify the new process and native tray menu have no Smart TODO entry/window, and that retained workflow files are unchanged. No new service, billing or external approval clock is needed. Update this task and shared memory with exact validation/release/runtime evidence before closeout.
