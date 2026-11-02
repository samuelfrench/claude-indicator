---
title: "Replace missing Claude quota headers with local status-line data"
status: done
area: product
due: null
updated: 2026-11-01
owner: agent
brief: "Fix the live missing-header error using the supported local Claude Code feed."
refs: ["a68e08052c4069eb4594d79d398920e453e39703"]
test: null
---
- **What:** Preserve the existing status-line output while capturing only quota fields locally; prefer this feed over inference probes.
- **Why:** Live widget.log repeatedly reports `Usage Headers Missing`; the session credential has no access token. The configured setup-token probe succeeds without usable quota headers.
- **Next:** None for this repair. Quotas refresh on normal Claude Code activity; the original five-minute expiry was superseded on November 2 by `docs/todo/done/product/claude-idle-quota-cache.md`, retaining last-known meters until reset, and absent windows stay hidden. Legacy adapter compatibility remains a separate deferred task.
- **Evidence:** Real Claude Code status-line event produced a seven-day-only quota snapshot; optional windows are handled independently. Collector installed as a wrapper around the existing display in local settings. Offline suite: 564 tests and 46 subtests passed before final visibility fixes; task tests 25 passed; clean-install verifier passed. Independent review identified and corrected stale visibility, partial-window handling and extra-usage clearing. Final isolated suite after visibility fixes: 564 tests and 46 subtests passed. Running legacy tests with real HOME after opt-in selects the real feed (8 mocked-probe failures); use the documented isolated HOME command, as CI does.
- **Done:** Local feed configured, no inference polling in this mode, honest waiting/stale state, focused and required gates pass, service runs revised code.

- **Deployment:** Implementation `a68e08052c4069eb4594d79d398920e453e39703` pushed to master. Python/install CI `41378452774` and repository guards `41378452786` passed. Restarted the authorized user service at 2026-11-01 20:35 CT: PID 1102681, active/running, event-loop ready, NRestarts=0. Live log: `fetch ok: 5h=unavailable 7d=93.0 plan=CLAUDE src=statusline`. Native 340x771 window capture verified weekly 93%, absent five-hour meter hidden, footer `Claude Code · 4m ago`, and no missing-header error. Private screenshot `/tmp/claude-indicator-quota-fix.png` is deliberately untracked.
- **Billing:** The configured local Claude mode makes no inference calls and adds no paid service. Existing status-line display command and unrelated provider adapters remain intact.
