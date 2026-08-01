# Task 5 report: recover tray controls after desktop host returns

## Root cause

`ClaudeWidget._setup_tray_icon()` checked `QSystemTrayIcon.isSystemTrayAvailable()`
once during construction. If the GNOME/KDE StatusNotifier host was unavailable at
that instant, the method returned and no later code retried tray creation.

## Implementation

- Added one parent-owned five-second periodic tray retry timer.
- The timer remains active for an unbounded lock/host outage and stops only when
  a tray is created or application shutdown begins.
- Tray setup is guarded by both `_shutdown_started` and the existing `_tray`
  identity, so retries cannot create duplicate menus, actions, or signal wiring.
- The unavailable condition is logged once per process instead of once per retry.
- Smart TODO behavior and persistence were not changed.

## TDD evidence

- RED: `python -m pytest tests/test_widget_ui.py -q -k 'tray_unavailable_retries or repeated_unavailable_tray_retries or shutdown_stops_tray_retry'`
  produced `3 failed, 25 deselected`; each failure showed the retry timer was absent.
- GREEN: the same command produced `3 passed, 25 deselected`.
- Focused file: `python -m pytest tests/test_widget_ui.py -q` produced
  `28 passed, 3 subtests passed`.

## Verification

- `python -m pytest -q` -> `220 passed, 3 subtests passed`.
- `PYTHONPATH=. python tests/test_widget_ui.py` -> `Ran 28 tests`, `OK`.
- `PYTHONPATH=. python tests/test_cron_jobs.py` -> `Ran 12 tests`, `OK`.
- `python -m pytest tests/test_smart_todos.py -q` -> `84 passed`.
- `python -m pytest tests/test_smart_todo_workflow.py -q` -> `35 passed`.
- `python -m py_compile claude_widget.py smart_todos.py smart_todo_workflow.py tests/test_widget_ui.py` -> exit 0.
- `git diff --check` -> exit 0.

An extra isolated invocation of `tests/test_smart_todo_ui.py` reproduced one
pre-existing offscreen focus/window-activation failure in
`test_keyboard_tab_order_has_visible_focus_for_interactive_controls`; the same
test passes in the required full-suite run. This task does not modify that UI or
its focus handling.

## Billing

No dependency, external service, network call, or billable resource was added.
