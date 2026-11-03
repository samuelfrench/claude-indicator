---
title: Open Cron Manager from the tray
status: now
area: product
due: null
updated: 2026-11-02
owner: agent
brief: "Tray action and exact URL test pass; 571 isolated tests and clean-install verifier pass. Push, verify CI and deploy."
refs: []
test: "QT_QPA_PLATFORM=offscreen python3 -m pytest -q"
---

- **What:** Add a Cron Manager action after Outreach Studio in the existing tray menu, opening http://127.0.0.1:4741/ with QDesktopServices and normal launch-failure feedback.
- **Why:** Sam requested direct access from the Claude indicator tray. The dashboard health endpoint is live at runtime c07e25ea2fcc58b7ab3c46a7855158c7ed363010.
- **Next:** Verify exact QAction URL and existing tray behavior, run required repository gates, push and verify green CI, then restart only claude-indicator.service and inspect both live DBus menu instances. Keep provider/scheduler logic unchanged; no jobs, sends or new provider probes are part of testing.

Starting checkout clean on master1dc469a and matched origin/master after fetch. Existing service active at PID1784377 and registered Claude/Codex menu instances; restarting the existing service is authorized by this tray feature request. No billing impact or external approval clocks.

Validation: 5 focused tray checks passed; full suite in the existing CI isolated HOME/XDG environment passed 571 tests and 46 subtests. The initial non-isolated run read the owner's configured status-line feed and produced 8 unrelated provider-fixture failures; repeating through the repository's CI isolation route resolved all 8 without altering provider code or user state. TODO tests25/25, generated-state check, diff check and clean installation/inert Qt render all passed; installer launched no live GUI or provider call. Scoped self-review confirms the shared menu exposes the new action on both icons and preserves existing controls, separator and tray-retry behavior.
