---
title: "Replace missing Claude quota headers with local status-line data"
status: now
area: product
due: null
updated: 2026-11-01
owner: agent
brief: "Fix the live missing-header error using the supported local Claude Code feed."
refs: []
test: null
---
- **What:** Preserve the existing status-line output while capturing only quota fields locally; prefer this feed over inference probes.
- **Why:** Live widget.log repeatedly reports `Usage Headers Missing`; the session credential has no access token. The configured setup-token probe succeeds without usable quota headers.
- **Next:** Push reviewed implementation, await green CI, deploy user service and verify live behavior. No provider requests or credential changes needed.
- **Evidence:** Real Claude Code status-line event produced a seven-day-only quota snapshot; optional windows are handled independently. Collector installed as a wrapper around the existing display in local settings. Offline suite: 564 tests and 46 subtests passed before final visibility fixes; task tests 25 passed; clean-install verifier passed. Independent review identified and corrected stale visibility, partial-window handling and extra-usage clearing. Final isolated suite after visibility fixes: 564 tests and 46 subtests passed. Running legacy tests with real HOME after opt-in selects the real feed (8 mocked-probe failures); use the documented isolated HOME command, as CI does.
- **Done:** Local feed configured, no inference polling in this mode, honest waiting/stale state, focused and required gates pass, service runs revised code.
