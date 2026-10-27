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

## Baseline audit

At source `3740354dc7acd5c7df4ee21722afef60af760331`, the widget imported `SmartTodoDialog` at `claude_widget.py:63`, constructed it on tray activation at `claude_widget.py:10157`, and called `show_and_refresh()` to launch `TodoScanWorker`. `smart_todos.py` and `smart_todo_workflow.py` implement deterministic filesystem scanning/ranking and local JSON state; the only subprocess launches a local source editor. No model request is present in that path. User/system unit listings, user crontab and inspected autostart entries contained no separate Smart TODO service/timer/job. The live widget uses `claude-indicator.service` from the primary checkout.

## Implementation checkpoint

The widget's Smart TODO import, tray action, dialog/scan entry point, summary callback and shutdown branch are removed. Both quota tray menus and tooltips omit Smart TODO, including after delayed tray-host creation. Existing TODO files and private workflow state are untouched; dormant modules remain packaged for compatibility. README and developer guidance now describe the retired feature. Focused validation `QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_widget_ui.py tests/test_widget_runtime.py` passed: 169 tests and 24 subtests in 3.33 seconds. The subprocess import regression confirms neither Smart TODO module loads when `claude_widget` imports; tray/lifecycle coverage passes with the integration absent. `git diff --check` passed.

## Next and done criteria

Run the full offline Python suite, task tests/build drift check and clean-install verification; independently review the patch. Push through normal CI, fast-forward the primary checkout and restart the existing user service. Verify the new process and native tray menu have no Smart TODO entry/window, and that retained workflow files are unchanged. No new service, billing or external approval clock is needed. Update this task and shared memory with exact validation/release/runtime evidence before closeout. The implementation checkpoint alone does not establish deployment or task completion.
