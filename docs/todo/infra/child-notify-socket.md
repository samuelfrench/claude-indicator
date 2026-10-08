---
title: "Child processes inherit the systemd notification socket"
status: known-failure
area: infra
due: null
updated: 2026-10-07
owner: agent
brief: "Historical non-blocking warning; isolate notification environment in a later runtime task."
refs: ["widget_runtime.py", "TODO-archive.md#pre-task-files-2026-10-07"]
test: "journalctl --user -u claude-indicator.service"
---
- **What:** Historical journald warning, not currently remeasured.
- **Why:** The original September record documented 1,253 warnings without a restart.
- **Next:** In a separately authorized runtime change, drop inherited socket after reading it, then test readiness/heartbeat. Do not restart the owner widget during beta validation.

- `journalctl --user -u claude-indicator.service` logs `Got notification message from PID <child>, but reception only permitted for main PID <main>` (1,253 lines 2026-09-26 → 2026-10-01; first seen 17:02:39 on 2026-09-26, the day the service unit shipped). Not a regression of `bd69af3`: present before it and the widget stays `active running`, `NRestarts=0`. Trigger: a short-lived child process inherits `NOTIFY_SOCKET` and sends sd_notify; systemd's default `NotifyAccess=main` drops it, so the watchdog is unaffected. Real fix not done: drop `NOTIFY_SOCKET` from `os.environ` after `widget_runtime.py:52` reads it so children never inherit it (then confirm readiness/heartbeat still arrive).

