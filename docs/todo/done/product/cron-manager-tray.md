---
title: Open Cron Manager from the tray
status: done
area: product
due: null
updated: 2026-11-02
owner: agent
brief: "Deployed 31415ec with green CI; live Claude/Codex tray menus expose enabled Cron Manager link to port4741."
refs: []
test: "QT_QPA_PLATFORM=offscreen python3 -m pytest -q"
---

- **What:** Add a Cron Manager action after Outreach Studio in the existing tray menu, opening http://127.0.0.1:4741/ with QDesktopServices and normal launch-failure feedback.
- **Why:** Sam requested direct access from the Claude indicator tray. The dashboard health endpoint is live at runtime c07e25ea2fcc58b7ab3c46a7855158c7ed363010.
- **Next:** No work remains. Right-click the Claude tray icon and choose Cron Manager. Both icons share the menu. Provider/scheduler logic is unchanged; no jobs, sends or new provider probes were part of testing.

Starting checkout clean on master1dc469a and matched origin/master after fetch. Existing service active at PID1784377 and registered Claude/Codex menu instances; restarting the existing service is authorized by this tray feature request. No billing impact or external approval clocks.

Validation: 5 focused tray checks passed; full suite in the existing CI isolated HOME/XDG environment passed 571 tests and 46 subtests. The initial non-isolated run read the owner's configured status-line feed and produced 8 unrelated provider-fixture failures; repeating through the repository's CI isolation route resolved all 8 without altering provider code or user state. TODO tests25/25, generated-state check, diff check and clean installation/inert Qt render all passed; installer launched no live GUI or provider call. Scoped self-review confirms the shared menu exposes the new action on both icons and preserves existing controls, separator and tray-retry behavior.


Deployment verified 2026-11-02: source `31415ecafc8eedb4024fd75ca51a6c0773ed85c0` pushed to origin/master. Python/install CI41563813773 and repository-guard CI41563813766 passed. Restarted only existing claude-indicator.service; active/running PID3483935, NRestarts0. Both registered native tray menu instances (:1.95191 and :1.95192 /MenuBar) expose action27 Cron Manager with enabled=true and visible=true. The actual QAction test confirms exact http://127.0.0.1:4741/ target; dashboard health was verified. No manual browser launch was needed for this menu-entry change. Post-restart journal scan found no traceback, destroyed-QThread or crash signatures. Documentation-only closeout does not require another restart.
