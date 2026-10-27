---
title: Retire unused Smart TODO GUI and scanner integration
status: done
area: product
due: null
updated: 2026-10-26
owner: agent
test: QT_QPA_PLATFORM=offscreen python3 -m pytest -q; python3 scripts/verify_install.py
brief: Smart TODO retired and live; 529 tests plus 31 subtests, 25 task tests, clean install and CI passed.
refs:
  - claude_widget.py
  - smart_todos.py
  - smart_todo_workflow.py
---

## What and why

Sam no longer uses the Smart TODO GUI and requested that its work stop, particularly any token consumption. Its tray action, dialog/scan entry point, summary and lifecycle integration are removed from Claude Indicator, including delayed tray-host creation. The widget no longer imports either Smart TODO module or starts its scanner. Existing task files and local workflow data are preserved; dormant source modules remain for compatibility.

## Baseline audit

At source `3740354dc7acd5c7df4ee21722afef60af760331`, the widget imported `SmartTodoDialog` at `claude_widget.py:63`, constructed it on tray activation at `claude_widget.py:10157`, and called `show_and_refresh()` to launch `TodoScanWorker`. `smart_todos.py` and `smart_todo_workflow.py` implement deterministic filesystem scanning/ranking and local JSON state; the only subprocess launches a local source editor. No model request is present in that path. User/system unit listings, user crontab and inspected autostart entries contained no separate Smart TODO service/timer/job. The live widget uses `claude-indicator.service` from the primary checkout.

## Implementation checkpoint

The widget's Smart TODO import, tray action, dialog/scan entry point, summary callback and shutdown branch are removed. Both quota tray menus and tooltips omit Smart TODO, including after delayed tray-host creation. Existing TODO files and private workflow state are untouched; dormant modules remain packaged for compatibility. README and developer guidance now describe the retired feature. Focused validation `QT_QPA_PLATFORM=offscreen /home/sam/miniconda3/bin/python3 -m pytest -q tests/test_widget_ui.py tests/test_widget_runtime.py` passed: 169 tests and 24 subtests in 3.33 seconds. The subprocess import regression confirms neither Smart TODO module loads when `claude_widget` imports; tray/lifecycle coverage passes with the integration absent. `git diff --check` passed.

## Release and validation

Implementation `dacfa2960277fcf3ecb7ecc4be33f698cde5ca4e` and aggregate `c7024cd5ede4922e4a1cf90caf479f8511c261d5` were pushed and fast-forwarded to master; [PR 1](https://github.com/samuelfrench/claude-indicator/pull/1) is merged. Parent validation passed the full isolated offline suite: 529 tests and 31 subtests in 12.52 seconds, exit 0. All 25 task workflow tests, generated-state drift and diff checks passed. Independent task/spec and whole-branch review found no issues. Local fresh-install verification passed on Python 3.13.9 / PySide6 6.12.0, with all eight packaged modules, help/version and inert 340x753 Qt rendering accepted; provider HTTP and subprocesses were blocked. The verifier explicitly imports the retained modules to check packaging; normal widget import does not load them, as confirmed by the subprocess regression.

Exact-source Python/install [40439152620](https://github.com/samuelfrench/claude-indicator/actions/runs/40439152620) and repository guards [40439152746](https://github.com/samuelfrench/claude-indicator/actions/runs/40439152746) passed. Hosted Python reported 529 tests and 31 subtests in 8.17 seconds, exit 0; clean install passed on Python 3.10 / PySide6 6.11.3 with HTTP/subprocesses blocked and inert 340x743 rendering. Final aggregate PR checks [40439267115](https://github.com/samuelfrench/claude-indicator/actions/runs/40439267115) / [40439267135](https://github.com/samuelfrench/claude-indicator/actions/runs/40439267135), and master checks [40439411937](https://github.com/samuelfrench/claude-indicator/actions/runs/40439411937) / [40439411942](https://github.com/samuelfrench/claude-indicator/actions/runs/40439411942), all succeeded at `c7024cd5ede4922e4a1cf90caf479f8511c261d5`.

## Live verification and handoff

Restarted the existing `claude-indicator.service` at 2026-10-26 21:37:06 CT after green exact-source CI. New PID 3172928 uses the primary checkout, active/running with zero automatic restarts. Runtime source SHA256 is `88c746555308293799a995da0c695ae579a4d4ff45bdf5602a0db6c37eae3cb8`. Both native tray D-Bus registrations owned by that PID expose exactly Traffic Report, Terminal recovery, Configure, Show/Hide and Quit (plus a separator); neither has Smart TODO. The native widget window is present and no Smart TODO window remains. The private finished/workflow JSON files have unchanged pre/post SHA256 hashes. Journal readback through 21:37:57 CT found zero tracebacks, destroyed-thread errors, shared-QObject crashes or segmentation faults; service remained active with zero restarts.

No remaining work for this request. No separate Smart TODO scheduler or AI-model request was found, including local Codex automation configurations; its former ranking/scanning path was deterministic local code, so no token savings amount is claimed. No new service, billing or external approval clock applies. Keep Smart TODO retired unless Sam requests otherwise. Private validation receipts are under `~/.local/state/claude-indicator/retire-smart-todo-20261026/`: `before.json`, `full-tests.log`, `todo-tests.log`, `install-validation.json`, `ci-python-source.log`, `native-after.json`, `runtime-health.json`. Shared memory records the retirement; final TODO/memory readback is required before closeout. Later task-only commits do not alter deployed runtime bytes.
