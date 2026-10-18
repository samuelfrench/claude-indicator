---
title: "Minimize to tray with Claude 5-hour and Codex 7-day indicators"
status: now
area: product
due: null
updated: 2026-10-18
owner: agent
brief: "89cea8a pushed after local gates/review; hosted Python/install CI running, then restart and native verification."
refs: ["claude_widget.py", "tests/test_widget_ui.py"]
test: null
---
- **What:** Main-window minimize must never open a closed terminal manager. Minimize to the desktop tray when available, with visible Claude 5-hour and Codex 7-day usage indicators that update from existing data. Preserve a recoverable screen-edge fallback when no tray host exists.
- **Why:** `claude_widget.py:10004` currently opens `TerminalTabsPanel` unconditionally whenever the tabs section is enabled; the header button calls that path instead of minimizing to tray.
- **Next:** Sole implementation agent edits window/tray behavior and focused tests; independent review follows. Run focused/full Python tests, task tests/drift, fresh-install verification and diff checks; commit/push; await green exact-revision CI; restart `claude-indicator.service` and verify native minimize/restore, both tray indicators, closed-manager invariant and service health. User explicitly requested the restart on October 18.

## Scope and evidence

- Start: clean `master` equals `origin/master` at `0272298`; existing service active with PID 8248 and main-checkout ExecStart. Existing minimization uses an edge sliver and opens the terminal panel; tray currently displays a Smart TODO compass only.
- No new provider adapter, direct authenticated probe, billing, account action, outreach or upstream contribution is needed. Existing provider refreshes continue normally when the app is restarted. External verification clock: hosted Python/install and repository guard runs after the code push. Native tray/window behavior must be checked after deployment.
- Done means the requested behavior is implemented, tested, independently reviewed, pushed with green CI, deployed through the existing user service, and verified on the desktop; generated TODO and shared memory agree with those receipts.

## October 18 implementation checkpoint

- Native baseline: X11 tray host is present; main window mapped, terminal manager and edge sliver both unmapped. No live app interaction or restart yet. Private cropped baseline evidence is under `~/indicator-beta/minimize-tray-2026-10-18/`.
- Sole implementer is replacing the compass with Claude C and Codex X quota icons, adding header/native minimize routing, and retaining sliver recovery only when needed. Existing polling results supply all data; no new provider request path. Parent inspected 22px and 32px icon previews: provider letters, quota numbers, unavailable question mark and cache dot are distinguishable. Tests/review remain pending; these previews are not deployment proof.
- Task workflow passed 25 tests and generated-state check (13 tasks). Planning checkpoint `cc456d47cac3ae0b85aaebcaced5c25bb4ddb7c0` has green repository guard run 39144295197.

## Local validation and review

- Frozen implementation covers header and native minimize-to-tray, closed-manager preservation, two visible C/X quota icons from existing polling data, actual duration-selected Codex weekly quota, unavailable/error/reset/expiry states, cached age marking, hidden-window updates, shared existing menus, restore, host-loss fallback and shutdown. README explains usage. No adapter or new provider call was added.
- Final full offline suite with isolated HOME passed **530 tests +31 subtests in 6.74s**, exit 0. Implementer widget suite passed **160 tests +24 subtests**; independent reviewer passed **28 focused tests +14 subtests** and approved the frozen diff without actionable findings. `git diff --check` passed. Receipt: `~/indicator-beta/minimize-tray-2026-10-18/full-tests-final.log`.
- Final clean-install smoke passed 8 installed modules, help/version and an inert 340x753 widget, with HTTP/subprocess creation blocked (Python 3.13.9, PySide6 6.12.0). This second fresh install started after the last host-loss fix and validates the frozen source. Receipt and rendered image: `~/indicator-beta/minimize-tray-2026-10-18/install-validation-final.json` and `install-widget-final.png`. No live service was changed during installation tests.
- Next: commit/push source and this task, observe exact-source Python/install plus repository guard CI, then restart the existing user service and verify native minimize/restore and both indicators. Runtime is still the pre-task process until that explicit deployment step.

## Pushed checkpoint

- Source `89cea8a91e488d85a2501cba1e2ab32b5b31838d` is pushed to `origin/master`; working tree was clean after push. Widget SHA-256: `54228b9aec5e4a8491431af52f50f6c1026c062985d1d16220f6da3c3cd910a7`.
- Exact-source repository guard [39144830445](https://github.com/samuelfrench/claude-indicator/actions/runs/39144830445) passed; Python/install [39144830504](https://github.com/samuelfrench/claude-indicator/actions/runs/39144830504) is live and running. Observe that existing run with `gh run view 39144830504 --json status,conclusion,jobs`; do not restart the app before it succeeds.
- Existing service is still active/running PID 8248 with 0 automatic restarts. Next after green CI: `systemctl --user restart claude-indicator.service`, verify changed PID/current source, use the real header minimize control, confirm main/terminal/sliver windows are unmapped and both quota icons visible, then restore from each icon and confirm manager stays closed. Capture only private app/tray crops and scoped service/error evidence under `~/indicator-beta/minimize-tray-2026-10-18/`.
