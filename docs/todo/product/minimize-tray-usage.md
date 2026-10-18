---
title: "Minimize to tray with Claude 5-hour and Codex 7-day indicators"
status: now
area: product
due: null
updated: 2026-10-18
owner: agent
brief: "Fix minimize opening the terminal manager; expose both quotas in the tray, validate, push and restart the existing app."
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
